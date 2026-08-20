"""Importiert den vorbereiteten FAQ-Bestand für Kurkuma forte.

Vorhandene FAQ werden nicht verändert. Bereits vorhandene Fragen werden
übersprungen, fehlende Fragen freigegeben und aktiv ergänzt.

Ausführen nach dem Deployment:
    docker compose exec app python -m scripts.importiere_kurkuma_forte_faq
"""

import asyncio
import json
from pathlib import Path

from sqlalchemy import select

from app.db import SessionLocal
from app.models import FaqEintrag, Produkt


ARTIKELNUMMER = "30017"
DATEN_PFAD = (
    Path(__file__).resolve().parent.parent
    / "data"
    / "kurkuma-forte-faq.json"
)
QUELLE = "Vom Nutzer bereitgestellter FAQ-Bestand"


async def importiere(session, daten: list[dict] | None = None) -> dict:
    produkt = (await session.execute(
        select(Produkt).where(Produkt.artikelnummer == ARTIKELNUMMER)
    )).scalar_one_or_none()
    if produkt is None:
        raise RuntimeError(
            "Produkt mit Artikelnummer 30017 nicht gefunden. Bitte zuerst "
            "in Krautl unter Wissensdatenbank 'Shop-Produkte aktualisieren' "
            "ausführen."
        )

    vorhandene_fragen = set((await session.execute(
        select(FaqEintrag.frage).where(FaqEintrag.produkt_id == produkt.id)
    )).scalars().all())
    daten = daten if daten is not None else json.loads(
        DATEN_PFAD.read_text(encoding="utf-8")
    )

    angelegt = 0
    uebersprungen = 0
    for eintrag in daten:
        if eintrag["frage"] in vorhandene_fragen:
            uebersprungen += 1
            continue
        session.add(FaqEintrag(
            produkt_id=produkt.id,
            kategorie=eintrag["gruppe"],
            frage=eintrag["frage"],
            antwort=eintrag["antwort"],
            quelle=QUELLE,
            status="freigegeben",
            sortierung=eintrag["sortierung"],
            aktiv=True,
        ))
        vorhandene_fragen.add(eintrag["frage"])
        angelegt += 1

    await session.commit()
    return {
        "produkt": produkt.name,
        "angelegt": angelegt,
        "uebersprungen": uebersprungen,
    }


async def main() -> None:
    async with SessionLocal() as session:
        ergebnis = await importiere(session)
    print(
        f"{ergebnis['angelegt']} aktive FAQ für {ergebnis['produkt']} "
        f"angelegt, {ergebnis['uebersprungen']} bereits vorhandene Fragen "
        "übersprungen."
    )


if __name__ == "__main__":
    asyncio.run(main())
