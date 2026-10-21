"""Read-only JTL invoice snapshot; no payment or message writes."""
import json
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from calendar import monthrange
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Request, Response
from .berechtigungen import ist_admin
from .jtl_client import JtlFehler

KANAL = "2-2-1"  # Confirmed dreikraut shop, also used by FAQ integration.
INTERVALL = timedelta(days=1)
router = APIRouter(prefix="/inkasso")


def jetzt():
    return datetime.now(timezone.utc)


def ordner():
    return Path(os.getenv("INKASSO_DIR", "/app/var/inkasso"))


def lesen(folder=None):
    path = Path(folder) if folder is not None else ordner()
    try:
        data = json.loads((path / "stand.json").read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("rechnungen"), list):
            raise ValueError()
        return data
    except FileNotFoundError:
        return {"rechnungen": [], "letzter_erfolg": None, "letzter_versuch": None,
                "fehler": None, "status": "unbekannt"}


def speichern(data, folder=None):
    path = Path(folder) if folder is not None else ordner()
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path / "stand.tmp"
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, allow_nan=False)
        f.flush()
        os.fsync(f.fileno())
    tmp.replace(path / "stand.json")


def betrag(value):
    try:
        number = Decimal(str(value))
        if not number.is_finite():
            raise InvalidOperation()
        return number
    except (InvalidOperation, ValueError):
        raise JtlFehler("JTL liefert keinen gültigen Rechnungsbetrag.") from None


def identitaet(value):
    if type(value) is not int or value <= 0:
        raise JtlFehler("Ungültige JTL-Rechnungs- oder Auftrags-ID.")
    return str(value)


def rechnungsdatum(row):
    try:
        return datetime.fromisoformat(row["InvoiceDate"].replace("Z", "+00:00")).date().isoformat()
    except (KeyError, ValueError, TypeError, AttributeError):
        raise JtlFehler("Ungültiges JTL-Rechnungsdatum.") from None


def rechnung(row):
    ident = identitaet(row.get("Id"))
    datum = rechnungsdatum(row)
    details = row.get("InvoicePaymentDetails")
    if not isinstance(details, dict):
        raise JtlFehler("JTL-Zahlungsdetails fehlen.")
    for key in ("IsCancelled", "DunningBlock"):
        if type(row.get(key)) is not bool:
            raise JtlFehler("JTL-Rechnungsstatus fehlt oder ist ungültig.")
    payment = details.get("PaymentStatus")
    if type(payment) is not int or payment not in (0, 1, 2):
        raise JtlFehler("Unbekannter JTL-Zahlungsstatus.")
    offen = betrag(details.get("StillToPay"))
    if not row["IsCancelled"] and payment == 2 and offen > 0:
        raise JtlFehler("JTL meldet eine bezahlte Rechnung mit positivem Restbetrag.")
    waehrung, nummer = details.get("CurrencyIso"), row.get("Number")
    if not isinstance(waehrung, str) or len(waehrung) != 3 or not waehrung.isalpha() or not isinstance(nummer, str) or not nummer:
        raise JtlFehler("JTL-Rechnungsnummer oder Währung fehlt/ist ungültig.")
    adresse = row.get("BillingAddress") or {}
    person = " ".join(str(adresse.get(k) or "").strip() for k in ("FirstName", "LastName")).strip()
    name = " · ".join(x for x in (str(adresse.get("Company") or "").strip(), person) if x)
    if not name:
        raise JtlFehler("JTL liefert keinen Namen in der Rechnungsadresse.")
    return {"id": ident, "nummer": nummer, "datum": datum, "kunde": name,
            "betrag": str(betrag(details.get("TotalGrossAmount"))), "offen": str(offen),
            "waehrung": waehrung.upper(), "mahnsperre": row["DunningBlock"],
            "status": "storniert" if row["IsCancelled"] else "bezahlt" if offen <= 0 else "offen"}


