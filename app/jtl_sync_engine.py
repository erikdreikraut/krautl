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


async def abgleichen(client, speicher, quellen):
    state = speicher.state
    bericht = {"geschrieben": 0, "bereits_gleich": 0, "fehler": []}
    # Recover a crash/timeout by readback, never by resending the request.
    for ident, ziel in state["ziele"].items():
        if ziel.get("offen"):
            try:
                journal = json.loads((speicher.folder / ziel["offen"]).read_text(encoding="utf-8"))
                ist = await client.lesen(ident, ziel["sku"])
                if signatur(ist) != signatur(journal["nachher"]):
                    raise JtlFehler("Unklarer Schreibversuch; Journal manuell prüfen, keine Wiederholung.")
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
            if signatur(ist) != signatur(nachher):
                raise JtlFehler("Rückleseprüfung fehlgeschlagen; Journal prüfen, keine Wiederholung.")
            ziel["erledigt"], ziel["offen"] = revision, None
            speicher.speichern()
            bericht["geschrieben"] += 1
        except JtlFehler as exc:
            bericht["fehler"].append(f"{ziel['sku']}: {exc}")
            if ziel.get("offen"):
                # A preservation failure must not risk the remaining catalog.
                break
    return bericht
