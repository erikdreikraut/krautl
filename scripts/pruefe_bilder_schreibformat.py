"""Isolate image request parsing against a verified nonexistent item, never a live one."""
import asyncio
import copy
import argparse
import json
from uuid import UUID, uuid4

from app.bilder_upload import auftraege, bildblock, schreibblock, ablehnungsdetails
from app.jtl_onprem import OnPremClient


def pruefziel(source):
    # Keep JTL's entity-key prefix, use the largest positive Int32 as the item key.
    # This is only a candidate: GET must confirm absence immediately before EVERY PATCH.
    value = UUID(source)
    target = str(UUID(hex=value.hex[:-8] + (2147483647).to_bytes(4, "little").hex()))
    if target == str(value):
        raise ValueError("Diagnoseziel entspricht dem Quellartikel; Abbruch.")
    return target


def artikel_fehlt(response):
    """Installed Wawi 2.1.1 returns HTTP 200 with literal JSON null for missing keys."""
    if response.status_code == 404:
        return True
    if response.status_code != 200:
        return False
    try:
        return response.json() is None
    except ValueError:
        return False


def faelle(block):
    block = schreibblock(block)
    yield "Gesamter Bildblock", {"images": copy.deepcopy(block)}
    for field, groups in block.items():
        yield field, {"images": {field: copy.deepcopy(groups)}}
        if field == "defaultImages":
            continue
        for index, group in enumerate(groups):
            key = next(k for k in group if k != "images")
            yield f"{field}[{index}] / {group[key]}", {"images": {field: [copy.deepcopy(group)]}}


async def pruefen(client, job, ausgabe=print):
    if job.get("api_ziel") != client.url:
        raise ValueError("Wawi-Ziel passt nicht zum gespeicherten Auftrag.")
    source = str(UUID(job["artikel"]))
    target = pruefziel(source)
    # Prove the API route/access using the source, which is only ever read.
    source_response = await client.http.get(client.url + "/v2/items/" + source)
    if source_response.status_code != 200:
        raise ValueError(f"Quellartikel nicht lesbar: HTTP {source_response.status_code}.")
    detail = source_response.json()
    if detail.get("id") != source or detail.get("identifiers", {}).get("sku") != job.get("sku"):
        raise ValueError("Quellartikel stimmt nicht mit Auftrag überein.")
    # Use the exact rejected snapshot, retaining it in the journal unchanged.
    block = bildblock({"images": job["ziel"]})
    endpoint = client.url + "/v2/items/" + target
    ausgabe(f"Quelle (nur lesen): {job['sku']} | Diagnoseziel: {target}")
    ausgabe("PATCH nur auf dieses jeweils per GET als fehlend geprüfte Diagnoseziel.")

    async def probe(label, body):
        response = await client.http.get(endpoint)
        if not artikel_fehlt(response):
            raise ValueError(f"Abbruch vor PATCH: Diagnoseziel liefert HTTP {response.status_code} ohne bestätigten Fehlbestand (404 oder JSON null).")
        response = await client.http.patch(endpoint, json=body)
        status = response.status_code
        ausgabe(f"{label}: HTTP {status}")
        if status != 404:
            ausgabe(ablehnungsdetails(response))
        if status not in (400, 404, 422):
            raise ValueError("Unerwartete Antwort; keine weiteren Requests. Kein automatischer Neuversuch.")
        return status

    baseline = await probe("Kontrolle ohne Bilddaten", {})
    if baseline != 404:
        raise ValueError("Kontrollrequest erreicht keine eindeutige Artikel-nicht-gefunden-Antwort; Diagnose beendet.")
    results = []
    for label, body in faelle(block):
        results.append((label, await probe(label, body)))
    ausgabe("Fertig. 404 wie Kontrolle: keine Ablehnung wie beim bisherigen Bildrequest.")
    ausgabe("400/422: betreffenden Teil gezielt untersuchen. 404 ist KEINE Schreibfreigabe für echte Artikel.")
    return results


async def identitaeten_lesen(client, job, ausgabe=print):
    """Read-only comparison of source, synthetic UUID and numeric key handling."""
    if job.get("api_ziel") != client.url:
        raise ValueError("Wawi-Ziel passt nicht zum gespeicherten Auftrag.")
    source = str(UUID(job["artikel"]))
    candidates = [("Quellartikel", source), ("Bisheriges Diagnoseziel", pruefziel(source)),
                  ("Numerischer Schlüssel", "2147483647"), ("Zufällige UUID", str(uuid4()))]
    for label, key in candidates:
        response = await client.http.get(client.url + "/v2/items/" + key)
        ausgabe(f"{label}: {key} | HTTP {response.status_code}")
        try:
            body = response.json()
        except ValueError:
            ausgabe("Kein JSON; Inhalt wird nicht ausgegeben.")
            continue
        if isinstance(body, dict):
            identifiers = body.get("identifiers")
            summary = {"felder": list(body), "id": body.get("id"),
                       "sku": identifiers.get("sku") if isinstance(identifiers, dict) else None}
            ausgabe(json.dumps(summary, ensure_ascii=False))
            if response.status_code != 200:
                ausgabe(ablehnungsdetails(response))
        else:
            ausgabe("JSON-Typ: " + type(body).__name__)
    ausgabe("Beendet: ausschließlich GET, keine PATCH-Requests und keine lokalen Änderungen.")


async def main(nur_lesen=False):
    jobs = sorted((j for j in auftraege() if j.get("art") == "reihenfolge"
                   and j.get("status") == "abgelehnt" and j.get("diagnose") and j.get("ziel")),
                  key=lambda j: j.get("erstellt", ""))
    if not jobs:
        raise ValueError("Kein abgelehnter Reihenfolgeauftrag mit Diagnose vorhanden.")
    async with OnPremClient.aus_umgebung() as client:
        await (identitaeten_lesen(client, jobs[-1]) if nur_lesen else pruefen(client, jobs[-1]))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--nur-lesen", action="store_true", help="Nur GET-Antworten zur Artikel-ID prüfen")
    args = parser.parse_args()
    try:
        asyncio.run(main(args.nur_lesen))
    except Exception as exc:
        # Do not print exception text from HTTP clients (may include sensitive URLs).
        if isinstance(exc, ValueError):
            print("Diagnose:", str(exc), flush=True)
        else:
            print("Diagnose abgebrochen:", type(exc).__name__, "Keine automatische Wiederholung.", flush=True)
        raise SystemExit(1)
