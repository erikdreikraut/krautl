"""Prüft den gesicherten FAQ-Auftrag gegen GraphQL-Inputtypen, ohne Mutation."""
import argparse
import asyncio
import json
from pathlib import Path

from app.jtl_client import JtlClient, JtlFehler
from app.jtl_faq_test import ITEM, TENANT, zielattribute, signatur, INHALT, KANAL


def schema_query():
    referenz = "kind name"
    for _ in range(7):
        referenz = "kind name ofType { " + referenz + " }"
    return "query { __schema { types { kind name inputFields { name defaultValue type { " + referenz + " } } } } }"


def validiere(wert, typ, typen, pfad="request"):
    fehler = []
    def melden(grund):
        fehler.append({"pfad": pfad, "fehler": grund})
    if typ["kind"] == "NON_NULL":
        if wert is None:
            melden("null ist hier laut Live-Schema unzulässig")
            return fehler
        return validiere(wert, typ["ofType"], typen, pfad)
    if wert is None:
        return fehler
    if typ["kind"] == "LIST":
        # GraphQL erlaubt auch einen Einzelwert als Liste mit einem Element.
        for i, eintrag in enumerate(wert if isinstance(wert, list) else [wert]):
            fehler.extend(validiere(eintrag, typ["ofType"], typen, f"{pfad}[{i}]"))
    elif typ["kind"] == "INPUT_OBJECT":
        if not isinstance(wert, dict):
            melden("Objekt erwartet")
            return fehler
        definition = typen.get(typ["name"])
        if definition is None:
            raise JtlFehler("Inputtyp fehlt im Schema: " + typ["name"])
        felder = {f["name"]: f for f in definition.get("inputFields") or []}
        for name in wert:
            if name not in felder:
                fehler.append({"pfad": pfad + "." + name, "fehler": "Feld im Inputtyp nicht erlaubt"})
        for name, feld in felder.items():
            if name in wert:
                fehler.extend(validiere(wert[name], feld["type"], typen, pfad + "." + name))
            elif feld["type"]["kind"] == "NON_NULL" and feld.get("defaultValue") is None:
                fehler.append({"pfad": pfad + "." + name, "fehler": "Pflichtfeld fehlt"})
    elif typ["kind"] == "SCALAR":
        name = typ["name"]
        korrekt = {"String": isinstance(wert, str), "ID": type(wert) in (str, int),
                   "Boolean": type(wert) is bool, "Int": type(wert) is int and -(2**31) <= wert < 2**31 if type(wert) is int else False,
                   "Float": type(wert) in (int, float)}
        if name not in korrekt:
            melden("Benutzerdefinierter Skalar lokal nicht prüfbar: " + name)
        elif not korrekt[name]:
            melden("Falscher JSON-Typ für " + name)
    else:
        melden("Typ lokal nicht prüfbar: " + str(typ.get("name") or typ["kind"]))
    return fehler


async def pruefe(client, daten):
    if client.tenant_id != TENANT or daten.get("tenant") != TENANT or daten.get("artikel_id") != ITEM:
        raise JtlFehler("Mandant oder Artikel passt nicht zum gesicherten Spirulina-Test.")
    ziel = signatur(daten["nachher"])
    html = ziel.get((INHALT, KANAL, "de"))
    if not isinstance(html, str) or ziel != signatur(zielattribute(daten["vorher"], html)):
        raise JtlFehler("Journal enthält Änderungen außerhalb der beiden vorgesehenen FAQ-Werte.")
    result = await client._lesen("/v2/graphql", {"query": schema_query()})
    if result.get("errors"):
        raise JtlFehler("Schema-Abfrage wurde von JTL abgelehnt.")
    typen = {t["name"]: t for t in ((result.get("data") or {}).get("__schema") or {}).get("types", [])}
    root = {"kind": "INPUT_OBJECT", "name": "ChangeItemCommandRequestInput"}
    fehler = validiere({"itemId": ITEM, "attributes": daten["nachher"]}, root, typen)
    def typtext(typ):
        if typ["kind"] == "NON_NULL":
            return typtext(typ["ofType"]) + "!"
        if typ["kind"] == "LIST":
            return "[" + typtext(typ["ofType"]) + "]"
        return typ["name"]
    relevante_typen = {name: {f["name"]: typtext(f["type"]) for f in definition.get("inputFields") or []}
                        for name, definition in typen.items()
                        if definition["kind"] == "INPUT_OBJECT" and (name.startswith("UpdateAttribute") or name == "UpdateItemAttributesInput")}
    return {"artikelnummer": "40047-000", "mutation_ausgefuehrt": False,
            "schema_befunde": fehler, "anzahl_befunde": len(fehler),
            "attribut_inputtypen": relevante_typen,
            "hinweis": "Prüft GraphQL-Eingabeformen, nicht JTL-Geschäftsregeln oder die Ersetzungs-/Zusammenführungssemantik."}


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--journal", default="/jtl-test/spirulina.json")
    args = parser.parse_args()
    try:
        daten = json.loads(Path(args.journal).read_text(encoding="utf-8"))
        async with JtlClient.aus_umgebung() as client:
            print(json.dumps(await pruefe(client, daten), ensure_ascii=False, indent=2))
    except (JtlFehler, OSError, ValueError, KeyError) as exc:
        print("Prüfung abgebrochen:", str(exc))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
