import copy
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")

import httpx

from app.jtl_client import JtlFehler
from app.jtl_faq_test import signatur, zielattribute
from app.jtl_onprem import OnPremClient
from app.jtl_sync_engine import Speicher, abgleichen, zielplan
from app.jtl_sync_service import quellen_bauen, INTERVALL


KATALOG = [{"id": "p", "sku": "VATER", "parent": None},
           {"id": "c", "sku": "KIND", "parent": "p"},
           {"id": "d", "sku": "KIND2", "parent": "p"},
           {"id": "x", "sku": "FREMD", "parent": None}]


class SyncTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Speicher(self.tmp.name)
        self.bestand = {item["id"]: {"values": [{"attributeId": "fremd",
            "defaultValues": [{"value": "sprachneutral"}],
            "salesChannelValues": [{"salesChannelId": "andererShop",
                                    "values": [{"languageIso": "en", "value": "retain"}]}]}]}
            for item in KATALOG}
        async def lesen(ident, sku):
            self.assertEqual(sku, next(i["sku"] for i in KATALOG if i["id"] == ident))
            return copy.deepcopy(self.bestand[ident])
        async def schreiben(ident, attrs):
            self.assertEqual(len(attrs["values"]), 2)
            # The durable pending marker must precede each write.
            fresh = Speicher(self.tmp.name)
            self.assertTrue(fresh.state["ziele"][ident]["offen"])
            for a in attrs["values"]:
                self.assertEqual(a["salesChannelValues"][0]["salesChannelId"], "2-2-1")
                self.assertEqual(a["salesChannelValues"][0]["values"][0]["languageIso"], "de")
            html = attrs["values"][1]["salesChannelValues"][0]["values"][0]["value"]
            self.bestand[ident] = zielattribute(self.bestand[ident], html)
        self.client = SimpleNamespace(katalog=AsyncMock(return_value=KATALOG),
            lesen=AsyncMock(side_effect=lesen), schreiben=AsyncMock(side_effect=schreiben))

    async def test_persistenz_kein_zugriff_ohne_aenderung(self):
        self.assertEqual(INTERVALL, 300)
        result = await abgleichen(self.client, self.store, {"VATER": "<p>FAQ</p>"})
        self.assertEqual(result["geschrieben"], 3)
        for mock in (self.client.katalog, self.client.lesen, self.client.schreiben):
            mock.reset_mock()
        await abgleichen(self.client, Speicher(self.tmp.name), {"VATER": "<p>FAQ</p>"})
        self.client.katalog.assert_not_called()
        self.client.lesen.assert_not_called()
        self.client.schreiben.assert_not_called()

    async def test_varianten_eigene_faq_vorrang_und_nur_geaenderte(self):
        await abgleichen(self.client, self.store, {"VATER": "alt", "KIND": "eigene"})
        self.client.schreiben.reset_mock()
        await abgleichen(self.client, self.store, {"VATER": "neu", "KIND": "eigene"})
        self.assertEqual([c.args[0] for c in self.client.schreiben.call_args_list], ["p", "d"])
        self.client.schreiben.reset_mock()
        await abgleichen(self.client, self.store, {"VATER": "neu"})
        self.assertEqual([c.args[0] for c in self.client.schreiben.call_args_list], ["c"])

    async def test_letzte_faq_entfernt_leert_beide_werte(self):
        await abgleichen(self.client, self.store, {"VATER": "alt"})
        self.client.schreiben.reset_mock()
        result = await abgleichen(self.client, self.store, {})
        self.assertEqual(result["geschrieben"], 3)
        for call in self.client.schreiben.call_args_list:
            for a in call.args[1]["values"]:
                self.assertEqual(a["salesChannelValues"][0]["values"][0]["value"], "")
        self.assertEqual(len(self.bestand["x"]["values"]), 1)

    async def test_gleicher_bestand_keine_schreibzugriffe(self):
        for ident in ("p", "c", "d"):
            self.bestand[ident] = zielattribute(self.bestand[ident], "FAQ")
        result = await abgleichen(self.client, self.store, {"VATER": "FAQ"})
        self.assertEqual(result["bereits_gleich"], 3)
        self.client.schreiben.assert_not_called()

    async def test_timeout_nie_blind_wiederholen(self):
        self.client.schreiben.side_effect = JtlFehler("Timeout")
        result = await abgleichen(self.client, self.store, {"VATER": "FAQ"})
        self.assertTrue(result["fehler"])
        await abgleichen(self.client, Speicher(self.tmp.name), {"VATER": "neuer FAQ"})
        self.assertEqual(self.client.schreiben.await_count, 1)

    async def test_timeout_nach_erfolg_wird_durch_lesen_aufgeloest(self):
        original = self.client.schreiben.side_effect
        async def timeout(ident, attrs):
            await original(ident, attrs)
            raise JtlFehler("Timeout nach Übernahme")
        self.client.schreiben.side_effect = timeout
        await abgleichen(self.client, self.store, {"VATER": "FAQ"})
        self.client.schreiben.side_effect = original
        result = await abgleichen(self.client, Speicher(self.tmp.name), {"VATER": "FAQ"})
        self.assertFalse(result["fehler"])
        self.assertEqual([c.args[0] for c in self.client.schreiben.call_args_list], ["p", "c", "d"])

    async def test_verlust_stoppt_weitere_artikel(self):
        async def verlust(ident, attrs):
            self.bestand[ident] = attrs
        self.client.schreiben.side_effect = verlust
        result = await abgleichen(self.client, self.store, {"VATER": "FAQ"})
        self.assertTrue(result["fehler"])
        self.assertEqual(self.client.schreiben.await_count, 1)

    async def test_fehlende_sku_stoppt_vor_schreiben(self):
        with self.assertRaises(JtlFehler):
            await abgleichen(self.client, self.store, {"NICHTVORHANDEN": "FAQ"})
        self.client.schreiben.assert_not_called()

    def test_keine_prefix_vererbung(self):
        katalog = KATALOG + [{"id": "falsch", "sku": "VATER-2", "parent": None}]
        self.assertNotIn("falsch", zielplan({"VATER": "FAQ"}, katalog))

    def test_auswahl_google_und_entwurf_unabhaengig(self):
        p = SimpleNamespace(id=1, artikelnummer="VATER")
        faq = SimpleNamespace(id=1, produkt_id=1, aktiv=True, status="freigegeben",
            sortierung=0, kategorie="FAQ", frage="Was?", antwort="Antwort", include_in_google_product_qa=False)
        original = quellen_bauen([p], [faq])
        faq.include_in_google_product_qa = True
        self.assertEqual(quellen_bauen([p], [faq]), original)
        faq.status = "entwurf"
        self.assertEqual(quellen_bauen([p], [faq]), {})


class ClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_https_pflicht_und_pagination(self):
        with self.assertRaises(JtlFehler):
            OnPremClient("http://example.org/api/eazybusiness", "secret")
        async def handler(request):
            self.assertEqual(request.headers["authorization"], "Wawi secret")
            page = int(request.url.params["pageNumber"])
            return httpx.Response(200, json={"items": [{"id": f"00000000-0000-0000-0000-{page:012}",
                "sKU": str(page), "parentItemId": None}], "pageNumber": page,
                "totalItems": 2, "hasNextPage": page == 1})
        async with OnPremClient("https://example.org/api/eazybusiness", "secret",
                                transport=httpx.MockTransport(handler)) as client:
            self.assertEqual(len(await client.katalog()), 2)

    async def test_redirect_nicht_verfolgen(self):
        async def handler(request):
            return httpx.Response(302, headers={"location": "https://other.example/"})
        async with OnPremClient("https://example.org/api/eazybusiness", "secret",
                                transport=httpx.MockTransport(handler)) as client:
            with self.assertRaisesRegex(JtlFehler, "HTTP 302"):
                await client.katalog()
