"""Legt das freigegebene Ablaufwissen für normale Rücksendungen an.

Einmal nach dem Deployment ausführen:
    docker compose exec app python -m scripts.aktualisiere_ruecksende_wissen
"""
import asyncio
from pathlib import Path

from sqlalchemy import select

from app.db import SessionLocal
from app.models import Wissenseintrag


QUELLE = "data/ruecksendungen.md"
WISSENSPFAD = Path(__file__).resolve().parent.parent / QUELLE
TITEL = "Rücksendungen ohne Qualitätsmangel"
SCHLAGWOERTER = [
    "Rücksendung", "Retoure", "Widerruf", "Erstattung",
    "Rücksendeadresse", "Rücksendekosten",
]


async def aktualisiere(session) -> Wissenseintrag:
    if not WISSENSPFAD.exists():
        raise RuntimeError(f"Wissensdatei nicht gefunden: {WISSENSPFAD}")
    inhalt = WISSENSPFAD.read_text(encoding="utf-8")
    eintrag = (await session.execute(
        select(Wissenseintrag).where(Wissenseintrag.quelle == QUELLE)
    )).scalar_one_or_none()
    if eintrag is None:
        eintrag = Wissenseintrag(quelle=QUELLE)
        session.add(eintrag)
    eintrag.wissensart = "ablauf"
    eintrag.titel = TITEL
    eintrag.inhalt = inhalt
    eintrag.stand = "2026-08-06"
    eintrag.status = "freigegeben"
    eintrag.sensibel = False
    eintrag.schlagwoerter = SCHLAGWOERTER
    await session.commit()
    await session.refresh(eintrag)
    return eintrag


async def main() -> None:
    async with SessionLocal() as session:
        eintrag = await aktualisiere(session)
    print(f"Wissenseintrag aktualisiert: {eintrag.titel}")


if __name__ == "__main__":
    asyncio.run(main())