async def api_lesen(client, path, **kwargs):
    try:
        return await client._request("GET", path, **kwargs)
    except JtlFehler as exc:
        raise JtlFehler(f"{path}: {exc}") from None


def fenster(zeit):
    heute = zeit.astimezone(ZoneInfo("Europe/Berlin")).date()
    start = heute.replace(year=heute.year - 1,
                         day=min(heute.day, monthrange(heute.year - 1, heute.month)[1]))
    return start.isoformat(), heute.isoformat()


async def offene_rechnungen(client):
    result = {}
    for payment in (0, 1):
        gesehen, total = set(), None
        for page in range(1, 10001):
            data = await api_lesen(client, "/v1/invoices", params={
                "pageNumber": page, "pageSize": 100, "paymentStatus": payment})
            rows, count = data.get("Items"), data.get("TotalItems")
            if (not isinstance(rows, list) or data.get("PageNumber") != page
                    or type(count) is not int or count < 0 or data.get("PageSize") != 100
                    or type(data.get("HasNextPage")) is not bool):
                raise JtlFehler("Ungültige JTL-Rechnungsseite.")
            if total is not None and total != count:
                raise JtlFehler("Rechnungsbestand während Abruf verändert; vorheriger Stand bleibt erhalten.")
            total = count
            for row in rows:
                if not isinstance(row, dict):
                    raise JtlFehler("Ungültiger JTL-Rechnungseintrag.")
                ident = identitaet(row.get("Id"))
                if ident in result:
                    raise JtlFehler("Doppelte Rechnung oder Zahlungsstatus während Abruf verändert.")
                if (row.get("InvoicePaymentDetails") or {}).get("PaymentStatus") != payment:
                    raise JtlFehler("JTL-Zahlungsfilter stimmt nicht mit der Rechnung überein.")
                gesehen.add(ident)
                result[ident] = row
            if len(gesehen) == total and not data["HasNextPage"]:
                break
            if not rows or len(gesehen) >= total or not data["HasNextPage"]:
                raise JtlFehler("Unvollständige JTL-Rechnungsliste.")
        else:
            raise JtlFehler("JTL-Rechnungsabruf überschreitet das Seitenlimit.")
    return result


async def shop_zuordnung(client, ident, cache):
    rows = await api_lesen(client, f"/v1/invoices/{ident}/lineitems", expected_type=list)
    auftraege = set()
    for row in rows:
        if not isinstance(row, dict) or identitaet(row.get("InvoiceId")) != ident:
            raise JtlFehler("Rechnungsposition gehört nicht zur angefragten Rechnung.")
        order = row.get("SalesOrderId")
        if type(order) is not int or order < 0:
            raise JtlFehler("Ungültige Auftragsverknüpfung.")
        if order:
            auftraege.add(str(order))
    if not auftraege:
        raise JtlFehler("Rechnung ohne belegbare Auftragszuordnung; Shopfilter nicht möglich.")
    kanaele = set()
    for order in sorted(auftraege):
        if order not in cache:
            data = await api_lesen(client, f"/v1/salesOrders/{order}")
            if identitaet(data.get("Id")) != order or not isinstance(data.get("SalesChannelId"), str) or not data["SalesChannelId"]:
                raise JtlFehler("JTL-Auftrags-ID oder Verkaufskanal fehlt/ist widersprüchlich.")
            cache[order] = data["SalesChannelId"]
        kanaele.add(cache[order])
    if KANAL in kanaele and len(kanaele) != 1:
        raise JtlFehler("Rechnung enthält Aufträge aus mehreren Verkaufskanälen; manuelle Prüfung erforderlich.")
    return kanaele == {KANAL}


