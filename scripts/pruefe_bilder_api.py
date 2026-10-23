"""Gezielter Lesetest des vorhandenen FAQ-Zugangs, ohne Datenänderungen."""
import asyncio
import argparse
import re
from urllib.parse import unquote
from unittest.mock import patch
from app import bilder_abgleich
from app.jtl_onprem import OnPremClient
from app.jtl_client import JtlFehler
from app.bilder_abgleich import bild_laden, shop_bilder, ident, einzelshop_pruefen
from app import bilder_speicher as speicher


def bereinigen(text, request):
    werte = list(request.url.params.values())
    auth = request.headers.get("Authorization", "")
    werte += [auth, auth.removeprefix("Wawi ")]
    for wert in sorted(set(werte), key=len, reverse=True):
        if len(wert) >= 4:
            text = text.replace(wert, "[ausgeblendet]").replace(unquote(wert), "[ausgeblendet]")
    text = re.sub(r'https?://[^\s"<>]+', '[URL]', text)
    text = re.sub(r'[A-Za-z0-9_+/=-]{32,}', '[lange Kennung]', text)
    return text[:1500]


async def diagnose_antwort(response):
    if response.status_code != 200:
        inhalt = bytearray()
        async for chunk in response.aiter_bytes():
            inhalt.extend(chunk[:8192 - len(inhalt)])
            if len(inhalt) >= 8192:
                break
        print("Bild-Endpunkt:", "Datei" if "/v2/file/" in response.request.url.path else "image-data", flush=True)
        print("Serverantwort:", bereinigen(inhalt.decode("utf-8", errors="replace"), response.request), flush=True)
    return await normale_bildantwort(response)


normale_bildantwort = bilder_abgleich.bildantwort


async def main(alle=False):
    async with OnPremClient.aus_umgebung() as client:
        einzelshop = False
        anzahl = 0
        revisionen = {a['id']: a['revision'] for a in speicher.lesen()['artikel']}
        for page in range(1, 10001 if alle else 11):
            data = await client._request("GET", "/v2/items", params={"pageNumber": page, "pageSize": 100})
            for row in data.get("items", []):
                key = ident(row.get("id"))
                # Ignore hidden items even during diagnostics.
                if not row.get("isShopActive") or not row.get("isActive") or not speicher.freigegeben(key, revisionen.get(key, 0)):
                    continue
                detail = await client._request("GET", "/v2/items/" + key)
                if detail.get("salesChannels") is None and not einzelshop:
                    einzelshop = await einzelshop_pruefen(client.url)
                bilder = shop_bilder(detail, row, einzelshop)
                if bilder is None:
                    continue
                sku = row.get("sKU", row.get("sku")) or detail.get("identifiers", {}).get("sku") or key
                print("Shop-Artikel:", sku, "| Shop-Bilder:", len(bilder), flush=True)
                for bild in bilder:
                    if not speicher.freigegeben(key, revisionen.get(key, 0)):
                        break
                    print("Prüfe Bildposition:", bild["sortNumber"], flush=True)
                    thumb = await bild_laden(client, bild["blobIdentifier"], bild)
                    anzahl += 1
                    if not alle:
                        print("Bildlesezugriff erfolgreich. Vorschaubild:", len(thumb), "Bytes; nichts gespeichert.", flush=True)
                        return
            if data.get("hasNextPage") is False:
                if alle:
                    print("Vollständige Bildprüfung erfolgreich:", anzahl, "Bilder; kein Bestand veröffentlicht.", flush=True)
                    return
                break
        raise JtlFehler("Kein aktiver, sichtbarer Shop-Artikel mit Bildern in den geprüften Seiten gefunden.")


async def artikel_pruefen(sku):
    """Read only one matching article's details; no image downloads or snapshot writes."""
    async with OnPremClient.aus_umgebung() as client:
        for page in range(1, 10001):
            data = await client._request("GET", "/v2/items", params={"pageNumber": page, "pageSize": 100})
            for row in data.get("items", []):
                if row.get("sKU", row.get("sku")) != sku:
                    continue
                key = ident(row.get("id"))
                alt = next((a for a in speicher.lesen()["artikel"] if a["id"] == key), {})
                if not speicher.freigegeben(key, alt.get("revision", 0)):
                    raise JtlFehler("Artikel ist ausgeblendet; kein Detailabruf.")
                async with client.http.stream("GET", client.url + "/v2/items/" + key) as response:
                    print("Artikeldetails:", sku, "| HTTP", response.status_code, flush=True)
                    if response.status_code != 200:
                        inhalt = bytearray()
                        async for chunk in response.aiter_bytes():
                            inhalt.extend(chunk[:8192 - len(inhalt)])
                            if len(inhalt) >= 8192:
                                break
                        print("Serverantwort:", bereinigen(inhalt.decode("utf-8", errors="replace"), response.request), flush=True)
                        raise JtlFehler("Detailprüfung fehlgeschlagen; nichts geändert.")
                    print("Detailabruf erfolgreich; keine Bilder geladen und nichts geändert.")
                    return
            if data.get("hasNextPage") is False:
                break
        raise JtlFehler("Artikelnummer nicht im Katalog gefunden.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--artikel", help="Nur Details dieser Artikelnummer prüfen, ohne Bildabrufe.")
    parser.add_argument("--alle", action="store_true", help="Alle sichtbaren Shop-Bilder bis zum ersten Fehler lesen; nichts veröffentlichen.")
    args = parser.parse_args()
    try:
        with patch.object(bilder_abgleich, "bildantwort", diagnose_antwort):
            asyncio.run(artikel_pruefen(args.artikel) if args.artikel else main(args.alle))
    except JtlFehler as exc:
        print("Bildprüfung:", exc)
        raise SystemExit(1)
