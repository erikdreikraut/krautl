import os
import unittest
from datetime import datetime, timezone

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_ebay_kategorie.db")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")

from sqlalchemy import select

from app.db import SessionLocal, engine
from app.models import (
    Base, Klassifikation, KlassifikationAufgabe, Mail, MailAufgabe, Postfach,
)
from scripts.aktualisiere_ebay_kategorie import aktualisiere


class EbayKategorieTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        async with SessionLocal() as session:
            postfach = Postfach(
                adresse="service@dreikraut.de",
                funktion="service",
                imap_host="imap.test",
            )
            ungeklärt = Klassifikation(
                klassifikation_id="UNGEKLAERT",
                hauptkategorie="Prüfen",
                unterkategorie="Ungeklärt",
                beschreibung="Keine passende Kategorie",
                standard_prio="normal",
                aktion_id="BESTAETIGUNG_EINHOLEN",
            )
            einkauf = Klassifikation(
                klassifikation_id="LIEFERANT_AUFTRAGSBESTAETIGUNG",
                hauptkategorie="Einkauf",
                unterkategorie="Auftragsbestätigung",
                beschreibung="Bestätigung eines Einkaufs",
                standard_prio="normal",
                aktion_id="BESTAETIGUNG_EINHOLEN",
            )
            session.add_all([postfach, ungeklärt, einkauf])
            await session.flush()
            verkauf = Mail(
                message_id="<ebay-verkauf@test>",
                imap_uid=10,
                postfach_id=postfach.id,
                absender_name="eBay",
                absender_adresse="ebay@ebay.de",
                betreff="Artikel verkauft - Mistelkraut Bio",
                text_auszug=(
                    "Verpacken Sie jetzt den Artikel. Ihr Käufer hat bezahlt."
                ),
                empfangen_am=datetime.now(timezone.utc),
                klassifikation_id="UNGEKLAERT",
                im_krautl_posteingang=True,
            )
            einkaufsbestaetigung = Mail(
                message_id="<ebay-einkauf@test>",
                imap_uid=11,
                postfach_id=postfach.id,
                absender_name="eBay",
                absender_adresse="ebay@ebay.de",
                betreff="Bestellung bestätigt: Tablet Halterung",
                text_auszug="Ihre Bestellung wird an Erik Schweitzer verschickt.",
                empfangen_am=datetime.now(timezone.utc),
                klassifikation_id="LIEFERANT_AUFTRAGSBESTAETIGUNG",
                im_krautl_posteingang=True,
            )
            session.add_all([verkauf, einkaufsbestaetigung])
            await session.flush()
            session.add(MailAufgabe(
                mail_id=verkauf.id,
                position=1,
                aufgabe_typ="BESTAETIGUNG_EINHOLEN",
                status="wartet",
            ))
            await session.commit()
            self.verkauf_id = verkauf.id
            self.einkauf_id = einkaufsbestaetigung.id

    async def test_kategorie_aufgaben_und_bestandsmail_werden_idempotent_gesetzt(self):
        async with SessionLocal() as session:
            erstes = await aktualisiere(session)
        async with SessionLocal() as session:
            zweites = await aktualisiere(session)

        async with SessionLocal() as session:
            kategorie = await session.get(Klassifikation, "BESTELLUNG_EBAY")
            vorlagen = (await session.execute(
                select(KlassifikationAufgabe)
                .where(KlassifikationAufgabe.klassifikation_id == "BESTELLUNG_EBAY")
                .order_by(KlassifikationAufgabe.position)
            )).scalars().all()
            verkauf = await session.get(Mail, self.verkauf_id)
            einkauf = await session.get(Mail, self.einkauf_id)
            aufgaben = (await session.execute(
                select(MailAufgabe)
                .where(MailAufgabe.mail_id == self.verkauf_id)
                .order_by(MailAufgabe.position)
            )).scalars().all()

        self.assertEqual(1, erstes["umgestellte_offene_mails"])
        self.assertEqual(0, zweites["umgestellte_offene_mails"])
        self.assertEqual("service@dreikraut.de", kategorie.zielpostfach)
        self.assertEqual("Bestellungen eBay", kategorie.zielordner)
        self.assertEqual(
            ["BESTAETIGUNG_EINHOLEN", "MAIL_VERSCHIEBEN"],
            [a.aufgabe_typ for a in vorlagen],
        )
        self.assertEqual("BESTELLUNG_EBAY", verkauf.klassifikation_id)
        self.assertEqual(
            [
                ("BESTAETIGUNG_EINHOLEN", "wartet"),
                ("MAIL_VERSCHIEBEN", "blockiert"),
            ],
            [(a.aufgabe_typ, a.status) for a in aufgaben],
        )
        self.assertEqual(
            "LIEFERANT_AUFTRAGSBESTAETIGUNG",
            einkauf.klassifikation_id,
        )


if __name__ == "__main__":
    unittest.main()
