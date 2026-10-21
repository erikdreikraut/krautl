"""Daily read-only Wawi invoice import, separate from the FAQ writer."""
import argparse
import asyncio
import logging
from datetime import datetime, timedelta
from .inkasso import INTERVALL, abrufen, auswahl_abrufen, jetzt, lesen, ordner, speichern
from .jtl_client import JtlFehler
from .inkasso_zugang import client_aus_umgebung

logger = logging.getLogger("krautl.inkasso")


def faellig(data, zeit):
    letzter = data.get("letzter_versuch")
    return not letzter or not timedelta(0) <= zeit - datetime.fromisoformat(letzter) < INTERVALL


async def lauf(folder=None, client_factory=client_aus_umgebung):
    data = lesen(folder)
    data.update(letzter_versuch=jetzt().isoformat(), status="laeuft", fehler=None)
    speichern(data, folder)
    try:
        async with client_factory() as client:
            result = await asyncio.wait_for(abrufen(client, data), timeout=3600)
        data.update(result)
        data.update(letzter_erfolg=jetzt().isoformat(), status="ok", fehler=None)
        logger.info("Inkasso: %s offene Rechnungen (JTL-Shop/JTL-Wawi); %s Rechnungen geprüft.",
                    len(result["rechnungen"]), result["geprueft"])
    except Exception as exc:
        detail = str(exc) if isinstance(exc, JtlFehler) else "Technischer Abruffehler: " + type(exc).__name__
        data.update(status="fehler", fehler=detail)
        logger.error("Inkasso: %s", detail)
    speichern(data, folder)
    return data["status"] == "ok"


async def auswahl_lauf(folder=None, client_factory=client_aus_umgebung):
    from . import inkasso_auftrag as auftrag
    with auftrag.sperre(warten=True):
        job = auftrag.lesen()
        if not job or job["status"] not in ("wartet", "laeuft"):
            return False
        job.update(status="laeuft", gestartet_am=jetzt().isoformat())
        auftrag.speichern(job)
    try:
        async with client_factory() as client:
            data = await asyncio.wait_for(auswahl_abrufen(client, lesen(folder), job["ids"]), timeout=900)
        speichern(data, folder)
        job.update(status="ok", abgeschlossen_am=jetzt().isoformat(), fehler=None)
        logger.info("Inkasso: %s ausgewählte Rechnungen aktualisiert.", job["anzahl"])
    except Exception as exc:
        detail = str(exc) if isinstance(exc, JtlFehler) else "Technischer Abruffehler: " + type(exc).__name__
        job.update(status="fehler", abgeschlossen_am=jetzt().isoformat(), fehler=detail)
        logger.error("Inkasso-Auswahl: %s", detail)
    with auftrag.sperre(warten=True):
        auftrag.speichern(job)
    return True


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--einmal", action="store_true", help="Einmal lesen und Snapshot aktualisieren")
    args = parser.parse_args()
    import fcntl
    path = ordner()
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (path / "worker.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit("Ein Inkasso-Abruf läuft bereits.") from None
        if args.einmal:
            raise SystemExit(0 if await lauf(path) else 1)
        while True:
            if await auswahl_lauf(path):
                await asyncio.sleep(5)
                continue
            if faellig(lesen(path), jetzt()):
                await lauf(path)
            await asyncio.sleep(5)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    asyncio.run(main())
