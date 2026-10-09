"""Small, credential-free status snapshot for UI and container healthcheck."""
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .jtl_sync_engine import digest

MAX_ALTER = 900


def status_speichern(speicher, ergebnis, jetzt=None):
    jetzt = jetzt or datetime.now(timezone.utc)
    zeit = jetzt.isoformat()
    state = speicher.state
    offen = sum(z.get("erledigt") != digest({"sku": z["sku"], "html": z["html"]})
                for z in state["ziele"].values())
    gesperrt = sum(bool(z.get("offen")) for z in state["ziele"].values())
    if not ergebnis.get("fehler") and not offen and not gesperrt:
        state["letzter_erfolg"] = zeit
    state["status"] = {"zeit": zeit, **ergebnis}
    speicher.speichern()
    daten = {"letzter_lauf": zeit, "letzter_erfolg": state.get("letzter_erfolg"),
             "offene_artikel": offen,
             "gesperrte_artikel": gesperrt,
             "fehler": ergebnis.get("fehler", []),
             "geschrieben": ergebnis.get("geschrieben", 0)}
    pfad = speicher.folder / "status.json"
    tmp = pfad.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(daten, f, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, pfad)


def status_laden(folder=None, *, aktiviert=None, jetzt=None):
    if aktiviert is None:
        aktiviert = os.getenv("JTL_SYNC_ENABLED", "false").lower() == "true"
    if not aktiviert:
        return {"status": "deaktiviert", "gesund": False,
                "detail": "JTL-Abgleich ist ausgeschaltet."}
    pfad = Path(folder or os.getenv("JTL_SYNC_DIR", "/app/var/jtl-sync")) / "status.json"
    try:
        daten = json.loads(pfad.read_text(encoding="utf-8"))
        zeit = datetime.fromisoformat(daten["letzter_lauf"])
        if zeit.tzinfo is None:
            raise ValueError("Zeit ohne Zeitzone")
        alter = ((jetzt or datetime.now(timezone.utc)) - zeit).total_seconds()
        if not isinstance(daten["fehler"], list):
            raise ValueError("Ungültiger Fehlerstatus")
        for key in ("offene_artikel", "gesperrte_artikel"):
            if not isinstance(daten[key], int) or daten[key] < 0:
                raise ValueError("Ungültige Artikelanzahl")
    except (OSError, ValueError, KeyError, TypeError):
        return {"status": "unbekannt", "gesund": False,
                "detail": "Noch kein lesbarer JTL-Prüflauf vorhanden."}
    if alter < -60 or alter >= MAX_ALTER:
        status, detail = "ausgeblieben", "Kein aktueller abgeschlossener Prüflauf. Dienst und Serverzeit prüfen."
    elif daten["gesperrte_artikel"]:
        status, detail = "gesperrt", "Schreibabgleich gesperrt; ein unklarer Vorgang muss geprüft werden."
    elif daten["fehler"]:
        status, detail = "fehler", "Der letzte Prüflauf meldet Fehler."
    elif daten["offene_artikel"]:
        status, detail = "offen", "Es stehen noch Artikel aus dem letzten Prüflauf aus."
    else:
        status, detail = "ok", "Letzter Prüflauf erfolgreich."
    return {**daten, "status": status, "detail": detail, "gesund": status == "ok"}


if __name__ == "__main__":
    status = status_laden()
    print(status["detail"])
    raise SystemExit(0 if status["gesund"] else 1)
