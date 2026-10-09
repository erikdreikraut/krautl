"""Einmalige, ausdrücklich genehmigte Annahme des fehlenden leeren Attributs."""
import argparse
import asyncio
import json
import os
from datetime import datetime, timezone

from app.jtl_client import JtlFehler
from app.jtl_faq_test import signatur, zielattribute
from app.jtl_onprem import OnPremClient
from app.jtl_sync_engine import Speicher, digest

ITEM = "770f139d-18dd-405c-9f84-3221c0010000"
ATTR = "29708817-225b-4208-9a57-5ff5f0000000"
JOURNAL = "versuch-72a7f960fc4542cab7aa0709804ddde0.json"


async def freigeben(client, speicher, anwenden=False):
    ziel = speicher.state["ziele"].get(ITEM)
    if (not ziel or ziel.get("sku") != "20015" or ziel.get("offen") != JOURNAL
            or speicher.state.get("api_url") != client.url):
        raise JtlFehler("Nicht der freigegebene offene Vorgang; nichts geändert.")
    journal = json.loads((speicher.folder / JOURNAL).read_text(encoding="utf-8"))
    revision = digest({"sku": "20015", "html": ziel["html"]})
    if journal.get("id") != ITEM or journal.get("sku") != "20015" or journal.get("revision") != revision:
        raise JtlFehler("Journal und Auftrag stimmen nicht überein.")
    vorher, erwartet = signatur(journal["vorher"]), signatur(journal["nachher"])
    ausnahme = {(ATTR,): True, (ATTR, None, None): ""}
    for werte in (vorher, erwartet):
        if {k: v for k, v in werte.items() if k[0] == ATTR} != ausnahme:
            raise JtlFehler("Das betroffene Attribut war nicht ausschließlich leer.")
    if erwartet != signatur(zielattribute(journal["vorher"], ziel["html"])):
        raise JtlFehler("Gesicherter Zielstand passt nicht zum FAQ-Auftrag.")
    akzeptiert = {k: v for k, v in erwartet.items() if k[0] != ATTR}
    aktuell = await client.lesen(ITEM, "20015")
    if signatur(aktuell) != akzeptiert:
        raise JtlFehler("Aktueller Artikel zeigt andere Abweichungen; nichts freigegeben.")
    if not anwenden:
        return {"sku": "20015", "freigabe_moeglich": True, "angewendet": False}
    audit = speicher.sichern({"art": "manuelle_einmalfreigabe_20015",
        "zeit": datetime.now(timezone.utc).isoformat(), "ursprungsjournal": JOURNAL,
        "genehmigte_abweichung": "Fehlende leere Attributzuordnung " + ATTR,
        "akzeptierter_lesestand": aktuell, "revision": revision})
    ziel["erledigt"] = revision
    ziel["offen"] = None
    ziel["manuelle_freigabe"] = audit
    speicher.speichern()
    return {"sku": "20015", "angewendet": True, "audit": audit, "wawi_schreibzugriffe": 0}


async def main():
    import fcntl
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--anwenden", action="store_true")
    args = parser.parse_args()
    folder = os.getenv("JTL_SYNC_DIR", "/app/var/jtl-sync")
    speicher = Speicher(folder)
    with (speicher.folder / "worker.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise JtlFehler("Abgleich zuerst stoppen.") from None
        speicher = Speicher(folder)
        async with OnPremClient.aus_umgebung() as client:
            print(json.dumps(await freigeben(client, speicher, args.anwenden), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except JtlFehler as exc:
        raise SystemExit(str(exc))
