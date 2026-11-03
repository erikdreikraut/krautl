"""Isolated, single-attempt content replacement and restoration for SKU 1036."""
import argparse
import asyncio
import base64
import copy
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import httpx

from app.jtl_client import ERP_URL, JtlClient
from app.jtl_onprem import OnPremClient
from app.jtl_faq_test import antwortdiagnose
from scripts.teste_bilder_cloud import TENANT, SHOP, POS, canonical, locked, save_once

ARTICLE = "770f139d-18dd-405c-9f84-322128000000"
TARGET, SOURCE = 2729, 2731
FOLDER = "/app/var/bilder/cloud-v1-inhalt-1036"
META = {"Filename", "ImageDataType", "Size", "Width", "Height"}


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def base_url(c):
    return c.url if isinstance(c, OnPremClient) else ERP_URL


async def headers_for(c):
    if isinstance(c, OnPremClient):
        return {}  # The client's own authenticated headers remain in effect.
    return {"Authorization": "Bearer " + await c._token(), "X-Tenant-ID": TENANT}


async def fetch(c, path):
    r = await c.http.get(base_url(c) + path, headers=await headers_for(c))
    if r.status_code != 200:
        raise ValueError(f"Cloud-Lesen HTTP {r.status_code}")
    return r


async def snapshot(c):
    item = (await fetch(c, "/v1/items/" + ARTICLE)).json()
    if item.get("Id") != 40 or item.get("SKU") != "1036":
        raise ValueError("Artikelidentitaet stimmt nicht.")
    rows = (await fetch(c, "/v1/items/" + ARTICLE + "/images")).json()
    if not isinstance(rows, list) or not rows:
        raise ValueError("Bildliste fehlt.")
    for r in rows:
        if (r.get("ItemId") != 40 or type(r.get("ImageId")) is not int
                or r["ImageId"] <= 0 or type(r.get("SortNumber")) is not int
                or r["SortNumber"] <= 0 or not r.get("SalesChannelId")):
            raise ValueError("Ungueltige Zuordnung.")
    rows = [r for r in rows if r["SalesChannelId"] != POS]
    files = {}
    for ident in sorted({r["ImageId"] for r in rows}):
        r = await fetch(c, "/v1/items/imagedata/" + str(ident))
        raw = (base64.b64decode(r.json(), validate=True)
               if "json" in r.headers.get("content-type", "") else r.content)
        if not raw or len(raw) > 20 * 1024 * 1024:
            raise ValueError("Originaldatei fehlt oder ist zu gross.")
        files[str(ident)] = raw
    # Detect assignment/metadata changes during downloads.
    check = (await fetch(c, "/v1/items/" + ARTICLE + "/images")).json()
    if canonical(rows) != canonical([r for r in check if r["SalesChannelId"] != POS]):
        raise ValueError("Bestand waehrend Sicherung geaendert.")
    return rows, files


def topology(rows):
    # Retain unknown fields, account identifiers and duplicate counts.
    return canonical([{k: v for k, v in r.items()
                       if not (r["ImageId"] == TARGET and k in META)} for r in rows])


def state(plan, rows, files):
    hashes = {k: digest(v) for k, v in files.items()}
    if canonical(rows) == canonical(plan["rows"]) and hashes == plan["hashes"]:
        return "ORIGINAL"
    desired = dict(plan["hashes"])
    desired[str(TARGET)] = desired[str(SOURCE)]
    if topology(rows) == topology(plan["rows"]) and hashes == desired:
        return "ZIEL"
    # Exact observed v1 behavior: only the shop assignment changes image ID.
    expected = copy.deepcopy(plan["rows"])
    source_meta = [{k: r.get(k) for k in META} for r in expected if r["ImageId"] == SOURCE]
    if source_meta and all(m == source_meta[0] for m in source_meta):
        for r in expected:
            if r["ImageId"] == TARGET and r["SalesChannelId"] == SHOP:
                r["ImageId"] = SOURCE
                r.update(source_meta[0])
        used = {str(r["ImageId"]) for r in expected}
        expected_hashes = {k: v for k, v in plan["hashes"].items() if k in used}
        if canonical(rows) == canonical(expected) and hashes == expected_hashes:
            return "SHOP_NEU_ZUGEORDNET"
    return "ABWEICHUNG"


def backup(path, raw):
    with path.open("xb") as f:
        f.write(raw)
        f.flush()
        os.fsync(f.fileno())


