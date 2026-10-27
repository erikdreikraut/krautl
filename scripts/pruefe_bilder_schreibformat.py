"""Isolate image request parsing against a verified nonexistent item, never a live one."""
import asyncio
import copy
from uuid import UUID

from app.bilder_upload import auftraege, bildblock, schreibblock, ablehnungsdetails
from app.jtl_onprem import OnPremClient


def pruefziel(source):
    # Keep JTL's entity-key prefix, use the largest positive Int32 as the item key.
    # This is only a candidate: GET must return 404 immediately before EVERY PATCH.
    value = UUID(source)
    target = str(UUID(hex=value.hex[:-8] + (2147483647).to_bytes(4, "little").hex()))
    if target == str(value):
        raise ValueError("Diagnoseziel entspricht dem Quellartikel; Abbruch.")
    return target


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
        if response.status_code != 404:
            raise ValueError(f"Abbruch vor PATCH: Diagnoseziel liefert HTTP {response.status_code} statt 404.")
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


async def main():
    jobs = sorted((j for j in auftraege() if j.get("art") == "reihenfolge"
                   and j.get("status") == "abgelehnt" and j.get("diagnose") and j.get("ziel")),
                  key=lambda j: j.get("erstellt", ""))
    if not jobs:
        raise ValueError("Kein abgelehnter Reihenfolgeauftrag mit Diagnose vorhanden.")
    async with OnPremClient.aus_umgebung() as client:
        await pruefen(client, jobs[-1])


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:
        # Do not print exception text from HTTP clients (may include sensitive URLs).
        if isinstance(exc, ValueError):
            print("Diagnose:", str(exc), flush=True)
        else:
            print("Diagnose abgebrochen:", type(exc).__name__, "Keine automatische Wiederholung.", flush=True)
        raise SystemExit(1)
