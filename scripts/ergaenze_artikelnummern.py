"""Ergänzt nur fehlende Artikelnummern anhand eindeutiger Shop-SKU-Angaben."""
import argparse
import asyncio
import json

from sqlalchemy import select, update, or_
from app.db import SessionLocal, engine
from app.models import Produkt
from app.shop_import import artikelnummer_nachladen


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--anwenden", action="store_true", help="Geprüfte Ergänzungen speichern")
    args = parser.parse_args()
    async with SessionLocal() as session:
        produkte = (await session.execute(select(Produkt).order_by(Produkt.id))).scalars().all()
        belegt = {p.artikelnummer for p in produkte if p.artikelnummer}
        plan = []
        offen = []
        for p in produkte:
            if p.artikelnummer:
                continue
            try:
                nummer = await asyncio.to_thread(artikelnummer_nachladen, p.website_url or "")
            except Exception:
                offen.append({"id": p.id, "grund": "Produktseite nicht lesbar"})
                continue
            if not nummer or nummer in belegt:
                offen.append({"id": p.id, "grund": "Keine eindeutige, freie Artikelnummer"})
                continue
            belegt.add(nummer)
            plan.append({"id": p.id, "name": p.name, "artikelnummer": nummer})
        gespeichert = 0
        if args.anwenden:
            for p in plan:
                ergebnis = await session.execute(update(Produkt).where(
                    Produkt.id == p["id"], or_(Produkt.artikelnummer.is_(None), Produkt.artikelnummer == "")
                ).values(artikelnummer=p["artikelnummer"]))
                gespeichert += ergebnis.rowcount
            await session.commit()
        print(json.dumps({"ergaenzungen": plan, "gespeichert": gespeichert, "offen": offen}, ensure_ascii=False, indent=2))
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
