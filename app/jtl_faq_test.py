"""Begrenzte Schreibabnahme für Spirulina; keine automatische Synchronisierung."""
import copy
import hashlib
import json
import os
import re
from pathlib import Path
from uuid import uuid4

import httpx

from .jtl_client import ERP_URL, JtlFehler

TENANT = "5bb11f28-30fd-4966-84c5-f59d3841c64b"
SKU = "40047-000"
ITEM = "770f139d-18dd-405c-9f84-322131010000"
INHALT = "29708817-225b-4208-9a57-5ff511000000"
NAME = "29708817-225b-4208-9a57-5ff512000000"
KANAL = "2-2-1"
TITEL = "Fragen / Antworten"


def signatur(attribute):
    """Vergleicht Werte unabhängig von Listenreihenfolge; Mehrdeutigkeit ablehnen."""
    result = {}
    ids = set()
    for a in attribute.get("values") or []:
        ident = a["attributeId"]
        if ident in ids:
            raise JtlFehler("Doppelte Attribut-ID; Abbruch.")
        ids.add(ident)
        result[(ident,)] = True
        gruppen = [(None, a.get("defaultValues") or [])]
        kanaele = set()
        for k in a.get("salesChannelValues") or []:
            kanal = k["salesChannelId"]
            if kanal in kanaele:
                raise JtlFehler("Doppelter Attributkanal; Abbruch.")
            kanaele.add(kanal)
            gruppen.append((kanal, k.get("values") or []))
        for kanal, werte in gruppen:
            for w in werte:
                sprache = w.get("languageIso")
                key = (ident, kanal, sprache.lower() if sprache else None)
                if key in result:
                    raise JtlFehler("Doppelter Attributwert; Abbruch.")
                result[key] = w["value"]
    return result


def zielattribute(vorher, html):
    signatur(vorher)
    ziel = copy.deepcopy(vorher)
    werte = ziel.setdefault("values", [])
    for ident, text in [(NAME, TITEL if html else ""), (INHALT, html)]:
        a = next((a for a in werte if a["attributeId"] == ident), None)
        if a is None:
            a = {"attributeId": ident, "salesChannelValues": []}
            werte.append(a)
        if a.get("salesChannelValues") is None:
            a["salesChannelValues"] = []
        kanal = next((k for k in a["salesChannelValues"] if k["salesChannelId"] == KANAL), None)
        if kanal is None:
            kanal = {"salesChannelId": KANAL, "values": []}
            a["salesChannelValues"].append(kanal)
        if kanal.get("values") is None:
            kanal["values"] = []
        wert = next((w for w in kanal["values"] if (w.get("languageIso") or "").lower() == "de"), None)
        if wert is None:
            kanal["values"].append({"languageIso": "de", "value": text})
        else:
            wert["value"] = text
    return ziel


async def artikel(client):
    if client.tenant_id != TENANT:
        raise JtlFehler("Dieser Test ist ausschließlich für den bestätigten dreikraut-Tenant freigegeben.")
    daten = await client.artikel_lesen(SKU)
    if daten["id"] != ITEM:
        raise JtlFehler("Spirulina-Artikel-ID hat sich geändert; Abbruch.")
    return daten.get("attributes") or {"values": []}


async def pruefen(client, journal):
    daten = json.loads(Path(journal).read_text(encoding="utf-8"))
    if daten.get("tenant") != TENANT or daten.get("artikel_id") != ITEM:
        raise JtlFehler("Journal gehört nicht zu diesem Test.")
    aktuell = signatur(await artikel(client))
    if aktuell == signatur(daten["nachher"]):
        return "Erfolgreich rückgelesen: FAQ-Zielwerte stimmen; alle übrigen Attributwerte sind erhalten."
    if aktuell == signatur(daten["vorher"]):
        raise JtlFehler("Wawi enthält weiterhin den gesicherten Ausgangsstand. Keine automatische Wiederholung.")
    raise JtlFehler("Wawi weicht vom Ziel und Ausgangsstand ab. Journal erhalten; manuell prüfen, nicht erneut schreiben.")


