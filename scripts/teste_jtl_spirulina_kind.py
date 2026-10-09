"""Expliziter Teilupdate-Test für 40047-1000; keine Vererbung oder Automatik."""
import argparse
import asyncio
import json
import os
from pathlib import Path
from uuid import uuid4

import httpx

from app.jtl_client import JtlClient, JtlFehler, ERP_URL
from app.jtl_faq_test import TENANT, NAME, INHALT, KANAL, zielattribute, signatur, antwortdiagnose
from scripts.pruefe_jtl_schreibschema import schema_query, validiere

SKU = "40047-1000"
KURZTEXT = "Krautl FAQ Schreibtest 40047-1000"


def sichern(pfad, daten):
    with os.fdopen(os.open(pfad, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w", encoding="utf-8") as datei:
        json.dump(daten, datei, ensure_ascii=False, indent=2)
        datei.flush()
        os.fsync(datei.fileno())
    if os.name == "posix":
        fd = os.open(str(Path(pfad).parent), os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


async def lesen(client):
    if client.tenant_id != TENANT:
        raise JtlFehler("Falscher Tenant; Abbruch.")
    return await client.artikel_lesen(SKU)


def vergleich(vorher, ziel, aktuell):
    alt, soll, ist = map(signatur, (vorher, ziel, aktuell))
    zielkeys = {(NAME, KANAL, "de"), (INHALT, KANAL, "de")}
    andere = {k: v for k, v in alt.items() if k not in zielkeys}
    return {"ziel_erreicht": all(ist.get(k) == soll.get(k) for k in zielkeys),
            "andere_bestandswerte_erhalten": all(ist.get(k) == v for k, v in andere.items()),
            "exakter_zielstand": ist == soll,
            "ausgangsstand_unveraendert": ist == alt,
            "fehlende_oder_geaenderte_bestandsfelder": [list(k) for k, v in andere.items() if ist.get(k) != v]}


async def ruecklesen(client, daten):
    if daten.get("tenant") != TENANT or daten.get("artikelnummer") != SKU:
        raise JtlFehler("Journal passt nicht zum Kind-Test.")
    aktuell = await lesen(client)
    if aktuell["id"] != daten["artikel_id"]:
        raise JtlFehler("Artikel-ID stimmt nicht mit Sicherung überein.")
    return vergleich(daten["vorher"], daten["ziel"], aktuell.get("attributes") or {"values": []})


async def testen(client, html, journal, anwenden=False, ergebnis_test=False,
                 kurztext=False, transport="graphql"):
    if transport not in ("graphql", "rest"):
        raise JtlFehler("Unbekannter Transport.")
    if (kurztext or transport == "rest") and ergebnis_test:
        raise JtlFehler("Kurztext und REST benötigen einen eigenen Auftrag, keinen Ergebnis-Wiederholungsversuch.")
    if kurztext:
        html = KURZTEXT
    if not html:
        raise JtlFehler("Keine freigegebenen FAQ; kein Schreibtest.")
    artikel = await lesen(client)
    vorher = artikel.get("attributes") or {"values": []}
    if kurztext or transport == "rest":
        bestand = signatur(vorher)
        if any((ident, KANAL, "de") not in bestand for ident in (NAME, INHALT)):
            raise JtlFehler("Dieser Test erfordert beide vorhandenen deutschen Shop-Attributwerte.")
    ziel = zielattribute(vorher, html)
    # Bewusst nur die beiden Zielwerte. Ob JTL übrige Werte erhält, wird am
    # ausdrücklich freigegebenen Kind-Artikel geprüft und nicht vorausgesetzt.
    teilupdate = zielattribute({"values": []}, html)
    request = {"itemId": artikel["id"], "attributes": teilupdate}
    schema = await client._lesen("/v2/graphql", {"query": schema_query()})
    if schema.get("errors"):
        raise JtlFehler("Live-Schema konnte nicht geprüft werden.")
    typen = {t["name"]: t for t in ((schema.get("data") or {}).get("__schema") or {}).get("types", [])}
    befunde = validiere(request, {"kind": "INPUT_OBJECT", "name": "ChangeItemCommandRequestInput"}, typen)
    if befunde:
        raise JtlFehler("Auftrag nicht schemakonform: " + json.dumps(befunde, ensure_ascii=False))
    bericht = {"artikelnummer": SKU, "artikel_id": artikel["id"], "html_zeichen": len(html),
               "schema_befunde": befunde, "gesendete_attributanzahl": 2,
               "transport": transport, "inhalt_art": "kurztext" if kurztext else "faq_html"}
    if not anwenden and not ergebnis_test:
        return bericht
    if Path(journal).exists() and not ergebnis_test:
        raise JtlFehler("Kind-Journal existiert bereits. Nur --pruefen verwenden; nicht erneut schreiben.")
    original = None
    if ergebnis_test:
        original = json.loads(Path(journal).read_text(encoding="utf-8"))
        if (original.get("tenant") != TENANT or original.get("artikelnummer") != SKU
                or original.get("artikel_id") != artikel["id"] or original.get("request") != request):
            raise JtlFehler("Ursprünglicher Auftrag stimmt nicht mehr überein; Abbruch.")
        if signatur(vorher) != signatur(original["vorher"]):
            raise JtlFehler("Kind-Ausgangsstand verändert; nur rücklesen, kein weiterer Schreibzugriff.")
    if signatur(vorher) == signatur(ziel):
        return {**bericht, "ergebnis": "Ziel bereits vorhanden; kein Schreibzugriff und keine neue Teilupdate-Abnahme."}
    aktuell = await lesen(client)
    if aktuell["id"] != artikel["id"] or signatur(aktuell.get("attributes") or {"values": []}) != signatur(vorher):
        raise JtlFehler("Kind-Artikel hat sich geändert; Abbruch.")
    token = await client._token()
    daten = {"tenant": TENANT, "artikelnummer": SKU, "artikel_id": artikel["id"],
             "vorher": vorher, "ziel": ziel, "request": request, "idempotency_key": str(uuid4()),
             "transport": transport, "inhalt_art": bericht["inhalt_art"]}
    if original:
        daten = original
    ausgabe = str(journal) + (".item-ergebnis" if ergebnis_test else "")
    sichern(ausgabe, daten)
    try:
        headers = {
            "Authorization": "Bearer " + token, "X-Tenant-ID": TENANT,
            "Idempotency-Key": daten["idempotency_key"]}
        if transport == "rest":
            antwort = await client.http.patch(ERP_URL + "/v2/items/" + artikel["id"],
                headers=headers, json={"attributes": teilupdate})
        else:
            antwort = await client.http.post(ERP_URL + "/v2/graphql", headers=headers, json={
                "query": "mutation KrautlKindTest($request: ChangeItemCommandRequestInput!) { ChangeItem(request: $request) { item { id } } }",
                "variables": {"request": request}})
    except httpx.HTTPError as exc:
        raise JtlFehler("Versandergebnis unklar. Journal behalten und nur --pruefen verwenden.") from exc
    diagnose = antwortdiagnose(antwort, [token, client.client_secret])
    try:
        body = antwort.json()
        ergebnis = body if transport == "rest" else (body.get("data") or {}).get("ChangeItem")
        ergebnis_id = ((ergebnis or {}).get("item") or {}).get("id")
        diagnose["ergebnis_artikel_id"] = ergebnis_id
        api_ok = antwort.status_code == 200 and isinstance(body, dict) and not body.get("errors") and ergebnis_id == artikel["id"]
    except (ValueError, AttributeError):
        api_ok = False
    sichern(ausgabe + ".antwort.json", diagnose)
    # Auch bei einer API-Fehlermeldung den tatsächlichen Zustand zurücklesen.
    pruefung = await ruecklesen(client, daten)
    bericht.update({"api_erfolg": api_ok, "antwort": diagnose, "ruecklesepruefung": pruefung,
                    "test_erfolgreich": api_ok and pruefung["exakter_zielstand"]})
    sichern(ausgabe + ".ergebnis.json", bericht)
    return bericht


async def faq_html():
    from sqlalchemy import select
    from app.db import SessionLocal, engine
    from app.models import Produkt, FaqEintrag
    from app.wissensbasis import faq_als_jtl_html
    try:
        async with SessionLocal() as session:
            produkte = (await session.execute(select(Produkt).where(Produkt.artikelnummer == "40047-000"))).scalars().all()
            if len(produkte) != 1:
                raise JtlFehler("Krautl-Vaterprodukt nicht eindeutig gefunden.")
            faq = (await session.execute(select(FaqEintrag).where(FaqEintrag.produkt_id == produkte[0].id,
                FaqEintrag.aktiv.is_(True), FaqEintrag.status == "freigegeben"))).scalars().all()
            if not faq:
                raise JtlFehler("Keine ausgewählten Vater-FAQ vorhanden.")
            return faq_als_jtl_html(produkte[0], faq)
    finally:
        await engine.dispose()


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modus = parser.add_mutually_exclusive_group()
    modus.add_argument("--anwenden", action="store_true")
    modus.add_argument("--pruefen", action="store_true")
    modus.add_argument("--ergebnis-test", action="store_true", help="Einmaliger Originalauftrag mit fachlicher item-Rückgabe, nur bei unverändertem Ausgangsstand")
    parser.add_argument("--kurztext-test", action="store_true", help="Temporären kurzen Text ohne HTML statt FAQ verwenden")
    parser.add_argument("--transport", choices=("graphql", "rest"), default="graphql")
    parser.add_argument("--journal")
    args = parser.parse_args()
    journal = args.journal or (f"/jtl-test/spirulina-kind-40047-1000-kurztext-{args.transport}.json"
                              if args.kurztext_test else
                              "/jtl-test/spirulina-kind-40047-1000-html-rest.json" if args.transport == "rest"
                              else "/jtl-test/spirulina-kind-40047-1000.json")
    try:
        async with JtlClient.aus_umgebung() as client:
            if args.pruefen:
                result = await ruecklesen(client, json.loads(Path(journal).read_text(encoding="utf-8")))
            else:
                result = await testen(client, KURZTEXT if args.kurztext_test else await faq_html(),
                    journal, args.anwenden, args.ergebnis_test, args.kurztext_test, args.transport)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 1 if result.get("test_erfolgreich") is False else 0
    except (JtlFehler, OSError, ValueError, KeyError) as exc:
        print("Test abgebrochen:", str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
