"""Read-only Wawi reconciliation of the two confirmed 2026-11-03 uploads."""
import asyncio
import copy
from pathlib import Path
import json
from app import bilder_speicher as store
from app.jtl_onprem import OnPremClient
from app.bilder_upload import auftraege, detail_lesen, bildblock, fingerprint, sichern
from app.bilder_ersetzen import liste, zuordnungen, bild, hinzufuegen_pruefen
from app.bilder_upload import bildinhalt_bestaetigt

JOBS = {"1082-500": "beafb0d0-15b9-481d-b312-9d951156e9de",
        "1082-100": "86acd14b-f54d-4023-bdaa-ca22e7b2d13b"}
NEW = 2734


def validate(job, detail, rows):
    if job.get("id") != JOBS.get(job.get("sku")) or job.get("phase") != "upload" or job.get("ziel"):
        raise ValueError("Kein passender alter Uploadauftrag.")
    # Only the observed missing identifiers may be removed for comparison.
    clean = copy.deepcopy(detail)
    block = clean["images"]
    for field in ("defaultImages", "platformImages", "saleschannelImages", "ebayImages"):
        groups = [{"images": block.get(field, [])}] if field == "defaultImages" else block.get(field, [])
        for group in groups:
            group["images"] = [b for b in group["images"] if b.get("blobIdentifier")]
        block[field] = groups[0]["images"] if field == "defaultImages" else [g for g in groups if g["images"]]
    if fingerprint(bildblock(clean)) != fingerprint(job["vorher"]):
        raise ValueError("Vorhandene Zuordnungen haben sich veraendert.")
    item = 442 if job["sku"] == "1082-500" else 422
    old_channels = ("1-1-1", "2-2-1", "8-140-7", "9-7-8-0", "8-140-9", "11-8-12-15", "11-8-26-16", "6-51-0", "5-30-1")
    before = [] if item == 442 else sorted([[item,2707,ch,"",1] for ch in old_channels])
    pos = 1 if item == 442 else 2
    expected = sorted(before + [[item,NEW,ch,"",pos] for ch in ("1-1-1","2-2-1")])
    if zuordnungen(rows) != expected:
        raise ValueError("v1-Zuordnungen entsprechen nicht dem erwarteten Zusatzbild.")
    for r in rows:
        if r["ImageId"] == NEW and not r.get("Filename", "").endswith("krautl-" + JOBS["1082-500"] + ".png"):
            raise ValueError("Unerwartete Importdatei.")
    return before


async def main():
    with store.Laufsperre():
        async with OnPremClient.aus_umgebung() as c:
            for sku, key in JOBS.items():
                job = next(j for j in auftraege() if j["id"] == key)
                if job.get("art") == "hinzufuegen_v1":
                    print(sku, (await hinzufuegen_pruefen(c, job))["status"])
                    continue
                if job["api_ziel"] != c.url or job["status"] != "unklar":
                    raise ValueError("Unerwarteter Auftragsstand.")
                rows = await liste(c, job["artikel"])
                before = validate(job, await detail_lesen(c, job["artikel"], sku), rows)
                if not bildinhalt_bestaetigt(job, await bild(c, NEW)):
                    raise ValueError("Dateiinhalt stimmt nicht mit dem Upload ueberein.")
                if zuordnungen(await liste(c, job["artikel"])) != zuordnungen(rows):
                    raise ValueError("Bestand waehrend der Pruefung geaendert.")
                audit = Path("var/bilder/ausleitung-upload-bestaetigung")
                audit.mkdir(parents=True, exist_ok=True)
                path = audit / (key + ".json")
                if not path.exists():
                    path.write_text(json.dumps({"auftrag":job,"v1":rows},ensure_ascii=False),encoding="utf-8")
                job.update(legacy_upload=copy.deepcopy(job),art="hinzufuegen_v1",v1_ausgang=before)
                sichern(job)
                print(sku, (await hinzufuegen_pruefen(c, job))["status"], "Keine Wawi-Schreibzugriffe.")


if __name__ == "__main__":
    asyncio.run(main())
