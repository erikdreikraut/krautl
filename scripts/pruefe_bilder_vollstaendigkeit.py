"""Read-only catalogue comparison. Does not download images or change sync status."""
import asyncio
import json
from app import bilder_speicher as store
from app.bilder_abgleich import einzelshop_pruefen, ident
from app.jtl_onprem import OnPremClient
from app.jtl_client import JtlFehler


def vergleich(stand, rows):
    local={a["id"]:a for a in stand["artikel"]}
    active={ident(r["id"]):r for r in rows if r.get("isActive") is True and r.get("isShopActive") is True}
    def kurz(r):
        return {"sku":r.get("sKU",r.get("sku")),"name":r.get("name")}
    return {"aktive_shopartikel_im_katalog":len(active), "lokal_gespeichert":len(local),
        "davon_ausgeblendet":sum(bool(a["ausgeblendet"]) for a in local.values()),
        "fehlende_artikel":[kurz(r) for key,r in active.items() if key not in local],
        "lokal_nicht_mehr_shopaktiv":[kurz(a) for key,a in local.items() if key not in active],
        "ungeprueft":stand.get("ungeprueft",[]),
        "fehlende_vorschauen":sum(not b.get("thumb") for a in local.values() if not a["ausgeblendet"] for b in a["bilder"]),
        "exportvorschauen":sum(bool(b.get("thumb")) and b.get("quelle")=="ameise" for a in local.values() for b in a["bilder"]),
        "hinweis":"Artikelabdeckung geprüft; keine Aussage über aktuelle Bildvollständigkeit oder öffentliche Shop-Veröffentlichung."}


async def main():
    stand=store.lesen()
    print("Gespeicherter Abgleichstatus:",json.dumps({k:stand.get(k) for k in ("status","teilstand","gestartet_am","lauf_beendet_am","letzter_erfolg","fehler","fortschritt")},ensure_ascii=False))
    async with OnPremClient.aus_umgebung() as c:
        if stand.get("api_ziel")!=c.url:
            raise JtlFehler("API-Ziel stimmt nicht mit dem Bestand überein.")
        await einzelshop_pruefen(c.url)
        rows=[];seen=set();total=None
        for page in range(1,10001):
            d=await c._request("GET","/v2/items",params={"pageNumber":page,"pageSize":100})
            items=d.get("items")
            if not isinstance(items,list) or d.get("pageNumber")!=page or type(d.get("totalItems")) is not int or (total is not None and total!=d["totalItems"]):
                raise JtlFehler("Katalog während der Prüfung unvollständig oder verändert.")
            total=d["totalItems"]
            for r in items:
                key=ident(r.get("id"))
                if key in seen or type(r.get("isActive")) is not bool or type(r.get("isShopActive")) is not bool:
                    raise JtlFehler("Katalog nicht eindeutig.")
                seen.add(key);rows.append(r)
            if d.get("hasNextPage") is False and len(rows)==total:
                print(json.dumps(vergleich(stand,rows),ensure_ascii=False,indent=2));return
            if not items or d.get("hasNextPage") is not True:break
        raise JtlFehler("Katalogprüfung nicht vollständig.")


if __name__=="__main__":
    try:asyncio.run(main())
    except JtlFehler as exc:print("Prüfung nicht bestätigt:",str(exc))
