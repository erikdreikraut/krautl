import asyncio
import base64
from io import BytesIO
import json
import os
import tempfile
import unittest
from unittest.mock import patch
from uuid import UUID

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")
import httpx
from PIL import Image
from app import main, bilder, bilder_speicher as store
from app.bilder_abgleich import abgleichen, bild_laden, shop_bilder
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
            return httpx.Response(403)
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
        with self.assertRaisesRegex(JtlFehler, "Shop-Aktivierung"):
            await self.run_sync()
        self.assertEqual(store.lesen()["artikel"], old["artikel"])
        self.assertEqual(store.lesen()["letzter_erfolg"], old["letzter_erfolg"])

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