async def run(c, folder, mode):
    if not isinstance(c, OnPremClient) and c.tenant_id != TENANT:
        raise ValueError("Falscher Tenant.")
    with locked(folder):
        if mode == "vorbereiten":
            if (folder / "plan.json").exists():
                raise ValueError("Vorbereitung bereits vorhanden.")
            rows, files = await snapshot(c)
            shops = [(r["ImageId"], r["SortNumber"]) for r in rows if r["SalesChannelId"] == SHOP]
            if sorted(shops) != [(2365, 2), (2729, 1)] or str(SOURCE) not in files:
                raise ValueError("Nicht der bestaetigte Ausgangsbestand.")
            if files[str(TARGET)] == files[str(SOURCE)]:
                raise ValueError("Testdatei unterscheidet sich nicht.")
            names = {r["Filename"] for r in rows if r["ImageId"] == TARGET}
            if len(names) != 1:
                raise ValueError("Originaldateiname nicht eindeutig.")
            for ident, raw in files.items():
                backup(folder / (ident + ".original"), raw)
            save_once(folder / "plan.json", {
                "tenant": TENANT, "article": ARTICLE, "url": base_url(c),
                "created": datetime.now(timezone.utc).isoformat(), "rows": rows,
                "hashes": {k: digest(v) for k, v in files.items()},
                "original_name": next(iter(names)),
                "test_name": "krautl-cloud-inhalttest-1036.jpg"})
        plan = json.loads((folder / "plan.json").read_text(encoding="utf-8"))
        if (plan["tenant"], plan["article"], plan["url"]) != (TENANT, ARTICLE, base_url(c)):
            raise ValueError("Falscher Plan.")
        for ident, sha in plan["hashes"].items():
            if digest((folder / (ident + ".original")).read_bytes()) != sha:
                raise ValueError("Sicherung beschaedigt.")
        rows, files = await snapshot(c)
        current = state(plan, rows, files)
        if mode in ("vorbereiten", "pruefen"):
            return {"zustand": current, "schreibversuch": False}
        intent = folder / (mode + ".intent.json")
        if intent.exists():
            raise ValueError("Schreibversuch verbraucht. Nur ruecklesen.")
        restore = mode == "zuruecksetzen"
        if mode == "diagnose403":
            previous = json.loads((folder / "ausfuehren.result.json").read_text(encoding="utf-8"))
            if previous.get("http") != 403 or previous.get("zustand") != "ORIGINAL":
                raise ValueError("Diagnose nur nach bestaetigt wirkungslosem 403.")
        if restore and not (folder / "ausfuehren.intent.json").exists():
            raise ValueError("Kein eigener Schreibversuch.")
        if not restore:
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(plan["created"])).total_seconds()
            if age < 0 or age > 7200 or (folder / "zuruecksetzen.intent.json").exists():
                raise ValueError("Plan veraltet oder bereits zurueckgesetzt.")
        if current not in (("ZIEL", "SHOP_NEU_ZUGEORDNET") if restore else ("ORIGINAL",)):
            raise ValueError("Ausgangsbestand weicht ab: " + current)
        raw = (folder / (str(TARGET if restore else SOURCE) + ".original")).read_bytes()
        headers = await headers_for(c)
        save_once(intent, {"zeit": datetime.now(timezone.utc).isoformat(), "sha256": digest(raw)})
        result = {"http": None}
        try:
            image_id = SOURCE if restore and current == "SHOP_NEU_ZUGEORDNET" else TARGET
            r = await c.http.patch(base_url(c) + "/v1/items/" + ARTICLE + "/images/" + str(image_id),
                headers=headers, json={"SalesChannelId": SHOP, "ImageData": base64.b64encode(raw).decode(),
                "Filename": plan["original_name"] if restore else plan["test_name"]})
            result["http"] = r.status_code
            auth = headers.get("Authorization", "")
            if isinstance(c, OnPremClient):
                auth = c.http.headers.get("Authorization", "")
            result["diagnose"] = antwortdiagnose(r, [auth,
                auth.removeprefix("Bearer ").removeprefix("Wawi "), getattr(c, "client_secret", "")])
            # Preserve the response even if the subsequent verification is interrupted.
            save_once(folder / (mode + ".antwort.json"), result["diagnose"])
        except httpx.HTTPError:
            result["transportfehler"] = True
        # HTTP success alone does not confirm any image change.
        try:
            rows, files = await snapshot(c)
            result["zustand"] = state(plan, rows, files)
            save_once(folder / (mode + ".bestand.json"), {
                "rows": rows, "hashes": {k: digest(v) for k, v in files.items()}})
        except Exception as exc:
            result["zustand"] = "UNGEPRUEFT"
            result["lesefehler_typ"] = type(exc).__name__
        result["bestaetigt"] = result["zustand"] == ("ORIGINAL" if restore else "ZIEL")
        save_once(folder / (mode + ".result.json"), result)
        return result


async def main(mode, direkt=False):
    async with (OnPremClient.aus_umgebung() if direkt else JtlClient.aus_umgebung()) as c:
        folder = Path(FOLDER + "-direkt" if direkt else FOLDER)
        print(json.dumps(await run(c, folder, mode), ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["vorbereiten", "ausfuehren", "zuruecksetzen", "pruefen", "diagnose403"])
    parser.add_argument("--direkt", action="store_true")
    args = parser.parse_args()
    asyncio.run(main(args.mode, args.direkt))
