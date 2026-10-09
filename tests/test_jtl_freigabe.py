import copy
import json
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.jtl_client import JtlFehler
from app.jtl_faq_test import zielattribute
from app.jtl_sync_engine import Speicher, digest
from scripts.freigabe_jtl_20015 import ATTR, ITEM, JOURNAL, freigeben


class FreigabeTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Speicher(self.tmp.name)
        self.vorher = {"values": [{"attributeId": ATTR, "defaultValues": [{"value": ""}]},
                                  {"attributeId": "anderes", "defaultValues": [{"value": "erhalten"}]}]}
        self.journal = {"id": ITEM, "sku": "20015", "vorher": self.vorher,
            "nachher": zielattribute(self.vorher, "FAQ"),
            "revision": digest({"sku": "20015", "html": "FAQ"})}
        self.store.state.update(api_url="https://wawi/api/eazybusiness", ziele={ITEM: {
            "sku": "20015", "html": "FAQ", "offen": JOURNAL}})
        self.store.speichern()
        (self.store.folder / JOURNAL).write_text(json.dumps(self.journal), encoding="utf-8")
        self.aktuell = copy.deepcopy(self.journal["nachher"])
        self.aktuell["values"] = [a for a in self.aktuell["values"] if a["attributeId"] != ATTR]
        self.client = SimpleNamespace(url=self.store.state["api_url"], lesen=AsyncMock(return_value=self.aktuell))

    async def test_freigabe_mit_unveraendertem_originaljournal(self):
        original = (self.store.folder / JOURNAL).read_bytes()
        await freigeben(self.client, self.store)
        self.assertEqual(self.store.state["ziele"][ITEM]["offen"], JOURNAL)
        result = await freigeben(self.client, self.store, True)
        self.assertTrue(result["angewendet"])
        self.assertEqual((self.store.folder / JOURNAL).read_bytes(), original)
        self.assertIsNone(Speicher(self.tmp.name).state["ziele"][ITEM]["offen"])
        with self.assertRaises(JtlFehler):
            await freigeben(self.client, self.store, True)

    async def test_zusaetzlicher_verlust_bleibt_gesperrt(self):
        self.aktuell["values"] = self.aktuell["values"][1:]
        with self.assertRaises(JtlFehler):
            await freigeben(self.client, self.store, True)
        self.assertEqual(Speicher(self.tmp.name).state["ziele"][ITEM]["offen"], JOURNAL)

    async def test_anderer_vorgang_bleibt_gesperrt(self):
        self.store.state["ziele"][ITEM]["offen"] = "anderer-versuch.json"
        with self.assertRaises(JtlFehler):
            await freigeben(self.client, self.store, True)
        self.client.lesen.assert_not_called()

    async def test_nichtleeres_attribut_nicht_freigeben(self):
        self.journal["vorher"]["values"][0]["defaultValues"][0]["value"] = "wichtig"
        (self.store.folder / JOURNAL).write_text(json.dumps(self.journal), encoding="utf-8")
        with self.assertRaises(JtlFehler):
            await freigeben(self.client, self.store, True)
