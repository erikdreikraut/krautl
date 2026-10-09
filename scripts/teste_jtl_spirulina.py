"""Einmalige FAQ-Schreibabnahme für 40047-000. Standard: nur Vorschau."""
import argparse
import asyncio
import json
import sys

from app.jtl_client import JtlClient, JtlFehler
from app.jtl_faq_test import SKU, pruefen, uebertragen, diagnose403


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modus = parser.add_mutually_exclusive_group()
    modus.add_argument("--anwenden", action="store_true")
    modus.add_argument("--pruefen", action="store_true")
    modus.add_argument("--graphql", action="store_true", help="Gesicherten Auftrag einmalig über die bestätigte ChangeItem-Mutation übertragen")
    modus.add_argument("--diagnose-403", action="store_true", help="Einmaliger kontrollierter Wiederholungsversuch mit Originalauftrag und Originalschlüssel")
    parser.add_argument("--journal", default="/jtl-test/spirulina.json")
    args = parser.parse_args()
    try:
        async with JtlClient.aus_umgebung() as client:
            if args.pruefen:
                print(await pruefen(client, args.journal))
                return 0
            from sqlalchemy import select
            from app.db import SessionLocal, engine
            from app.models import Produkt, FaqEintrag
            from app.wissensbasis import faq_als_jtl_html
            try:
                async with SessionLocal() as session:
                    produkte = (await session.execute(select(Produkt).where(Produkt.artikelnummer == SKU))).scalars().all()
                    if len(produkte) != 1:
                        raise JtlFehler("Spirulina in Krautl nicht eindeutig gefunden.")
                    produkt = produkte[0]
                    faq = (await session.execute(select(FaqEintrag).where(
                        FaqEintrag.produkt_id == produkt.id, FaqEintrag.aktiv.is_(True),
                        FaqEintrag.status == "freigegeben"))).scalars().all()
                    # Die erste Schreibabnahme muss tatsächliche FAQ übertragen.
                    if not faq:
                        raise JtlFehler("Keine ausgewählten FAQ vorhanden; dieser Ersttest löscht keine Wawi-Werte.")
                    html = faq_als_jtl_html(produkt, faq)
                bericht = (await diagnose403(client, html, args.journal, graphql=args.graphql) if args.diagnose_403 or args.graphql
                           else await uebertragen(client, html, args.journal, args.anwenden))
                bericht["faq_anzahl"] = len(faq)
                print(json.dumps(bericht, ensure_ascii=False, indent=2))
            finally:
                await engine.dispose()
    except (JtlFehler, OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
