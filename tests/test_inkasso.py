import json
import os
import tempfile
import unittest
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")
import httpx
from app import inkasso, inkasso_service, inkasso_zugang, main
from app.auth import COOKIE_NAME, sitzung_erstellen
from app.jtl_client import JtlFehler
from app.jtl_onprem import OnPremClient

NOW = datetime(2026, 10, 21, 12, tzinfo=timezone.utc)


def invoice(n=1, date="2026-01-02T23:00:00", payment=1, due=25.5, cancelled=False):
    return {"Id": n, "Number": f"RE-{n}", "InvoiceDate": date,
            "IsCancelled": cancelled, "DunningBlock": False,
            "BillingAddress": {"FirstName": "Erika", "LastName": "Muster"},
            "InvoicePaymentDetails": {"PaymentMethodId": 12, "PaymentStatus": payment, "StillToPay": due,
                                      "TotalGrossAmount": 100, "CurrencyIso": "EUR"}}


class Server:
    def __init__(self, rows=(), details=None, channels=None, orders=None, lines=None):
        self.rows, self.details = list(rows), details or {}
        self.channels = channels if channels is not None else [{"id": inkasso.KANAL, "type": 0, "name": "dreikraut"}, {"id": "1-1-0", "type": 0, "name": "JTL-Wawi"}]
        self.orders, self.lines, self.requests = orders or {}, lines or {}, []
        self.failure = None
        self.broken_page = None

    def handler(self, r):
        self.requests.append(r)
        path = r.url.path.removeprefix("/api/eazybusiness")
        if self.failure and path == self.failure:
            return httpx.Response(403)
        if path == "/v2/sales-channels":
            return httpx.Response(200, json=self.channels)
        if path == "/v1/invoices":
            payment = int(r.url.params["paymentStatus"])
            rows = [i for i in self.rows if i["InvoicePaymentDetails"]["PaymentStatus"] == payment]
            page = int(r.url.params["pageNumber"])
            data = {"Items": rows[(page-1)*100:page*100], "TotalItems": len(rows),
                    "PageNumber": page, "PageSize": 100, "HasNextPage": page*100 < len(rows)}
            if self.broken_page:
                data.update(self.broken_page)
            return httpx.Response(200, json=data)
        if path.endswith("/lineitems"):
            n = int(path.split("/")[-2])
            return httpx.Response(200, json=self.lines.get(n, [{"InvoiceId": n, "SalesOrderId": n, "Name": "Artikel", "SKU": "SKU1", "Quantity": 2, "SalesPriceGross": 12.5}]))
        if path.startswith("/v1/salesOrders/"):
            n = int(path.rsplit("/", 1)[1])
            return httpx.Response(200, json={"Id": n, "SalesChannelId": self.orders.get(n, inkasso.KANAL), "Number": f"AU-{n}", "BillingAddress": {"PhoneNumber": "0123 456", "MobilePhoneNumber": "0170 111"}})
        if path.startswith("/v1/invoices/"):
            n = int(path.rsplit("/", 1)[1])
            return httpx.Response(200, json=self.details[n]) if n in self.details else httpx.Response(404)
        return httpx.Response(404)

    def client(self):
        return OnPremClient("https://wawi.test/api/eazybusiness", "test", transport=httpx.MockTransport(self.handler))

    async def run(self, bestand=None, zeit=NOW):
        async with self.client() as c:
            return await inkasso.abrufen(c, bestand, zeit)


class AuswahlTest(unittest.TestCase):
    def test_name_betrag_status(self):
        row = invoice()
        row["BillingAddress"]["Company"] = "Firma"
        row["DunningBlock"] = True
        result = inkasso.rechnung(row)
        self.assertEqual(result["kunde"], "Firma · Erika Muster")
        self.assertEqual(result["offen"], "25.5")
        self.assertTrue(result["mahnsperre"])
        self.assertEqual(result["status"], "offen")
        self.assertEqual(result["zahlungsart_id"], 12)
        self.assertEqual(inkasso.rechnung(invoice(due=0, payment=2))["status"], "bezahlt")
        self.assertEqual(inkasso.rechnung(invoice(cancelled=True))["status"], "storniert")

    def test_invalid_amount_paid_and_id(self):
        for due in (None, "NaN", "Infinity"):
            with self.assertRaises(JtlFehler):
                inkasso.rechnung(invoice(due=due))
        with self.assertRaises(JtlFehler):
            inkasso.rechnung(invoice(payment=2))
        for ident in (True, 0, -1, "1"):
            with self.assertRaises(JtlFehler):
                inkasso.rechnung(invoice(ident))

    def test_calendar_window_and_timezone(self):
        self.assertEqual(inkasso.fenster(NOW), ("2025-10-21", "2026-10-21"))
        self.assertEqual(inkasso.fenster(datetime(2024, 2, 29, tzinfo=timezone.utc)), ("2023-02-28", "2024-02-29"))
        self.assertEqual(inkasso.fenster(datetime(2026, 10, 20, 23, tzinfo=timezone.utc))[1], "2026-10-21")

    def test_status_and_interval(self):
        self.assertTrue(inkasso.status({}, NOW)["veraltet"])
        for hours, stale in ((0, False), (24, False), (25, True), (-1, True)):
            data = {"letzter_erfolg": (NOW-timedelta(hours=hours)).isoformat()}
            self.assertEqual(inkasso.status(data, NOW)["veraltet"], stale)
        self.assertFalse(inkasso_service.faellig({"letzter_versuch": NOW.isoformat()}, NOW))
        self.assertTrue(inkasso_service.faellig({}, NOW))


