"""Ausschließlich lesender JTL-Shop-Bildabgleich. Keine Wawi-Schreiboperationen."""
import asyncio
import base64
import binascii
from io import BytesIO
from uuid import UUID
from urllib.parse import urlsplit, urlunsplit, unquote, parse_qsl

import httpx
from PIL import Image, ImageOps, UnidentifiedImageError

from .jtl_client import JtlFehler
from .jtl_onprem import OnPremClient
from .inkasso_zugang import client_aus_umgebung as kanal_client
from . import bilder_speicher as speicher

SHOP = "2-2-1"
MAX_BYTES = 20 * 1024 * 1024


def ident(wert):
    try:
        return str(UUID(wert))
    except (ValueError, TypeError, AttributeError):
        raise JtlFehler("Ungültige Artikel- oder Bild-ID in der Wawi-Antwort.") from None


def vorschaubild(daten):
    try:
        with Image.open(BytesIO(daten)) as bild:
            if bild.width * bild.height > 40_000_000:
                raise JtlFehler("Ein Bild überschreitet 40 Megapixel.")
            bild = ImageOps.exif_transpose(bild)
            bild.thumbnail((240, 180))
            rgba = bild.convert("RGBA")
            hintergrund = Image.new("RGB", rgba.size, "white")
            hintergrund.paste(rgba, mask=rgba.getchannel("A"))
            out = BytesIO()
            hintergrund.save(out, "JPEG", quality=82)
            return out.getvalue()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise JtlFehler("Eine Wawi-Bilddatei konnte nicht als Vorschaubild gelesen werden.") from None


def datei_url(client, bild_id, bild):
    """Allow only this image on the configured Wawi origin; never log URL tokens."""
    raw = (bild or {}).get("url") or (bild or {}).get("previewUrl")
    if not isinstance(raw, str) or not raw:
        raise JtlFehler("Wawi-Bildabruf: HTTP 404. Bild-Endpunkt fehlt oder Bild nicht gefunden; keine Download-Adresse geliefert.")
    try:
        u, base = urlsplit(raw), urlsplit(client.url)
        if (u.scheme != "https" or u.hostname != base.hostname
                or (u.port or 443) != (base.port or 443)
                or u.username or u.password or u.fragment
                or any(ord(c) < 32 for c in raw)):
            raise ValueError()
        prefix = base.path + "/v2/file/"
        path = unquote(u.path)
        normal = prefix + ident(bild_id)
        broken = prefix + "{blobId}?version=2/" + ident(bild_id)
        query = u.query
        if path == broken:
            versions = [v for k, v in parse_qsl(query) if k.lower() == "version"]
            if versions and versions != ["2"]:
                raise ValueError()
            if not versions:
                query += ("&" if query else "") + "version=2"
        elif path != normal:
            raise ValueError()
        return urlunsplit((base.scheme, base.netloc, normal, query, ""))
    except (ValueError, TypeError):
        raise JtlFehler("Unsichere oder unpassende Wawi-Bildadresse; Abruf abgebrochen.") from None


async def bild_laden(client, bild_id, bild=None):
    try:
        url = client.url + "/v2/items/image-data/" + ident(bild_id)
        # Only a missing modern endpoint permits the legacy file URL.
        async with client.http.stream("GET", url) as response:
            if response.status_code == 404 and bild is not None:
                legacy = datei_url(client, bild_id, bild)
            else:
                return await bildantwort(response)
        async with client.http.stream("GET", legacy, follow_redirects=False) as response:
            return await bildantwort(response)
    except httpx.HTTPError:
        raise JtlFehler("Wawi-Bildabruf fehlgeschlagen (TLS/Netz/Zeitlimit).") from None


async def bildantwort(response):
    if response.status_code != 200:
        hinweis = ("Bildleserechte des bestehenden FAQ-Zugangs prüfen."
                   if response.status_code in (401, 403) else
                   "Datei-Endpunkt oder Bild nicht gefunden." if response.status_code == 404 else
                   "Unerwartete Antwort des Bild-Endpunkts.")
        raise JtlFehler(f"Wawi-Bildabruf: HTTP {response.status_code}. {hinweis}")
    inhalt = bytearray()
    async for chunk in response.aiter_bytes():
        inhalt.extend(chunk)
        if len(inhalt) > MAX_BYTES * 4 // 3 + 100:
            raise JtlFehler("Eine Bilddatei überschreitet das Abruflimit von 20 MB.")
    if "json" in response.headers.get("content-type", "").lower():
        import json
        try:
            wert = json.loads(inhalt)
            if not isinstance(wert, str):
                raise ValueError()
            daten = base64.b64decode(wert, validate=True)
        except (ValueError, binascii.Error):
            raise JtlFehler("Wawi-Bildantwort enthält keine gültigen Bilddaten.") from None
    else:
        daten = bytes(inhalt)
    if len(daten) > MAX_BYTES:
        raise JtlFehler("Eine Bilddatei überschreitet 20 MB.")
    return await asyncio.to_thread(vorschaubild, daten)


