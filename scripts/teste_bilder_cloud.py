"""Einmaliger Cloud-Bildtest fuer SKU 1036: Shoppositionen 1/2 tauschen."""
import argparse
import asyncio
import copy
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

import httpx

from app.jtl_client import ERP_URL, JtlClient, JtlFehler

TENANT = "5bb11f28-30fd-4966-84c5-f59d3841c64b"
SKU = "1036"
SHOP = "2-2-1"
POS = "9-7-8-0"
GROUPS = {"defaultImages": None, "platformImages": "platformId",
          "saleschannelImages": "saleschannelId", "ebayImages": "ebayAccountId"}


def canonical(value):
    if isinstance(value, dict):
        return {k: canonical(v) for k, v in value.items()}
    if isinstance(value, list):
        return sorted((canonical(v) for v in value), key=lambda v: json.dumps(v, sort_keys=True))
    return value


def images(detail):
    """Fail closed on unknown fields; never silently strip image metadata."""
    block = copy.deepcopy(detail.get("images"))
    if not isinstance(block, dict) or set(block) != set(GROUPS):
        raise ValueError("Unbekannter oder fehlender Bildblock.")
    for field, key in GROUPS.items():
        groups = block.setdefault(field, [])
        if not isinstance(groups, list):
            raise ValueError("Bildgruppen sind keine Liste.")
        seen = set()
        for group in groups if key else [{"images": groups}]:
            if key:
                if not isinstance(group, dict) or set(group) != {key, "images"}:
                    raise ValueError("Unbekannte Bildgruppenfelder.")
                ident = group[key]
                if not isinstance(ident, str) or not ident or ident in seen:
                    raise ValueError("Kanal fehlt oder ist mehrfach enthalten.")
                seen.add(ident)
                if field == "saleschannelImages" and ident == POS:
                    continue
            rows = group["images"]
            if not isinstance(rows, list):
                raise ValueError("Bilder sind keine Liste.")
            bids = set()
            for row in rows:
                if not isinstance(row, dict) or set(row) != {"blobIdentifier", "sortNumber", "isMainImage"}:
                    raise ValueError("Unbekannte Bildfelder; keine Metadaten verwerfen.")
                bid = str(UUID(row["blobIdentifier"]))
                if bid in bids or type(row["sortNumber"]) is not int or type(row["isMainImage"]) is not bool:
                    raise ValueError("Bildposition oder Bildkennung uneindeutig.")
                bids.add(bid)
    block["saleschannelImages"] = [g for g in block["saleschannelImages"] if g["saleschannelId"] != POS]
    return block


def target(before):
    result = copy.deepcopy(before)
    shops = [g for g in result["saleschannelImages"] if g["saleschannelId"] == SHOP]
    if len(shops) != 1:
        raise ValueError("Shopkanal fehlt oder ist nicht eindeutig.")
    rows = sorted(shops[0]["images"], key=lambda r: r["sortNumber"])
    if len(rows) < 2 or [r["sortNumber"] for r in rows] != list(range(1, len(rows) + 1)):
        raise ValueError("Mindestens zwei Bilder mit fortlaufenden Positionen erforderlich.")
    if [r["isMainImage"] for r in rows] != [True] + [False] * (len(rows) - 1):
        raise ValueError("Hauptbild nicht eindeutig auf Position 1.")
    rows[0]["sortNumber"], rows[1]["sortNumber"] = 2, 1
    rows[0]["isMainImage"], rows[1]["isMainImage"] = False, True
    return result


