import os
import unittest
from datetime import datetime, timezone

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_steuerkategorie.db")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")

from sqlalchemy import select

from app.db import SessionLocal, engine
from app.models import (
    Base, Klassifikation, KlassifikationAufgabe, Mail, MailAufgabe, Postfach,
)
from scripts.aktualisiere_steuerkategorie import aktualisiere


class SteuerkategorieTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        async with SessionLocal() as session:
            postfach = Postfach(
                adresse="erik@dreikraut.de",
                funktion="erik",
                imap_host="imap.test",
            )
            alt = Klassifikation(
                klassifikation_id="RECHT_BEHOERDE",
                hauptkategorie="Recht und Behörden",
                unterkategorie="Behörde",
                beschreibung="Allgemeine Behördensache",
                standard_prio="hoch",
                aktion_id="RECHTSSACHE_BEARBEITEN",
            )
            session.add_all([postfach, alt])
            await session.flush()
            countx = Mail(
                message_id="<countx@test>",
                imap_uid=10,
                postfach_id=postfach.id,
                absender_name="CountX",
                absender_adresse="notice@countx.com",
                betreff="Umsatzsteuer",
                text_auszug="Neue Meldung verfügbar",
                empfangen_am=datetime.now(timezone.utc),
                klassifikation_id="RECHT_BEHOERDE",
                im_krautl_posteingang=True,
            )
            session.add(countx)
            await session.flush()
            session.add(MailAufgabe(
                mail_id=countx.id,
                position=1,
                aufgabe_typ="RECHTSSACHE_BEARBEITEN",
                status="wartet",
            ))
            await session.commit()
            self.mail_id = countx.id

    async def test_kategorie_aufgaben_und_bestandsmail_werden_idempotent_gesetzt(self):
        async with SessionLocal() as session:
            erstes = await aktualisiere(session)
        async with SessionLocal() as session:
            zweites = await aktualisiere(session)

        async with SessionLocal() as session:
            kategorie = await session.get(Klassifikation, "RECHT_STEUERN")
            vorlagen = (await session.execute(
                select(KlassifikationAufgabe)
                .where(KlassifikationAufgabe.klassifikation_id == "RECHT_STEUERN")
                .order_by(KlassifikationAufgabe.position)
            )).scalars().all()
            mail = await session.get(Mail, self.mail_id)
            aufgaben = (await session.execute(
                select(MailAufgabe)
                .where(MailAufgabe.mail_id == self.mail_id)
                .order_by(MailAufgabe.position)
            )).scalars().all()

        self.assertEqual(1, erstes["umgestellte_offene_mails"])
        self.assertEqual(0, zweites["umgestellte_offene_mails"])
        self.assertEqual("erik@dreikraut.de", kategorie.zielpostfach)
        self.assertEqual("Steuern", kategorie.zielordner)
        self.assertEqual(
            ["BESTAETIGUNG_EINHOLEN", "MAIL_VERSCHIEBEN"],
            [a.aufgabe_typ for a in vorlagen],
        )
        self.assertEqual("RECHT_STEUERN", mail.klassifikation_id)
        self.assertEqual(
            [
                ("BESTAETIGUNG_EINHOLEN", "wartet"),
                ("MAIL_VERSCHIEBEN", "blockiert"),
            ],
            [(a.aufgabe_typ, a.status) for a in aufgaben],
        )


if __name__ == "__main__":
    unittest.main()
