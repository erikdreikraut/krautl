import asyncio
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
from scripts.historische_rechnungen_importieren import (
    HISTORISCH_KEINE_RECHNUNG,
    ROHDATEN_BATCH_GROESSE,
    _liegt_im_zeitraum,
    importieren,
)


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

    async def test_negativer_befund_wird_beim_fortsetzen_nicht_neu_analysiert(self):
        eingang = datetime(2026, 2, 3, 9, 5, tzinfo=timezone.utc)

        def kandidaten(config, _ordner, _start, _ende):
            if config.funktion == "info":
                return 1, [{
                    "uid": 42,
                    "ordner": "INBOX",
                    "eingegangen_am": eingang,
                }]
            return 0, []

        verarbeiten = AsyncMock(side_effect=RuntimeError(
            "Anhaenge enthalten laut Auswertung keine Rechnung"
        ))
        with patch(
            "scripts.historische_rechnungen_importieren._rechnungskandidaten_laden",
            side_effect=kandidaten,
        ), patch(
            "scripts.historische_rechnungen_importieren._rohdaten_batch_laden",
            return_value={42: EML},
        ), patch(
            "scripts.historische_rechnungen_importieren.rechnung_aus_rohdaten_verarbeiten",
            verarbeiten,
        ):
            erstes = await importieren(configs=configs())
            zweites = await importieren(configs=configs())
            verarbeiten.side_effect = None
            verarbeiten.return_value = {
                "rechnungen": [{"id": 1, "dublette": False}]
            }
            erzwungen = await importieren(
                configs=configs(),
                erneut_pruefen=True,
            )

        self.assertEqual(1, erstes["keine_rechnung"])
        self.assertEqual(1, zweites["uebersprungen"])
        self.assertEqual(1, erzwungen["rechnungen"])
        self.assertEqual(2, verarbeiten.await_count)
        async with SessionLocal() as session:
            mail = (await session.execute(select(Mail))).scalar_one()
        self.assertEqual("geprueft", mail.pruefstatus)
        self.assertFalse(mail.im_krautl_posteingang)

    async def test_erfolgreicher_import_wird_beim_fortsetzen_uebersprungen(self):
        eingang = datetime(2026, 2, 3, 9, 5, tzinfo=timezone.utc)

        def kandidaten(config, _ordner, _start, _ende):
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
            return_value={42: EML},
        ), patch(
            "scripts.historische_rechnungen_importieren.rechnung_aus_rohdaten_verarbeiten",
            verarbeiten,
        ):
            erstes = await importieren(configs=configs())
            zweites = await importieren(configs=configs())

        self.assertEqual(1, erstes["rechnungen"])
        self.assertEqual(1, zweites["uebersprungen"])
        verarbeiten.assert_awaited_once()

    async def test_rohdaten_werden_nur_in_kleinen_bloecken_geladen(self):
        eingang = datetime(2026, 2, 3, 9, 5, tzinfo=timezone.utc)
        kandidaten_liste = [
            {"uid": uid, "ordner": "INBOX", "eingegangen_am": eingang}
            for uid in range(1, 13)
        ]
        batchgroessen = []

        def kandidaten(config, _ordner, _start, _ende):
            return (
                (len(kandidaten_liste), kandidaten_liste)
                if config.funktion == "info" else (0, [])
            )

        def rohdaten(_config, _ordner, uids):
            batchgroessen.append(len(uids))
            return {}

        with patch(
            "scripts.historische_rechnungen_importieren._rechnungskandidaten_laden",
            side_effect=kandidaten,
        ), patch(
            "scripts.historische_rechnungen_importieren._rohdaten_batch_laden",
            side_effect=rohdaten,
        ):
            await importieren(configs=configs())

        self.assertEqual(
            [ROHDATEN_BATCH_GROESSE, ROHDATEN_BATCH_GROESSE, 2],
            batchgroessen,
        )

    async def test_ungueltiger_zeitraum_wird_abgewiesen(self):
        with self.assertRaisesRegex(RuntimeError, "Startdatum"):
            await importieren(
                start=datetime(2026, 5, 1).date(),
                ende_einschliesslich=datetime(2026, 4, 30).date(),
                configs=configs(),
            )

    async def test_wiederholte_systemfehler_brechen_den_lauf_sicher_ab(self):
        eingang = datetime(2026, 2, 3, 9, 5, tzinfo=timezone.utc)
        kandidaten_liste = [
            {"uid": uid, "ordner": "INBOX", "eingegangen_am": eingang}
            for uid in range(1, 13)
        ]

        def kandidaten(config, _ordner, _start, _ende):
            return (
                (len(kandidaten_liste), kandidaten_liste)
                if config.funktion == "info" else (0, [])
            )

        verarbeiten = AsyncMock(return_value={
            "status": "fehler",
            "detail": "API-Zugang ungueltig",
        })
        with patch(
            "scripts.historische_rechnungen_importieren._rechnungskandidaten_laden",
            side_effect=kandidaten,
        ), patch(
            "scripts.historische_rechnungen_importieren._rohdaten_batch_laden",
            side_effect=lambda _config, _ordner, uids: {uid: EML for uid in uids},
        ), patch(
            "scripts.historische_rechnungen_importieren.rechnungsanhaenge",
            return_value=[{"dateiname": "rechnung.pdf"}],
        ), patch(
            "scripts.historische_rechnungen_importieren._kandidat_verarbeiten",
            verarbeiten,
        ):
            ergebnis = await importieren(configs=configs())

        self.assertTrue(ergebnis["abgebrochen"])
        self.assertEqual(5, verarbeiten.await_count)
        self.assertIn("Sicherheitsabbruch", ergebnis["fehler"][-1])

    async def test_rechnungsanalysen_laufen_begrenzt_parallel(self):
        eingang = datetime(2026, 2, 3, 9, 5, tzinfo=timezone.utc)
        kandidaten_liste = [
            {"uid": uid, "ordner": "INBOX", "eingegangen_am": eingang}
            for uid in range(1, 6)
        ]
        gleichzeitig = 0
        maximal_gleichzeitig = 0

        def kandidaten(config, _ordner, _start, _ende):
            return (
                (len(kandidaten_liste), kandidaten_liste)
                if config.funktion == "info" else (0, [])
            )

        async def verarbeiten(*_args, **_kwargs):
            nonlocal gleichzeitig, maximal_gleichzeitig
            gleichzeitig += 1
            maximal_gleichzeitig = max(maximal_gleichzeitig, gleichzeitig)
            await asyncio.sleep(0.02)
            gleichzeitig -= 1
            return {"status": "keine_rechnung"}

        with patch(
            "scripts.historische_rechnungen_importieren._rechnungskandidaten_laden",
            side_effect=kandidaten,
        ), patch(
            "scripts.historische_rechnungen_importieren._rohdaten_batch_laden",
            side_effect=lambda _config, _ordner, uids: {uid: EML for uid in uids},
        ), patch(
            "scripts.historische_rechnungen_importieren.rechnungsanhaenge",
            return_value=[{"dateiname": "rechnung.pdf"}],
        ), patch(
            "scripts.historische_rechnungen_importieren._kandidat_verarbeiten",
            side_effect=verarbeiten,
        ):
            ergebnis = await importieren(configs=configs(), parallelitaet=2)

        self.assertEqual(2, maximal_gleichzeitig)
        self.assertEqual(5, ergebnis["keine_rechnung"])


if __name__ == "__main__":
    unittest.main()
