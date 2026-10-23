import os
import unittest
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")

import httpx
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from app import main
from app.auth import BENUTZER, COOKIE_NAME, sitzung_erstellen, sitzung_lesen
from app.db import get_session
from app.models import Base


class GrafikZugriffTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.env = patch.dict(os.environ, {"KRAUTL_SESSION_SECRET": "grafik-test-secret"})
        self.env.start()
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        sessions = async_sessionmaker(self.engine, expire_on_commit=False)

        async def session():
            async with sessions() as db:
                yield db
        main.app.dependency_overrides[get_session] = session
        self.web = httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="https://test")

    async def asyncTearDown(self):
        await self.web.aclose()
        main.app.dependency_overrides.pop(get_session, None)
        await self.engine.dispose()
        self.env.stop()

    def cookie(self, user="micha"):
        return {"Cookie": f"{COOKIE_NAME}={sitzung_erstellen(user)}"}

    async def test_grafik_blockiert_fremde_bereiche_auch_direkt(self):
        for method, path in [
            ("GET", "/mails"), ("GET", "/mails/1"), ("GET", "/rechnungen"),
            ("GET", "/inkasso"), ("POST", "/inkasso/aktualisieren"),
            ("PUT", "/inkasso/1/zuweisung"), ("GET", "/whatsapp/chats"),
            ("GET", "/gesendet"), ("GET", "/aktionslog"),
            ("GET", "/klassifikationen"), ("GET", "/rollen-mailzugriff"),
            ("GET", "/jtl-sync/status"), ("GET", "/entwuerfe"),
            ("GET", "/wissensvorschlaege"), ("GET", "/faq/vorschlaege"),
            ("POST", "/faq/vorschlaege/1/uebernehmen"), ("GET", "/openapi.json"),
        ]:
            with self.subTest(method=method, path=path):
                response = await self.web.request(method, path, headers=self.cookie())
                self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual((await self.web.get("/wissensbasis")).status_code, 401)

    async def test_grafik_kann_wissen_und_faq_bearbeiten_admin_behaelt_uebersicht(self):
        headers = self.cookie()
        me = await self.web.get("/auth/me", headers=headers)
        self.assertEqual(me.json()["rolle"], "grafik")
        body = {"wissensart": "allgemein", "titel": "Grafik", "inhalt": "Testwissen"}
        response = await self.web.post("/wissen", json=body, headers=headers)
        self.assertEqual(response.status_code, 200, response.text)
        response = await self.web.put(f"/wissen/{response.json()['id']}", json={**body, "inhalt": "Geändert"}, headers=headers)
        self.assertEqual(response.status_code, 200, response.text)
        basis = (await self.web.get("/wissensbasis", headers=headers)).json()
        self.assertEqual(basis["eintraege"][0]["inhalt"], "Geändert")
        with patch.object(main.google_product_qa_feed, "aktualisieren", new=AsyncMock()):
            response = await self.web.post("/faq", headers=headers, json={"frage": "Frage?", "antwort": "Antwort", "kategorie": "Test", "include_in_faq": False})
            self.assertEqual(response.status_code, 200, response.text)
            faq_id = response.json()["id"]
            response = await self.web.patch(f"/faq/{faq_id}/auswahl", headers=headers, json={"include_in_faq": True})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["status"], "freigegeben")
        self.assertEqual(len((await self.web.get("/faq", headers=headers)).json()), 1)
        response = await self.web.get("/rollen-mailzugriff", headers=self.cookie("erik"))
        self.assertEqual(response.status_code, 200, response.text)
        rollen = {r["id"]: r for r in response.json()["rollen"]}
        self.assertEqual([b["benutzername"] for b in rollen["grafik"]["benutzer"]], ["micha"])
        self.assertNotIn("micha", [b["benutzername"] for b in rollen["sachbearbeiter"]["benutzer"]])
        for user in ("erik", "ludwig"):
            self.assertEqual((await self.web.get("/mails", headers=self.cookie(user))).status_code, 200)

    async def test_alte_sitzung_erhaelt_sofort_aktuelle_rolle(self):
        with patch.dict(BENUTZER["micha"], {"rolle": "sachbearbeiter"}):
            token = sitzung_erstellen("micha")
        self.assertEqual(sitzung_lesen(token)["rolle"], "grafik")
        response = await self.web.get("/mails", headers={"Cookie": f"{COOKIE_NAME}={token}"})
        self.assertEqual(response.status_code, 403)
