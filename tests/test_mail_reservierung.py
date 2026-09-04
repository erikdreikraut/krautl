import os
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from sqlalchemy import select

os.environ.setdefault(
    "DATABASE_URL", "sqlite+aiosqlite:///./test_mail_reservierung.db"
)
os.environ.setdefault("ANTHROPIC_API_KEY", "test")

from app.db import SessionLocal, engine
from app.main import (
    liste_mails,
    mail_reservieren,
    mail_reservierung_freigeben,
)
from app.models import Base, Klassifikation, Mail, MailReservierung, Postfach


ERIK = SimpleNamespace(state=SimpleNamespace(benutzer={
    "benutzername": "erik",
    "name": "Erik Schweitzer",
    "rolle": "admin",
}))
LUDWIG = SimpleNamespace(state=SimpleNamespace(benutzer={
    "benutzername": "ludwig",
    "name": "Ludwig Schnorrenberg",
    "rolle": "sachbearbeiter",
}))


class MailReservierungTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        async with engine.begin() as verbindung:
            await verbindung.run_sync(Base.metadata.drop_all)
            await verbindung.run_sync(Base.metadata.create_all)
        async with SessionLocal() as session:
            postfach = Postfach(
                adresse="service@dreikraut.de",
                funktion="service",
                imap_host="imap.test",
            )
            klassifikation = Klassifikation(
                klassifikation_id="KUNDE_TEST",
                hauptkategorie="Kundenservice",
                unterkategorie="Test",
                beschreibung="Test",
                standard_prio="normal",
                zielpostfach="service@dreikraut.de",
                zielordner="INBOX",
                aktion_id="BESTAETIGUNG_EINHOLEN",
            )
            session.add_all([postfach, klassifikation])
            await session.flush()
            mail = Mail(
                message_id="<reservierung@example.test>",
                postfach_id=postfach.id,
                absender_name="Testkunde",
                absender_adresse="kunde@example.test",
                betreff="Reservierung prüfen",
                text_auszug="Test",
                empfangen_am=datetime.now(timezone.utc),
                klassifikation_id=klassifikation.klassifikation_id,
                im_krautl_posteingang=True,
                zustaendig_admin=False,
                zustaendig_sachbearbeiter=False,
                zustaendigkeit_manuell=False,
            )
            session.add(mail)
            await session.commit()
            self.mail_id = mail.id

    async def test_reservierung_sperrt_andere_bis_sie_abgelaufen_ist(self):
        async with SessionLocal() as session:
            erik = await mail_reservieren(self.mail_id, ERIK, session)
        self.assertTrue(erik["eigene"])

        async with SessionLocal() as session:
            mails = await liste_mails(ERIK, session, alle=True)
            ludwig = await mail_reservieren(self.mail_id, LUDWIG, session)
        self.assertEqual("Erik Schweitzer", mails[0]["reservierung"]["name"])
        self.assertFalse(ludwig["eigene"])
        self.assertEqual("Erik Schweitzer", ludwig["name"])

        async with SessionLocal() as session:
            reservierung = await session.get(MailReservierung, self.mail_id)
            reservierung.letzter_kontakt = (
                datetime.now(timezone.utc) - timedelta(seconds=91)
            )
            await session.commit()
            ludwig = await mail_reservieren(self.mail_id, LUDWIG, session)
        self.assertTrue(ludwig["eigene"])
        self.assertEqual("Ludwig Schnorrenberg", ludwig["name"])

    async def test_nur_eigene_reservierung_wird_freigegeben(self):
        async with SessionLocal() as session:
            await mail_reservieren(self.mail_id, ERIK, session)
            await mail_reservierung_freigeben(self.mail_id, LUDWIG, session)
        async with SessionLocal() as session:
            reservierung = await session.get(MailReservierung, self.mail_id)
        self.assertEqual("erik", reservierung.benutzername)

        async with SessionLocal() as session:
            await mail_reservierung_freigeben(self.mail_id, ERIK, session)
        async with SessionLocal() as session:
            reservierung = await session.get(MailReservierung, self.mail_id)
        self.assertIsNone(reservierung)


if __name__ == "__main__":
    unittest.main()
