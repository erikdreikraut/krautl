"""Importiert einmalig redaktionelle FAQ-Entwürfe für Chlorella.

Der Import überschreibt keine vorhandenen FAQ. Zwei bekannte redaktionelle
Selbstverweise werden bei einem erneuten Lauf jedoch sicher aus den bereits
importierten Chlorella-Entwürfen entfernt.

Ausführen nach dem Deployment:
    docker compose exec app python -m scripts.importiere_chlorella_faq_entwuerfe
"""

import asyncio
import json
from pathlib import Path

from sqlalchemy import func, or_, select

from app.db import SessionLocal
from app.models import FaqEintrag, Produkt


ARTIKELNUMMER = "40046"
PRODUKT_URL = "https://dreikraut.de/bio-chlorella-tabletten-presslinge"
DATEN_PFAD = (
    Path(__file__).resolve().parent.parent / "data" / "chlorella-faq-entwuerfe.json"
)

QUELLENHINWEIS_KORREKTUREN = {
    (
        "Laut unserer Produktbeschreibung werden dabei unter anderem "
        "Wassertemperatur und pH-Wert überwacht."
    ): "Dabei werden unter anderem Wassertemperatur und pH-Wert überwacht.",
    "Das ist auch der Hinweis auf unserer Produktseite. ": "",
}

ZU_ENTFERNENDE_FRAGEN = {
    "Sind Chlorella-Presslinge eine verlässliche Vitamin-B12-Quelle?",
}


async def _entwuerfe_bereinigen(session, produkt_id: int) -> tuple[int, int]:
    eintraege = (await session.execute(
        select(FaqEintrag).where(FaqEintrag.produkt_id == produkt_id)
    )).scalars().all()
    geaendert = 0
    entfernt = 0
    for eintrag in eintraege:
        if eintrag.frage in ZU_ENTFERNENDE_FRAGEN:
            await session.delete(eintrag)
            entfernt += 1
            continue
        antwort = eintrag.antwort
        for alter_text, neuer_text in QUELLENHINWEIS_KORREKTUREN.items():
            antwort = antwort.replace(alter_text, neuer_text)
        if antwort != eintrag.antwort:
            eintrag.antwort = antwort
            geaendert += 1
    await session.flush()
    return geaendert, entfernt


async def importiere(session, daten: list[dict] | None = None) -> dict:
    produkt = (await session.execute(
        select(Produkt).where(or_(
            Produkt.artikelnummer == ARTIKELNUMMER,
            func.lower(Produkt.website_url) == PRODUKT_URL.lower(),
        ))
    )).scalar_one_or_none()
    if produkt is None:
        raise RuntimeError(
            "Chlorella-Produkt nicht gefunden. Bitte zuerst in Krautl unter "
            "Wissensdatenbank 'Shop-Produkte aktualisieren' ausführen."
        )

    bereinigt, entfernt = await _entwuerfe_bereinigen(session, produkt.id)
    vorhandene_anzahl = (await session.execute(
        select(func.count(FaqEintrag.id)).where(FaqEintrag.produkt_id == produkt.id)
    )).scalar_one()
    if vorhandene_anzahl:
        await session.commit()
        return {
            "produkt": produkt.name,
            "angelegt": 0,
            "bereinigt": bereinigt,
            "entfernt": entfernt,
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
        "bereinigt": bereinigt,
        "entfernt": entfernt,
        "uebersprungen": False,
    }


async def main() -> None:
    async with SessionLocal() as session:
        ergebnis = await importiere(session)
    if ergebnis["uebersprungen"]:
        print(
            f"Keine neuen FAQ: {ergebnis['produkt']} – {ergebnis['grund']}. "
            f"{ergebnis['bereinigt']} Quellenhinweis(e) bereinigt, "
            f"{ergebnis['entfernt']} ungeeignete Frage(n) entfernt."
        )
    else:
        print(
            f"{ergebnis['angelegt']} FAQ-Entwürfe für "
            f"{ergebnis['produkt']} angelegt."
        )


if __name__ == "__main__":
    asyncio.run(main())
