import os
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_aufgaben.db")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")

from sqlalchemy import select

from app.aufgaben import aufgaben_fuer_mail_anlegen, bestaetigung_erfassen
from app.db import SessionLocal, engine
from app.main import liste_mails
from app.models import (
    Aktionslog, Base, Klassifikation, KlassifikationAufgabe, Mail, MailAufgabe, Postfach,
)


class AufgabenPipelineTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)

        async with SessionLocal() as session:
            postfach = Postfach(
                adresse="info@dreikraut.de", funktion="info", imap_host="imap.example.test"
            )
            klassifikation = Klassifikation(
                klassifikation_id="SPAM_TEST", hauptkategorie="Spam",
                unterkategorie="Test", beschreibung="Test", standard_prio="spam",
                zielpostfach="info@dreikraut.de", zielordner="KI-Spam",
                aktion_id="MAIL_VERSCHIEBEN",
            )
            session.add_all([postfach, klassifikation])
            await session.flush()
            session.add_all([
                KlassifikationAufgabe(
                    klassifikation_id="SPAM_TEST", position=1,
                    aufgabe_typ="BESTAETIGUNG_EINHOLEN", bestaetiger_typ="alle",
                ),
                KlassifikationAufgabe(
                    klassifikation_id="SPAM_TEST", position=2,
                    aufgabe_typ="MAIL_VERSCHIEBEN",
                    parameter={"zielpostfach": "info@dreikraut.de", "zielordner": "KI-Spam"},
                ),
            ])
            await session.flush()
            mail = Mail(
                message_id="<test@example.test>", imap_uid=42, postfach_id=postfach.id,
                absender_name="Test", absender_adresse="test@example.test",
                betreff="Testmail", text_auszug="Inhalt",
                empfangen_am=datetime.now(timezone.utc), klassifikation_id="SPAM_TEST",
            )
            session.add(mail)
            await session.flush()
            await aufgaben_fuer_mail_anlegen(session, mail)
            self.mail_id = mail.id
            await session.commit()

    async def test_bestaetigung_blockiert_und_verschiebt_danach(self):
        async with SessionLocal() as session:
            aufgaben = (await session.execute(
                select(MailAufgabe).order_by(MailAufgabe.position)
            )).scalars().all()
            self.assertEqual(["wartet", "blockiert"], [a.status for a in aufgaben])

        fake_config = type("Config", (), {
            "user": "info@dreikraut.de", "host": "imap.example.test",
            "password": "secret", "funktion": "info",
        })()
        with patch("app.aufgaben.lade_postfaecher", return_value=[fake_config]), \
             patch("app.aufgaben.mail_verschieben") as verschieben:
            ergebnis = await bestaetigung_erfassen(self.mail_id)

        self.assertEqual("erledigt", ergebnis["status"])
        verschieben.assert_called_once()

        async with SessionLocal() as session:
            mail = await session.get(Mail, self.mail_id)
            self.assertFalse(mail.im_krautl_posteingang)
            aufgaben = (await session.execute(
                select(MailAufgabe).order_by(MailAufgabe.position)
            )).scalars().all()
            self.assertEqual(["erledigt", "erledigt"], [a.status for a in aufgaben])
            ereignisse = (await session.execute(
                select(Aktionslog.ereignis).order_by(Aktionslog.id)
            )).scalars().all()
            self.assertEqual(["bestaetigt", "verschoben"], list(ereignisse))
            self.assertEqual([], await liste_mails(session))

    async def test_fehlgeschlagenes_verschieben_wird_protokolliert_und_mail_ausgeblendet(self):
        fake_config = type("Config", (), {
            "user": "info@dreikraut.de", "host": "imap.example.test",
            "password": "secret", "funktion": "info",
        })()
        with patch("app.aufgaben.lade_postfaecher", return_value=[fake_config]), \
             patch("app.aufgaben.mail_verschieben", side_effect=RuntimeError("IMAP-Testfehler")):
            ergebnis = await bestaetigung_erfassen(self.mail_id)
        self.assertEqual("fehlgeschlagen", ergebnis["status"])

        async with SessionLocal() as session:
            self.assertEqual([], await liste_mails(session))
            mail = await session.get(Mail, self.mail_id)
            self.assertFalse(mail.im_krautl_posteingang)
            aufgabe = (await session.execute(
                select(MailAufgabe).where(MailAufgabe.status == "fehlgeschlagen")
            )).scalar_one()
            self.assertEqual("IMAP-Testfehler", aufgabe.fehler)
            log = (await session.execute(
                select(Aktionslog).where(Aktionslog.ereignis == "verschieben_fehlgeschlagen")
            )).scalar_one()
            self.assertIn("aus Krautl-Posteingang entfernt", log.detail)


if __name__ == "__main__":
    unittest.main()