class AbrufTest(unittest.IsolatedAsyncioTestCase):
    async def test_window_shop_and_all_pages(self):
        rows = [invoice(n, date="2020-01-01") for n in range(1, 102)]
        rows += [invoice(102, date="2025-10-21"), invoice(103), invoice(104, date="2026-10-22")]
        server = Server(rows, orders={103: "amazon"})
        result = await server.run()
        self.assertEqual([i["id"] for i in result["rechnungen"]], ["102"])
        self.assertEqual(result["geprueft"], 104)
        self.assertTrue(all(r.method == "GET" for r in server.requests))
        self.assertEqual(sum(r.url.path.endswith("/lineitems") for r in server.requests), 2)
        self.assertTrue(any(r.url.params.get("pageNumber") == "2" for r in server.requests))

    async def test_old_case_closes_and_reopens_outside_window(self):
        first = await Server([invoice(date="2025-10-21")]).run()
        original = deepcopy(first)
        later = NOW + timedelta(days=2)
        open_result = await Server([invoice(date="2025-10-21")]).run(first, later)
        self.assertEqual(len(open_result["rechnungen"]), 1)
        closed = await Server(details={1: invoice(date="2025-10-21", due=0, payment=2)}).run(first, later)
        self.assertEqual(closed["rechnungen"], [])
        self.assertEqual(closed["faelle"]["1"]["status"], "bezahlt")
        self.assertEqual(closed["faelle"]["1"]["erfasst_am"], first["faelle"]["1"]["erfasst_am"])
        reopened = await Server([invoice(date="2025-10-21")]).run(closed, later)
        self.assertEqual(len(reopened["rechnungen"]), 1)
        self.assertNotIn("abgeschlossen_am", reopened["faelle"]["1"])
        self.assertEqual(first, original)

    async def test_cancelled_archived(self):
        first = await Server([invoice()]).run()
        result = await Server(details={1: invoice(cancelled=True)}).run(first)
        self.assertEqual(result["rechnungen"], [])
        self.assertEqual(result["faelle"]["1"]["status"], "storniert")

    async def test_empty(self):
        self.assertEqual((await Server().run())["rechnungen"], [])

    async def test_missing_tracked_invoice_is_error(self):
        first = await Server([invoice()]).run()
        with self.assertRaisesRegex(JtlFehler, "404"):
            await Server().run(first)

    async def test_ambiguous_missing_and_foreign_position(self):
        for lines in ([], [{"InvoiceId": 1, "SalesOrderId": 0}],
                      [{"InvoiceId": 2, "SalesOrderId": 1}],
                      [{"InvoiceId": 1, "SalesOrderId": 1}, {"InvoiceId": 1, "SalesOrderId": 2}]):
            with self.subTest(lines=lines), self.assertRaises(JtlFehler):
                await Server([invoice()], lines={1: lines}, orders={2: "amazon"}).run()

    async def test_phones_and_order_overview(self):
        row = invoice()
        row["BillingAddress"].update(PhoneNumber="0123-456", MobilePhoneNumber="")
        result = await Server([row]).run()
        item = result["rechnungen"][0]
        self.assertEqual(item["telefone"], ["0123-456", "0170 111"])
        self.assertEqual(item["bestellungen"][0]["nummer"], "AU-1")
        self.assertEqual(item["bestellungen"][0]["positionen"][0]["menge"], "2")
        self.assertEqual(item["bestellungen"][0]["positionen"][0]["einzelpreis"], "12.5")
        closed = await Server(details={1: invoice(due=0, payment=2)}).run(result)
        self.assertEqual(closed["faelle"]["1"]["bestellungen"], item["bestellungen"])

    async def test_re315603_wawi_order_channel_alias(self):
        row = invoice(369597, date="2026-10-07T12:15:28.817+02:00", payment=0, due=38.7)
        row["Number"] = "RE315603"
        row["InvoicePaymentDetails"]["TotalGrossAmount"] = 38.7
        lines = {369597: [{"InvoiceId": 369597, "SalesOrderId": 441222}]}
        result = await Server([row], lines=lines, orders={441222: "1-1-1"}).run()
        self.assertEqual(len(result["rechnungen"]), 1)
        actual = result["rechnungen"][0]
        self.assertEqual(actual["nummer"], "RE315603")
        self.assertEqual(actual["offen"], "38.7")
        self.assertEqual(actual["kanal"], "JTL-Wawi")
        self.assertEqual(actual["kanaele"], ["1-1-0"])
        self.assertEqual(actual["bestellungen"][0]["quellkanal_id"], "1-1-1")
        for foreign in ("1-1-2", "1-2-1", "6-51-1"):
            result = await Server([row], lines=lines, orders={441222: foreign}).run()
            self.assertEqual(result["rechnungen"], [])

    async def test_combined_allowed_channels(self):
        lines = {1: [{"InvoiceId": 1, "SalesOrderId": n} for n in (1, 2)]}
        result = await Server([invoice()], lines=lines, orders={2: "1-1-0"}).run()
        self.assertEqual(len(result["rechnungen"]), 1)
        self.assertEqual(len(result["rechnungen"][0]["bestellungen"]), 2)
        self.assertEqual(result["rechnungen"][0]["kanaele"], ["1-1-0", inkasso.KANAL])

    async def test_orders_cached_per_run(self):
        lines = {n: [{"InvoiceId": n, "SalesOrderId": 1}] for n in (1, 2)}
        server = Server([invoice(1), invoice(2)], lines=lines)
        self.assertEqual(len((await server.run())["rechnungen"]), 2)
        self.assertEqual(sum("salesOrders" in r.url.path for r in server.requests), 1)

    async def test_live_channel_types_include_wawi_but_not_marketplaces(self):
        channels = [
            {"id": "1-1-0", "type": 0, "name": "JTL-Wawi"},
            {"id": "2-2-1", "type": 0, "name": "JTL-Shop: dreikraut JTL-Shop"},
            {"id": "5-30-1", "type": 3, "name": "Ebay"},
            {"id": "6-51-1", "type": 9, "name": "Amazon dreikraut"},
        ]
        server = Server([invoice(1), invoice(2), invoice(3)], channels=channels,
                        orders={2: "1-1-0", 3: "6-51-1"})
        result = await server.run()
        self.assertEqual([r["id"] for r in result["rechnungen"]], ["1", "2"])
        self.assertEqual(result["shop"], "JTL-Shop und JTL-Wawi")
        self.assertEqual(result["rechnungen"][1]["kanal"], "JTL-Wawi")
        for invalid in (channels[:1], [channels[1], channels[1]],
                        [channels[1] | {"type": 1}], [channels[1] | {"type": 9}]):
            with self.subTest(channels=invalid), self.assertRaises(JtlFehler):
                await Server(channels=invalid).run()

    async def test_bad_pagination_duplicate_and_channels(self):
        for bad in ({"TotalItems": 2}, {"HasNextPage": True}, {"PageNumber": 4}, {"HasNextPage": None}):
            server = Server([invoice()]); server.broken_page = bad
            with self.subTest(bad=bad), self.assertRaises(JtlFehler):
                await server.run()
        with self.assertRaises(JtlFehler):
            await Server([invoice(), invoice()]).run()
        for channels in ([], [{"id": inkasso.KANAL, "type": True}], [None]):
            with self.assertRaises(JtlFehler):
                await Server(channels=channels).run()

    async def test_failure_preserves_cases_and_last_success(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch("app.inkasso.jetzt", return_value=NOW):
                self.assertTrue(await inkasso_service.lauf(folder, Server([invoice()]).client))
                before = inkasso.lesen(folder)
                server = Server([invoice()]); server.failure = "/v1/salesOrders/1"
                self.assertFalse(await inkasso_service.lauf(folder, server.client))
            after = inkasso.lesen(folder)
            for key in ("faelle", "rechnungen", "letzter_erfolg"):
                self.assertEqual(after[key], before[key])
            self.assertEqual(after["status"], "fehler")

    async def test_api_permissions_and_no_archive_in_response(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {
                "KRAUTL_SESSION_SECRET": "inkasso-test-secret", "INKASSO_DIR": folder}):
            inkasso.speichern(await Server([invoice()]).run(), folder)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="https://test") as web:
                self.assertEqual((await web.get("/inkasso")).status_code, 401)
                for user, code in (("ludwig", 403), ("erik", 200)):
                    response = await web.get("/inkasso", headers={"Cookie": f"{COOKIE_NAME}={sitzung_erstellen(user)}"})
                    self.assertEqual(response.status_code, code)
                    if code == 200:
                        self.assertEqual(response.headers["cache-control"], "no-store")
                        self.assertNotIn("faelle", response.json())
                    else:
                        self.assertNotIn("Erika", response.text)


