"""Read-only JTL invoice snapshot; no payment or message writes."""
import json
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from uuid import UUID

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


def rechnung(row):
    if row.get("salesChannelId") != KANAL:
        return None
    for key in ("isDraft", "isCancelled", "isCompletelyPaid", "isDunningBlocked"):
        if type(row.get(key)) is not bool:
            raise JtlFehler("JTL-Rechnungsstatus fehlt oder hat ein unbekanntes Format.")
    if row["isDraft"] or row["isCancelled"]:
        return None
    offen = betrag(row.get("stillToPay"))
    if offen <= 0:
        return None
    if row["isCompletelyPaid"]:
        raise JtlFehler("JTL meldet eine bezahlte Rechnung mit positivem Restbetrag.")
    try:
        ident = str(UUID(row["salesInvoiceId"]))
        datum = datetime.fromisoformat(row["salesInvoiceDate"].replace("Z", "+00:00")).date().isoformat()
    except (KeyError, ValueError, TypeError, AttributeError):
        raise JtlFehler("JTL-Rechnungs-ID oder Rechnungsdatum fehlt/ist ungültig.") from None
    waehrung = row.get("currencyIso")
    nummer = row.get("salesInvoiceNumber")
    if not isinstance(waehrung, str) or len(waehrung) != 3 or not waehrung.isalpha() or not nummer:
        raise JtlFehler("JTL-Rechnungsnummer oder Währung fehlt/ist ungültig.")
    person = " ".join(str(row.get(k) or "").strip() for k in
                      ("billingAddressFirstName", "billingAddressLastName")).strip()
    firma = str(row.get("billingAddressCompanyName") or "").strip()
    name = " · ".join(x for x in (firma, person) if x)
    if not name:
        raise JtlFehler("JTL liefert keinen Namen in der Rechnungsadresse.")
    return {"id": ident, "nummer": nummer, "datum": datum, "kunde": name,
            "betrag": str(betrag(row.get("totalGrossAmount"))), "offen": str(offen),
            "waehrung": waehrung.upper(), "mahnsperre": row["isDunningBlocked"]}


async def api_lesen(client, path, **kwargs):
    try:
        return await client._request("GET", path, **kwargs)
    except JtlFehler as exc:
        raise JtlFehler(f"{path}: {exc}") from None


async def abrufen(client):
    kanal = await api_lesen(client, f"/v2/sales-channels/{KANAL}")
    if kanal.get("id") != KANAL or kanal.get("type") != 1:
        raise JtlFehler("Der bestätigte JTL-Shopkanal wurde nicht als Onlineshop erkannt.")
    result, gesehen, total = [], set(), None
    for page in range(1, 10001):
        data = await api_lesen(client, "/v2/sales-invoices", params={
            "pageNumber": page, "pageSize": 100, "sortBy": "salesInvoiceId",
            "sortDescending": False})
        rows = data.get("items")
        count = data.get("totalItems")
        if (not isinstance(rows, list) or data.get("pageNumber") != page
                or type(count) is not int or count < 0 or data.get("pageSize") != 100):
            raise JtlFehler("Ungültige JTL-Rechnungsseite; kein neuer Datenstand übernommen.")
        if total is not None and total != count:
            raise JtlFehler("Rechnungsbestand während Abruf verändert; kein neuer Datenstand übernommen.")
        total = count
        for row in rows:
            try:
                ident = str(UUID(row["salesInvoiceId"]))
            except (KeyError, TypeError, ValueError, AttributeError):
                raise JtlFehler("Ungültige JTL-Rechnungs-ID in der Übersicht.") from None
            if ident in gesehen:
                raise JtlFehler("Doppelte JTL-Rechnung beim Seitenabruf.")
            gesehen.add(ident)
            if "salesChannelId" not in row:
                raise JtlFehler("JTL liefert keine Shop-Zuordnung für Rechnungen.")
            item = rechnung(row)
            if item:
                result.append(item)
        if len(gesehen) == total:
            if data.get("hasNextPage") is True:
                raise JtlFehler("Widersprüchliche JTL-Paginierung.")
            return {"rechnungen": sorted(result, key=lambda x: (x["datum"], x["id"])),
                    "geprueft": total, "shop": kanal.get("name") or KANAL, "kanal": KANAL}
        if not rows or len(gesehen) > total or data.get("hasNextPage") is False:
            raise JtlFehler("Unvollständige JTL-Rechnungsliste; vorheriger Datenstand bleibt erhalten.")
    raise JtlFehler("JTL-Rechnungsabruf überschreitet das Seitenlimit.")


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
        return status(lesen())
    except (OSError, ValueError, TypeError):
        raise HTTPException(status_code=503, detail="Inkasso-Datenstand nicht lesbar; Prüfung erforderlich.") from None
