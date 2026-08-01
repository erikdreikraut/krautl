"""Legt die redaktionelle Wissensbasis an und erweitert bestehende FAQ."""
import asyncio
import json
from pathlib import Path

from sqlalchemy import inspect, select, text

from app.db import SessionLocal, engine
from app.models import Base, FaqEintrag, Produkt, Produktfamilie, Wissenseintrag


FALLWISSEN_PFAD = Path(__file__).resolve().parent.parent / "data" / "fallwissen.md"
AUFTRAGSNUMMERN_PFAD = (
    Path(__file__).resolve().parent.parent / "data" / "auftragsnummern-vertriebskanaele.md"
)
HAGEBUTTEN_FAQ_PFAD = Path(__file__).resolve().parent.parent / "data" / "hagebutten-faq.json"
HAGEBUTTEN_URL = "https://dreikraut.de/Bio-Hagebuttenpulver-aus-EU-Wildsammlung"


FAQ_SPALTEN = {
    "produkt_id": "INTEGER REFERENCES produkt(id)",
    "quelle": "TEXT",
    "status": "VARCHAR(20) NOT NULL DEFAULT 'freigegeben'",
    "sortierung": "INTEGER NOT NULL DEFAULT 0",
}


async def migriere() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

        def faq_spalten(sync_conn):
            if "faq_eintrag" not in inspect(sync_conn).get_table_names():
                return set(FAQ_SPALTEN)
            return {spalte["name"] for spalte in inspect(sync_conn).get_columns("faq_eintrag")}

        vorhanden = await conn.run_sync(faq_spalten)
        for name, typ in FAQ_SPALTEN.items():
            if name not in vorhanden:
                await conn.execute(text(
                    f'ALTER TABLE "faq_eintrag" ADD COLUMN "{name}" {typ}'
                ))
        await conn.execute(text(
            'CREATE INDEX IF NOT EXISTS "ix_faq_eintrag_produkt_id" '
            'ON "faq_eintrag" ("produkt_id")'
        ))

    async with SessionLocal() as session:
        familie = (await session.execute(
            select(Produktfamilie).where(Produktfamilie.name == "Hagebutte")
        )).scalar_one_or_none()
        if familie is None:
            familie = Produktfamilie(name="Hagebutte", aktiv=True)
            session.add(familie)
            await session.flush()
        produkt = (await session.execute(
            select(Produkt).where(Produkt.artikelnummer == "20810")
        )).scalar_one_or_none()
        if produkt is None:
            produkt = Produkt(
                produktfamilie_id=familie.id,
                name="Bio-Hagebuttenpulver aus EU-Wildsammlung",
                artikelnummer="20810",
                aliases=["Hagebuttenpulver", "Bio-Hagebuttenpulver", "Hagebutte"],
                website_url="https://dreikraut.de/Bio-Hagebuttenpulver-aus-EU-Wildsammlung",
                aktiv=True,
            )
            session.add(produkt)
            await session.flush()
        fallwissen = (await session.execute(
            select(Wissenseintrag).where(
                Wissenseintrag.quelle == "data/fallwissen.md"
            )
        )).scalar_one_or_none()
        if fallwissen is None and FALLWISSEN_PFAD.exists():
            session.add(Wissenseintrag(
                wissensart="ablauf",
                titel="Amazon-Rezension und angebotene Gratispackung",
                inhalt=FALLWISSEN_PFAD.read_text(encoding="utf-8"),
                quelle="data/fallwissen.md",
                status="freigegeben",
                schlagwoerter=["Amazon", "Rezension", "Gratispackung"],
            ))
        auftragsnummern = (await session.execute(
            select(Wissenseintrag).where(
                Wissenseintrag.quelle == "data/auftragsnummern-vertriebskanaele.md"
            )
        )).scalar_one_or_none()
        if auftragsnummern is None and AUFTRAGSNUMMERN_PFAD.exists():
            session.add(Wissenseintrag(
                wissensart="ablauf",
                titel="Vertriebskanal aus Bestell- und Auftragsnummern erkennen",
                inhalt=AUFTRAGSNUMMERN_PFAD.read_text(encoding="utf-8"),
                quelle="data/auftragsnummern-vertriebskanaele.md",
                stand="2026-08-01",
                status="freigegeben",
                schlagwoerter=[
                    "Auftragsnummer", "Bestellnummer", "JTL", "Amazon",
                    "Temu", "Shop Apotheke", "Vertriebskanal",
                ],
            ))
        if HAGEBUTTEN_FAQ_PFAD.exists():
            vorhandene_fragen = {
                eintrag.frage
                for eintrag in (await session.execute(
                    select(FaqEintrag).where(FaqEintrag.produkt_id == produkt.id)
                )).scalars().all()
            }
            for daten in json.loads(HAGEBUTTEN_FAQ_PFAD.read_text(encoding="utf-8")):
                if daten["frage"] in vorhandene_fragen:
                    continue
                session.add(FaqEintrag(
                    produkt_id=produkt.id,
                    kategorie=daten["gruppe"],
                    frage=daten["frage"],
                    antwort=daten["antwort"],
                    quelle=HAGEBUTTEN_URL,
                    status="freigegeben",
                    sortierung=daten["sortierung"],
                    aktiv=True,
                ))
        await session.commit()
    print("Wissensbasis-Migration abgeschlossen.")


if __name__ == "__main__":
    asyncio.run(migriere())