async def abrufen(client, bestand=None, zeit=None):
    zeit = zeit or jetzt()
    start, ende = fenster(zeit)
    alt = (bestand or {}).get("faelle", {})
    if not isinstance(alt, dict):
        raise JtlFehler("Inkasso-Vorgangsbestand ist ungültig.")
    if not alt and (bestand or {}).get("rechnungen"):
        raise JtlFehler("Alter Inkasso-Snapshot ohne Vorgangsbestand; Migration manuell prüfen.")
    kanaele = await api_lesen(client, "/v2/sales-channels", expected_type=list)
    if any(not isinstance(k, dict) for k in kanaele):
        raise JtlFehler("Ungültige JTL-Verkaufskanalliste.")
    treffer = [k for k in kanaele if k.get("id") == KANAL]
    if len(treffer) != 1 or type(treffer[0].get("type")) is not int or treffer[0]["type"] != 1:
        raise JtlFehler("Der bestätigte JTL-Shopkanal wurde nicht eindeutig als Onlineshop erkannt.")
    rows = await offene_rechnungen(client)
    geprueft = len(rows)
    # Previously captured cases are checked individually even outside the window,
    # including closed cases so that reopened balances are not lost.
    for ident, fall in alt.items():
        if not isinstance(fall, dict) or fall.get("id") != ident or not ident.isdecimal() or int(ident) <= 0:
            raise JtlFehler("Ungültige ID im Inkasso-Vorgangsbestand.")
        if ident not in rows:
            row = await api_lesen(client, f"/v1/invoices/{ident}")
            if identitaet(row.get("Id")) != ident:
                raise JtlFehler("Rechnungsdetails bestätigen die angefragte ID nicht.")
            rows[ident] = row
            geprueft += 1
    faelle, cache = {}, {}
    for ident, row in rows.items():
        vorher = alt.get(ident)
        if vorher is None and not start <= rechnungsdatum(row) <= ende:
            continue
        item = rechnung(row)
        if vorher is None and (item["status"] != "offen" or not start <= item["datum"] <= ende):
            continue
        if item["status"] == "offen":
            passt = await shop_zuordnung(client, ident, cache)
            if not passt:
                if vorher is not None:
                    raise JtlFehler("Verkaufskanal einer erfassten Rechnung hat sich geändert.")
                continue
        item.update(erfasst_am=vorher["erfasst_am"] if vorher else zeit.isoformat(),
                    geprueft_am=zeit.isoformat())
        if item["status"] != "offen":
            item["abgeschlossen_am"] = (vorher or {}).get("abgeschlossen_am") or zeit.isoformat()
        faelle[ident] = item
    return {"version": 2, "faelle": faelle,
            "rechnungen": sorted((f for f in faelle.values() if f["status"] == "offen"),
                                 key=lambda x: (x["datum"], x["id"])),
            "geprueft": geprueft, "aufnahme_ab": start,
            "shop": treffer[0].get("name") or KANAL, "kanal": KANAL}


def status(data, zeit=None):
    data = dict(data)
    zeit = zeit or jetzt()
    data["veraltet"] = True
    if data.get("letzter_erfolg"):
        alter = zeit - datetime.fromisoformat(data["letzter_erfolg"])
        data["veraltet"] = not timedelta(0) <= alter < INTERVALL + timedelta(hours=1)
    if data.get("status") == "laeuft" and data.get("letzter_versuch"):
        if zeit - datetime.fromisoformat(data["letzter_versuch"]) > timedelta(hours=1, minutes=5):
            data.update(status="fehler", fehler="Der letzte Abruf wurde nicht abgeschlossen. Dienst prüfen.")
    return data


@router.get("")
async def liste(request: Request, response: Response):
    if not ist_admin(request.state.benutzer):
        raise HTTPException(status_code=403, detail="Nur für Administratoren")
    response.headers["Cache-Control"] = "no-store"
    try:
        data = status(lesen())
        data.pop("faelle", None)
        return data
    except (OSError, ValueError, TypeError):
        raise HTTPException(status_code=503, detail="Inkasso-Datenstand nicht lesbar; Prüfung erforderlich.") from None
