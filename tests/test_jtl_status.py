import asyncio
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.jtl_sync_engine import Speicher, abgleichen, digest
from app.jtl_sync_status import status_laden, status_speichern


class StatusTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Speicher(self.tmp.name)
        self.jetzt = datetime(2026, 10, 9, 12, tzinfo=timezone.utc)

    def lesen(self, **kwargs):
        return status_laden(self.tmp.name, aktiviert=True, jetzt=kwargs.get("jetzt", self.jetzt))

    def test_fehlt_und_deaktiviert(self):
        self.assertEqual(self.lesen()["status"], "unbekannt")
        self.assertEqual(status_laden(self.tmp.name, aktiviert=False)["status"], "deaktiviert")

    def test_erfolg_auch_ohne_schreiben_und_ablauf(self):
        status_speichern(self.store, {"fehler": [], "geschrieben": 0}, self.jetzt)
        self.assertTrue(self.lesen()["gesund"])
        self.assertEqual(self.lesen()["letzter_erfolg"], self.jetzt.isoformat())
        self.assertTrue(self.lesen(jetzt=self.jetzt + timedelta(seconds=899))["gesund"])
        self.assertEqual(self.lesen(jetzt=self.jetzt + timedelta(seconds=900))["status"], "ausgeblieben")

    def test_fehler_erhaelt_letzten_erfolg(self):
        status_speichern(self.store, {"fehler": []}, self.jetzt)
        status_speichern(self.store, {"fehler": ["Verbindung fehlgeschlagen"]}, self.jetzt + timedelta(minutes=5))
        result = self.lesen(jetzt=self.jetzt + timedelta(minutes=5))
        self.assertEqual(result["status"], "fehler")
        self.assertEqual(result["letzter_erfolg"], self.jetzt.isoformat())

    def test_offen_gesperrt_und_keine_inhalte_im_status(self):
        self.store.state["ziele"] = {"id": {"sku": "123", "html": "VERTRAULICH", "offen": "journal.json"}}
        status_speichern(self.store, {"fehler": ["Bitte prüfen"]}, self.jetzt)
        result = self.lesen()
        self.assertEqual(result["status"], "gesperrt")
        self.assertEqual(result["offene_artikel"], 1)
        self.assertNotIn("VERTRAULICH", (self.store.folder / "status.json").read_text())
        self.store.state["ziele"]["id"]["offen"] = None
        status_speichern(self.store, {"fehler": []}, self.jetzt)
        self.assertEqual(self.lesen()["status"], "offen")

    def test_kaputte_datei_und_zukunft_nicht_gruen(self):
        (self.store.folder / "status.json").write_text("{}")
        self.assertFalse(self.lesen()["gesund"])
        status_speichern(self.store, {"fehler": []}, self.jetzt + timedelta(hours=1))
        self.assertFalse(self.lesen()["gesund"])


class TimeoutTest(unittest.IsolatedAsyncioTestCase):
    async def test_abgebrochener_patch_bleibt_offen_kein_retry(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Speicher(folder)
            async def haengt(*args):
                await asyncio.Event().wait()
            client = SimpleNamespace(
                katalog=AsyncMock(return_value=[{"id": "p", "sku": "123", "parent": None}]),
                lesen=AsyncMock(return_value={"values": []}), schreiben=AsyncMock(side_effect=haengt))
            with self.assertRaises(asyncio.TimeoutError):
                await asyncio.wait_for(abgleichen(client, store, {"123": "FAQ"}), timeout=0.1)
            fresh = Speicher(folder)
            self.assertTrue(fresh.state["ziele"]["p"]["offen"])
            result = await abgleichen(client, fresh, {"123": "FAQ"})
            self.assertTrue(result["fehler"])
            self.assertEqual(client.schreiben.await_count, 1)
