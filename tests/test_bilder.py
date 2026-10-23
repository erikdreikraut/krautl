import asyncio
import base64
from io import BytesIO
import json
import os
import tempfile
import unittest
from unittest.mock import patch, AsyncMock
from uuid import UUID

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")
import httpx
from PIL import Image
from app import main, bilder, bilder_speicher as store
from app.bilder_abgleich import abgleichen, bild_laden, shop_bilder, einzelshop_bestaetigen, einzelshop_pruefen, datei_url
from app.jtl_onprem import OnPremClient
from app.jtl_client import JtlFehler
from app.auth import COOKIE_NAME, sitzung_erstellen


def uid(n):
    return str(UUID(int=n))


def row(n=1, parent=None):
    return {"id": uid(n), "sKU": f"A-{n}", "name": f"Artikel {n}", "parentItemId": parent, "isActive": True, "isShopActive": True}


def detail(n=1, shop=True, images=None):
    return {"id": uid(n), "identifiers": {"sku": f"A-{n}"},
            "salesChannels": {"salesChannels": [{"salesChannelId": "2-2-1", "isActive": shop}]},
            "images": {"defaultImages": [{"blobIdentifier": uid(999)}], "saleschannelImages": [
                {"saleschannelId": "other", "images": [{"blobIdentifier": uid(998)}]},
                {"saleschannelId": "2-2-1", "images": images if images is not None else [
                    {"blobIdentifier": uid(n+100), "sortNumber": 2, "isMainImage": False, "modificationDate": "2026-10-23T10:00:00Z"}]}]}}


def png():
    data = BytesIO()
    Image.new("RGBA", (800, 600), (0, 128, 0, 100)).save(data, "PNG")
    return data.getvalue()


class BilderTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"BILDER_DIR": self.folder.name, "KRAUTL_SESSION_SECRET": "test-bilder"})
        self.env.start()
        self.requests = []
        self.rows = [row(1), row(2, uid(1)), row(3)]
        self.details = {uid(1): detail(1), uid(2): detail(2, images=[]), uid(3): detail(3, shop=False)}
        self.fail_path = None
        self.fail_status = 403
        self.hide_on_detail = None

    async def asyncTearDown(self):
        await bilder.beenden()
        self.env.stop()
        self.folder.cleanup()

    def transport(self, req):
        self.requests.append((req.method, req.url.path))
        self.assertEqual(req.method, "GET")
        path = req.url.path.removeprefix("/api/eazybusiness")
        if self.fail_path == path:
            return httpx.Response(self.fail_status)
        if path == "/v2/items":
            return httpx.Response(200, json={"items": self.rows, "pageNumber": 1, "hasNextPage": False, "totalItems": len(self.rows)})
        if path.startswith("/v2/items/image-data/"):
            return httpx.Response(200, json=base64.b64encode(png()).decode())
        key = path.rsplit("/", 1)[1]
        if key == self.hide_on_detail:
            store.ausblenden(key, True, 0, "micha")
        return httpx.Response(200, json=self.details[key])

    def client(self):
        return OnPremClient("https://wawi.test/api/eazybusiness", "test-key", transport=httpx.MockTransport(self.transport))

    async def run_sync(self):
        async with self.client() as client:
            await abgleichen(client)

    async def test_shop_only_thumbnails_parent_and_cache(self):
        await self.run_sync()
        stand = store.lesen()
        self.assertEqual(stand["status"], "ok")
        self.assertEqual(len(stand["artikel"]), 2)
        self.assertEqual(stand["artikel"][1]["parent_id"], uid(1))
        self.assertEqual(stand["artikel"][1]["bilder"], [])
        thumb = stand["artikel"][0]["bilder"][0]["thumb"]
        with Image.open(BytesIO(store.thumb_lesen(uid(1), thumb))) as image:
            self.assertEqual(image.size, (240, 180))
            self.assertEqual(image.format, "JPEG")
        self.assertIsNone(store.thumb_lesen(uid(2), thumb))
        self.assertFalse(any(uid(999) in p or uid(998) in p for _,p in self.requests))
        self.requests.clear()
        await self.run_sync()
        self.assertFalse(any("image-data" in p for _,p in self.requests))

    async def test_hidden_survives_updates_removed_catalogue_and_unhide(self):
        await self.run_sync()
        before = store.lesen()["artikel"][0]
        store.ausblenden(uid(1), True, 0, "micha")
        self.rows[0]["name"] = "Changed"
        self.requests.clear()
        await self.run_sync()
        self.assertFalse(any(p.endswith("/" + uid(1)) or "image-data" in p for _,p in self.requests))
        hidden = next(a for a in store.lesen()["artikel"] if a["id"] == uid(1))
        self.assertEqual(hidden["name"], before["name"])
        self.assertTrue(hidden["ausgeblendet"])
        self.rows = []
        await self.run_sync()
        self.assertEqual(len(store.lesen()["artikel"]), 1)
        store.ausblenden(uid(1), False, 1, "erik")
        with self.assertRaises(ValueError):
            store.ausblenden(uid(1), True, 1, "micha")
        self.rows = [row()]
        self.rows[0]["name"] = "New name"
        await self.run_sync()
        self.assertEqual(store.lesen()["artikel"][0]["name"], "New name")

    async def test_hide_during_detail_skips_images_and_snapshot(self):
        await self.run_sync()
        self.hide_on_detail = uid(1)
        self.requests.clear()
        self.details[uid(1)]["images"]["saleschannelImages"][1]["images"][0]["modificationDate"] = "new"
        await self.run_sync()
        self.assertFalse(any("image-data" in p for _,p in self.requests))
        self.assertTrue(store.lesen()["artikel"][0]["ausgeblendet"])
        self.assertEqual(store.lesen()["artikel"][0]["bilder"][0]["version"], "2026-10-23T10:00:00Z")

    async def test_failure_preserves_complete_snapshot_and_success_time(self):
        await self.run_sync()
        old = store.lesen()
        self.fail_path = "/v2/items/" + uid(2)
        self.rows[0]["name"] = "Must not publish"
        with self.assertRaises(JtlFehler):
            await self.run_sync()
        self.assertEqual(store.lesen()["artikel"], old["artikel"])
        self.assertEqual(store.lesen()["letzter_erfolg"], old["letzter_erfolg"])
        self.fail_path = None
        self.details[uid(1)].pop("salesChannels")
        with patch("app.bilder_abgleich.einzelshop_pruefen", side_effect=JtlFehler("Shop-Aktivierung unklar")):
            with self.assertRaisesRegex(JtlFehler, "Shop-Aktivierung"):
                await self.run_sync()
        self.assertEqual(store.lesen()["artikel"], old["artikel"])
        self.assertEqual(store.lesen()["letzter_erfolg"], old["letzter_erfolg"])

    async def test_legacy_single_shop_checked_each_run_and_hidden_skipped(self):
        for d in self.details.values():
            d.pop("salesChannels")
        self.rows[2]["isShopActive"] = False
        with patch("app.bilder_abgleich.einzelshop_pruefen", new_callable=AsyncMock, return_value=True) as check:
            await self.run_sync()
            check.assert_awaited_once_with("https://wawi.test/api/eazybusiness")
            self.assertEqual(len(store.lesen()["artikel"]), 2)
            store.ausblenden(uid(1), True, 0, "micha")
            self.requests.clear()
            await self.run_sync()
            self.assertEqual(check.await_count, 2)
            self.assertFalse(any(p.endswith("/" + uid(1)) or p.endswith("/" + uid(3)) or "image-data" in p for _, p in self.requests))

    def test_legacy_does_not_infer_activity_from_images(self):
        d = detail()
        d.pop("salesChannels")
        with self.assertRaises(JtlFehler):
            shop_bilder(d, row())
        inactive = row()
        inactive["isShopActive"] = False
        self.assertIsNone(shop_bilder(d, inactive, True))
        inactive["isShopActive"] = 1
        with self.assertRaises(JtlFehler):
            shop_bilder(d, inactive, True)
        d["salesChannels"] = {}
        with self.assertRaises(JtlFehler):
            shop_bilder(d, row(), True)
        d = detail(shop=False)
        self.assertIsNone(shop_bilder(d, row(), True))

    def test_channel_proof_rejects_ambiguity(self):
        def channel(key, typ, active):
            return {"id": key, "type": typ, "itemCapabilities": {"onlineShopActivation": active}}
        channels = [channel("1-1-0", 0, False), channel("2-2-1", 0, True),
                    channel("9-7-8-0", 2, True), channel("amazon", 9, False)]
        self.assertTrue(einzelshop_bestaetigen(channels))
        for extra in (channel("second", 0, True), channel("second", 1, False),
                      channel("unknown", 99, False), channels[1], {}):
            with self.assertRaises(JtlFehler):
                einzelshop_bestaetigen(channels + [extra])
        for invalid in ([], {}, channels[:1]):
            with self.assertRaises(JtlFehler):
                einzelshop_bestaetigen(invalid)

    async def test_channel_reader_uses_same_api_and_only_get(self):
        calls = []
        def reply(req):
            calls.append((req.method, req.url.path))
            return httpx.Response(200, json=[{"id": "2-2-1", "type": 0,
                "itemCapabilities": {"onlineShopActivation": True}}])
        def reader():
            return OnPremClient("https://wawi.test/api/eazybusiness", "read-key",
                                transport=httpx.MockTransport(reply))
        with patch("app.bilder_abgleich.kanal_client", side_effect=reader):
            self.assertTrue(await einzelshop_pruefen("https://wawi.test/api/eazybusiness"))
            with self.assertRaisesRegex(JtlFehler, "anderen API-Ziel"):
                await einzelshop_pruefen("https://different.test/api/eazybusiness")
        self.assertEqual(calls, [("GET", "/api/eazybusiness/v2/sales-channels")])

    async def test_duplicate_catalogue_rejected(self):
        self.rows.append(row())
        with self.assertRaisesRegex(JtlFehler, "Doppelte Artikel-ID"):
            await self.run_sync()
        self.assertIsNone(store.lesen()["letzter_erfolg"])

    async def test_shop_image_order_and_no_default_fallback(self):
        d = detail(images=[{"blobIdentifier": uid(8), "sortNumber": 3}, {"blobIdentifier": uid(9), "sortNumber": 1}])
        self.assertEqual([b["sortNumber"] for b in shop_bilder(d)], [1, 3])
        d["images"].pop("saleschannelImages")
        self.assertEqual(shop_bilder(d), [])
        self.fail_path = "/v2/items/image-data/" + uid(101)
        async with self.client() as c:
            with self.assertRaisesRegex(JtlFehler, "HTTP 403"):
                await bild_laden(c, uid(101))

    async def test_legacy_file_fallback_normalizes_url_and_preserves_query(self):
        calls = []
        def reply(req):
            calls.append(req)
            if "image-data" in req.url.path:
                return httpx.Response(404)
            self.assertEqual(req.url.path, "/api/eazybusiness/v2/file/" + uid(101))
            self.assertEqual(req.url.params["token"], "test-secret")
            self.assertEqual(req.url.params["version"], "2")
            return httpx.Response(200, content=png(), headers={"Content-Type": "image/png"})
        async with OnPremClient("https://wawi.test/api/eazybusiness", "test-key",
                                transport=httpx.MockTransport(reply)) as c:
            b = {"url": c.url + "/v2/file/%7BblobId%7D%3Fversion=2/" + uid(101) + "?token=test-secret"}
            data = await bild_laden(c, uid(101), b)
            with Image.open(BytesIO(data)) as img:
                self.assertEqual(img.size, (240, 180))
        self.assertEqual(len(calls), 2)

    async def test_legacy_url_rejects_other_hosts_ids_paths_and_redirects(self):
        async with self.client() as c:
            good = c.url + "/v2/file/" + uid(101)
            self.assertEqual(datei_url(c, uid(101), {"url": good}), good)
            for url in (good.replace("wawi.test", "evil.test"), good.replace("https:", "http:"),
                        good.replace(uid(101), uid(102)), good.replace("/file/", "/users/"),
                        good + "#fragment", good.replace("wawi.test", "user@wawi.test"),
                        good.replace("wawi.test", "wawi.test:8443")):
                with self.assertRaises(JtlFehler):
                    datei_url(c, uid(101), {"url": url})
        calls = []
        def reply(req):
            calls.append(req)
            return httpx.Response(404 if len(calls) == 1 else 302,
                                  headers={"Location": "https://evil.test"})
        async with OnPremClient("https://wawi.test/api/eazybusiness", "key",
                                transport=httpx.MockTransport(reply)) as c:
            with self.assertRaisesRegex(JtlFehler, "HTTP 302"):
                await bild_laden(c, uid(101), {"url": c.url + "/v2/file/" + uid(101)})
        self.assertEqual(len(calls), 2)

    async def test_no_legacy_fallback_for_permission_error(self):
        self.fail_path = "/v2/items/image-data/" + uid(101)
        async with self.client() as c:
            with self.assertRaisesRegex(JtlFehler, "HTTP 403"):
                await bild_laden(c, uid(101), {"url": c.url + "/v2/file/" + uid(101)})
        self.assertEqual(len(self.requests), 1)

    async def test_full_diagnostic_reaches_later_failure_without_publishing(self):
        from scripts import pruefe_bilder_api as diagnostic
        self.details[uid(2)] = detail(2)
        self.fail_path = "/v2/items/image-data/" + uid(102)
        with patch.object(diagnostic.OnPremClient, "aus_umgebung", return_value=self.client()), patch("builtins.print"):
            with self.assertRaisesRegex(JtlFehler, "HTTP 403"):
                await diagnostic.main(alle=True)
        self.assertTrue(any(p.endswith(uid(101)) for _, p in self.requests))
        self.assertTrue(any(p.endswith(uid(102)) for _, p in self.requests))
        self.assertEqual(store.lesen()["artikel"], [])
        self.assertIsNone(store.lesen()["letzter_erfolg"])
        with self.assertRaisesRegex(JtlFehler, "Artikel A-2, Bildposition 2"):
            await self.run_sync()

    def test_diagnostic_redacts_credentials_and_urls(self):
        from scripts.pruefe_bilder_api import bereinigen
        request = httpx.Request("GET", "https://wawi.test/file?token=secret-query-value",
                                headers={"Authorization": "Wawi secret-api-key"})
        output = bereinigen('Failure secret-query-value secret-api-key https://wawi.test/file?token=secret-query-value', request)
        self.assertNotIn("secret", output)
        self.assertNotIn("https://", output)

    async def test_image_failure_publishes_placeholder_and_retries_unchanged_version(self):
        self.details[uid(2)] = detail(2)
        self.fail_path = "/v2/items/image-data/" + uid(101)
        self.fail_status = 400
        await self.run_sync()
        stand = store.lesen()
        self.assertEqual(stand["status"], "warnung")
        self.assertEqual(stand["bildfehler"], 1)
        bad, good = stand["artikel"]
        self.assertIsNone(bad["bilder"][0]["thumb"])
        self.assertIn("HTTP 400", bad["bilder"][0]["fehler"])
        self.assertEqual(bad["bilder"][0]["position"], 2)
        self.assertTrue(good["bilder"][0]["thumb"])
        self.assertIsNotNone(stand["letzter_erfolg"])
        self.fail_path = None
        self.requests.clear()
        await self.run_sync()
        self.assertTrue(any(p.endswith(uid(101)) for _, p in self.requests))
        self.assertFalse(any("image-data" in p and p.endswith(uid(102)) for _, p in self.requests))
        self.assertEqual(store.lesen()["status"], "ok")
        self.assertEqual(store.lesen()["bildfehler"], 0)
        self.assertIsNone(store.lesen()["artikel"][0]["bilder"][0]["fehler"])

    async def test_missing_image_without_download_url_becomes_placeholder(self):
        self.fail_path = "/v2/items/image-data/" + uid(101)
        self.fail_status = 404
        await self.run_sync()
        self.assertEqual(store.lesen()["status"], "warnung")
        self.assertIn("HTTP 404", store.lesen()["artikel"][0]["bilder"][0]["fehler"])

    async def test_hidden_placeholder_is_not_retried(self):
        self.fail_path = "/v2/items/image-data/" + uid(101)
        self.fail_status = 400
        await self.run_sync()
        store.ausblenden(uid(1), True, 0, "micha")
        self.requests.clear()
        await self.run_sync()
        self.assertFalse(any(p.endswith(uid(1)) or p.endswith(uid(101)) for _, p in self.requests))
        self.assertEqual(store.lesen()["status"], "ok")
        self.assertIn("HTTP 400", store.lesen()["artikel"][0]["bilder"][0]["fehler"])

    async def test_api_roles_hide_thumbnail_and_single_run(self):
        await self.run_sync()
        thumb = store.lesen()["artikel"][0]["bilder"][0]["thumb"]
        def cookie(user):
            return {"Cookie": f"{COOKIE_NAME}={sitzung_erstellen(user)}"}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="https://test") as web:
            self.assertEqual((await web.get("/bilder")).status_code, 401)
            for user, status in (("micha", 200), ("erik", 200), ("ludwig", 403)):
                self.assertEqual((await web.get("/bilder", headers=cookie(user))).status_code, status)
                self.assertEqual((await web.get(f"/bilder/{uid(1)}/thumb/{thumb}", headers=cookie(user))).status_code, status)
            self.assertEqual((await web.put(f"/bilder/{uid(1)}/ausblenden", json={"ausgeblendet": True, "revision": 0}, headers=cookie("micha"))).status_code, 200)
            self.assertEqual((await web.put(f"/bilder/{uid(1)}/ausblenden", json={"ausgeblendet": False, "revision": 0}, headers=cookie("erik"))).status_code, 409)
            self.assertEqual((await web.post("/bilder/aktualisieren", headers=cookie("ludwig"))).status_code, 403)
            barrier = asyncio.Event()
            with patch.object(bilder, "ausfuehren", barrier.wait):
                self.assertEqual((await web.post("/bilder/aktualisieren", headers=cookie("micha"))).status_code, 202)
                self.assertEqual((await web.post("/bilder/aktualisieren", headers=cookie("erik"))).status_code, 409)
                self.assertEqual((await web.get("/bilder", headers=cookie("erik"))).json()["status"], "laeuft")
                await bilder.beenden()
            self.assertEqual(store.zustand()["status"], "fehler")
            self.assertIsNotNone(store.lesen()["letzter_erfolg"])

    async def test_interrupted_run_is_not_shown_as_running_forever(self):
        store.status_setzen(status="laeuft")
        self.assertEqual(store.zustand()["status"], "fehler")
