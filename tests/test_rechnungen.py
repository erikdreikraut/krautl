import os
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_rechnungen.db")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")
os.environ.setdefault("DROPBOX_ACCESS_TOKEN", "test")

from sqlalchemy import select

from app.db import SessionLocal, engine
from app.mail_parser import rechnungsanhaenge
from app.models import Base, Mail, Postfach, Rechnung
from app.rechnungen import rechnung_verarbeiten


EML = b"""From: Lieferant <rechnung@example.test>\r
To: einkauf@dreikraut.de\r
Subject: Rechnung 4711\r
Message-ID: <rechnung@example.test>\r
MIME-Version: 1.0\r
Content-Type: multipart/mixed; boundary=x\r
\r
--x\r
Content-Type: text/plain; charset=utf-8\r
\r
Ihre Rechnung.\r
--x\r
Content-Type: application/pdf\r
Content-Disposition: attachment; filename=rechnung.pdf\r
Content-Transfer-Encoding: base64\r
\r
JVBERi0xLjQ=\r
--x--\r
"""


class RechnungenTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        async with SessionLocal() as session:
            postfach = Postfach(adresse="einkauf@dreikraut.de", funktion="einkauf", imap_host="imap.test")
            session.add(postfach)
            await session.flush()
            mail = Mail(
                message_id="<rechnung@example.test>", imap_uid=7, postfach_id=postfach.id,
                absender_name="Lieferant", absender_adresse="rechnung@example.test",
                betreff="Rechnung 4711", text_auszug="Ihre Rechnung",
                empfangen_am=datetime.now(timezone.utc),
            )
            session.add(mail)
            await session.commit()
            self.mail_id = mail.id

    def test_pdf_anhang_wird_extrahiert(self):
        anhaenge = rechnungsanhaenge(EML)
        self.assertEqual(1, len(anhaenge))
        self.assertEqual(".pdf", anhaenge[0]["endung"])

    async def test_rechnung_wird_abgelegt_und_dedupliziert(self):
        config = type("Config", (), {"user": "einkauf@dreikraut.de"})()
        analyse = {
            "ist_rechnung": True, "aussteller": "Test GmbH", "rechnungsnummer": "4711",
            "rechnungsdatum": "2026-07-21", "faellig_am": "2026-08-04",
            "bruttobetrag": 119.0, "waehrung": "EUR", "zahlungsstatus": "offen",
            "zahlungshinweis": "Bitte überweisen",
        }
        dbx = MagicMock()
        with patch("app.rechnungen.lade_postfaecher", return_value=[config]), \
             patch("app.rechnungen.mail_rohdaten_laden", return_value=EML), \
             patch("app.rechnungen._analysiere", return_value=analyse), \
             patch("app.rechnungen._dropbox_client", return_value=dbx):
            async with SessionLocal() as session:
                mail = await session.get(Mail, self.mail_id)
                erstes = await rechnung_verarbeiten(session, mail)
                await session.commit()
            async with SessionLocal() as session:
                mail = await session.get(Mail, self.mail_id)
                zweites = await rechnung_verarbeiten(session, mail)
                await session.commit()

        self.assertFalse(erstes["rechnungen"][0]["dublette"])
        self.assertTrue(zweites["rechnungen"][0]["dublette"])
        dbx.files_upload.assert_called_once()
        pfad = dbx.files_upload.call_args.args[1]
        self.assertEqual("/Rechnungen/2026/2026-07-21-Test-GmbH-4711.pdf", pfad)
        async with SessionLocal() as session:
            rechnungen = (await session.execute(select(Rechnung))).scalars().all()
            self.assertEqual(1, len(rechnungen))
            self.assertEqual("offen", rechnungen[0].zahlungsstatus)


if __name__ == "__main__":
    unittest.main()
