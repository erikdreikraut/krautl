"""One journaled v1 position change for an already requested two-image swap."""
import argparse
import asyncio
import httpx
from app import bilder_speicher as store
from app.bilder_upload import (SHOP, auftraege, sichern, lokal, detail_lesen,
    bildblock, fingerprint, shop, pruefen, ablehnungsdetails)
from app.jtl_onprem import OnPremClient


def schritt(before, target, rows):
    old = sorted(shop(before), key=lambda b: b["sortNumber"])
    new = sorted(shop(target), key=lambda b: b["sortNumber"])
    if len(old) != len(new) or len(old) < 3:
        raise ValueError("Nur eine Vertauschung zweier vorhandener Nebenbilder ist freigegeben.")
    ids = [b["blobIdentifier"] for b in old]
    newids = [b["blobIdentifier"] for b in new]
    if len(set(ids)) != len(ids) or set(ids) != set(newids):
        raise ValueError("Bildmenge ist nicht eindeutig.")
    if [b["sortNumber"] for b in old] != list(range(1,len(old)+1)):
        raise ValueError("Ausgangspositionen sind nicht fortlaufend.")
    changed = [i for i in range(len(old)) if ids[i] != newids[i]]
    if len(changed) != 2 or changed[0] == 0 or changed[1] != changed[0]+1:
        raise ValueError("Nur zwei benachbarte Nebenbilder dürfen vertauscht werden.")
    for i,b in enumerate(new):
        if b["sortNumber"] != i+1 or b["isMainImage"] != (i==0):
            raise ValueError("Zielpositionen/Hauptbild sind uneindeutig.")
    if any(b["isMainImage"] != (i==0) for i,b in enumerate(old)):
        raise ValueError("Vorhandenes Hauptbild ist uneindeutig.")
    # Prove target differs only in the requested shop ordering.
    import copy
    expected = copy.deepcopy(before)
    shop(expected)[:] = new
    if fingerprint(expected) != fingerprint(target):
        raise ValueError("Auftrag verändert weitere Zuordnungen.")
    positions = {}
    item_ids = set()
    for row in rows:
        if row.get("SalesChannelId") != SHOP:
            continue
        ident, pos, item = row.get("ImageId"), row.get("SortNumber"), row.get("ItemId")
        if any(type(v) is not int or v <= 0 for v in (ident,pos,item)):
            raise ValueError("Ungültige v1-Bildkennung oder Position.")
        item_ids.add(item)
        if pos in positions and positions[pos] != ident:
            raise ValueError("Mehrere v1-Bilder an derselben Shop-Position.")
        positions[pos] = ident
    if len(item_ids) != 1 or set(positions) != set(range(1,len(old)+1)) or len(set(positions.values())) != len(old):
        raise ValueError("v1- und v2-Bildlisten lassen sich nicht eindeutig zuordnen.")
    # Move the later image to the earlier position. Never upload bytes or delete images.
    start, end = changed[1]+1, changed[0]+1
    return {"image_id": positions[start], "von": start, "nach": end}


async def ausfuehren(c, job, ausgabe=print):
    if job.get("api_ziel") != c.url or job.get("art") != "reihenfolge":
        raise ValueError("Auftrag oder Wawi-Ziel passt nicht.")
    if job.get("v1_sortierversuch") or job.get("status") == "wawi":
        ausgabe("Dieser Auftrag wird ausschließlich rückgelesen; kein weiterer Schreibversuch.")
        result = await pruefen(c,job)
        ausgabe(result["meldung"])
        return result
    if job.get("status") != "unklar":
        raise ValueError("Nur ein ungeklärter bestehender Reihenfolgeauftrag ist erlaubt.")
    lokal(job["artikel"],job["revision"])
    current = bildblock(await detail_lesen(c,job["artikel"],job["sku"]))
    if fingerprint(current) == fingerprint(job["ziel"]):
        return await pruefen(c,job)
    if fingerprint(current) != fingerprint(job["vorher"]):
        raise ValueError("Wawi entspricht weder Ausgang noch Ziel. Kein Schreibversuch.")
    rows = await c._request("GET", "/v1/items/"+job["artikel"]+"/images", expected_type=list)
    step = schritt(current,job["ziel"],rows)
    again = bildblock(await detail_lesen(c,job["artikel"],job["sku"]))
    if fingerprint(current) != fingerprint(again) or not store.freigegeben(job["artikel"],job["revision"]):
        raise ValueError("Artikel wurde während der Vorbereitung geändert.")
    job["v1_sortierversuch"] = {**step,"zeit":store.jetzt()}
    job.update(status="unklar",meldung="Einmaliger v1-Sortierschritt vorbereitet; Ausgang wird rückgelesen.")
    sichern(job)  # Durable before any mutation; reruns only read.
    ausgabe(f"Artikel {job['sku']}: Shop-Bildposition {step['von']} nach {step['nach']}.")
    try:
        response = await c.http.patch(c.url+"/v1/items/"+job["artikel"]+"/images/"+str(step["image_id"]),
                                     json={"SalesChannelId":SHOP,"SortNumber":step["nach"]})
        job["v1_sortierversuch"]["http_status"] = response.status_code
        if response.status_code != 201:
            job["v1_sortierversuch"]["diagnose"] = ablehnungsdetails(response)
            ausgabe(ablehnungsdetails(response))
        sichern(job)
        ausgabe(f"v1-Antwort: HTTP {response.status_code}; jetzt Rückprüfung.")
    except httpx.HTTPError:
        ausgabe("Verbindungsfehler; kein Neuversuch. Jetzt ausschließlich rücklesen.")
    result = await pruefen(c,job)
    ausgabe(result["meldung"])
    return result


async def main(sku):
    with store.Laufsperre():
        jobs = sorted((j for j in auftraege() if j.get("sku")==sku and j.get("art")=="reihenfolge"),
                      key=lambda j:j.get("erstellt", ""))
        if not jobs:
            raise ValueError("Kein vorhandener Reihenfolgeauftrag für diesen Artikel.")
        async with OnPremClient.aus_umgebung() as client:
            await ausfuehren(client,jobs[-1])


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sku")
    args=parser.parse_args()
    try:
        asyncio.run(main(args.sku))
    except Exception as exc:
        print("Abbruch:", str(exc) if isinstance(exc,ValueError) else type(exc).__name__)
        raise SystemExit(1)
