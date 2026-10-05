import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app import main
from app.auth import COOKIE_NAME, sitzung_erstellen
from app.gesendet_ablage import _ordner, ausstehende_kopien_ablegen, kopie_in_gesendet, versandkopie_ablegen
from app.imap_client import PostfachConfig
from app.models import Base, Entwurf, Klassifikation, Mail, Postfach, RollenMailzugriff, Versandkopie


EML = b"From: service@example.test\r\nTo: kunde@example.test\r\nMessage-ID: <sent@test>\r\nSubject: Re: Frage\r\n\r\nAntwort.\r\n"


class GesendetImapTest(unittest.TestCase):
    def test_special_use_folder_and_explicit_override(self):
        client = MagicMock()
        client.list_folders.return_value = [((), b"/", "Sent"), ((b"\\Sent",), b"/", "Gesendete Nachrichten")]
        self.assertEqual(_ordner(client, ""), "Gesendete Nachrichten")
        self.assertEqual(_ordner(client, "Sent"), "Sent")
        with self.assertRaisesRegex(RuntimeError, "nicht gefunden"):
            _ordner(client, "Unbekannt")

    def test_fallback_nested_folder_and_ambiguity(self):
        client = MagicMock()
        client.list_folders.return_value = [((), b".", b"INBOX.Gesendet")]
        self.assertEqual(_ordner(client, ""), "INBOX.Gesendet")
        client.list_folders.return_value += [((), b".", "Sent")]
        with self.assertRaisesRegex(RuntimeError, "nicht eindeutig"):
            _ordner(client, "")

    def test_exact_message_id_is_idempotent_partial_match_is_not(self):
        client = MagicMock()
        client.list_folders.return_value = [((b"\\Sent",), b"/", "Sent")]
        client.search.return_value = [11]
        config = PostfachConfig("service", "imap.example.test", "service@example.test", "test")
        with patch("app.gesendet_ablage.lade_postfaecher", return_value=[config]), \
             patch("app.gesendet_ablage.IMAPClient") as imap, \
             patch.dict(os.environ, {"IMAP_SERVICE_SENT_FOLDER": ""}):
            imap.return_value.__enter__.return_value = client
            client.fetch.return_value = {11: {b"BODY[HEADER.FIELDS (MESSAGE-ID)]": b"Message-ID: <sent@test.extra>\r\n\r\n"}}
            self.assertEqual(kopie_in_gesendet(EML, config.user, "<sent@test>"), "Sent")
            client.append.assert_called_once_with("Sent", EML, flags=[b"\\Seen"])
            client.append.reset_mock()
            client.fetch.return_value = {11: {b"BODY[HEADER.FIELDS (MESSAGE-ID)]": b"Message-ID: <sent@test>\r\n\r\n"}}
            self.assertEqual(kopie_in_gesendet(EML, config.user, "<sent@test>"), "Sent")
            client.append.assert_not_called()

    def test_missing_imap_configuration_is_reported(self):
        with patch("app.gesendet_ablage.lade_postfaecher", return_value=[]):
            with self.assertRaisesRegex(RuntimeError, "nicht konfiguriert"):
                kopie_in_gesendet(EML, "service@example.test", "<sent@test>")


class GesendeteAntwortenTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async def override():
            async with self.sessions() as session:
                yield session
        main.app.dependency_overrides[main.get_session] = override
        self.env_patch = patch.dict(os.environ, {"KRAUTL_SESSION_SECRET": "synthetic-sent-tests-only"})
        self.env_patch.start()
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="https://krautl.test")
        self.admin = {"Cookie": f"{COOKIE_NAME}={sitzung_erstellen('erik')}"}
        self.sachbearbeiter = {"Cookie": f"{COOKIE_NAME}={sitzung_erstellen('ludwig')}"}
        async with self.sessions() as session:
            postfach = Postfach(adresse="service@example.test", funktion="service", imap_host="imap.example.test")
            session.add(postfach)
            session.add(Klassifikation(klassifikation_id="PRIVAT", hauptkategorie="Privat",
                unterkategorie="Privat", beschreibung="Test", standard_prio="normal", aktion_id="KEINE_AKTION"))
            session.add(RollenMailzugriff(rolle="sachbearbeiter", klassifikation_id="PRIVAT", darf_sehen=False))
            await session.flush()
            jetzt = datetime.now(timezone.utc)
            self.ids = []
            for i in range(4):
                mail = Mail(message_id=f"<mail-{i}@test>", postfach_id=postfach.id,
                    absender_name="Mika Muster" if i == 0 else f"Kunde {i}", absender_adresse=f"kunde{i}@example.test",
                    antwort_an_adresse="ziel@example.test" if i == 0 else None,
                    betreff=f"Frage {i}", text_auszug="Anfrage.", empfangen_am=jetzt,
                    im_krautl_posteingang=False, klassifikation_id="PRIVAT" if i == 2 else None,
                    zustaendigkeit_manuell=i == 3, zustaendig_admin=True, zustaendig_sachbearbeiter=False)
                session.add(mail)
                await session.flush()
                entwurf = Entwurf(mail_id=mail.id, text_ki="Entwurf niemals als gesendet zeigen",
                    text_final="Original 100% Antwort" if i == 0 else f"Antwort {i}",
                    text_final_deutsch="Deutsche Arbeitsfassung", status="versendet",
                    versendet_am=jetzt-timedelta(days=i))
                session.add(entwurf)
                await session.flush()
                self.ids.append(entwurf.id)
                if i != 1:
                    session.add(Versandkopie(entwurf_id=entwurf.id, message_id=f"<sent-{i}@test>",
                        absender="service@example.test", empfaenger=f"snapshot{i}@example.test",
                        betreff=f"Re: Frage {i}", gesendet_von="Testnutzer", anhaenge=["Anhang.pdf"],
                        eml=EML))
            session.add(Entwurf(mail_id=mail.id, text_ki="Wartender Entwurf", status="wartet"))
            await session.commit()

    async def asyncTearDown(self):
        await self.client.aclose()
        main.app.dependency_overrides.clear()
        self.env_patch.stop()
        await self.engine.dispose()

    async def test_history_search_pagination_and_final_text(self):
        response = await self.client.get("/gesendet", headers=self.admin)
        self.assertEqual(response.status_code, 200, response.text)
        daten = response.json()
        self.assertEqual(daten["gesamt"], 4)
        self.assertEqual([e["id"] for e in daten["eintraege"]], self.ids)
        self.assertNotIn("eml", daten["eintraege"][0])
        self.assertNotIn("text", daten["eintraege"][0])
        self.assertEqual((await self.client.get("/gesendet?suche=Mika", headers=self.admin)).json()["gesamt"], 1)
        self.assertEqual((await self.client.get("/gesendet", params={"suche": "%"}, headers=self.admin)).json()["gesamt"], 1)
        self.assertEqual((await self.client.get("/gesendet?suche=snapshot0", headers=self.admin)).json()["gesamt"], 1)
        page = (await self.client.get("/gesendet?pro_seite=1&seite=2", headers=self.admin)).json()
        self.assertEqual(page["eintraege"][0]["id"], self.ids[1])
        detail = (await self.client.get(f"/gesendet/{self.ids[0]}", headers=self.admin)).json()
        self.assertEqual(detail["text"], "Original 100% Antwort")
        self.assertEqual(detail["empfaenger"], "snapshot0@example.test")
        self.assertEqual(detail["text_deutsch"], "Deutsche Arbeitsfassung")
        self.assertEqual(detail["anfrage"]["text"], "Anfrage.")

    async def test_legacy_answer_and_log_are_available_without_invented_eml(self):
        ident = self.ids[1]
        detail = (await self.client.get(f"/gesendet/{ident}", headers=self.admin)).json()
        self.assertTrue(detail["historisch"])
        self.assertEqual(detail["text"], "Antwort 1")
        self.assertIsNone(detail["anhaenge"])
        self.assertIsNone(detail["absender"])
        self.assertEqual((await self.client.get(f"/gesendet/{ident}/eml", headers=self.admin)).status_code, 404)
        self.assertEqual((await self.client.post(f"/gesendet/{ident}/ablage", headers=self.admin)).status_code, 409)
        log = (await self.client.get(f"/aktionslog/mails/{detail['mail_id']}", headers=self.admin)).json()
        self.assertEqual(log["gesendete_antworten"][0]["text"], "Antwort 1")

    async def test_login_classification_and_manual_assignment_guard_all_routes(self):
        for url in ("/gesendet", f"/gesendet/{self.ids[0]}", f"/gesendet/{self.ids[0]}/eml"):
            self.assertEqual((await self.client.get(url)).status_code, 401)
        self.assertEqual((await self.client.post(f"/gesendet/{self.ids[0]}/ablage")).status_code, 401)
        daten = (await self.client.get("/gesendet", headers=self.sachbearbeiter)).json()
        self.assertEqual(daten["gesamt"], 2)
        for ident in self.ids[2:]:
            for suffix in ("", "/eml"):
                self.assertEqual((await self.client.get(f"/gesendet/{ident}{suffix}", headers=self.sachbearbeiter)).status_code, 403)
            self.assertEqual((await self.client.post(f"/gesendet/{ident}/ablage", headers=self.sachbearbeiter)).status_code, 403)

    async def test_exact_eml_download(self):
        response = await self.client.get(f"/gesendet/{self.ids[0]}/eml", headers=self.admin)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, EML)
        self.assertIn("message/rfc822", response.headers["content-type"])
        self.assertEqual(response.headers["cache-control"], "private, no-store")

    async def test_failed_copy_preserves_sent_state_and_retry_never_sends_smtp(self):
        ident = self.ids[0]
        with patch("app.gesendet_ablage.kopie_in_gesendet", side_effect=RuntimeError("IMAP offline")), \
             patch("app.mail_versand._synchron_senden") as smtp, \
             self.assertLogs("app.gesendet_ablage", level="ERROR"):
            response = await self.client.post(f"/gesendet/{ident}/ablage", headers=self.admin)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["imap_status"], "fehler")
            smtp.assert_not_called()
        async with self.sessions() as session:
            entwurf = await session.get(Entwurf, ident)
            self.assertEqual(entwurf.status, "versendet")
            self.assertEqual(entwurf.text_final, "Original 100% Antwort")
            kopie = await session.get(Versandkopie, ident)
            self.assertEqual(kopie.imap_versuche, 1)
        with patch("app.gesendet_ablage.kopie_in_gesendet", return_value="Sent") as ablage, \
             patch("app.mail_versand._synchron_senden") as smtp:
            response = await self.client.post(f"/gesendet/{ident}/ablage", headers=self.admin)
            self.assertEqual(response.json()["imap_status"], "gespeichert")
            await self.client.post(f"/gesendet/{ident}/ablage", headers=self.admin)
            ablage.assert_called_once()
            smtp.assert_not_called()

    async def test_retry_refreshes_status_after_another_session_archived(self):
        ident = self.ids[0]
        async with self.sessions() as first:
            cached = await first.get(Versandkopie, ident)
            self.assertEqual(cached.imap_status, "ausstehend")
            async with self.sessions() as other:
                copy = await other.get(Versandkopie, ident)
                copy.imap_status = "gespeichert"
                copy.imap_ordner = "Sent"
                await other.commit()
            with patch("app.gesendet_ablage.kopie_in_gesendet") as ablage:
                result = await versandkopie_ablegen(first, ident)
                self.assertEqual(result.imap_status, "gespeichert")
                ablage.assert_not_called()

    async def test_background_picks_persisted_pending_copies(self):
        with patch("app.gesendet_ablage.kopie_in_gesendet", return_value="Sent") as ablage:
            await ausstehende_kopien_ablegen(self.sessions)
            self.assertEqual(ablage.call_count, 3)
            await ausstehende_kopien_ablegen(self.sessions)
            self.assertEqual(ablage.call_count, 3)
        async with self.sessions() as session:
            kopien = (await session.execute(select(Versandkopie))).scalars().all()
            self.assertTrue(all(k.imap_status == "gespeichert" for k in kopien))

    async def test_failed_copy_retry_delay_and_attempt_limit(self):
        async with self.sessions() as session:
            for ident in (self.ids[0], *self.ids[2:]):
                kopie = await session.get(Versandkopie, ident)
                kopie.imap_status = "fehler"
                kopie.imap_letzter_versuch = datetime.now(timezone.utc)
                kopie.imap_versuche = 1
            await session.commit()
        with patch("app.gesendet_ablage.kopie_in_gesendet", return_value="Sent") as ablage:
            await ausstehende_kopien_ablegen(self.sessions)
            ablage.assert_not_called()
            async with self.sessions() as session:
                for ident in (self.ids[0], self.ids[2]):
                    kopie = await session.get(Versandkopie, ident)
                    kopie.imap_letzter_versuch = datetime.now(timezone.utc)-timedelta(minutes=6)
                    kopie.imap_versuche = 10 if ident == self.ids[2] else 1
                await session.commit()
            await ausstehende_kopien_ablegen(self.sessions)
            ablage.assert_called_once()


if __name__ == "__main__":
    unittest.main()
