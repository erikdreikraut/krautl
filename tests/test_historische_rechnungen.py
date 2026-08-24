import os
import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

os.environ.setdefault(
    "DATABASE_URL", "sqlite+aiosqlite:///./test_historische_rechnungen.db"
)
os.environ.setdefault("ANTHROPIC_API_KEY", "test")
os.environ.setdefault("DROPBOX_ACCESS_TOKEN", "test")

from sqlalchemy import select

from app.db import SessionLocal, engine
from app.imap_client import PostfachConfig
from app.models import Base, Mail, Postfach
from scripts.historische_rechnungen_importieren import _liegt_im_zeitraum, importieren


EML = b"""From: Lieferant <rechnung@example.test>\r
To: info@dreikraut.de\r
Date: Tue, 3 Feb 2026 10:00:00 +0100\r
Subject: Rechnung 4711\r
Message-ID: <historische-rechnung@example.test>\r
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


def configs():
    return [
        PostfachConfig(name, "imap.test", f"{name}@dreikraut.de", "pw")
        for name in ("info", "service", "einkauf", "marketing")
    ]


class HistorischeRechnungenTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)

    async def test_import_bleibt_aus_arbeitsliste_und_nutzt_eingangsordner(self):
        eingang = datetime(2026, 2, 3, 9, 5, tzinfo=timezone.utc)
        abgefragte_ordner = []

        def kandidaten(config, ordner, _start, _ende):
            abgefragte_ordner.append(ordner)
            if config.funktion == "info":
                return 1, [{
                    "uid": 42,
                    "ordner": "INBOX",
                    "eingegangen_am": eingang,
                }]
            return 0, []

        verarbeiten = AsyncMock(return_value={
            "rechnungen": [{"id": 1, "dublette": False}]
        })
        with patch(
            "scripts.historische_rechnungen_importieren._rechnungskandidaten_laden",
            side_effect=kandidaten,
        ), patch(
            "scripts.historische_rechnungen_importieren._rohdaten_batch_laden",
            side_effect=lambda config, _ordner, _uids: (
                {42: EML} if config.funktion == "info" else {}
            ),
        ), patch(
            "scripts.historische_rechnungen_importieren.rechnung_aus_rohdaten_verarbeiten",
            verarbeiten,
        ):
            ergebnis = await importieren(configs=configs())

        self.assertEqual(4, ergebnis["postfaecher"])
        self.assertEqual(["INBOX"] * 4, abgefragte_ordner)
        self.assertEqual(4, ergebnis["ordner"])
        self.assertEqual(1, ergebnis["rechnungen"])
        self.assertEqual("/Rechnungen/Eingang", ergebnis["zielordner"])
        verarbeiten.assert_awaited_once()
        self.assertEqual(
            "/Rechnungen/Eingang",
            verarbeiten.await_args.kwargs["zielordner"],
        )
        self.assertFalse(verarbeiten.await_args.kwargs["jahresordner"])

        async with SessionLocal() as session:
            mail = (await session.execute(select(Mail))).scalar_one()
            postfaecher = (await session.execute(select(Postfach))).scalars().all()
        self.assertFalse(mail.im_krautl_posteingang)
        self.assertIsNone(mail.imap_uid)
        self.assertEqual(
            eingang.replace(tzinfo=None),
            mail.empfangen_am.replace(tzinfo=None),
        )
        self.assertEqual(4, len(postfaecher))

    def test_zeitraum_wird_nach_internaldate_in_berliner_zeit_strikt_geprueft(self):
        start = datetime(2026, 2, 1, 0, 0, tzinfo=timezone.utc).date()
        ende = datetime(2026, 5, 1, 0, 0, tzinfo=timezone.utc).date()

        self.assertFalse(_liegt_im_zeitraum(
            datetime(2026, 1, 31, 22, 59, tzinfo=timezone.utc), start, ende
        ))
        self.assertTrue(_liegt_im_zeitraum(
            datetime(2026, 1, 31, 23, 0, tzinfo=timezone.utc), start, ende
        ))
        self.assertTrue(_liegt_im_zeitraum(
            datetime(2026, 4, 30, 21, 59, tzinfo=timezone.utc), start, ende
        ))
        self.assertFalse(_liegt_im_zeitraum(
            datetime(2026, 4, 30, 22, 0, tzinfo=timezone.utc), start, ende
        ))

    async def test_fehlendes_quellpostfach_bricht_vor_import_ab(self):
        with self.assertRaisesRegex(RuntimeError, "marketing"):
            await importieren(configs=configs()[:-1])


if __name__ == "__main__":
    unittest.main()
