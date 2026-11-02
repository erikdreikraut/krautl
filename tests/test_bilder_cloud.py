import copy
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx

from scripts.teste_bilder_cloud import TENANT, images, target, run


def detail():
    rows = [{"blobIdentifier": f"00000000-0000-4000-8000-{i:012d}",
             "sortNumber": i, "isMainImage": i == 1} for i in (1, 2, 3)]
    return {"id": "00000000-0000-4000-8000-000000000040", "identifiers": {"sku": "1036"},
            "images": {"defaultImages": copy.deepcopy(rows), "platformImages": [],
                       "saleschannelImages": [{"saleschannelId": "2-2-1", "images": copy.deepcopy(rows)},
                                              {"saleschannelId": "1-1-0", "images": copy.deepcopy(rows)},
                                              {"saleschannelId": "9-7-8-0", "images": copy.deepcopy(rows)}],
                       "ebayImages": []}}


class CloudTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.current = detail()
        self.calls = []

        async def get(sku):
            self.assertEqual(sku, "1036")
            return copy.deepcopy(self.current)

        async def patch(url, *, headers, json):
            self.assertTrue((self.folder / (self.mode + ".intent.json")).exists())
            self.calls.append(copy.deepcopy(json))
            self.current["images"] = copy.deepcopy(json["images"])
            return httpx.Response(200)

        self.client = SimpleNamespace(tenant_id=TENANT, artikel_lesen=get,
                                      _token=AsyncMock(return_value="secret"),
                                      http=SimpleNamespace(patch=patch))
        self.mode = "ausfuehren"

    async def prepare(self):
        return await run(self.client, self.folder, "vorbereiten")

    async def test_prepare_has_no_write_and_preserves_original(self):
        result = await self.prepare()
        self.assertEqual(result["zustand"], "ORIGINAL")
        self.assertEqual(self.calls, [])
        self.assertEqual(json.loads((self.folder / "plan.json").read_text())["detail_backup"], detail())

    async def test_real_change_readback_and_explicit_restore(self):
        await self.prepare()
        result = await run(self.client, self.folder, self.mode)
        self.assertTrue(result["zuordnungen_bestaetigt"])
        self.assertEqual(result["zustand"], "ZIEL")
        before = images(detail())
        sent = self.calls[0]["images"]
        self.assertEqual(sent["defaultImages"], before["defaultImages"])
        self.assertEqual(sent["saleschannelImages"][1], before["saleschannelImages"][1])
        self.assertEqual(sent["saleschannelImages"][0]["images"][0]["sortNumber"], 2)
        self.assertEqual(sent["saleschannelImages"][0]["images"][1]["sortNumber"], 1)
        self.assertNotIn("9-7-8-0", json.dumps(sent))
        self.mode = "zuruecksetzen"
        result = await run(self.client, self.folder, self.mode)
        self.assertTrue(result["zuordnungen_bestaetigt"])
        self.assertEqual(images(self.current), before)

    async def test_success_http_without_change_is_not_success(self):
        await self.prepare()
        self.client.http.patch = AsyncMock(return_value=httpx.Response(201))
        result = await run(self.client, self.folder, self.mode)
        self.assertFalse(result["zuordnungen_bestaetigt"])
        with self.assertRaisesRegex(ValueError, "bereits protokolliert"):
            await run(self.client, self.folder, self.mode)
        self.assertEqual(self.client.http.patch.await_count, 1)

    async def test_lost_reply_readback_and_no_repeat(self):
        await self.prepare()
        original = self.client.http.patch

        async def lost(*args, **kwargs):
            await original(*args, **kwargs)
            raise httpx.ReadTimeout("timeout")

        self.client.http.patch = lost
        result = await run(self.client, self.folder, self.mode)
        self.assertTrue(result["zuordnungen_bestaetigt"])
        with self.assertRaises(ValueError):
            await run(self.client, self.folder, self.mode)
        self.assertEqual(len(self.calls), 1)

    async def test_other_channel_change_blocks_restore(self):
        await self.prepare()
        await run(self.client, self.folder, self.mode)
        self.current["images"]["defaultImages"][0]["sortNumber"] = 9
        with self.assertRaisesRegex(ValueError, "Ausgangsstand"):
            await run(self.client, self.folder, "zuruecksetzen")
        self.assertEqual(len(self.calls), 1)

    async def test_foreign_tenant_and_modified_plan_block(self):
        await self.prepare()
        self.client.tenant_id = "other"
        with self.assertRaises(ValueError):
            await run(self.client, self.folder, self.mode)
        self.client.tenant_id = TENANT
        p = self.folder / "plan.json"
        plan = json.loads(p.read_text())
        plan["after"]["defaultImages"] = []
        p.write_text(json.dumps(plan))
        with self.assertRaisesRegex(ValueError, "andere Aenderungen"):
            await run(self.client, self.folder, self.mode)
        self.assertEqual(self.calls, [])

    async def test_crash_intent_blocks_and_check_is_read_only(self):
        await self.prepare()
        (self.folder / "ausfuehren.intent.json").write_text("{}")
        with self.assertRaises(ValueError):
            await run(self.client, self.folder, self.mode)
        result = await run(self.client, self.folder, "pruefen")
        self.assertTrue(result["testversuch"])
        self.assertEqual(self.calls, [])

    async def test_changed_article_and_stale_plan_block(self):
        await self.prepare()
        self.current["id"] = "00000000-0000-4000-8000-000000000041"
        with self.assertRaisesRegex(ValueError, "Artikelidentitaet"):
            await run(self.client, self.folder, self.mode)
        self.current = detail()
        p = self.folder / "plan.json"
        plan = json.loads(p.read_text())
        plan["created"] = "2000-01-01T00:00:00+00:00"
        p.write_text(json.dumps(plan))
        with self.assertRaisesRegex(ValueError, "zwei Stunden"):
            await run(self.client, self.folder, self.mode)
        self.assertEqual(self.calls, [])

    async def test_unauthorized_response_not_retried(self):
        await self.prepare()
        self.client.http.patch = AsyncMock(return_value=httpx.Response(401))
        report = await run(self.client, self.folder, self.mode)
        self.assertEqual(report["http_status"], 401)
        self.assertFalse(report["zuordnungen_bestaetigt"])
        self.assertEqual(self.client.http.patch.await_count, 1)

    async def test_journal_failure_prevents_patch(self):
        await self.prepare()
        with patch("scripts.teste_bilder_cloud.save_once", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                await run(self.client, self.folder, self.mode)
        self.assertEqual(self.calls, [])

    async def test_failed_readback_leaves_uncertain_and_blocks_repeat(self):
        await self.prepare()
        original = self.client.http.patch

        async def fail_after_write(*args, **kwargs):
            response = await original(*args, **kwargs)
            self.client.artikel_lesen = AsyncMock(side_effect=ValueError("unavailable"))
            return response

        self.client.http.patch = fail_after_write
        result = await run(self.client, self.folder, self.mode)
        self.assertEqual(result["zustand"], "UNKLAR")
        self.assertFalse(result["zuordnungen_bestaetigt"])
        with self.assertRaisesRegex(ValueError, "bereits protokolliert"):
            await run(self.client, self.folder, self.mode)
        self.assertEqual(len(self.calls), 1)

    def test_unknown_metadata_and_duplicate_channels_rejected(self):
        value = detail()
        value["images"]["defaultImages"][0]["seo"] = "keep"
        with self.assertRaises(ValueError):
            images(value)
        value = detail()
        value["images"]["saleschannelImages"].append(value["images"]["saleschannelImages"][0])
        with self.assertRaises(ValueError):
            images(value)

    def test_ambiguous_main_and_missing_positions_rejected(self):
        for field, value in (("sortNumber", 5), ("isMainImage", False)):
            block = images(detail())
            block["saleschannelImages"][0]["images"][0][field] = value
            with self.assertRaises(ValueError):
                target(block)


if __name__ == "__main__":
    unittest.main()
