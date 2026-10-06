import hashlib
import hmac
import json
import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch
from uuid import uuid4
from types import SimpleNamespace

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")
import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from app import main, whatsapp
from app.auth import COOKIE_NAME, sitzung_erstellen
from app.models import Base, WhatsAppChat as Chat, WhatsAppNachricht as Nachricht, WhatsAppEreignis as Ereignis, Klassifikation, RollenMailzugriff


class WhatsAppTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async def override():
            async with self.sessions() as session:
                yield session
        main.app.dependency_overrides[main.get_session] = override
        self.env = patch.dict(os.environ, {"KRAUTL_SESSION_SECRET": "synthetic-whatsapp-test",
            "WHATSAPP_ENABLED": "true", "WHATSAPP_PHONE_NUMBER_ID": "123",
            "WHATSAPP_ACCESS_TOKEN": "synthetic", "WHATSAPP_APP_SECRET": "test-secret",
            "WHATSAPP_VERIFY_TOKEN": "verify", "WHATSAPP_API_VERSION": "v23.0",
            "WHATSAPP_PROVIDER": "meta"})
        self.env.start()
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="https://krautl.test")
        self.admin = {"Cookie": f"{COOKIE_NAME}={sitzung_erstellen('erik')}"}
        self.staff = {"Cookie": f"{COOKIE_NAME}={sitzung_erstellen('ludwig')}"}

    async def asyncTearDown(self):
        await self.client.aclose()
        main.app.dependency_overrides.clear()
        self.env.stop()
        await self.engine.dispose()

    def payload(self, mid="in-1", zeit=None, echo=False, telefon="123", text="Hallo"):
        msg = {"id": mid, "timestamp": str(int((zeit or datetime.now(timezone.utc)).timestamp())),
            "type": "text", "text": {"body": text}, "from": "4912345"}
        if echo:
            msg["to"] = "4912345"
        value = {"metadata": {"phone_number_id": telefon}, "contacts": [{"wa_id": "4912345", "profile": {"name": "Testkunde"}}],
            "message_echoes" if echo else "messages": [msg]}
        return {"object": "whatsapp_business_account", "entry": [{"changes": [{"field": "smb_message_echoes" if echo else "messages", "value": value}]}]}

    async def webhook(self, payload, gueltig=True):
        body = json.dumps(payload).encode()
        signature = "sha256=" + hmac.new(b"test-secret", body, hashlib.sha256).hexdigest()
        return await self.client.post("/whatsapp/webhook", content=body,
            headers={"X-Hub-Signature-256": signature if gueltig else "invalid", "Content-Type": "application/json"})

    async def eingang(self, payload=None):
        response = await self.webhook(payload or self.payload())
        self.assertEqual(response.status_code, 200, response.text)
        await whatsapp.ereignisse_verarbeiten(self.sessions)
        async with self.sessions() as session:
            return (await session.execute(select(Chat))).scalar_one()

    async def send(self, chat, auftrag=None, revision=None):
        return await self.client.post(f"/whatsapp/chats/{chat.id}/senden", headers=self.admin,
            json={"text": "Antwort", "revision": chat.revision if revision is None else revision, "auftrag_id": str(auftrag or uuid4())})

    async def test_webhook_requires_signature_not_login(self):
        self.assertEqual((await self.webhook(self.payload(), False)).status_code, 403)
        self.assertEqual((await self.client.get("/whatsapp/chats")).status_code, 401)
        self.assertEqual((await self.client.get("/whatsapp/webhook?hub.mode=subscribe&hub.verify_token=verify&hub.challenge=123")).text, "123")

    async def test_disabled_webhook(self):
        with patch.dict(os.environ, {"WHATSAPP_ENABLED": "false"}):
            self.assertEqual((await self.webhook(self.payload())).status_code, 503)

    async def test_duplicate_body_and_message_are_idempotent(self):
        chat = await self.eingang()
        await self.webhook(self.payload())
        await self.webhook(self.payload(text="different payload same message id"))
        await whatsapp.ereignisse_verarbeiten(self.sessions)
        async with self.sessions() as session:
            self.assertEqual(len((await session.execute(select(Nachricht))).scalars().all()), 1)
            self.assertEqual((await session.get(Chat, chat.id)).revision, 1)

    async def test_other_number_not_imported(self):
        await self.webhook(self.payload(telefon="other"))
        await whatsapp.ereignisse_verarbeiten(self.sessions)
        async with self.sessions() as session:
            self.assertEqual((await session.execute(select(Chat))).scalars().all(), [])

    async def test_multiple_messages_one_chat_reopens(self):
        chat = await self.eingang()
        response = await self.client.put(f"/whatsapp/chats/{chat.id}/erledigen", headers=self.admin, json={"revision": 1})
        self.assertEqual(response.status_code, 200)
        chat = await self.eingang(self.payload("in-2"))
        self.assertEqual(chat.status, "offen")
        self.assertEqual(chat.revision, 2)

    async def test_echo_closes_and_preserves_history(self):
        chat = await self.eingang()
        chat = await self.eingang(self.payload("echo", datetime.now(timezone.utc)+timedelta(seconds=1), echo=True))
        self.assertEqual(chat.status, "wartet_auf_kunde")
        detail = (await self.client.get(f"/whatsapp/chats/{chat.id}", headers=self.admin)).json()
        self.assertEqual(len(detail["nachrichten"]), 2)
        self.assertEqual(detail["nachrichten"][1]["quelle"], "app")

    async def test_stale_draft_and_complete_rejected(self):
        chat = await self.eingang()
        for feld in ["erledigen", "entwurf"]:
            response = await self.client.put(f"/whatsapp/chats/{chat.id}/{feld}", headers=self.admin, json={"revision": 0, "text": "old"})
            self.assertEqual(response.status_code, 409)
        with patch("app.whatsapp.api_senden", new_callable=AsyncMock) as send:
            self.assertEqual((await self.send(chat, revision=0)).status_code, 409)
            send.assert_not_called()

    async def test_expired_window_no_send(self):
        chat = await self.eingang(self.payload(zeit=datetime.now(timezone.utc)-timedelta(days=2)))
        with patch("app.whatsapp.api_senden", new_callable=AsyncMock) as send:
            self.assertEqual((await self.send(chat)).status_code, 409)
            send.assert_not_called()

    async def test_send_hides_chat_and_same_id_never_resends(self):
        chat = await self.eingang()
        auftrag = uuid4()
        with patch("app.whatsapp.api_senden", new_callable=AsyncMock, return_value="out-1") as send:
            response = await self.send(chat, auftrag)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual((await self.send(chat, auftrag)).status_code, 200)
            send.assert_awaited_once()
        async with self.sessions() as session:
            self.assertEqual((await session.get(Chat, chat.id)).status, "wartet_auf_kunde")

    async def test_new_message_during_send_stays_open(self):
        chat = await self.eingang()
        async def race(*args):
            await self.eingang(self.payload("in-2", datetime.now(timezone.utc)+timedelta(seconds=1)))
            return "out-1"
        with patch("app.whatsapp.api_senden", side_effect=race):
            self.assertEqual((await self.send(chat)).status_code, 200)
        async with self.sessions() as session:
            self.assertEqual((await session.get(Chat, chat.id)).status, "offen")

    async def test_ambiguous_send_cannot_be_repeated(self):
        chat = await self.eingang()
        with patch("app.whatsapp.api_senden", side_effect=httpx.ReadTimeout("test")) as send:
            self.assertEqual((await self.send(chat)).status_code, 502)
            self.assertEqual((await self.send(chat)).status_code, 409)
            send.assert_awaited_once()
        async with self.sessions() as session:
            self.assertEqual((await session.execute(select(Nachricht).where(Nachricht.richtung == "ausgehend"))).scalar_one().status, "unklar")

    async def test_reservation_blocks_other_user(self):
        chat = await self.eingang()
        self.assertEqual((await self.client.post(f"/whatsapp/chats/{chat.id}/reservierung", headers=self.staff)).status_code, 200)
        self.assertEqual((await self.send(chat)).status_code, 409)
        self.assertEqual((await self.client.post(f"/whatsapp/chats/{chat.id}/reservierung", headers=self.admin)).status_code, 409)

    async def test_assignment_hides_from_staff(self):
        chat = await self.eingang()
        self.assertEqual((await self.client.put(f"/whatsapp/chats/{chat.id}/zustaendigkeit", headers=self.admin,
            json={"revision": 1, "rolle": "admin"})).status_code, 200)
        self.assertEqual((await self.client.get(f"/whatsapp/chats/{chat.id}", headers=self.staff)).status_code, 403)
        self.assertEqual((await self.client.get("/whatsapp/chats?archiv=true", headers=self.staff)).json(), [])

    async def test_status_order_does_not_regress_and_failure_reopens(self):
        chat = await self.eingang()
        with patch("app.whatsapp.api_senden", new_callable=AsyncMock, return_value="out-1"):
            await self.send(chat)
        for state in ["delivered", "sent", "read", "failed"]:
            p = self.payload()
            value = p["entry"][0]["changes"][0]["value"]
            value.pop("messages")
            value["statuses"] = [{"id": "out-1", "status": state}]
            await self.webhook(p)
            await whatsapp.ereignisse_verarbeiten(self.sessions)
        async with self.sessions() as session:
            msg = (await session.execute(select(Nachricht).where(Nachricht.message_id == "out-1"))).scalar_one()
            self.assertEqual(msg.status, "read")
            self.assertEqual((await session.get(Chat, chat.id)).status, "wartet_auf_kunde")

    async def test_failed_delivery_reopens(self):
        chat = await self.eingang()
        with patch("app.whatsapp.api_senden", new_callable=AsyncMock, return_value="out-1"):
            await self.send(chat)
        p = self.payload(); value = p["entry"][0]["changes"][0]["value"]
        value.pop("messages"); value["statuses"] = [{"id": "out-1", "status": "failed", "errors": [{"code": 123}]}]
        await self.webhook(p); await whatsapp.ereignisse_verarbeiten(self.sessions)
        async with self.sessions() as session:
            self.assertEqual((await session.get(Chat, chat.id)).status, "offen")

    async def test_360dialog_header_auth(self):
        with patch.dict(os.environ, {"WHATSAPP_PROVIDER": "360dialog", "WHATSAPP_WEBHOOK_TOKEN": "synthetic-token"}):
            self.assertEqual((await self.webhook(self.payload())).status_code, 403)
            response = await self.client.post("/whatsapp/webhook", json=self.payload(), headers={"X-Krautl-Webhook-Token": "synthetic-token"})
            self.assertEqual(response.status_code, 200)

    async def test_template_outside_window_requires_approved_template(self):
        chat = await self.eingang(self.payload(zeit=datetime.now(timezone.utc)-timedelta(days=2)))
        body = {"text": "placeholder", "revision": 1, "auftrag_id": str(uuid4()), "template_name": "service", "template_sprache": "de", "parameter": ["Testkunde"]}
        with patch("app.whatsapp.vorlagen_laden", new_callable=AsyncMock, return_value=[{"name": "service", "sprache": "de", "text": "Hallo {{1}}", "parameter": 1}]), patch("app.whatsapp.api_senden", new_callable=AsyncMock, return_value="out-1") as send:
            response = await self.client.post(f"/whatsapp/chats/{chat.id}/senden", headers=self.admin, json=body)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(send.call_args.args[1], "Hallo Testkunde")
            self.assertEqual(send.call_args.args[2]["name"], "service")

    async def test_template_missing_or_invalid_params_no_send(self):
        chat = await self.eingang()
        with patch("app.whatsapp.vorlagen_laden", new_callable=AsyncMock, return_value=[]), patch("app.whatsapp.api_senden", new_callable=AsyncMock) as send:
            response = await self.client.post(f"/whatsapp/chats/{chat.id}/senden", headers=self.admin,
                json={"text": "x", "revision": 1, "auftrag_id": str(uuid4()), "template_name": "missing", "template_sprache": "de"})
            self.assertEqual(response.status_code, 400)
            send.assert_not_called()

    async def test_archive_search_finds_message_and_retains_completed(self):
        chat = await self.eingang()
        await self.client.put(f"/whatsapp/chats/{chat.id}/erledigen", headers=self.admin, json={"revision": 1})
        self.assertEqual((await self.client.get("/whatsapp/chats?alle=true", headers=self.admin)).json(), [])
        result = (await self.client.get("/whatsapp/chats?archiv=true&suche=Hallo", headers=self.admin)).json()
        self.assertEqual(len(result), 1)

    async def test_media_cannot_access_other_chat(self):
        chat = await self.eingang()
        self.assertEqual((await self.client.get(f"/whatsapp/chats/{chat.id}/medien/9999", headers=self.admin)).status_code, 404)

    async def test_early_status_replayed_after_send(self):
        chat = await self.eingang()
        async def early(*args):
            p = self.payload(); value = p["entry"][0]["changes"][0]["value"]
            value.pop("messages"); value["statuses"] = [{"id": "out-1", "status": "delivered"}]
            await self.webhook(p); await whatsapp.ereignisse_verarbeiten(self.sessions)
            return "out-1"
        with patch("app.whatsapp.api_senden", side_effect=early):
            self.assertEqual((await self.send(chat)).status_code, 200)
        await whatsapp.ereignisse_verarbeiten(self.sessions)
        async with self.sessions() as session:
            self.assertEqual((await session.execute(select(Nachricht).where(Nachricht.message_id == "out-1"))).scalar_one().status, "delivered")

    async def test_malformed_event_visible_to_admin_only(self):
        p = self.payload(); p["entry"][0]["changes"][0]["value"]["messages"][0]["timestamp"] = "invalid"
        await self.webhook(p); await whatsapp.ereignisse_verarbeiten(self.sessions)
        self.assertEqual(len((await self.client.get("/whatsapp/diagnose", headers=self.admin)).json()["fehler"]), 1)
        self.assertEqual((await self.client.get("/whatsapp/diagnose", headers=self.staff)).status_code, 403)

    async def test_late_incoming_older_than_our_answer_does_not_reopen(self):
        chat = await self.eingang(self.payload(zeit=datetime.now(timezone.utc)-timedelta(seconds=20)))
        with patch("app.whatsapp.api_senden", new_callable=AsyncMock, return_value="out-1"):
            await self.send(chat)
        chat = await self.eingang(self.payload("late", datetime.now(timezone.utc)-timedelta(seconds=10)))
        self.assertEqual(chat.status, "wartet_auf_kunde")

    async def test_category_permission_protects_all_routes(self):
        chat = await self.eingang()
        async with self.sessions() as session:
            session.add(Klassifikation(klassifikation_id="PRIVAT", hauptkategorie="Privat", unterkategorie="Privat",
                beschreibung="Test", standard_prio="normal", aktion_id="KEINE_AKTION"))
            session.add(RollenMailzugriff(rolle="sachbearbeiter", klassifikation_id="PRIVAT", darf_sehen=False))
            current = await session.get(Chat, chat.id)
            current.klassifikation_id = "PRIVAT"  # Historische Berechtigungen bleiben geschützt.
            await session.commit()
        self.assertEqual((await self.client.get(f"/whatsapp/chats/{chat.id}", headers=self.staff)).status_code, 403)
        self.assertEqual((await self.client.post(f"/whatsapp/chats/{chat.id}/vorschlag", headers=self.staff)).status_code, 403)
        self.assertEqual((await self.client.get(f"/whatsapp/chats/{chat.id}/medien/1", headers=self.staff)).status_code, 403)

    async def test_manual_resolution_only_after_unclear_send(self):
        chat = await self.eingang()
        with patch("app.whatsapp.api_senden", side_effect=httpx.ReadTimeout("test")):
            await self.send(chat)
        async with self.sessions() as session:
            msg = (await session.execute(select(Nachricht).where(Nachricht.richtung == "ausgehend"))).scalar_one()
        response = await self.client.put(f"/whatsapp/chats/{chat.id}/nachrichten/{msg.id}/versand-pruefen",
            headers=self.admin, json={"revision": 1, "text": "nicht_versendet"})
        self.assertEqual(response.status_code, 200)
        with patch("app.whatsapp.api_senden", new_callable=AsyncMock, return_value="out-1") as send:
            self.assertEqual((await self.send(chat)).status_code, 200)
            send.assert_awaited_once()

    async def test_pdf_upload_and_send(self):
        chat = await self.eingang()
        real_client = httpx.AsyncClient
        calls = []
        def handler(req):
            calls.append(str(req.url))
            return httpx.Response(200, json={"id": "media-1"})
        with patch("app.whatsapp.httpx.AsyncClient", side_effect=lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw)), patch("app.whatsapp.api_senden", new_callable=AsyncMock, return_value="out-1") as send:
            response = await self.client.post(f"/whatsapp/chats/{chat.id}/senden-datei", headers=self.admin,
                data={"revision": "1", "auftrag_id": str(uuid4()), "text": "Hier ist das PDF"},
                files={"datei": ("hinweis.pdf", b"%PDF-1.4 synthetic", "application/pdf")})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(send.call_args.args[3]["typ"], "document")
            self.assertTrue(calls[0].endswith("/123/media"))

    async def test_invalid_file_never_uploaded_or_sent(self):
        chat = await self.eingang()
        with patch("app.whatsapp.api_senden", new_callable=AsyncMock) as send:
            response = await self.client.post(f"/whatsapp/chats/{chat.id}/senden-datei", headers=self.admin,
                data={"revision": "1", "auftrag_id": str(uuid4())}, files={"datei": ("fake.pdf", b"malicious", "application/pdf")})
            self.assertEqual(response.status_code, 415)
            send.assert_not_called()

    async def test_360dialog_media_uses_documented_download_host(self):
        chat = await self.eingang()
        async with self.sessions() as session:
            msg = (await session.execute(select(Nachricht))).scalar_one()
            msg.media_id = "media-1"; await session.commit(); msg_id = msg.id
        urls = []
        def handler(req):
            urls.append(str(req.url))
            if str(req.url).endswith("/media-1"):
                return httpx.Response(200, json={"url": "https://lookaside.fbsbx.com/whatsapp_business/attachments/?mid=123"})
            return httpx.Response(200, content=b"test media")
        real_client = httpx.AsyncClient
        with patch.dict(os.environ, {"WHATSAPP_PROVIDER": "360dialog"}), patch("app.whatsapp.httpx.AsyncClient", side_effect=lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw)):
            response = await self.client.get(f"/whatsapp/chats/{chat.id}/medien/{msg_id}", headers=self.admin)
            self.assertEqual(response.content, b"test media")
            self.assertTrue(urls[1].startswith("https://waba-v2.360dialog.io/whatsapp_business/attachments/"))

    async def test_cloud_api_adapter_payload_and_ambiguous_server_error(self):
        real_client = httpx.AsyncClient
        def handler(req):
            self.assertEqual(json.loads(req.content)["to"], "49123")
            self.assertEqual(req.headers["Authorization"], "Bearer synthetic")
            return httpx.Response(500)
        with patch("app.whatsapp.httpx.AsyncClient", side_effect=lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw)):
            with self.assertRaises(RuntimeError):
                await whatsapp.api_senden("49123", "Antwort")

    async def test_rejection_codes_saved_without_provider_secrets_or_retry(self):
        chat = await self.eingang()
        real_client = httpx.AsyncClient
        calls = []
        def handler(req):
            calls.append(req)
            return httpx.Response(400, json={"error": {"code": 190, "error_subcode": 463,
                "message": "synthetic-private-token"}})
        with patch("app.whatsapp.httpx.AsyncClient", side_effect=lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw)):
            response = await self.send(chat)
        self.assertEqual(response.status_code, 502)
        self.assertIn("Meta-Code 190", response.text)
        self.assertIn("Untercode 463", response.text)
        self.assertNotIn("synthetic-private-token", response.text)
        self.assertEqual(len(calls), 1)
        async with self.sessions() as session:
            msg = (await session.execute(select(Nachricht).where(Nachricht.richtung == "ausgehend"))).scalar_one()
            self.assertEqual(msg.status, "failed")
            self.assertIn("Meta-Code 190", msg.fehler)
            self.assertEqual((await session.get(Chat, chat.id)).status, "offen")

    async def test_non_json_rejection_retains_http_status(self):
        real_client = httpx.AsyncClient
        with patch("app.whatsapp.httpx.AsyncClient", side_effect=lambda **kw: real_client(
                transport=httpx.MockTransport(lambda req: httpx.Response(403, text="synthetic-private-token")), **kw)):
            with self.assertRaises(whatsapp.HTTPException) as caught:
                await whatsapp.api_senden("49123", "Antwort")
        self.assertIn("HTTP 403", caught.exception.detail)
        self.assertNotIn("synthetic-private-token", caught.exception.detail)

    async def test_crashed_send_recovered_without_resending(self):
        chat = await self.eingang()
        async with self.sessions() as session:
            current = await session.get(Chat, chat.id); current.status = "wartet_auf_kunde"
            session.add(Nachricht(chat_id=chat.id, richtung="ausgehend", text="Test",
                zeit=datetime.now(timezone.utc)-timedelta(minutes=5), status="uebergabe"))
            await session.commit()
        await whatsapp.unterbrochene_versandauftraege(self.sessions)
        async with self.sessions() as session:
            self.assertEqual((await session.get(Chat, chat.id)).status, "offen")
            msg = (await session.execute(select(Nachricht).where(Nachricht.richtung == "ausgehend"))).scalar_one()
            self.assertEqual(msg.status, "unklar")

    async def test_incoming_and_reopened_chat_do_not_call_ai(self):
        with patch("app.whatsapp.Anthropic") as ai:
            chat = await self.eingang()
            await self.client.put(f"/whatsapp/chats/{chat.id}/erledigen", headers=self.admin, json={"revision": 1})
            chat = await self.eingang(self.payload("follow-up"))
            ai.assert_not_called()
        self.assertEqual(chat.status, "offen")
        self.assertIsNone(chat.klassifikation_id)
        self.assertEqual(chat.revision, 2)

    async def test_category_action_removed(self):
        chat = await self.eingang()
        response = await self.client.put(f"/whatsapp/chats/{chat.id}/kategorie", headers=self.admin,
            json={"revision": 1, "klassifikation_id": "KUNDE"})
        self.assertEqual(response.status_code, 404)

    async def test_explicit_proposal_still_uses_ai_and_never_sends(self):
        chat = await self.eingang()
        with patch("app.whatsapp.Anthropic") as ai, patch("app.whatsapp.api_senden", new_callable=AsyncMock) as send:
            ai.return_value.messages.create.return_value = SimpleNamespace(
                content=[SimpleNamespace(type="text", text="Hallo, wie kann ich helfen?")])
            response = await self.client.post(f"/whatsapp/chats/{chat.id}/vorschlag", headers=self.admin)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["text"], "Hallo, wie kann ich helfen?")
            ai.return_value.messages.create.assert_called_once()
            send.assert_not_awaited()
        detail = (await self.client.get(f"/whatsapp/chats/{chat.id}", headers=self.admin)).json()
        self.assertEqual(detail["entwurf"], "Hallo, wie kann ich helfen?")
        self.assertEqual(detail["status"], "offen")
        self.assertEqual(len(detail["nachrichten"]), 1)


if __name__ == "__main__":
    unittest.main()