class ZugangTest(unittest.TestCase):
    def test_separate_identity_and_no_faq_fallback(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {
                "INKASSO_ZUGANG_DIR": folder, "JTL_LOCAL_URL": "https://wawi.test/api/eazybusiness",
                "JTL_LOCAL_API_KEY": "faq-secret"}):
            with self.assertRaises(JtlFehler):
                inkasso_zugang.client_aus_umgebung()
            data = {"app_id": inkasso_zugang.APP_ID, "api_key": "inkasso-secret",
                    "api_url": os.environ["JTL_LOCAL_URL"], "scopes": inkasso_zugang.SCOPES}
            inkasso_zugang.sichern(Path(folder)/"zugang.json", data)
            c = inkasso_zugang.client_aus_umgebung()
            self.assertEqual(c.http.headers["x-appid"], "krautl-inkasso")
            self.assertEqual(c.http.headers["Authorization"], "Wawi inkasso-secret")
            import asyncio
            asyncio.run(c.http.aclose())
            data["scopes"] = ["invoices.read"]
            with self.assertRaises(JtlFehler):
                inkasso_zugang.validieren(data)

    def test_exclusive_registration_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/"anfrage.json"
            inkasso_zugang.sichern(path, {"original": True}, exklusiv=True)
            with self.assertRaises(FileExistsError):
                inkasso_zugang.sichern(path, {"original": False}, exklusiv=True)
            self.assertTrue(json.loads(path.read_text())["original"])