def einzelshop_bestaetigen(kanaele):
    """Older Wawi exposes shop activity only globally in the item catalogue."""
    if not isinstance(kanaele, list) or not kanaele:
        raise JtlFehler("Shop-Aktivierung: Verkaufskanalliste fehlt.")
    gesehen, shops = set(), set()
    for kanal in kanaele:
        if not isinstance(kanal, dict):
            raise JtlFehler("Shop-Aktivierung: ungültiger Verkaufskanal.")
        key, typ = kanal.get("id"), kanal.get("type")
        caps = kanal.get("itemCapabilities")
        if (not isinstance(key, str) or not key or key in gesehen
                or type(typ) is not int or typ not in range(11)
                or not isinstance(caps, dict)
                or type(caps.get("onlineShopActivation")) is not bool):
            raise JtlFehler("Shop-Aktivierung: uneindeutige Verkaufskanalliste.")
        gesehen.add(key)
        # Installed Wawi reports the JTL shop as type 0; POS (2) is separate.
        if typ == 1 or (caps["onlineShopActivation"] and typ != 2):
            shops.add(key)
    if shops != {SHOP}:
        raise JtlFehler("Shop-Aktivierung: dreikraut ist nicht eindeutig der einzige Shop. Bisheriger Stand bleibt erhalten.")
    return True


async def einzelshop_pruefen(api_url):
    async with kanal_client() as client:
        if client.url != api_url:
            raise JtlFehler("Shop-Aktivierung: Verkaufskanäle gehören zu einem anderen API-Ziel.")
        kanaele = await client._request("GET", "/v2/sales-channels", expected_type=list)
    return einzelshop_bestaetigen(kanaele)


def shop_bilder(detail, katalogzeile=None, einzelshop=False):
    kanalblock = detail.get("salesChannels")
    if kanalblock is None:
        if einzelshop is not True:
            raise JtlFehler("Shop-Aktivierung: Einzelshop wurde nicht bestätigt.")
        row = katalogzeile or {}
        if type(row.get("isActive")) is not bool or type(row.get("isShopActive")) is not bool:
            raise JtlFehler("Shop-Aktivierung: eindeutiger Katalogstatus fehlt.")
        if not row["isActive"] or not row["isShopActive"]:
            return None
    else:
        if not isinstance(kanalblock, dict) or not isinstance(kanalblock.get("salesChannels"), list):
            raise JtlFehler("Shop-Aktivierung: ungültige Artikel-Shop-Zuordnung.")
        if any(not isinstance(k, dict) for k in kanalblock["salesChannels"]):
            raise JtlFehler("Shop-Aktivierung: ungültiger Artikelkanal.")
        kanaele = [k for k in kanalblock["salesChannels"] if k.get("salesChannelId") == SHOP]
        if len(kanaele) > 1 or (kanaele and not isinstance(kanaele[0].get("isActive"), bool)):
            raise JtlFehler("Uneindeutige Shop-Zuordnung im Wawi-Artikel.")
        if not kanaele or not kanaele[0]["isActive"]:
            return None
    block = detail.get("images") or {}
    gruppen = block.get("saleschannelImages") or []
    if not isinstance(gruppen, list):
        raise JtlFehler("Ungültige Shop-Bildzuordnung.")
    zuordnung = [g for g in gruppen if g.get("saleschannelId") == SHOP]
    if len(zuordnung) > 1:
        raise JtlFehler("Doppelte Shop-Bildzuordnung.")
    bilder = (zuordnung[0].get("images") or []) if zuordnung else []
    if not isinstance(bilder, list):
        raise JtlFehler("Ungültige Shop-Bildliste.")
    ids = set()
    for bild in bilder:
        bild_id = ident(bild.get("blobIdentifier"))
        if bild_id in ids or not isinstance(bild.get("sortNumber"), int):
            raise JtlFehler("Uneindeutige Bild-ID oder Bildreihenfolge.")
        ids.add(bild_id)
    return sorted(bilder, key=lambda b: (b["sortNumber"], b["blobIdentifier"]))


