"""Einmaliger Cloud-v1-Positionstausch für Artikel 1036, ohne Dateiupload."""
import argparse
import asyncio
import copy
import json
from datetime import datetime, timezone
from pathlib import Path

import httpx
from app.jtl_client import ERP_URL, JtlClient
from scripts.teste_bilder_cloud import TENANT, SHOP, POS, canonical, locked, save_once

ARTICLE = "770f139d-18dd-405c-9f84-322128000000"
FOLDER = "/app/var/bilder/cloud-v1-test-1036"

async def get(client, path):
    token = await client._token()
    response = await client.http.get(ERP_URL + path, headers={
        "Authorization": "Bearer " + token, "X-Tenant-ID": TENANT})
    if response.status_code != 200:
        raise ValueError(f"Cloud-Lesen HTTP {response.status_code}")
    return response.json()

async def read(client):
    item = await get(client, "/v1/items/" + ARTICLE)
    if item.get("Id") != 40 or item.get("SKU") != "1036":
        raise ValueError("Artikelidentität nicht bestätigt.")
    rows = await get(client, "/v1/items/" + ARTICLE + "/images")
    if not isinstance(rows, list) or not rows:
        raise ValueError("Bildliste fehlt.")
    for row in rows:
        if (not isinstance(row, dict) or row.get("ItemId") != 40
                or type(row.get("ImageId")) is not int or row["ImageId"] <= 0
                or type(row.get("SortNumber")) is not int
                or not isinstance(row.get("SalesChannelId"), str)):
            raise ValueError("Ungültige Bildzuordnung.")
    return [r for r in rows if r["SalesChannelId"] != POS]


def target(rows):
    result = copy.deepcopy(rows)
    shop = sorted((r for r in result if r["SalesChannelId"] == SHOP), key=lambda r:r["SortNumber"])
    if len(shop) != 2 or [r["SortNumber"] for r in shop] != [1, 2] or len({r["ImageId"] for r in shop}) != 2:
        raise ValueError("Genau zwei eindeutige Shopbilder an Position 1/2 erforderlich.")
    shop[0]["SortNumber"], shop[1]["SortNumber"] = 2, 1
    return result


def state(rows, plan):
    if canonical(rows) == canonical(plan["before"]): return "ORIGINAL"
    if canonical(rows) == canonical(plan["after"]): return "ZIEL"
    return "ABWEICHUNG"

async def run(client, folder, mode):
    if client.tenant_id != TENANT: raise ValueError("Falscher Mandant.")
    folder = Path(folder)
    with locked(folder):
        path = folder / "plan.json"
        if not path.exists():
            if mode != "vorbereiten": raise ValueError("Vorbereitung fehlt.")
            rows = await read(client)
            save_once(path, {"tenant": TENANT, "article": ARTICLE, "url": ERP_URL,
                "created": datetime.now(timezone.utc).isoformat(), "before": rows, "after": target(rows),
                "altauftrag": "8b42f33a-d8aa-4933-9b61-15f58e2d9014",
                "hinweis": "Altauftrag bleibt unklar/unverändert. Neuer isolierter Test auf aktuellem Bestand; keine Wiederholung des Austauschs."})
        plan = json.loads(path.read_text())
        if (plan.get("tenant") != TENANT or plan.get("article") != ARTICLE or plan.get("url") != ERP_URL
                or canonical(target(plan["before"])) != canonical(plan["after"])):
            raise ValueError("Plan passt nicht zum begrenzten Test.")
        if mode in ("vorbereiten", "pruefen"):
            return {"zustand": state(await read(client), plan), "schreibzugriff": False,
                "testversuch": (folder / "ausfuehren.intent.json").exists()}
        if mode not in ("ausfuehren", "zuruecksetzen"): raise ValueError("Ungültiger Modus.")
        intent = folder / (mode + ".intent.json")
        if intent.exists() or (mode == "ausfuehren" and (folder / "zuruecksetzen.intent.json").exists()):
            raise ValueError("Bereits versucht; nur rücklesen.")
        if mode == "zuruecksetzen" and not (folder / "ausfuehren.intent.json").exists():
            raise ValueError("Kein eigener Testversuch.")
        age = (datetime.now(timezone.utc)-datetime.fromisoformat(plan["created"])).total_seconds()
        if mode == "ausfuehren" and not 0 <= age <= 7200: raise ValueError("Plan veraltet.")
        token = await client._token()
        expected = "ORIGINAL" if mode == "ausfuehren" else "ZIEL"
        if state(await read(client), plan) != expected: raise ValueError("Bestand verändert; kein Schreiben.")
        desired = plan["after"] if mode == "ausfuehren" else plan["before"]
        image = next(r["ImageId"] for r in desired if r["SalesChannelId"] == SHOP and r["SortNumber"] == 1)
        body = {"SalesChannelId": SHOP, "SortNumber": 1}
        save_once(intent, {"at": datetime.now(timezone.utc).isoformat(), "image": image, "request": body})
        result = {"modus": mode, "http_status": None, "zustand": "UNKLAR"}
        try:
            response = await client.http.patch(ERP_URL + "/v1/items/" + ARTICLE + "/images/" + str(image),
                headers={"Authorization": "Bearer " + token, "X-Tenant-ID": TENANT}, json=body)
            result["http_status"] = response.status_code
        except httpx.HTTPError:
            result["transportfehler"] = True
        try:
            result["zustand"] = state(await read(client), plan)
        except (ValueError, httpx.HTTPError):
            result["ruecklesen_fehlgeschlagen"] = True
        result["bestaetigt"] = result["zustand"] == ("ZIEL" if mode == "ausfuehren" else "ORIGINAL")
        save_once(folder / (mode + ".result.json"), result)
        return result

async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    for mode in ("vorbereiten", "ausfuehren", "pruefen", "zuruecksetzen"):
        modes.add_argument("--"+mode, action="store_const", const=mode, dest="mode")
    args = parser.parse_args()
    async with JtlClient.aus_umgebung() as client:
        print(json.dumps(await run(client, FOLDER, args.mode), ensure_ascii=False))

if __name__ == "__main__":
    asyncio.run(main())
