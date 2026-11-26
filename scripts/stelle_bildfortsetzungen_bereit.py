"""Queue selected, already uploaded replacements for the updated Windows worker."""
import argparse
import asyncio
import json
from uuid import UUID

from app import bilder_speicher as store
from app.bilder_abgleich import SHOP
from app.bilder_ersetzen import _originaldatei, liste, zuordnungen
from app.bilder_upload import auftraege, detail_lesen, lokal
from app.jtl_onprem import OnPremClient


async def vorbereiten(client, job, datei):
    if (job.get("status") != "unklar" or job.get("art") != "ersetzen_alle"
            or job.get("operation") not in (None, "ersetzen") or not job.get("bruecke")
            or not job.get("bruecke_worker") or job.get("bruecke_lieferungen") != 1
            or job.get("ruecksetzung") or job.get("bruecke_bestaetigt")
            or job.get("bruecke_fortsetzen") or job["api_ziel"] != client.url or not datei):
        raise ValueError("Kein vorbereitbarer Austauschauftrag.")
    lokal(job["artikel"], job["revision"])
    await detail_lesen(client, job["artikel"], job["sku"])
    vorher = job["v1_vorher"]
    aktuell = zuordnungen(await liste(client, job["artikel"]))
    zusatz = [r for r in aktuell if r not in vorher]
    bisherige_ids = {r[1] for r in vorher}
    erlaubte_kanaele = {SHOP, "1-1-1"}
    if (
        any(r not in aktuell for r in vorher) or len({r[1] for r in zusatz}) != 1
        or len({r[2] for r in zusatz}) != len(zusatz)
        or not any(r[2] == SHOP for r in zusatz)
        or any(r[1] in bisherige_ids or r[2] not in erlaubte_kanaele or r[3]
               or r[4] != 1 + max((alt[4] for alt in vorher if alt[2] == r[2]), default=0)
               for r in zusatz)
    ):
        raise ValueError("Wawi-Zuordnungen passen nicht zur gespeicherten Importphase.")
    if await _originaldatei(client, zusatz[0][1]) != datei:
        raise ValueError("Vorhandenes Zusatzbild stimmt nicht bytegleich mit der Auftragsdatei überein.")
    if zuordnungen(await liste(client, job["artikel"])) != aktuell:
        raise ValueError("Wawi-Bildbestand während der Prüfung geändert.")


async def ausfuehren(ids):
    with store.Laufsperre():
        jobs = {j["id"]: j for j in auftraege()}
        auftraege_zur_fortsetzung = []
        async with OnPremClient.aus_umgebung() as client:
            for ident in ids:
                job = jobs[ident]
                with store.datenbank() as db:
                    datei = db.execute("SELECT datei FROM bildauftraege WHERE id=?", (ident,)).fetchone()[0]
                await vorbereiten(client, job, datei)
                auftraege_zur_fortsetzung.append(job)
        with store.datenbank() as db:
            db.execute("BEGIN IMMEDIATE")
            for job in auftraege_zur_fortsetzung:
                row = db.execute("SELECT daten FROM bildauftraege WHERE id=?", (job["id"],)).fetchone()
                artikel = db.execute("SELECT ausgeblendet,revision FROM artikel WHERE id=?",
                                     (job["artikel"],)).fetchone()
                if json.loads(row[0]) != job or artikel != (0, job["revision"]):
                    raise ValueError("Auftrag oder Artikel während der Prüfung verändert.")
                job["bruecke_fortsetzen"] = {"geplant": store.jetzt()}
                job["meldung"] = "Vorhandener Upload geprüft. Fortsetzung durch den aktualisierten Bilddienst vorgemerkt."
                db.execute("UPDATE bildauftraege SET daten=? WHERE id=?", (json.dumps(job), job["id"]))
        for job in auftraege_zur_fortsetzung:
            print(f'{job["sku"]}: Fortsetzung vorgemerkt.')


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("auftraege", nargs="+", type=UUID)
    args = parser.parse_args()
    asyncio.run(ausfuehren(list(dict.fromkeys(map(str, args.auftraege)))))