async def katalog(client):
    ergebnis, gesehen = [], set()
    total = None
    for page in range(1, 10001):
        data = await client._request("GET", "/v2/items", params={"pageNumber": page, "pageSize": 100})
        items = data.get("items")
        if not isinstance(items, list) or data.get("pageNumber") != page or not isinstance(data.get("totalItems"), int):
            raise JtlFehler("Ungültige Wawi-Katalogseite.")
        if total is not None and total != data["totalItems"]:
            raise JtlFehler("Der Artikelkatalog hat sich während des Abrufs geändert. Bitte erneut aktualisieren.")
        total = data["totalItems"]
        for row in items:
            key = ident(row.get("id"))
            if key in gesehen:
                raise JtlFehler("Doppelte Artikel-ID im Wawi-Katalog.")
            gesehen.add(key)
            ergebnis.append(row)
        speicher.status_setzen(fortschritt=f"Artikelkatalog: {len(ergebnis)} von {total}")
        if data.get("hasNextPage") is False:
            if len(ergebnis) != total:
                raise JtlFehler("Unvollständiger Wawi-Katalog; bisheriger Stand bleibt erhalten.")
            return ergebnis
        if not items or data.get("hasNextPage") is not True:
            raise JtlFehler("Unvollständige Wawi-Paginierung.")
    raise JtlFehler("Der Wawi-Katalog überschreitet das Seitenlimit.")


async def abgleichen(client):
    stand = speicher.lesen()
    if stand.get("api_ziel") and stand["api_ziel"] != client.url:
        raise JtlFehler("Das Wawi-API-Ziel wurde geändert. Den Bilderbestand vor einem Wechsel prüfen.")
    vorher = {r["id"]: r for r in stand["artikel"]}
    rows = await katalog(client)
    neuer_stand = {}
    einzelshop = False
    for nr, row in enumerate(rows, 1):
        key = ident(row.get("id"))
        alt = vorher.get(key, {})
        rev = alt.get("revision", 0)
        if not speicher.freigegeben(key, rev):
            continue
        if not isinstance(row.get("isActive"), bool) or not isinstance(row.get("isShopActive"), bool):
            raise JtlFehler("Der Wawi-Katalog enthält keinen eindeutigen Artikel-/Shop-Status.")
        if not row["isActive"] or not row["isShopActive"]:
            continue
        sku = row.get("sKU", row.get("sku"))
        name = row.get("name")
        if not isinstance(sku, str) or not sku.strip() or not isinstance(name, str) or not name.strip():
            raise JtlFehler("Artikelname oder Artikelnummer fehlt in der Wawi-Antwort.")
        speicher.status_setzen(fortschritt=f"Artikel {nr} von {len(rows)}: {sku}")
        detail = await client._request("GET", "/v2/items/" + key)
        if detail.get("id") != key or detail.get("identifiers", {}).get("sku") != sku:
            raise JtlFehler("Artikel-ID oder Artikelnummer passt nicht zum Katalog.")
        if not speicher.freigegeben(key, rev):
            continue
        if detail.get("salesChannels") is None and not einzelshop:
            einzelshop = await einzelshop_pruefen(client.url)
        bilder = shop_bilder(detail, row, einzelshop)
        if bilder is None:
            continue
        result = []
        for bild in bilder:
            if not speicher.freigegeben(key, rev):
                break
            bid = ident(bild["blobIdentifier"])
            version = bild.get("modificationDate")
            cache = next((b for b in alt.get("bilder", []) if b["id"] == bid and version and b.get("version") == version), None)
            thumb = cache["thumb"] if cache and speicher.thumb_lesen(key, cache["thumb"]) else None
            if not thumb:
                try:
                    daten = await bild_laden(client, bid, bild)
                except JtlFehler as exc:
                    raise JtlFehler(f"Artikel {sku}, Bildposition {bild['sortNumber']}: {exc}") from None
                if not speicher.freigegeben(key, rev):
                    break
                thumb = speicher.thumb_speichern(daten)
            result.append({"id": bid, "thumb": thumb, "version": version, "position": bild["sortNumber"],
                           "hauptbild": bool(bild.get("isMainImage")), "dateiname": str(bild.get("filename") or "")[:200]})
        if speicher.freigegeben(key, rev):
            parent = row.get("parentItemId")
            parent = ident(parent) if parent and parent != "00000000-0000-0000-0000-000000000000" else None
            if parent == key:
                raise JtlFehler("Ein Artikel verweist auf sich selbst als Vaterartikel.")
            neuer_stand[key] = {"id": key, "sku": sku, "name": name, "parent_id": parent,
                                "bilder": result, "aktualisiert_am": speicher.jetzt()}
    speicher.uebernehmen(neuer_stand, vorher, client.url)


async def ausfuehren():
    async with OnPremClient.aus_umgebung() as client:
        await abgleichen(client)
