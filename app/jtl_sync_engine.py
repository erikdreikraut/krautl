"""Durable change-only FAQ synchronization; no blind retries after PATCH."""
import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4

from .jtl_client import JtlFehler
from .jtl_faq_test import signatur, zielattribute


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":")).encode("utf-8")).hexdigest()


class Speicher:
    def __init__(self, folder):
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        self.path = self.folder / "stand.json"
        self.state = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {
            "version": 1, "quelle": None, "ziele": {}}
        if self.state.get("version") != 1:
            raise JtlFehler("Unbekannte JTL-Abgleichzustandsversion.")

    def speichern(self):
        tmp = self.path.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(self.state, f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.path)

    def sichern(self, daten):
        name = "versuch-" + uuid4().hex + ".json"
        with (self.folder / name).open("x", encoding="utf-8") as f:
            json.dump(daten, f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        return name


def zielplan(quellen, katalog):
    """Own selected FAQ wins over parent FAQ; only actual parent IDs propagate."""
    by_sku = {}
    for item in katalog:
        by_sku.setdefault(item["sku"], []).append(item)
    eigene = {}
    for sku, html in quellen.items():
        if not html:
            continue
        treffer = by_sku.get(sku, [])
        if len(treffer) != 1:
            raise JtlFehler(f"JTL-SKU {sku}: nicht eindeutig gefunden; kein Schreiblauf.")
        eigene[treffer[0]["id"]] = html
    result = {}
    for item in katalog:
        html = eigene.get(item["id"], eigene.get(item["parent"]))
        if html is not None:
            if not item["sku"]:
                raise JtlFehler("Zielartikel ohne Artikelnummer.")
            result[item["id"]] = {"sku": item["sku"], "html": html}
    return result


# Only the two concrete empty-value shapes observed in this installation.
# Never normalize all empty attributes, FAQ values, whitespace or null values.
LEERES_ALTATTRIBUT = "29708817-225b-4208-9a57-5ff5f0000000"
LEERER_KANALWERT = ("29708817-225b-4208-9a57-5ff59a000000", "1-1-0", "de")


def bekannte_leerwertabweichungen(vorher, erwartet, aktuell):
    alt, soll, ist = map(signatur, (vorher, erwartet, aktuell))
    erlaubt = set()
    leer = {(LEERES_ALTATTRIBUT,): True, (LEERES_ALTATTRIBUT, None, None): ""}
    if (all({k: v for k, v in stand.items() if k[0] == LEERES_ALTATTRIBUT} == leer
            for stand in (alt, soll))
            and not any(k[0] == LEERES_ALTATTRIBUT for k in ist)):
        erlaubt.update(leer)
    if (LEERER_KANALWERT in alt and alt[LEERER_KANALWERT] == ""
            and LEERER_KANALWERT in soll and soll[LEERER_KANALWERT] == ""
            and LEERER_KANALWERT not in ist):
        erlaubt.add(LEERER_KANALWERT)
    abweichungen = {k for k in set(soll) | set(ist)
                   if k not in soll or k not in ist or soll[k] != ist[k]}
    if not abweichungen or not abweichungen <= erlaubt:
        return []
    return sorted(abweichungen, key=str)


def ruecklesestand_bestaetigen(speicher, ident, ziel, journal, ist):
    revision = digest({"sku": ziel["sku"], "html": ziel["html"]})
    if (journal.get("id") != ident or journal.get("sku") != ziel["sku"]
            or journal.get("revision") != revision
            or signatur(journal["nachher"]) != signatur(zielattribute(journal["vorher"], ziel["html"]))):
        raise JtlFehler("Journal passt nicht zum offenen FAQ-Auftrag; keine Freigabe.")
    if signatur(ist) == signatur(journal["nachher"]):
        return
    abweichungen = bekannte_leerwertabweichungen(journal["vorher"], journal["nachher"], ist)
    if not abweichungen:
        raise JtlFehler("Unklarer Schreibversuch; Journal manuell prüfen, keine Wiederholung.")
    # Durable audit precedes clearing the pending flag. No API write or replay.
    ziel["leerwert_nachweis"] = speicher.sichern({
        "art": "bekannte_leerwertabweichung", "regelversion": 1,
        "ursprungsjournal": ziel["offen"], "id": ident, "sku": ziel["sku"],
        "revision": revision, "abweichungen": abweichungen, "lesestand": ist,
    })


async def abgleichen(client, speicher, quellen):
    state = speicher.state
    bericht = {"geschrieben": 0, "bereits_gleich": 0, "fehler": []}
    # Recover a crash/timeout by readback, never by resending the request.
    for ident, ziel in state["ziele"].items():
        if ziel.get("offen"):
            try:
                journal = json.loads((speicher.folder / ziel["offen"]).read_text(encoding="utf-8"))
                ist = await client.lesen(ident, ziel["sku"])
                ruecklesestand_bestaetigen(speicher, ident, ziel, journal, ist)
                ziel["erledigt"] = journal["revision"]
                ziel["offen"] = None
                speicher.speichern()
            except JtlFehler as exc:
                bericht["fehler"].append(f"{ziel['sku']}: {exc}")
    # Do not replace plans while unresolved writes exist.
    if bericht["fehler"]:
        return bericht
    revision = digest(quellen)
    if state["quelle"] != revision:
        katalog = await client.katalog() if any(quellen.values()) else []
        plan = zielplan(quellen, katalog)
        for ident, alt in state["ziele"].items():
            if ident not in plan:
                plan[ident] = {"sku": alt["sku"], "html": ""}
        for ident, ziel in plan.items():
            alt = state["ziele"].get(ident, {})
            ziel["erledigt"] = alt.get("erledigt")
        state["ziele"], state["quelle"] = plan, revision
        speicher.speichern()
    for ident, ziel in state["ziele"].items():
        revision = digest({"sku": ziel["sku"], "html": ziel["html"]})
        if ziel.get("erledigt") == revision:
            continue
        try:
            vorher = await client.lesen(ident, ziel["sku"])
            nachher = zielattribute(vorher, ziel["html"])
            if signatur(vorher) == signatur(nachher):
                ziel["erledigt"] = revision
                speicher.speichern()
                bericht["bereits_gleich"] += 1
                continue
            if signatur(await client.lesen(ident, ziel["sku"])) != signatur(vorher):
                raise JtlFehler("Attribute inzwischen verändert; nächster Lauf prüft neu.")
            ziel["offen"] = speicher.sichern({"id": ident, "sku": ziel["sku"],
                "revision": revision, "vorher": vorher, "nachher": nachher})
            speicher.speichern()
            # Only the two German shop values, never echo unrelated neutral values.
            await client.schreiben(ident, zielattribute({"values": []}, ziel["html"]))
            ist = await client.lesen(ident, ziel["sku"])
            journal = json.loads((speicher.folder / ziel["offen"]).read_text(encoding="utf-8"))
            ruecklesestand_bestaetigen(speicher, ident, ziel, journal, ist)
            ziel["erledigt"], ziel["offen"] = revision, None
            speicher.speichern()
            bericht["geschrieben"] += 1
        except JtlFehler as exc:
            bericht["fehler"].append(f"{ziel['sku']}: {exc}")
            if ziel.get("offen"):
                # A preservation failure must not risk the remaining catalog.
                break
    return bericht
