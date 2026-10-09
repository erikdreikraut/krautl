import copy
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx

from app.jtl_client import JtlFehler
from app.jtl_faq_test import TENANT, zielattribute
from scripts.teste_jtl_spirulina_kind import testen, SKU, KURZTEXT


def typ(name):
    if name.endswith("!"):
        return {"kind": "NON_NULL", "ofType": typ(name[:-1])}
    if name.startswith("["):
        return {"kind": "LIST", "ofType": typ(name[1:-1])}
    return {"kind": "SCALAR" if name in ("ID", "String") else "INPUT_OBJECT", "name": name}


SCHEMA = {"ChangeItemCommandRequestInput": {"itemId": "ID!", "attributes": "Attributes"},
          "Attributes": {"values": "[Attribute]"},
          "Attribute": {"attributeId": "ID!", "salesChannelValues": "[Channel]"},
          "Channel": {"salesChannelId": "ID!", "values": "[Value]"},
          "Value": {"languageIso": "String!", "value": "String!"}}


class KindTest(unittest.IsolatedAsyncioTestCase):
    async def test_transport_ruecklesen_und_sicherung(self):
        for transport, kurztext in (("graphql", True), ("rest", True), ("rest", False)):
            html = '<div itemscope itemtype="https://schema.org/FAQPage">Fragen &amp; Antworten</div>' * 250
            inhalt = KURZTEXT if kurztext else html
            for uebernommen in (False, True):
                vorher = zielattribute({"values": [{"attributeId": "other",
                    "defaultValues": [{"value": "neutral"}]}]}, "alter Inhalt")
                state = copy.deepcopy(vorher)
                schema = {"data": {"__schema": {"types": [
                    {"name": n, "inputFields": [{"name": k, "type": typ(v)} for k, v in fields.items()]}
                    for n, fields in SCHEMA.items()]}}}
                async def lesen(sku):
                    self.assertEqual(sku, SKU)
                    return {"id": "child-id", "attributes": copy.deepcopy(state)}
                with tempfile.TemporaryDirectory() as tmp:
                    journal = Path(tmp) / "kurz.json"
                    async def senden(url, **kwargs):
                        nonlocal state
                        self.assertEqual(json.loads(journal.read_text())["vorher"], vorher)
                        payload = kwargs["json"]
                        request = payload if transport == "rest" else payload["variables"]["request"]
                        self.assertEqual(request["attributes"], zielattribute({"values": []}, inhalt))
                        self.assertEqual(url.rsplit("/", 1)[-1], "child-id" if transport == "rest" else "graphql")
                        if transport == "rest":
                            self.assertEqual(set(payload), {"attributes"})
                        if uebernommen:
                            state = zielattribute(vorher, inhalt)
                        result = {"item": {"id": "child-id"}}
                        return httpx.Response(200, json=result if transport == "rest" else {"data": {"ChangeItem": result}})
                    client = SimpleNamespace(tenant_id=TENANT, client_secret="secret", artikel_lesen=lesen,
                        _token=AsyncMock(return_value="token"), _lesen=AsyncMock(return_value=schema),
                        http=SimpleNamespace(post=AsyncMock(side_effect=senden), patch=AsyncMock(side_effect=senden)))
                    result = await testen(client, html, journal, True, kurztext=kurztext, transport=transport)
                    self.assertEqual(result["test_erfolgreich"], uebernommen)
                    self.assertTrue(result["ruecklesepruefung"]["andere_bestandswerte_erhalten"])
                    with self.assertRaisesRegex(JtlFehler, "Journal"):
                        await testen(client, html, journal, True, kurztext=kurztext, transport=transport)
                    self.assertEqual(client.http.post.await_count + client.http.patch.await_count, 1)

    async def test_kurztext_ohne_zugeordnete_werte_schreibt_nicht(self):
        client = SimpleNamespace(tenant_id=TENANT,
            artikel_lesen=AsyncMock(return_value={"id": "child-id", "attributes": {"values": []}}))
        with self.assertRaisesRegex(JtlFehler, "vorhandenen"):
            await testen(client, "ignored", "unused", True, kurztext=True)

    async def test_ergebnisversuch_bewahrt_original_und_sperrt_wiederholung(self):
        vorher = {"values": []}
        request = {"itemId": "child-id", "attributes": zielattribute(vorher, "FAQ")}
        daten = {"tenant": TENANT, "artikelnummer": SKU, "artikel_id": "child-id", "vorher": vorher,
                 "ziel": request["attributes"], "request": request, "idempotency_key": "original"}
        schema = {"data": {"__schema": {"types": [
            {"name": n, "inputFields": [{"name": k, "type": typ(v)} for k,v in fields.items()]}
            for n,fields in SCHEMA.items()]}}}
        client = SimpleNamespace(tenant_id=TENANT, client_secret="secret",
            artikel_lesen=AsyncMock(return_value={"id":"child-id", "attributes":vorher}),
            _lesen=AsyncMock(return_value=schema), _token=AsyncMock(return_value="token"),
            http=SimpleNamespace(post=AsyncMock(return_value=httpx.Response(200,
                json={"data":{"ChangeItem":{"__typename":"ChangeItemCommandResponse"}}}))))
        with tempfile.TemporaryDirectory() as tmp:
            journal = Path(tmp)/'kind.json'
            journal.write_text(json.dumps(daten), encoding='utf-8')
            result = await testen(client, 'FAQ', journal, ergebnis_test=True)
            self.assertFalse(result['api_erfolg'])
            self.assertFalse(result['test_erfolgreich'])
            self.assertEqual(json.loads(journal.read_text()), daten)
            self.assertEqual(client.http.post.await_args.kwargs['headers']['Idempotency-Key'], 'original')
            with self.assertRaises(FileExistsError):
                await testen(client, 'FAQ', journal, ergebnis_test=True)
            self.assertEqual(client.http.post.await_count,1)

    async def test_teilupdate_erhaelt_oder_erkennt_verlust_und_keine_wiederholung(self):
        for ersetzt in (False, True):
            vorher = {"values": [{"attributeId": "other", "defaultValues": [{"value": "neutral"}]}]}
            state = copy.deepcopy(vorher)
            async def lesen(sku):
                self.assertEqual(sku, SKU)
                return {"id": "child-id", "attributes": copy.deepcopy(state)}
            schema = {"data": {"__schema": {"types": [
                {"name": n, "inputFields": [{"name": k, "type": typ(v)} for k, v in fields.items()]}
                for n, fields in SCHEMA.items()]}}}
            with tempfile.TemporaryDirectory() as tmp:
                journal = Path(tmp) / "kind.json"
                async def post(url, **kwargs):
                    nonlocal state
                    self.assertTrue(journal.exists())
                    request = kwargs["json"]["variables"]["request"]
                    self.assertEqual(request["itemId"], "child-id")
                    self.assertEqual(len(request["attributes"]["values"]), 2)
                    self.assertNotIn("neutral", json.dumps(request))
                    state = request["attributes"] if ersetzt else zielattribute(vorher, "FAQ")
                    self.assertIn("item { id }", kwargs["json"]["query"])
                    return httpx.Response(200, json={"data": {"ChangeItem": {"item": {"id": "child-id"}}}})
                client = SimpleNamespace(tenant_id=TENANT, client_secret="secret", artikel_lesen=lesen,
                    _token=AsyncMock(return_value="token"), _lesen=AsyncMock(return_value=schema),
                    http=SimpleNamespace(post=AsyncMock(side_effect=post)))
                await testen(client, "FAQ", journal)
                client.http.post.assert_not_awaited()
                self.assertFalse(journal.exists())
                result = await testen(client, "FAQ", journal, True)
                self.assertEqual(result["test_erfolgreich"], not ersetzt)
                self.assertEqual(result["ruecklesepruefung"]["andere_bestandswerte_erhalten"], not ersetzt)
                self.assertEqual(json.loads(journal.read_text())["vorher"], vorher)
                with self.assertRaisesRegex(JtlFehler, "Journal"):
                    await testen(client, "FAQ", journal, True)
                self.assertEqual(client.http.post.await_count, 1)

    async def test_falscher_tenant_schreibt_nicht(self):
        client = SimpleNamespace(tenant_id="falsch")
        with self.assertRaisesRegex(JtlFehler, "Tenant"):
            await testen(client, "FAQ", "unused", True)
