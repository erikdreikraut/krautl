"""Gezielter Lesetest des vorhandenen FAQ-Zugangs, ohne Datenänderungen."""
import asyncio
from app.jtl_onprem import OnPremClient
from app.jtl_client import JtlFehler
from app.bilder_abgleich import bild_laden, shop_bilder, ident, einzelshop_pruefen
from app import bilder_speicher as speicher


async def main():
    async with OnPremClient.aus_umgebung() as client:
        einzelshop = False
        for page in range(1, 11):
            data = await client._request("GET", "/v2/items", params={"pageNumber": page, "pageSize": 100})
            for row in data.get("items", []):
                key = ident(row.get("id"))
                # Ignore hidden items even during diagnostics.
                if not row.get("isShopActive") or not row.get("isActive") or not speicher.freigegeben(key, next((a["revision"] for a in speicher.lesen()["artikel"] if a["id"] == key), 0)):
                    continue
                detail = await client._request("GET", "/v2/items/" + key)
                if detail.get("salesChannels") is None and not einzelshop:
                    einzelshop = await einzelshop_pruefen(client.url)
                bilder = shop_bilder(detail, row, einzelshop)
                if bilder is None:
                    continue
                print("Shop-Artikel gelesen:", row.get("sKU"), "| zugeordnete Shop-Bilder:", len(bilder))
                if bilder:
                    thumb = await bild_laden(client, bilder[0]["blobIdentifier"], bilder[0])
                    print("Bildlesezugriff erfolgreich. Vorschaubild:", len(thumb), "Bytes; nichts gespeichert.")
                    return
            if data.get("hasNextPage") is False:
                break
        raise JtlFehler("Kein aktiver, sichtbarer Shop-Artikel mit Bildern in den geprüften Seiten gefunden.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except JtlFehler as exc:
        print("Bildprüfung:", exc)
        raise SystemExit(1)
