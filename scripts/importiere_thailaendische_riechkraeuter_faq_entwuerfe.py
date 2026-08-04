"""Importiert einmalig FAQ-Entwürfe für thailändische Riechkräuter.

Der Import verändert keine vorhandenen FAQ. Sobald für das Produkt auch nur
ein Eintrag existiert, wird der gesamte Lauf ohne Schreibzugriff übersprungen.

Ausführen nach dem Deployment:
    docker compose exec app python -m scripts.importiere_thailaendische_riechkraeuter_faq_entwuerfe
"""

import asyncio
import json
from pathlib import Path

from sqlalchemy import func, or_, select

from app.db import SessionLocal
from app.models import FaqEintrag, Produkt


ARTIKELNUMMER = "20015"
PRODUKT_URL = "https://dreikraut.de/Thailaendische-Riechkraeuter-in-der-Dose_1"
DATEN_PFAD = (
    Path(__file__).resolve().parent.parent
    / "data"
    / "thailaendische-riechkraeuter-faq-entwuerfe.json"
)


async def importiere(session, daten: list[dict] | None = None) -> dict:
    produkt = (await session.execute(
        select(Produkt).where(or_(
            Produkt.artikelnummer == ARTIKELNUMMER,
            func.lower(Produkt.website_url) == PRODUKT_URL.lower(),
        ))
    )).scalar_one_or_none()
    if produkt is None:
        raise RuntimeError(
            "Produkt 'Thailändische Riechkräuter dreikraut im Glas' nicht "
            "gefunden. Bitte zuerst in Krautl unter Wissensdatenbank "
            "'Shop-Produkte aktualisieren' ausführen."
        )

    vorhandene_anzahl = (await session.execute(
        select(func.count(FaqEintrag.id)).where(FaqEintrag.produkt_id == produkt.id)
    )).scalar_one()
    if vorhandene_anzahl:
        return {
            "produkt": produkt.name,
            "angelegt": 0,
            "uebersprungen": True,
            "grund": f"bereits {vorhandene_anzahl} FAQ-Einträge vorhanden",
        }

    daten = daten if daten is not None else json.loads(
        DATEN_PFAD.read_text(encoding="utf-8")
    )
    for eintrag in daten:
        session.add(FaqEintrag(
            produkt_id=produkt.id,
            kategorie=eintrag["gruppe"],
            frage=eintrag["frage"],
            antwort=eintrag["antwort"],
            quelle=" | ".join(eintrag["quellen"]),
            status="entwurf",
            sortierung=eintrag["sortierung"],
            aktiv=True,
        ))
    await session.commit()
    return {
        "produkt": produkt.name,
        "angelegt": len(daten),
        "uebersprungen": False,
    }


async def main() -> None:
    async with SessionLocal() as session:
        ergebnis = await importiere(session)
    if ergebnis["uebersprungen"]:
        print(
            f"Keine Änderung: {ergebnis['produkt']} – {ergebnis['grund']}."
        )
    else:
        print(
            f"{ergebnis['angelegt']} FAQ-Entwürfe für "
            f"{ergebnis['produkt']} angelegt."
        )


if __name__ == "__main__":
    asyncio.run(main())