def save_once(path, data):
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    if os.name != "nt":
        fd = os.open(str(path.parent), os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


@contextmanager
def locked(folder):
    folder.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(folder / "lock.sqlite", timeout=1)
    try:
        db.execute("BEGIN EXCLUSIVE")
        yield
    finally:
        db.rollback()
        db.close()


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def validate_plan(plan, tenant):
    if plan.get("tenant") != TENANT or tenant != TENANT or plan.get("sku") != SKU or plan.get("url") != ERP_URL:
        raise ValueError("Mandant, Artikel oder Cloud-Ziel passt nicht zum Plan.")
    UUID(plan["article"])
    before = images({"images": plan["before"]})
    if canonical(target(before)) != canonical(plan["after"]):
        raise ValueError("Plan enthaelt andere Aenderungen als den Positionstausch.")


async def read(client, plan=None):
    detail = await client.artikel_lesen(SKU)
    if plan and detail["id"] != plan["article"]:
        raise ValueError("Artikelidentitaet hat sich geaendert.")
    return detail, images(detail)


async def inspect(client, plan):
    _, current = await read(client, plan)
    if canonical(current) == canonical(plan["after"]):
        return "ZIEL"
    if canonical(current) == canonical(plan["before"]):
        return "ORIGINAL"
    return "ABWEICHUNG"


async def run(client, folder, mode):
    if client.tenant_id != TENANT:
        raise ValueError("Falscher Cloud-Mandant; kein Zugriff.")
    folder = Path(folder)
    with locked(folder):
        path = folder / "plan.json"
        if not path.exists():
            if mode != "vorbereiten":
                raise ValueError("Zuerst --vorbereiten ausfuehren.")
            detail, before = await read(client)
            plan = {"tenant": TENANT, "url": ERP_URL, "sku": SKU, "article": detail["id"],
                    "created": datetime.now(timezone.utc).isoformat(), "before": before,
                    "after": target(before), "detail_backup": detail}
            save_once(path, plan)
        plan = load(path)
        validate_plan(plan, client.tenant_id)
        if mode in ("vorbereiten", "pruefen"):
            state = await inspect(client, plan)
            return {"sku": SKU, "zustand": state, "schreibzugriff": False,
                    "testversuch": (folder / "ausfuehren.intent.json").exists(),
                    "ruecksetzversuch": (folder / "zuruecksetzen.intent.json").exists(),
                    "hinweis": "ZIEL bestaetigt die Bildzuordnungen, nicht Dateiaustausch oder Shop-Veroeffentlichung."}
        if mode not in ("ausfuehren", "zuruecksetzen"):
            raise ValueError("Unbekannter Modus.")
        intent = folder / (mode + ".intent.json")
        if intent.exists() or (mode == "ausfuehren" and (folder / "zuruecksetzen.intent.json").exists()):
            raise ValueError("Schreibversuch bereits protokolliert. Nur --pruefen, niemals blind wiederholen.")
        if mode == "zuruecksetzen" and not (folder / "ausfuehren.intent.json").exists():
            raise ValueError("Kein eigener Testversuch vorhanden.")
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(plan["created"])).total_seconds()
        if mode == "ausfuehren" and not 0 <= age <= 7200:
            raise ValueError("Plan aelter als zwei Stunden. Keine automatische Neuplanung.")
        # Obtain token before the last comparison. No authentication/write retries.
        token = await client._token()
        expected = "ORIGINAL" if mode == "ausfuehren" else "ZIEL"
        if await inspect(client, plan) != expected:
            raise ValueError("Bestand entspricht nicht dem erwarteten Ausgangsstand; kein Schreiben.")
        body = {"images": plan["after"] if mode == "ausfuehren" else plan["before"]}
        save_once(intent, {"at": datetime.now(timezone.utc).isoformat(), "tenant": TENANT,
                           "article": plan["article"], "request": body})
        report = {"sku": SKU, "modus": mode, "http_status": None, "zustand": "UNKLAR"}
        try:
            response = await client.http.patch(ERP_URL + "/v2/items/" + plan["article"],
                headers={"Authorization": "Bearer " + token, "X-Tenant-ID": TENANT}, json=body)
            report["http_status"] = response.status_code
            report["antworttyp"] = response.headers.get("content-type", "")
        except httpx.HTTPError:
            report["transportfehler"] = True
        try:
            report["zustand"] = await inspect(client, plan)
        except (JtlFehler, ValueError, httpx.HTTPError):
            report["ruecklesen_fehlgeschlagen"] = True
        desired = "ZIEL" if mode == "ausfuehren" else "ORIGINAL"
        report["zuordnungen_bestaetigt"] = report["zustand"] == desired
        report["hinweis"] = "Kein automatischer Wiederholungsversuch. HTTP allein ist kein Erfolgsnachweis."
        save_once(folder / (mode + ".result.json"), report)
        return report


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    for mode in ("vorbereiten", "ausfuehren", "pruefen", "zuruecksetzen"):
        modes.add_argument("--" + mode, dest="mode", action="store_const", const=mode)
    args = parser.parse_args()
    # Fixed persistent host-mounted folder; no CLI override enabling accidental retries.
    async with JtlClient.aus_umgebung() as client:
        report = await run(client, "/app/var/bilder/cloud-test-1036", args.mode)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (ValueError, JtlFehler, OSError, sqlite3.Error) as exc:
        print("Abbruch:", str(exc))
        raise SystemExit(1)
