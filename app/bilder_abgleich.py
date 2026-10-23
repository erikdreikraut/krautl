"""Ausschließlich lesender JTL-Shop-Bildabgleich. Keine Wawi-Schreiboperationen."""
import asyncio
import base64
import binascii
from io import BytesIO
from uuid import UUID

import httpx
from PIL import Image, ImageOps, UnidentifiedImageError

from .jtl_client import JtlFehler
from .jtl_onprem import OnPremClient
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


async def bild_laden(client, bild_id):
    # Never fetch arbitrary URLs from Wawi responses or expose API keys to browsers.
    try:
        async with client.http.stream("GET", client.url + "/v2/items/image-data/" + ident(bild_id)) as response:
            if response.status_code != 200:
                raise JtlFehler(f"Wawi-Bildabruf: HTTP {response.status_code}. Bildleserechte des bestehenden FAQ-Zugangs prüfen.")
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
    except httpx.HTTPError:
        raise JtlFehler("Wawi-Bildabruf fehlgeschlagen (TLS/Netz/Zeitlimit).") from None


def shop_bilder(detail):
    kanalblock = detail.get("salesChannels")
    if not isinstance(kanalblock, dict) or not isinstance(kanalblock.get("salesChannels"), list):
        raise JtlFehler("Diese Wawi-API liefert keine eindeutige Shop-Aktivierung (salesChannels). API-Version prüfen; der bisherige Stand bleibt erhalten.")
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
        bilder = shop_bilder(detail)
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
                daten = await bild_laden(client, bid)
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