class RegistrierungTest(unittest.IsolatedAsyncioTestCase):
    async def test_register_retrieve_and_recover_without_second_get(self):
        from contextlib import redirect_stdout
        from io import StringIO
        requests = []
        def handler(r):
            requests.append(r)
            self.assertNotIn("authorization", r.headers)
            self.assertEqual(r.headers["x-appid"], "krautl-inkasso")
            if r.method == "POST":
                payload = json.loads(r.content)
                self.assertEqual(payload["mandatoryApiScopes"], inkasso_zugang.SCOPES)
                self.challenge = r.headers["x-challengecode"]
                return httpx.Response(201, json={"registrationRequestId": "reg-1", "status": 0})
            self.assertEqual(r.headers["x-challengecode"], self.challenge)
            return httpx.Response(200, json={"requestStatusInfo": {"status": 2},
                "token": {"apiKey": "never-print-me"}, "grantedScopes": inkasso_zugang.SCOPES})
        def factory(url, key, **kwargs):
            return OnPremClient(url, key, transport=httpx.MockTransport(handler))
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {
                "INKASSO_ZUGANG_DIR": folder, "JTL_LOCAL_URL": "https://wawi.test/api/eazybusiness"}), \
                patch("app.inkasso_zugang.OnPremClient", side_effect=factory), redirect_stdout(StringIO()) as out:
            await inkasso_zugang.registrieren()
            with self.assertRaises(JtlFehler):
                await inkasso_zugang.registrieren()
            await inkasso_zugang.registrieren(True)
            self.assertEqual(len(requests), 2)
            self.assertNotIn("never-print-me", out.getvalue())
            saved = json.loads((Path(folder)/"zugang.json").read_text())
            self.assertEqual(saved["api_key"], "never-print-me")
            (Path(folder)/"zugang.json").unlink()
            # Recover from a failure after saving the one-shot response.
            await inkasso_zugang.registrieren(True)
            self.assertEqual(len(requests), 2)

    async def test_uncertain_get_never_repeated(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {
                "INKASSO_ZUGANG_DIR": folder, "JTL_LOCAL_URL": "https://wawi.test/api/eazybusiness"}):
            inkasso_zugang.sichern(Path(folder)/"anfrage.json", {
                "http": 201, "body": '{"registrationRequestId":"reg-1"}',
                "api_url": os.environ["JTL_LOCAL_URL"], "challenge": "test"})
            inkasso_zugang.sichern(Path(folder)/"schluesselantwort.json", {"phase": "abruf_gestartet"})
            with self.assertRaisesRegex(JtlFehler, "Nicht erneut"):
                await inkasso_zugang.registrieren(True)
