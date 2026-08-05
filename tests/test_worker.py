import os
import unittest
from email.message import EmailMessage
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_worker.db")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")

from sqlalchemy import func, select

from app.db import SessionLocal, engine
from app.imap_client import PostfachConfig
from app.models import Aktionslog, Base, Mail, MailAufgabe
from app.worker import postfach_abrufen_und_klassifizieren


class WorkerInterneMailTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)

    async def test_interne_transkriptionsmail_wird_nicht_erneut_verarbeitet(self):
        nachricht = EmailMessage()
        nachricht["Message-ID"] = "<krautl-audio-17@dreikraut.de>"
        nachricht["X-Krautl-Generated"] = "audio-transcription"
        nachricht["From"] = "Krautl <service@dreikraut.de>"
        nachricht["To"] = "service@dreikraut.de"
        nachricht["Subject"] = "Anruf transkribiert: unbekannt"
        nachricht.set_content("Transkript")
        nachricht.add_attachment(
            b"audio", maintype="audio", subtype="mpeg", filename="anruf.mp3"
        )
        config = PostfachConfig(
            "service", "imap.example.test", "service@dreikraut.de", "pw"
        )

        with patch(
            "app.worker.neue_mails_abrufen",
            return_value=[{
                "uid": 4711,
                "postfach": "service",
                "eml": nachricht.as_bytes(),
            }],
        ), patch("app.worker.klassifiziere") as klassifiziere:
            anzahl = await postfach_abrufen_und_klassifizieren(config)

        async with SessionLocal() as session:
            mail = (await session.execute(select(Mail))).scalar_one()
            aufgaben = (await session.execute(
                select(func.count()).select_from(MailAufgabe)
            )).scalar_one()
            logs = (await session.execute(
                select(func.count()).select_from(Aktionslog)
            )).scalar_one()

        self.assertEqual(0, anzahl)
        self.assertFalse(mail.im_krautl_posteingang)
        self.assertEqual(4711, mail.imap_uid)
        self.assertEqual(0, aufgaben)
        self.assertEqual(0, logs)
        klassifiziere.assert_not_called()


if __name__ == "__main__":
    unittest.main()
