import unittest
from unittest.mock import AsyncMock
from types import SimpleNamespace

from scripts.pruefe_jtl_schreibschema import validiere, pruefe
from app.jtl_faq_test import TENANT, ITEM, zielattribute


STRING = {"kind": "SCALAR", "name": "String"}
REQUIRED = {"kind": "NON_NULL", "ofType": STRING}


class SchreibschemaTest(unittest.IsolatedAsyncioTestCase):
    def test_null_und_falsche_typen(self):
        self.assertEqual(validiere(None, STRING, {}), [])
        self.assertIn("null", validiere(None, REQUIRED, {})[0]["fehler"])
        self.assertTrue(validiere(123, STRING, {}))
        self.assertEqual(validiere("de", REQUIRED, {}), [])

    def test_verschachtelte_felder_und_pflichtfelder(self):
        typen = {"Wert": {"inputFields": [{"name": "languageIso", "type": REQUIRED, "defaultValue": None}]}}
        typ = {"kind": "LIST", "ofType": {"kind": "INPUT_OBJECT", "name": "Wert"}}
        fehler = validiere([{"languageIso": None}, {"fremd": "privater Wert"}], typ, typen)
        self.assertEqual(len(fehler), 3)
        self.assertEqual(fehler[0]["pfad"], "request[0].languageIso")
        self.assertNotIn("privater Wert", str(fehler))

    async def test_nur_introspektion_ohne_attributwerte(self):
        typen = [{"name": "ChangeItemCommandRequestInput", "kind": "INPUT_OBJECT", "inputFields": [
            {"name": "itemId", "type": STRING},
            {"name": "attributes", "type": {"kind": "INPUT_OBJECT", "name": "UpdateItemAttributesInput"}}]},
            {"name": "UpdateItemAttributesInput", "kind": "INPUT_OBJECT", "inputFields": []}]
        client = SimpleNamespace(tenant_id=TENANT, _lesen=AsyncMock(return_value={"data": {"__schema": {"types": typen}}}))
        daten = {"tenant": TENANT, "artikel_id": ITEM, "vorher": {"values": []},
                 "nachher": zielattribute({"values": []}, "PRIVATE-HTML")}
        result = await pruefe(client, daten)
        self.assertFalse(result["mutation_ausgefuehrt"])
        args = client._lesen.await_args.args
        self.assertEqual(args[0], "/v2/graphql")
        self.assertTrue(args[1]["query"].startswith("query { __schema"))
        self.assertNotIn("PRIVATE-HTML", str(args))
        self.assertNotIn("PRIVATE-HTML", str(result))
