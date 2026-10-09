import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

import httpx

from app.jtl_client import JtlClient, JtlFehler
from app.jtl_faq_test import TENANT, SKU, ITEM, NAME, INHALT, KANAL, TITEL, zielattribute, signatur, uebertragen, pruefen, antwortdiagnose, diagnose403


class FaqSchreibtest(unittest.IsolatedAsyncioTestCase):
    def test_diagnose_entfernt_geheimnisse_und_liest_html_titel(self):
        d = antwortdiagnose(httpx.Response(403, json={"message": "TOKEN SECRET", "access_token": "TOKEN"}), ["TOKEN", "SECRET"])
        self.assertNotIn("TOKEN", json.dumps(d))
        self.assertNotIn("SECRET", json.dumps(d))
        d = antwortdiagnose(httpx.Response(403, text='<html><title>Blocked</title>private</html>'), [])
        self.assertEqual(d["html_titel"], "Blocked")
        self.assertNotIn("private", json.dumps(d))

    async def test_diagnose403_nur_originalauftrag_und_einmal(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as tmp:
            journal = Path(tmp) / 'journal.json'
            daten = {"tenant": TENANT, "artikel_id": ITEM, "idempotency_key": "original",
                     "vorher": self.vorher, "nachher": zielattribute(self.vorher, "FAQ")}
            journal.write_text(json.dumps(daten), encoding="utf-8")
            client = SimpleNamespace(tenant_id=TENANT, client_secret="secret", _token=AsyncMock(return_value="token"),
                artikel_lesen=AsyncMock(return_value={"id": ITEM, "attributes": self.vorher}),
                http=SimpleNamespace(patch=AsyncMock(return_value=httpx.Response(403, json={"code":"Forbidden"}))))
            with self.assertRaisesRegex(JtlFehler, "FAQ-Auswahl"):
                await diagnose403(client, "GEAENDERT", journal)
            client.http.patch.assert_not_awaited()
            with self.assertRaisesRegex(JtlFehler, "Forbidden"):
                await diagnose403(client, "FAQ", journal)
            self.assertEqual(client.http.patch.await_args.kwargs["headers"]["Idempotency-Key"], "original")
            self.assertEqual(client.http.patch.await_args.kwargs["json"], {"attributes": daten["nachher"]})
            with self.assertRaises(FileExistsError):
                await diagnose403(client, "FAQ", journal)
            self.assertEqual(client.http.patch.await_count, 1)
            self.assertEqual(json.loads(journal.read_text()), daten)
            self.assertEqual(len(list(Path(tmp).glob('*.antwort-*.json'))), 1)

    def setUp(self):
        self.vorher = {"values": [
            {"attributeId": "anderes", "defaultValues": [{"languageIso": None, "value": "24"}]},
            {"attributeId": NAME, "defaultValues": [{"languageIso": "de", "value": "Standard bleibt"}],
             "salesChannelValues": [
                 {"salesChannelId": KANAL, "values": [{"languageIso": "en", "value": "English"}, {"languageIso": "de", "value": "Alt"}]},
                 {"salesChannelId": "1-1-0", "values": [{"languageIso": "de", "value": "Anderer Kanal"}]}]}]}

    def test_nur_zwei_zielwerte_aendern_und_fehlendes_attribut_ergaenzen(self):
        kopie = copy.deepcopy(self.vorher)
        ziel = zielattribute(self.vorher, "<p>FAQ</p>")
        alt, neu = signatur(self.vorher), signatur(ziel)
        for key, wert in alt.items():
            if key != (NAME, KANAL, "de"):
                self.assertEqual(neu[key], wert)
        self.assertEqual(neu[(NAME, KANAL, "de")], TITEL)
        self.assertEqual(neu[(INHALT, KANAL, "de")], "<p>FAQ</p>")
        self.assertEqual(self.vorher, kopie)
        self.assertEqual(zielattribute(ziel, "<p>FAQ</p>"), ziel)
        self.assertEqual(signatur(zielattribute(ziel, ""))[(NAME, KANAL, "de")], "")

    def test_duplikate_werden_abgelehnt(self):
        with self.assertRaises(JtlFehler):
            zielattribute({"values": self.vorher["values"] * 2}, "FAQ")

    async def test_vorschau_schreiben_ruecklesen_und_timeout_ohne_retry(self):
        for timeout in (False, True):
            state = copy.deepcopy(self.vorher)
            patches = []
            def antwort(req):
                nonlocal state
                if req.url.path.endswith('/token'):
                    return httpx.Response(200, json={"access_token": "secret", "expires_in": 3600})
                if req.url.path.endswith('/graphql'):
                    return httpx.Response(200, json={"data": {"QueryItems": {"nodes": [{"id": ITEM, "sku": SKU}], "pageInfo": {"hasNextPage": False}}}})
                if req.method == "PATCH":
                    self.assertEqual(req.url.path, "/erp/v2/items/" + ITEM)
                    self.assertTrue(req.headers['Idempotency-Key'])
                    self.assertTrue(journal.exists())
                    patches.append(req)
                    payload = json.loads(req.content)
                    self.assertEqual(set(payload), {"attributes"})
                    state = payload["attributes"]
                    if timeout:
                        raise httpx.ReadTimeout("private", request=req)
                    return httpx.Response(200, json={})
                return httpx.Response(200, json={"id": ITEM, "identifiers": {"sku": SKU}, "attributes": state})
            with tempfile.TemporaryDirectory() as tmp:
                journal = Path(tmp) / 'journal.json'
                async with JtlClient("test", "secret", TENANT, httpx.MockTransport(antwort)) as client:
                    await uebertragen(client, "FAQ", journal)
                    self.assertEqual(patches, [])
                    self.assertFalse(journal.exists())
                    if timeout:
                        with self.assertRaisesRegex(JtlFehler, "unklar"):
                            await uebertragen(client, "FAQ", journal, True)
                    else:
                        result = await uebertragen(client, "FAQ", journal, True)
                        self.assertIn("Erfolgreich", result["ergebnis"])
                    self.assertEqual(len(patches), 1)
                    self.assertIn("Erfolgreich", await pruefen(client, journal))
                    self.assertNotIn("secret", journal.read_text())
                    with self.assertRaisesRegex(JtlFehler, "Journal|journal"):
                        await uebertragen(client, "NEUER INHALT", journal, True)
                    self.assertEqual(len(patches), 1)
                    state["values"][0]["defaultValues"][0]["value"] = "VERLOREN"
                    with self.assertRaisesRegex(JtlFehler, "weicht"):
                        await pruefen(client, journal)

    async def test_falscher_tenant_verhindert_zugriff(self):
        def antwort(req):
            self.fail("Kein Netzwerkzugriff bei falschem Tenant")
        async with JtlClient("test", "secret", "11111111-1111-4111-8111-111111111111", httpx.MockTransport(antwort)) as client:
            with self.assertRaisesRegex(JtlFehler, "Tenant"):
                await uebertragen(client, "FAQ", "unused")
