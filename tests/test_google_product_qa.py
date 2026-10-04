import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app import main
from app.auth import COOKIE_NAME, sitzung_erstellen
from app.google_product_qa import FEED_PFAD, GoogleProductQaFeed, atomar_schreiben, feed_bauen, plaintext
from app.models import Base, FaqEintrag, Produkt
from scripts.migrate_google_product_qa import migriere


def faq(ident=1, **werte):
    return dict({
        "faq_id": ident, "produkt_id": 1, "produkt_name": "Testprodukt",
        "artikelnummer": "00123", "produkt_aktiv": True, "sortierung": 0,
        "frage": "Frage?", "antwort": "Antwort.", "status": "freigegeben",
        "aktiv": True, "include_in_google_product_qa": True,
    }, **werte)


class FeedFormatTest(unittest.TestCase):
    def test_google_group_quoting_without_outer_csv_layer(self):
        ergebnis = feed_bauen([faq(
            frage='Wie "warm", wann: genau?', antwort='Pfad C:\\Kräuter, "Bio": ja.\t\nMehr.',
        ), faq(2, frage="Zweite?", antwort="Grün & gut")])
        self.assertEqual(ergebnis["tsv"],
            'id\tquestion_and_answer\n00123\t"Wie ""warm"", wann: genau?":"Pfad C:\\Kräuter, ""Bio"": ja. Mehr.","Zweite?":"Grün & gut"\n')
        self.assertEqual(len(ergebnis["tsv"].splitlines()), 2)
        self.assertEqual(ergebnis["anzahl_produkte"], 1)
        self.assertEqual(ergebnis["anzahl_qa"], 2)

    def test_plaintext_html_markdown_entities_and_controls(self):
        self.assertEqual(plaintext('<p>**Öl** &amp; Kräuter</p><script>privat</script><p>[Mehr](https://example.test)<br>2 &lt; 5</p>'), 'Öl & Kräuter Mehr 2 < 5')
        self.assertEqual(plaintext('- Eins\n- Zwei\t\x00Drei'), 'Eins Zwei Drei')
        self.assertEqual(plaintext('&lt;b&gt;Bio&lt;/b&gt;'), 'Bio')

    def test_checkbox_alone_selects_faqs_regardless_of_status_and_active_flags(self):
        for status in ("entwurf", "freigegeben", "veraltet"):
            for aktiv in (False, True):
                for produkt_aktiv in (False, True):
                    for ausgewaehlt in (False, True):
                        with self.subTest(status=status, aktiv=aktiv, produkt_aktiv=produkt_aktiv, ausgewaehlt=ausgewaehlt):
                            ergebnis = feed_bauen([faq(status=status, aktiv=aktiv, produkt_aktiv=produkt_aktiv,
                                include_in_google_product_qa=ausgewaehlt)])
                            self.assertEqual(ergebnis["anzahl_qa"], int(ausgewaehlt))
                            self.assertEqual(ergebnis["anzahl_produkte"], int(ausgewaehlt))
                            eintrag = ergebnis["produkte"][0]["faq"][0]
                            self.assertEqual(eintrag["exportiert"], ausgewaehlt)
                            self.assertEqual(eintrag["ausgewaehlt"], ausgewaehlt)
                            self.assertEqual(eintrag["gruende"], [])
                            self.assertEqual(ergebnis["warnungen"], [])

    def test_unselected_faqs_do_not_warn_or_block_selected_products(self):
        ergebnis = feed_bauen([
            faq(),
            faq(2, produkt_id=2, include_in_google_product_qa=False),
            faq(3, produkt_id=None, produkt_name=None, artikelnummer=None,
                frage="", antwort="a" * 1001, include_in_google_product_qa=False),
        ])
        self.assertEqual(ergebnis["anzahl_qa"], 1)
        self.assertEqual(ergebnis["warnungen"], [])
        for produkt in ergebnis["produkte"]:
            for eintrag in produkt["faq"]:
                self.assertEqual(eintrag["gruende"], [])
        ohne_produkt = feed_bauen([faq(produkt_id=None, produkt_name=None, artikelnummer=None)])
        self.assertEqual(ohne_produkt["anzahl_qa"], 0)
        self.assertIn("Keinem Produkt zugeordnet", ohne_produkt["warnungen"][0]["meldung"])

    def test_30_pairs_stable_order_and_warning(self):
        ergebnis = feed_bauen([faq(i, sortierung=100-i) for i in range(1, 32)])
        self.assertEqual(ergebnis["anzahl_qa"], 30)
        self.assertEqual(ergebnis["warnungen"][0]["faq_id"], 1)
        self.assertIn("30 Q&A", ergebnis["warnungen"][0]["meldung"])

    def test_1000_characters_accepted_1001_rejected_without_truncation(self):
        ergebnis = feed_bauen([faq(frage="ü" * 1000, antwort="a" * 1000), faq(2, antwort="a" * 1001), faq(3, frage="q" * 1001)])
        self.assertEqual(ergebnis["anzahl_qa"], 1)
        self.assertEqual(len(ergebnis["warnungen"]), 2)
        self.assertEqual(ergebnis["produkte"][0]["faq"][1]["antwort"], "a" * 1001)

    def test_total_10000_including_formatting_and_escaping(self):
        zeilen = [faq(i, frage="q" * 1000, antwort="a" * (995 if i == 5 else 994)) for i in range(1, 6)]
        ergebnis = feed_bauen(zeilen + [faq(6)])
        self.assertEqual(ergebnis["anzahl_qa"], 5)
        self.assertEqual(ergebnis["produkte"][0]["zeichen"], 10000)
        self.assertIn("10.000", ergebnis["warnungen"][0]["meldung"])
        ergebnis = feed_bauen([faq(i, frage='"' * 1000, antwort='"' * 1000) for i in range(1, 5)])
        self.assertEqual(ergebnis["anzahl_qa"], 2)

    def test_empty_and_missing_or_duplicate_ids(self):
        self.assertEqual(feed_bauen([])["tsv"], "id\tquestion_and_answer\n")
        for nummer in (None, "", "a\tb", "a\nb", "x" * 51):
            with self.subTest(nummer=nummer):
                e = feed_bauen([faq(artikelnummer=nummer)])
                self.assertEqual(e["anzahl_produkte"], 0)
                self.assertTrue(e["warnungen"])
        self.assertEqual(feed_bauen([faq(), faq(2, produkt_id=2)])["anzahl_qa"], 0)
        self.assertEqual(feed_bauen([faq(antwort="<p></p>")])["anzahl_qa"], 0)

    def test_id_with_single_space_and_quotes_is_not_changed(self):
        ergebnis = feed_bauen([faq(artikelnummer='00 X"1')])
        self.assertTrue(ergebnis["tsv"].splitlines()[1].startswith('"00 X""1"\t'))

    def test_atomic_replace_failure_keeps_previous_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            pfad = Path(tmp) / "feed.tsv"
            atomar_schreiben(pfad, "alt\n")
            with patch("app.google_product_qa.os.replace", side_effect=OSError("disk error")):
                with self.assertRaises(OSError):
                    atomar_schreiben(pfad, "neu\n")
            self.assertEqual(pfad.read_bytes(), b"alt\n")
            self.assertEqual(list(Path(tmp).iterdir()), [pfad])


class FeedApiTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.service = GoogleProductQaFeed(self.sessions, self.tmp.name)
        self.service_patch = patch.object(main, "google_product_qa_feed", self.service)
        self.service_patch.start()
        self.env_patch = patch.dict(os.environ, {"KRAUTL_SESSION_SECRET": "only-local-test-secret-not-a-production-key"})
        self.env_patch.start()
        async def session_override():
            async with self.sessions() as session:
                yield session
        main.app.dependency_overrides[main.get_session] = session_override
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="https://krautl.test")
        self.headers = {"Cookie": f"{COOKIE_NAME}={sitzung_erstellen('erik')}"}
        async with self.sessions() as session:
            produkt = Produkt(name="Testprodukt", artikelnummer="00123", aktiv=True)
            session.add(produkt)
            await session.commit()
            self.produkt_id = produkt.id

    async def asyncTearDown(self):
        await self.client.aclose()
        main.app.dependency_overrides.clear()
        self.service_patch.stop()
        self.env_patch.stop()
        await self.engine.dispose()
        self.tmp.cleanup()

    async def anlegen(self, **werte):
        daten = dict({"produkt_id": self.produkt_id, "kategorie": "Test", "frage": "Wie?", "antwort": "So.", "status": "freigegeben", "include_in_google_product_qa": True}, **werte)
        response = await self.client.post("/faq", json=daten, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    async def test_default_false_and_public_empty_feed_200_utf8(self):
        response = await self.client.post("/faq", json={"produkt_id": self.produkt_id, "kategorie": "Test", "frage": "Wie?", "antwort": "So.", "status": "freigegeben"}, headers=self.headers)
        self.assertFalse(response.json()["include_in_google_product_qa"])
        response = await self.client.get(FEED_PFAD)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.text, "id\tquestion_and_answer\n")
        self.assertIn("text/tab-separated-values", response.headers["content-type"])
        self.assertIn("charset=utf-8", response.headers["content-type"])
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual((await self.client.head(FEED_PFAD)).status_code, 200)
        for pfad in ("/faq", "/google-product-qa", f"/produkte/{self.produkt_id}/google-product-qa"):
            self.assertEqual((await self.client.get(pfad)).status_code, 401)
        self.assertEqual((await self.client.post("/google-product-qa/generieren")).status_code, 401)

    async def test_save_updates_disk_and_revoking_removes_immediately(self):
        eintrag = await self.anlegen(antwort="Öl & Kräuter")
        self.assertIn('"Öl & Kräuter"', self.service.pfad.read_text(encoding="utf-8"))
        response = await self.client.put(f"/faq/{eintrag['id']}", json={**eintrag, "include_in_google_product_qa": False}, headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.service.pfad.read_text(), "id\tquestion_and_answer\n")
        vorschau = (await self.client.get(f"/produkte/{self.produkt_id}/google-product-qa", headers=self.headers)).json()
        self.assertFalse(vorschau["faq"][0]["exportiert"])
        self.assertFalse(vorschau["faq"][0]["ausgewaehlt"])
        self.assertEqual(vorschau["faq"][0]["gruende"], [])

    async def test_checked_drafts_exported_and_jtl_unchanged_by_flag(self):
        eintrag = await self.anlegen(status="entwurf", antwort="**Fett** und Text")
        self.assertEqual(self.service.snapshot["anzahl_qa"], 1)
        self.assertEqual(eintrag["status"], "entwurf")
        self.assertIn('"Wie?":"Fett und Text"', (await self.client.get(FEED_PFAD)).text)
        vorschau = (await self.client.get(f"/produkte/{self.produkt_id}/google-product-qa", headers=self.headers)).json()
        self.assertTrue(vorschau["faq"][0]["ausgewaehlt"])
        self.assertTrue(vorschau["faq"][0]["exportiert"])
        self.assertEqual(vorschau["faq"][0]["gruende"], [])
        url = f"/produkte/{self.produkt_id}/faq-export"
        vorher = (await self.client.get(url, headers=self.headers)).json()
        await self.client.put(f"/faq/{eintrag['id']}", json={**eintrag, "include_in_google_product_qa": False}, headers=self.headers)
        nachher = (await self.client.get(url, headers=self.headers)).json()
        self.assertEqual(vorher, nachher)
        self.assertEqual(self.service.snapshot["anzahl_qa"], 0)
        self.assertEqual(vorher["entwuerfe"], 1)
        self.assertIn("<strong>Fett</strong>", vorher["html"])

    async def test_api_status_and_active_changes_leave_checked_faq_in_feed(self):
        eintrag = await self.anlegen(status="entwurf", aktiv=False)
        for status, aktiv, produkt_aktiv in (("veraltet", False, False), ("freigegeben", True, True)):
            with self.subTest(status=status, aktiv=aktiv, produkt_aktiv=produkt_aktiv):
                produkt = await self.client.put(f"/produkte/{self.produkt_id}", headers=self.headers,
                    json={"name": "Testprodukt", "artikelnummer": "00123", "aktiv": produkt_aktiv})
                self.assertEqual(produkt.status_code, 200, produkt.text)
                response = await self.client.put(f"/faq/{eintrag['id']}", headers=self.headers,
                    json={**eintrag, "status": status, "aktiv": aktiv})
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json()["status"], status)
                self.assertEqual(response.json()["aktiv"], aktiv)
                feed = await self.client.get(FEED_PFAD)
                self.assertEqual(feed.status_code, 200)
                self.assertIn('00123\t"Wie?":"So."', feed.text)
                self.assertEqual(self.service.snapshot["anzahl_qa"], 1)
                self.assertEqual(self.service.snapshot["warnungen"], [])

    async def test_direct_database_update_detected_and_rollback_ignored(self):
        eintrag = await self.anlegen()
        vorher = self.service.snapshot["letzte_generierung"]
        async with self.sessions() as session:
            await session.execute(text("UPDATE faq_eintrag SET antwort='Neu' WHERE id=:id"), {"id": eintrag["id"]})
            await session.rollback()
        await self.service.aktualisieren()
        self.assertEqual(vorher, self.service.snapshot["letzte_generierung"])
        async with self.sessions() as session:
            await session.execute(text("UPDATE faq_eintrag SET include_in_google_product_qa=FALSE WHERE id=:id"), {"id": eintrag["id"]})
            await session.commit()
        response = await self.client.get(FEED_PFAD)
        self.assertEqual(response.text, "id\tquestion_and_answer\n")

    async def test_product_id_changes_and_manual_generation(self):
        await self.anlegen()
        response = await self.client.put(f"/produkte/{self.produkt_id}", headers=self.headers, json={"name": "Testprodukt", "artikelnummer": "000099"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("000099\t", self.service.pfad.read_text())
        vorher = self.service.snapshot["letzte_generierung"]
        status = (await self.client.post("/google-product-qa/generieren", headers=self.headers)).json()
        self.assertNotEqual(vorher, status["letzte_generierung"])
        self.assertEqual(status["anzahl_produkte"], 1)
        self.assertEqual(status["anzahl_qa"], 1)
        self.assertNotIn("produkte", status)  # Vorschau nur über geschützten Produkt-Endpunkt

    async def test_failed_generation_does_not_serve_revoked_content(self):
        eintrag = await self.anlegen()
        alter_inhalt = self.service.pfad.read_bytes()
        with patch("app.google_product_qa.atomar_schreiben", side_effect=OSError("disk full")), self.assertLogs("app.google_product_qa", level="ERROR"):
            response = await self.client.put(f"/faq/{eintrag['id']}", headers=self.headers, json={**eintrag, "include_in_google_product_qa": False})
            self.assertEqual(response.status_code, 200)  # Datensatz wurde trotzdem gespeichert
            self.assertEqual(response.headers["x-krautl-google-feed"], "error")
            self.assertEqual((await self.client.get(FEED_PFAD)).status_code, 503)
            status = (await self.client.get("/google-product-qa", headers=self.headers)).json()
            self.assertFalse(status["aktuell"])
            self.assertTrue(status["fehler"])
        self.assertEqual(self.service.pfad.read_bytes(), alter_inhalt)
        self.assertEqual((await self.client.get(FEED_PFAD)).text, "id\tquestion_and_answer\n")

    async def test_concurrent_generators_and_deleted_file(self):
        await self.anlegen()
        await asyncio.gather(*(self.service.aktualisieren(erzwingen=True) for _ in range(4)))
        self.assertEqual(self.service.pfad.read_text(), self.service.snapshot["tsv"])
        self.service.pfad.unlink()
        self.assertEqual((await self.client.get(FEED_PFAD)).status_code, 200)
        self.assertTrue(self.service.pfad.exists())

    async def test_migration_existing_rows_false_and_idempotent(self):
        async with self.engine.begin() as conn:
            await conn.execute(text("DROP TABLE faq_eintrag"))
            await conn.execute(text("CREATE TABLE faq_eintrag (id INTEGER PRIMARY KEY, frage TEXT)"))
            await conn.execute(text("INSERT INTO faq_eintrag VALUES (1, 'Alt')"))
            await migriere(conn)
            self.assertEqual((await conn.execute(text("SELECT include_in_google_product_qa FROM faq_eintrag"))).scalar_one(), 0)
            await conn.execute(text("UPDATE faq_eintrag SET include_in_google_product_qa=TRUE"))
            await migriere(conn)
            self.assertEqual((await conn.execute(text("SELECT include_in_google_product_qa FROM faq_eintrag"))).scalar_one(), 1)

    async def test_startup_and_background_refresh_without_http_request(self):
        with patch.object(main, "engine", self.engine), patch("app.google_product_qa.POLL_INTERVAL_SECONDS", 0.01):
            await main.on_startup()
            try:
                self.assertEqual(self.service.pfad.read_text(), "id\tquestion_and_answer\n")
                async with self.sessions() as session:
                    session.add(FaqEintrag(produkt_id=self.produkt_id, kategorie="Test", frage="Extern?", antwort="Import.", status="freigegeben", aktiv=True, include_in_google_product_qa=True))
                    await session.commit()
                async def warten():
                    while self.service.snapshot["anzahl_qa"] != 1:
                        await asyncio.sleep(0.01)
                await asyncio.wait_for(warten(), timeout=3)
                self.assertIn('"Extern?":"Import."', self.service.pfad.read_text())
            finally:
                await main.google_qa_beenden()
            self.assertTrue(main.app.state.google_qa_task.cancelled())


if __name__ == "__main__":
    unittest.main()
