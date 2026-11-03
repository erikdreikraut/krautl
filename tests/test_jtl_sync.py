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
from app.jtl_sync_engine import (Speicher, abgleichen, zielplan, LEERES_ALTATTRIBUT,
    LEERER_KANALWERT, LEERER_KANALWERT_SALBEI, bekannte_leerwertabweichungen)
from app.jtl_sync_service import quellen_bauen, INTERVALL


KATALOG = [{"id": "p", "sku": "VATER", "parent": None},
           {"id": "c", "sku": "KIND", "parent": "p"},
           {"id": "d", "sku": "KIND2", "parent": "p"},
           {"id": "x", "sku": "FREMD", "parent": None}]

for row in KATALOG:
    row.update(isActive=True, isShopActive=True)


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
        self.client = SimpleNamespace(shop_pruefen=AsyncMock(), katalog=AsyncMock(return_value=KATALOG),
            lesen=AsyncMock(side_effect=lesen), schreiben=AsyncMock(side_effect=schreiben))

    async def test_inaktiver_vater_vererbt_nur_an_aktive_kinder(self):
        rows = copy.deepcopy(KATALOG)
        rows[0]["isShopActive"] = False
        rows[1]["isActive"] = False
        self.client.katalog.return_value = rows
        result = await abgleichen(self.client, self.store, {"VATER": "FAQ"})
        self.assertEqual(result["geschrieben"], 1)
        self.assertEqual({c.args[0] for c in self.client.lesen.call_args_list}, {"d"})

    async def test_altauftrag_deaktivieren_und_reaktivieren(self):
        from app.jtl_sync_status import status_speichern, status_laden
        await abgleichen(self.client, self.store, {"VATER": "FAQ"})
        self.store.state["ziele"]["c"]["erledigt"] = None
        rows = copy.deepcopy(KATALOG)
        rows[1]["isShopActive"] = False
        self.client.katalog.return_value = rows
        self.client.lesen.reset_mock()
        self.client.schreiben.reset_mock()
        result = await abgleichen(self.client, self.store, {"VATER": "FAQ"})
        self.client.lesen.assert_not_called()
        self.client.schreiben.assert_not_called()
        self.assertTrue(self.store.state["ziele"]["c"]["ausgesetzt"])
        status_speichern(self.store, result)
        self.assertTrue(status_laden(self.tmp.name, aktiviert=True)["gesund"])
        rows[1]["isShopActive"] = True
        result = await abgleichen(self.client, self.store, {"VATER": "FAQ"})
        self.assertEqual(result["bereits_gleich"], 1)
        self.assertFalse(self.store.state["ziele"]["c"]["ausgesetzt"])

    async def test_deaktivierung_verwirft_keinen_unklaren_schreibversuch(self):
        self.client.schreiben.side_effect = JtlFehler("Timeout")
        await abgleichen(self.client, self.store, {"VATER": "FAQ"})
        journal = self.store.state["ziele"]["p"]["offen"]
        rows = copy.deepcopy(KATALOG)
        rows[0]["isShopActive"] = False
        self.client.katalog.return_value = rows
        result = await abgleichen(self.client, self.store, {"VATER": "FAQ"})
        self.assertTrue(result["fehler"])
        self.assertEqual(self.store.state["ziele"]["p"]["offen"], journal)
        self.assertEqual(self.client.schreiben.await_count, 1)

    async def test_unbekannter_shopstatus_und_shopfehler_sperren(self):
        rows = copy.deepcopy(KATALOG)
        rows[1].pop("isShopActive")
        self.client.katalog.return_value = rows
        with self.assertRaises(JtlFehler):
            await abgleichen(self.client, self.store, {"VATER": "FAQ"})
        self.client.lesen.assert_not_called()
        self.client.shop_pruefen.side_effect = JtlFehler("Mehrere Shops")
        with self.assertRaises(JtlFehler):
            await abgleichen(self.client, self.store, {"VATER": "FAQ"})
        self.client.schreiben.assert_not_called()

    async def test_persistenz_kein_zugriff_ohne_aenderung(self):
        self.assertEqual(INTERVALL, 300)
        result = await abgleichen(self.client, self.store, {"VATER": "<p>FAQ</p>"})
        self.assertEqual(result["geschrieben"], 3)
        for mock in (self.client.katalog, self.client.lesen, self.client.schreiben):
            mock.reset_mock()
        await abgleichen(self.client, Speicher(self.tmp.name), {"VATER": "<p>FAQ</p>"})
        self.client.katalog.assert_awaited_once()
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

    async def test_bekannter_leerverlust_mit_audit_ohne_wiederholung(self):
        self.bestand["p"]["values"].append({"attributeId": LEERES_ALTATTRIBUT,
                                              "defaultValues": [{"value": ""}]})
        original = self.client.schreiben.side_effect
        async def bereinigt(ident, attrs):
            await original(ident, attrs)
            self.bestand[ident]["values"] = [a for a in self.bestand[ident]["values"]
                                              if a["attributeId"] != LEERES_ALTATTRIBUT]
            raise JtlFehler("Antwort verloren")
        self.client.schreiben.side_effect = bereinigt
        await abgleichen(self.client, self.store, {"VATER": "FAQ"})
        journal_name = self.store.state["ziele"]["p"]["offen"]
        original_journal = (self.store.folder / journal_name).read_bytes()
        self.client.schreiben.side_effect = original
        result = await abgleichen(self.client, Speicher(self.tmp.name), {"VATER": "FAQ"})
        self.assertFalse(result["fehler"])
        state = Speicher(self.tmp.name).state
        self.assertIsNone(state["ziele"]["p"]["offen"])
        self.assertTrue((self.store.folder / state["ziele"]["p"]["leerwert_nachweis"]).exists())
        self.assertEqual(original_journal, (self.store.folder / journal_name).read_bytes())
        self.assertEqual([c.args[0] for c in self.client.schreiben.call_args_list], ["p", "c", "d"])

    async def test_bekannter_leerverlust_beim_ersten_ruecklesen(self):
        self.bestand["p"]["values"].append({"attributeId": LEERES_ALTATTRIBUT,
                                              "defaultValues": [{"value": ""}]})
        original = self.client.schreiben.side_effect
        async def bereinigt(ident, attrs):
            await original(ident, attrs)
            self.bestand[ident]["values"] = [a for a in self.bestand[ident]["values"]
                                              if a["attributeId"] != LEERES_ALTATTRIBUT]
        self.client.schreiben.side_effect = bereinigt
        result = await abgleichen(self.client, self.store, {"VATER": "FAQ"})
        self.assertFalse(result["fehler"])
        self.assertEqual(result["geschrieben"], 3)
        self.assertTrue(self.store.state["ziele"]["p"]["leerwert_nachweis"])

    def test_kein_pauschales_ignorieren_leerer_werte(self):
        for ident, value in (("fremd", ""), (LEERES_ALTATTRIBUT, " "),
                             (LEERES_ALTATTRIBUT, None), (LEERES_ALTATTRIBUT, "wichtig")):
            with self.subTest(ident=ident, value=value):
                vorher = {"values": [{"attributeId": ident, "defaultValues": [{"value": value}]}]}
                soll = zielattribute(vorher, "FAQ")
                ist = zielattribute({"values": []}, "FAQ")
                self.assertEqual(bekannte_leerwertabweichungen(vorher, soll, ist), [])

    def test_bekannte_abweichung_entschuldigt_keinen_faq_verlust(self):
        vorher = {"values": [{"attributeId": LEERES_ALTATTRIBUT, "defaultValues": [{"value": ""}]}]}
        soll = zielattribute(vorher, "FAQ")
        self.assertEqual(bekannte_leerwertabweichungen(vorher, soll, {"values": []}), [])
        self.assertEqual(bekannte_leerwertabweichungen(vorher, soll,
                         zielattribute({"values": []}, "anderer Text")), [])

    def test_nur_bekannter_kanalwert_darf_fehlen(self):
        ident, kanal, sprache = LEERER_KANALWERT
        vorher = {"values": [{"attributeId": ident, "salesChannelValues": [
            {"salesChannelId": kanal, "values": [{"languageIso": sprache, "value": ""},
                                                {"languageIso": "en", "value": "keep"}]}]}]}
        soll = zielattribute(vorher, "FAQ")
        ist = copy.deepcopy(soll)
        ist["values"][0]["salesChannelValues"][0]["values"].pop(0)
        self.assertEqual(bekannte_leerwertabweichungen(vorher, soll, ist), [LEERER_KANALWERT])
        ist["values"][0]["salesChannelValues"][0]["values"] = []
        self.assertEqual(bekannte_leerwertabweichungen(vorher, soll, ist), [])

    async def test_salbei_leerwert_ruecklesen_ohne_neuen_patch(self):
        ident, kanal, sprache = LEERER_KANALWERT_SALBEI
        self.bestand["p"]["values"].append({"attributeId": ident,
            "salesChannelValues": [{"salesChannelId": kanal,
                "values": [{"languageIso": sprache, "value": ""}]}]})
        original = self.client.schreiben.side_effect
        async def bereinigt(item, attrs):
            await original(item, attrs)
            for a in self.bestand[item]["values"]:
                if a["attributeId"] == ident:
                    a["salesChannelValues"][0]["values"] = []
            raise JtlFehler("Antwort verloren")
        self.client.schreiben.side_effect = bereinigt
        await abgleichen(self.client, self.store, {"VATER": "FAQ"})
        self.client.schreiben.side_effect = original
        result = await abgleichen(self.client, self.store, {"VATER": "FAQ"})
        self.assertFalse(result["fehler"])
        self.assertEqual([c.args[0] for c in self.client.schreiben.call_args_list], ["p", "c", "d"])
        self.assertIsNone(self.store.state["ziele"]["p"]["offen"])
        self.assertTrue(self.store.state["ziele"]["p"]["leerwert_nachweis"])

    def test_salbei_keine_ausnahme_fuer_inhalte_oder_andere_kanaele(self):
        ident, _, _ = LEERER_KANALWERT_SALBEI
        for kanal, sprache, value in [("1-1-0", "de", "Inhalt"),
                ("1-1-0", "de", None), ("1-1-0", "de", " "),
                ("2-2-1", "de", ""), ("1-1-0", "en", "")]:
            vorher = {"values": [{"attributeId": ident, "salesChannelValues": [
                {"salesChannelId": kanal, "values": [{"languageIso": sprache, "value": value}]}]}]}
            soll = zielattribute(vorher, "FAQ")
            ist = copy.deepcopy(soll)
            ist["values"][0]["salesChannelValues"][0]["values"] = []
            self.assertEqual(bekannte_leerwertabweichungen(vorher, soll, ist), [])

    async def test_fehlende_sku_stoppt_vor_schreiben(self):
        with self.assertRaises(JtlFehler):
            await abgleichen(self.client, self.store, {"NICHTVORHANDEN": "FAQ"})
        self.client.schreiben.assert_not_called()

    def test_keine_prefix_vererbung(self):
        katalog = KATALOG + [{"id": "falsch", "sku": "VATER-2", "parent": None, "isActive": True, "isShopActive": True}]
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
