import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch
from uuid import UUID

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")
import httpx
from app import inkasso, inkasso_service, main
from app.auth import COOKIE_NAME, sitzung_erstellen
from app.jtl_client import JtlFehler


def invoice(n=1, **kw):
    return dict(salesInvoiceId=str(UUID(int=n)), salesChannelId=inkasso.KANAL,
                salesInvoiceNumber=f"RE-{n}", salesInvoiceDate="2026-01-02T23:00:00",
                isDraft=False, isCancelled=False, isCompletelyPaid=False,
                isDunningBlocked=False, stillToPay=25.50, totalGrossAmount=100,
                currencyIso="EUR", billingAddressFirstName="Erika", billingAddressLastName="Muster", **kw)


def page(rows, number=1, total=None, more=False):
    return dict(items=rows, pageNumber=number, pageSize=100,
                totalItems=len(rows) if total is None else total, hasNextPage=more)


def client(*pages):
    c = AsyncMock()
    c._request.side_effect = [dict(id=inkasso.KANAL, type=1, name="dreikraut"), *pages]
    c.__aenter__.return_value = c
    return c


class AuswahlTest(unittest.TestCase):
    def test_teilzahlung_und_name_aus_rechnungsadresse(self):
        row = invoice()
        row.update(billingAddressCompanyName="Firma", shipmentAddressLastName="Falscher Name", isDunningBlocked=True)
        result = inkasso.rechnung(row)
        self.assertEqual(result["offen"], "25.5")
        self.assertEqual(result["betrag"], "100")
        self.assertEqual(result["kunde"], "Firma · Erika Muster")
        self.assertTrue(result["mahnsperre"])
        self.assertEqual(result["datum"], "2026-01-02")

    def test_ausgeschlossene_rechnungen(self):
        for changes in ({"salesChannelId": "amazon"}, {"salesChannelId": "2-3-1"},
                        {"isDraft": True}, {"isCancelled": True}, {"stillToPay": 0},
                        {"stillToPay": -10}, {"stillToPay": 0, "isCompletelyPaid": True}):
            with self.subTest(changes=changes):
                self.assertIsNone(inkasso.rechnung(invoice() | changes))

    def test_fehlende_werte_sind_keine_bezahlte_rechnung(self):
        for key in ("stillToPay", "totalGrossAmount", "isCancelled", "currencyIso", "salesInvoiceDate"):
            row = invoice()
            del row[key]
            with self.subTest(key=key), self.assertRaises(JtlFehler):
                inkasso.rechnung(row)
        for val in ("NaN", "Infinity", None):
            with self.assertRaises(JtlFehler):
                inkasso.rechnung(invoice() | {"stillToPay": val})
        with self.assertRaises(JtlFehler):
            inkasso.rechnung(invoice() | {"isCompletelyPaid": True})

    def test_status_und_tagesintervall(self):
        now = datetime(2026, 10, 21, tzinfo=timezone.utc)
        self.assertTrue(inkasso.status({}, now)["veraltet"])
        for age, stale in ((0, False), (24, False), (25, True), (-1, True)):
            data = {"letzter_erfolg": (now - timedelta(hours=age)).isoformat()}
            self.assertEqual(inkasso.status(data, now)["veraltet"], stale)
        interrupted = inkasso.status({"status": "laeuft", "letzter_versuch": (now - timedelta(hours=2)).isoformat()}, now)
        self.assertEqual(interrupted["status"], "fehler")
        self.assertTrue(inkasso_service.faellig({}, now))
        self.assertFalse(inkasso_service.faellig({"letzter_versuch": (now - timedelta(hours=23)).isoformat()}, now))
        self.assertTrue(inkasso_service.faellig({"letzter_versuch": (now - timedelta(days=1)).isoformat()}, now))


class AbrufTest(unittest.IsolatedAsyncioTestCase):
    async def test_leere_liste_ist_erfolgreich(self):
        result = await inkasso.abrufen(client(page([])))
        self.assertEqual(result["rechnungen"], [])
        self.assertEqual(result["geprueft"], 0)

    async def test_alle_seiten_und_ausschliesslich_get(self):
        c = client(page([invoice(1)], total=2, more=True), page([invoice(2) | {"salesChannelId": "amazon"}], number=2, total=2))
        result = await inkasso.abrufen(c)
        self.assertEqual(len(result["rechnungen"]), 1)
        self.assertEqual(result["geprueft"], 2)
        self.assertTrue(all(call.args[0] == "GET" for call in c._request.call_args_list))
        self.assertEqual(c._request.call_args_list[-1].kwargs["params"]["pageNumber"], 2)

    async def test_unvollstaendig_doppelt_veraendert_und_falscher_shop(self):
        for pages in ([page([invoice()], total=2)],
                      [page([invoice()], total=2, more=True), page([invoice()], number=2, total=2)],
                      [page([invoice()], total=2, more=True), page([], number=2, total=3)]):
            with self.assertRaises(JtlFehler):
                await inkasso.abrufen(client(*pages))
        c = client()
        c._request.side_effect = [dict(id="anderer-shop", type=1)]
        with self.assertRaises(JtlFehler):
            await inkasso.abrufen(c)
        row = invoice()
        del row["salesChannelId"]
        with self.assertRaises(JtlFehler):
            await inkasso.abrufen(client(page([row])))

    async def test_fehler_erhaelt_snapshot_bezahlt_entfernt_rechnung(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertTrue(await inkasso_service.lauf(folder, lambda: client(page([invoice()]))))
            before = inkasso.lesen(folder)
            c = client()
            c._request.side_effect = JtlFehler("HTTP 403")
            self.assertFalse(await inkasso_service.lauf(folder, lambda: c))
            after = inkasso.lesen(folder)
            self.assertEqual(after["rechnungen"], before["rechnungen"])
            self.assertEqual(after["letzter_erfolg"], before["letzter_erfolg"])
            self.assertEqual(after["status"], "fehler")
            self.assertTrue(await inkasso_service.lauf(folder, lambda: client(page([invoice() | {"stillToPay": 0}]))))
            self.assertEqual(inkasso.lesen(folder)["rechnungen"], [])

    async def test_timeout_erhaelt_snapshot(self):
        with tempfile.TemporaryDirectory() as folder:
            inkasso.speichern({"rechnungen": [inkasso.rechnung(invoice())], "letzter_erfolg": None}, folder)
            c = client()
            c._request.side_effect = TimeoutError()
            self.assertFalse(await inkasso_service.lauf(folder, lambda: c))
            self.assertEqual(len(inkasso.lesen(folder)["rechnungen"]), 1)

    async def test_api_admin_staff_und_anonym(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {
                "KRAUTL_SESSION_SECRET": "inkasso-test-secret", "INKASSO_DIR": folder}):
            inkasso.speichern({"rechnungen": [inkasso.rechnung(invoice())], "letzter_erfolg": None}, folder)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="https://test") as web:
                self.assertEqual((await web.get("/inkasso")).status_code, 401)
                for user, code in (("ludwig", 403), ("erik", 200)):
                    response = await web.get("/inkasso", headers={"Cookie": f"{COOKIE_NAME}={sitzung_erstellen(user)}"})
                    self.assertEqual(response.status_code, code)
                    if code == 200:
                        self.assertEqual(response.headers["cache-control"], "no-store")
                        self.assertEqual(len(response.json()["rechnungen"]), 1)
                    else:
                        self.assertNotIn("Erika", response.text)
