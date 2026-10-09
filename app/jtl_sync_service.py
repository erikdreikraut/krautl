"""Dedicated five-minute worker; enabled separately from mail/WhatsApp."""
import argparse
import asyncio
import json
import logging
import os
from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy import select

from .db import SessionLocal
from .jtl_client import JtlFehler
from .jtl_faq_test import signatur, zielattribute
from .jtl_onprem import OnPremClient
from .jtl_sync_engine import Speicher, abgleichen, zielplan
from .models import FaqEintrag, Produkt
from .wissensbasis import faq_als_jtl_html

INTERVALL = 300
logger = logging.getLogger("krautl.jtl_sync")


def quellen_bauen(produkte, faq):
    gruppen = defaultdict(list)
    for f in faq:
        if f.aktiv and f.status == "freigegeben":
            gruppen[f.produkt_id].append(f)
    result = {}
    for p in produkte:
        if not gruppen[p.id]:
            continue
        sku = (p.artikelnummer or "").strip()
        if not sku or sku in result:
            raise JtlFehler("FAQ-Produkt ohne eindeutige Artikelnummer; Zuordnung korrigieren.")
        result[sku] = faq_als_jtl_html(p, gruppen[p.id])
    return result


async def quellen_laden():
    async with SessionLocal() as session:
        # One database snapshot joins products and eligible FAQ in a single query.
        rows = (await session.execute(select(Produkt, FaqEintrag).join(
            FaqEintrag, FaqEintrag.produkt_id == Produkt.id).where(
            FaqEintrag.aktiv.is_(True), FaqEintrag.status == "freigegeben"))).all()
        produkte = {p.id: p for p, _ in rows}
        return quellen_bauen(produkte.values(), [f for _, f in rows])


async def vorschau(client, speicher, quellen):
    plan = zielplan(quellen, await client.katalog())
    for ident, alt in speicher.state["ziele"].items():
        plan.setdefault(ident, {"sku": alt["sku"], "html": ""})
    result = []
    for ident, ziel in plan.items():
        vorher = await client.lesen(ident, ziel["sku"])
        result.append({"sku": ziel["sku"], "artikel_id": ident,
            "html_zeichen": len(ziel["html"]),
            "aenderung_noetig": signatur(vorher) != signatur(zielattribute(vorher, ziel["html"])),
            "unklarer_versuch": bool(speicher.state["ziele"].get(ident, {}).get("offen"))})
    return result


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vorschau", action="store_true", help="Nur lesen; keine Artikel oder Abgleichstände ändern")
    args = parser.parse_args()
    if not args.vorschau and os.getenv("JTL_SYNC_ENABLED", "false").lower() != "true":
        raise JtlFehler("JTL_SYNC_ENABLED ist nicht true. Abgleich bleibt ausgeschaltet.")
    # Linux deployment: also protects against a second container/manual run.
    import fcntl
    speicher = Speicher(os.getenv("JTL_SYNC_DIR", "/app/var/jtl-sync"))
    with (speicher.folder / "worker.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise JtlFehler("Ein JTL-Abgleich läuft bereits.") from None
        # Reload only after obtaining the cross-process lock.
        speicher = Speicher(speicher.folder)
        async with OnPremClient.aus_umgebung() as client:
            if speicher.state.get("api_url", client.url) != client.url:
                raise JtlFehler("API-Ziel geändert; gespeicherte Zuordnung zuerst prüfen.")
            if args.vorschau:
                print(json.dumps(await vorschau(client, speicher, await quellen_laden()), ensure_ascii=False, indent=2))
                return
            speicher.state["api_url"] = client.url
            speicher.speichern()
            while True:
                try:
                    result = await abgleichen(client, speicher, await quellen_laden())
                    speicher.state["status"] = {"zeit": datetime.now(timezone.utc).isoformat(), **result}
                    speicher.speichern()
                    logger.info("FAQ-Abgleich: %s", json.dumps(result, ensure_ascii=False))
                except Exception as exc:
                    # Do not log request objects, headers, SQL or credentials.
                    detail = str(exc) if isinstance(exc, JtlFehler) else "Technischer Fehler: " + type(exc).__name__
                    speicher.state["status"] = {"zeit": datetime.now(timezone.utc).isoformat(), "fehler": [detail]}
                    speicher.speichern()
                    logger.error("FAQ-Abgleich: %s", detail)
                # No catch-up bursts after slow runs. No two runs overlap.
                await asyncio.sleep(INTERVALL)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    try:
        asyncio.run(main())
    except JtlFehler as exc:
        raise SystemExit(str(exc))
