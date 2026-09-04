import os
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

from sqlalchemy import select

os.environ.setdefault(
    "DATABASE_URL", "sqlite+aiosqlite:///./test_mail_notizen.db"
)
os.environ.setdefault("ANTHROPIC_API_KEY", "test")

from app.db import SessionLocal, engine
from app.main import MailNotizAenderung, liste_mails, mail_notiz_speichern
from app.models import Aktionslog, Base, Klassifikation, Mail, MailNotiz, Postfach


ERIK = SimpleNamespace(state=SimpleNamespace(benutzer={
    "benutzername": "erik",
    "name": "Erik Schweitzer",
    "rolle": "admin",
}))


class MailNotizenTest(unittest.IsolatedAsyncioTestCase):
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
                message_id="<notiz@example.test>",
                postfach_id=postfach.id,
                absender_name="Testkunde",
                absender_adresse="kunde@example.test",
                betreff="Notiz prüfen",
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

    async def test_notiz_wird_gespeichert_aktualisiert_und_in_liste_geliefert(self):
        async with SessionLocal() as session:
            ergebnis = await mail_notiz_speichern(
                self.mail_id,
                MailNotizAenderung(text="  Rückruf am Freitag\nBestellnummer prüfen.  "),
                ERIK,
                session,
            )
        self.assertEqual("gespeichert", ergebnis["status"])
        self.assertEqual(
            "Rückruf am Freitag\nBestellnummer prüfen.",
            ergebnis["notiz"]["text"],
        )

        async with SessionLocal() as session:
            mails = await liste_mails(ERIK, session, alle=True)
            await mail_notiz_speichern(
                self.mail_id,
                MailNotizAenderung(text="Neue interne Notiz"),
                ERIK,
                session,
            )
            notiz = await session.get(MailNotiz, self.mail_id)
            protokoll = (await session.execute(
                select(Aktionslog).where(
                    Aktionslog.mail_id == self.mail_id,
                    Aktionslog.ereignis == "mail_notiz_gespeichert",
                )
            )).scalars().all()

        self.assertEqual("<notiz@example.test>", mails[0]["message_id"])
        self.assertEqual(
            "Rückruf am Freitag\nBestellnummer prüfen.",
            mails[0]["notiz"]["text"],
        )
        self.assertEqual("Erik Schweitzer", mails[0]["notiz"]["bearbeitet_von"])
        self.assertEqual("Neue interne Notiz", notiz.text)
        self.assertEqual(2, len(protokoll))
        self.assertTrue(all("Neue interne Notiz" not in eintrag.detail for eintrag in protokoll))

    async def test_leerer_text_entfernt_die_notiz(self):
        async with SessionLocal() as session:
            await mail_notiz_speichern(
                self.mail_id,
                MailNotizAenderung(text="Kann später gelöscht werden"),
                ERIK,
                session,
            )
            ergebnis = await mail_notiz_speichern(
                self.mail_id,
                MailNotizAenderung(text="   "),
                ERIK,
                session,
            )
        self.assertEqual("geloescht", ergebnis["status"])

        async with SessionLocal() as session:
            notiz = await session.get(MailNotiz, self.mail_id)
            mails = await liste_mails(ERIK, session, alle=True)
        self.assertIsNone(notiz)
        self.assertIsNone(mails[0]["notiz"])


if __name__ == "__main__":
    unittest.main()
