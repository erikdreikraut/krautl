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
from scripts.teste_jtl_spirulina_kind import testen, SKU


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
                    return httpx.Response(200, json={"data": {"ChangeItem": {"__typename": "ChangeItemCommandResponse"}}})
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
