import os
import unittest
from datetime import datetime, timezone

os.environ.setdefault(
    "DATABASE_URL", "sqlite+aiosqlite:///./test_interne_aufgaben_kategorie.db"
)
os.environ.setdefault("ANTHROPIC_API_KEY", "test")

from sqlalchemy import select

from app.db import SessionLocal, engine
from app.models import (
    Base, Klassifikation, KlassifikationAufgabe, Mail, MailAufgabe, Postfach,
)
from scripts.aktualisiere_interne_aufgaben import aktualisiere


class InterneAufgabenKategorieTest(unittest.IsolatedAsyncioTestCase):
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
            session.add(Klassifikation(
                klassifikation_id="UNGEKLAERT",
                hauptkategorie="Prüfen",
                unterkategorie="Ungeklärt",
                beschreibung="Keine passende Kategorie",
                standard_prio="normal",
                aktion_id="BESTAETIGUNG_EINHOLEN",
            ))
            session.add(postfach)
            await session.flush()

            mails = [
                Mail(
                    message_id="<bestand-intern@test>",
                    postfach_id=postfach.id,
                    absender_name="dreikraut System",
                    absender_adresse="system@dreikraut.de",
                    betreff="Bestandswarnung für Artikel 4711",
                    text_auszug="Der Lagerbestand ist niedrig.",
                    empfangen_am=datetime.now(timezone.utc),
                    klassifikation_id="UNGEKLAERT",
                ),
                Mail(
                    message_id="<adresse-intern@test>",
                    postfach_id=postfach.id,
                    absender_name="Shop-Automatik",
                    absender_adresse="shop@system.dreikraut.de",
                    betreff="Möglicher Adressfehler",
                    text_auszug="Bitte die Lieferadresse prüfen.",
                    empfangen_am=datetime.now(timezone.utc),
                    klassifikation_id="UNGEKLAERT",
                ),
                Mail(
                    message_id="<bestand-extern@test>",
                    postfach_id=postfach.id,
                    absender_name="Externer Alarm",
                    absender_adresse="alarm@example.test",
                    betreff="dreikraut Lagerbestand niedrig",
                    text_auszug="Bitte prüfen.",
                    empfangen_am=datetime.now(timezone.utc),
                    klassifikation_id="UNGEKLAERT",
                ),
                Mail(
                    message_id="<intern-normal@test>",
                    postfach_id=postfach.id,
                    absender_name="Kollegin",
                    absender_adresse="kollegin@dreikraut.de",
                    betreff="Besprechung",
                    text_auszug="Können wir uns morgen abstimmen?",
                    empfangen_am=datetime.now(timezone.utc),
                    klassifikation_id="UNGEKLAERT",
                ),
            ]
            session.add_all(mails)
            await session.commit()
            self.mail_ids = [mail.id for mail in mails]

    async def test_kategorie_aufgaben_und_bestandsmails_werden_idempotent_gesetzt(self):
        async with SessionLocal() as session:
            erstes = await aktualisiere(session)
        async with SessionLocal() as session:
            zweites = await aktualisiere(session)

        async with SessionLocal() as session:
            kategorie = await session.get(Klassifikation, "INTERN_AUFGABEN")
            vorlagen = (await session.execute(
                select(KlassifikationAufgabe)
                .where(KlassifikationAufgabe.klassifikation_id == "INTERN_AUFGABEN")
                .order_by(KlassifikationAufgabe.position)
            )).scalars().all()
            mails = [await session.get(Mail, mail_id) for mail_id in self.mail_ids]
            aufgaben = (await session.execute(
                select(MailAufgabe)
                .where(MailAufgabe.mail_id == self.mail_ids[0])
                .order_by(MailAufgabe.position)
            )).scalars().all()

        self.assertEqual(2, erstes["umgestellte_offene_mails"])
        self.assertEqual(0, zweites["umgestellte_offene_mails"])
        self.assertEqual("service@dreikraut.de", kategorie.zielpostfach)
        self.assertEqual("Erledigt", kategorie.zielordner)
        self.assertEqual(
            ["BESTAETIGUNG_EINHOLEN", "MAIL_VERSCHIEBEN"],
            [vorlage.aufgabe_typ for vorlage in vorlagen],
        )
        self.assertEqual(
            ["INTERN_AUFGABEN", "INTERN_AUFGABEN", "UNGEKLAERT", "UNGEKLAERT"],
            [mail.klassifikation_id for mail in mails],
        )
        self.assertEqual(
            [
                ("BESTAETIGUNG_EINHOLEN", "wartet"),
                ("MAIL_VERSCHIEBEN", "blockiert"),
            ],
            [(aufgabe.aufgabe_typ, aufgabe.status) for aufgabe in aufgaben],
        )


if __name__ == "__main__":
    unittest.main()