async def uebertragen(client, html, journal, anwenden=False):
    vorher = await artikel(client)
    nachher = zielattribute(vorher, html)
    bericht = {"artikelnummer": SKU, "artikel_id": ITEM, "kanal": KANAL,
               "sprache": "de", "titel": TITEL if html else "", "html_zeichen": len(html),
               "html_sha256": hashlib.sha256(html.encode()).hexdigest(),
               "aenderung_noetig": signatur(vorher) != signatur(nachher)}
    if not anwenden or not bericht["aenderung_noetig"]:
        return bericht
    if Path(journal).exists():
        raise JtlFehler("Ein Testjournal existiert bereits. Nur mit --pruefen rücklesen; kein erneuter Schreibversuch.")
    # Vollständiger Attributstand: sowohl Ersetzen als auch Zusammenführen erhält
    # die übrigen Werte. Niemals eine ungeprüfte partielle Attributliste senden.
    if signatur(await artikel(client)) != signatur(vorher):
        raise JtlFehler("Wawi-Attribute wurden während der Vorbereitung geändert; Abbruch.")
    token = await client._token()
    key = str(uuid4())
    daten = {"tenant": TENANT, "artikel_id": ITEM, "idempotency_key": key,
             "vorher": vorher, "nachher": nachher}
    # Exklusive dauerhafte Reservierung vor Netzwerkzugriff; bei Abbruch/Timeout
    # bleibt sie bestehen. Das Journal enthält keine Zugangsdaten.
    fd = os.open(journal, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as datei:
        json.dump(daten, datei, ensure_ascii=False, indent=2)
        datei.flush()
        os.fsync(datei.fileno())
    if os.name == "posix":
        verzeichnis = os.open(str(Path(journal).parent), os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(verzeichnis)
        finally:
            os.close(verzeichnis)
    bericht["ergebnis"] = await senden(client, daten, journal, token)
    return bericht


def antwortdiagnose(antwort, geheimnisse):
    def bereinigen(wert):
        text = str(wert)
        for geheimnis in geheimnisse:
            if geheimnis:
                text = text.replace(geheimnis, "[entfernt]")
        return text[:1000]
    bericht = {"http_status": antwort.status_code}
    for name in ("content-type", "server", "cf-ray", "x-request-id", "x-correlation-id", "x-azure-ref", "date"):
        if name in antwort.headers:
            bericht[name] = bereinigen(antwort.headers[name])
    try:
        body = antwort.json()
    except ValueError:
        treffer = re.search(r"<title[^>]*>(.*?)</title>", antwort.text, re.I | re.S)
        if treffer:
            bericht["html_titel"] = bereinigen(treffer.group(1))
        bericht["antwortformat"] = "kein JSON"
    else:
        if isinstance(body, dict):
            if isinstance(body.get("errors"), list):
                bericht["graphql_fehler"] = [bereinigen(e.get("message", "GraphQL-Fehler"))
                    for e in body["errors"][:10] if isinstance(e, dict)]
            for name in ("code", "errorCode", "error", "title", "message", "detail", "traceId"):
                if isinstance(body.get(name), (str, int)):
                    bericht[name] = bereinigen(body[name])
    return bericht


async def senden(client, daten, journal, token, graphql=False):
    try:
        headers = {"Authorization": "Bearer " + token, "X-Tenant-ID": TENANT,
                   "Idempotency-Key": daten["idempotency_key"]}
        if graphql:
            antwort = await client.http.post(ERP_URL + "/v2/graphql", headers=headers, json={
                "query": "mutation KrautlFaqTest($request: ChangeItemCommandRequestInput!) { ChangeItem(request: $request) { __typename } }",
                "variables": {"request": {"itemId": ITEM, "attributes": daten["nachher"]}}})
        else:
            antwort = await client.http.patch(ERP_URL + "/v2/items/" + ITEM,
                headers=headers, json={"attributes": daten["nachher"]})
    except httpx.HTTPError as exc:
        raise JtlFehler("Versandergebnis unklar. Nicht wiederholen; mit --pruefen rücklesen.") from exc
    diagnose = antwortdiagnose(antwort, [token, client.client_secret])
    pfad = str(journal) + ".antwort-" + str(uuid4()) + ".json"
    with os.fdopen(os.open(pfad, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w", encoding="utf-8") as datei:
        json.dump(diagnose, datei, ensure_ascii=False, indent=2)
        datei.flush()
        os.fsync(datei.fileno())
    graphql_ok = True
    if graphql:
        try:
            body = antwort.json()
            graphql_ok = isinstance(body, dict) and not body.get("errors") and bool((body.get("data") or {}).get("ChangeItem"))
        except (ValueError, AttributeError):
            graphql_ok = False
    if antwort.status_code != 200 or not graphql_ok:
        raise JtlFehler("JTL-Schreibantwort: " + json.dumps(diagnose, ensure_ascii=False) +
                       ". Journal gesichert; mit --pruefen rücklesen, nicht wiederholen.")
    return await pruefen(client, journal)


async def diagnose403(client, html, journal, graphql=False):
    """Explizit ausgelöster, einmaliger Diagnoseversuch des abgelehnten Auftrags."""
    daten = json.loads(Path(journal).read_text(encoding="utf-8"))
    if daten.get("tenant") != TENANT or daten.get("artikel_id") != ITEM:
        raise JtlFehler("Journal gehört nicht zu diesem Test.")
    if signatur(daten["nachher"]) != signatur(zielattribute(daten["vorher"], html)):
        raise JtlFehler("Die FAQ-Auswahl wurde inzwischen verändert; kein veraltetes HTML übertragen.")
    aktuell = signatur(await artikel(client))
    if aktuell == signatur(daten["nachher"]):
        return {"ergebnis": "Ziel bereits vorhanden; kein Schreibzugriff."}
    if aktuell != signatur(daten["vorher"]):
        raise JtlFehler("Wawi-Ausgangsstand verändert; kein Diagnose-Schreibzugriff.")
    token = await client._token()
    # Permanente separate Sperre; ursprüngliches Journal niemals löschen/ersetzen.
    with os.fdopen(os.open(str(journal) + (".graphql" if graphql else ".diagnose403"), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as datei:
        datei.write(daten["idempotency_key"])
        datei.flush()
        os.fsync(datei.fileno())
    return {"ergebnis": await senden(client, daten, journal, token, graphql=graphql)}
