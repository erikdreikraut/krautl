"""
Legt einen einzelnen Wissenseintrag an (Ablauf-/Prozesswissen, nicht an ein
Produkt gebunden). Für einmalige, gezielte Ergänzungen der Wissensbasis
gedacht — für Massenimporte eher ein eigenes CSV-Skript nach dem Vorbild von
import_klassifikationen.py schreiben.

Aufruf (vom Projekt-Root):
    python -m scripts.add_wissenseintrag

Der Inhalt steht unten als EINTRAG-Dict — vor dem Ausführen anpassen, falls
ein anderer Eintrag angelegt werden soll.
"""
import asyncio

from app.db import SessionLocal
from app.models import Wissenseintrag

EINTRAG = {
    "wissensart": "ablauf",
    "titel": "Rücksendung bei berechtigter Reklamation",
    "inhalt": (
        "Stellt eine Kundin oder ein Kunde einen echten Fehler am Produkt fest "
        "(berechtigte Reklamation), organisieren wir ein Rücksendeetikett (DHL) "
        "an uns. Die Kundschaft muss dafür keinen DHL-Shop gezielt aufsuchen — "
        "es reicht, das Paket einem DHL-Fahrer mitzugeben, in einer Filiale "
        "abzugeben oder an einer Packstation zu hinterlassen."
    ),
    "quelle": "Erik Schweitzer (dreikraut e.K.)",
    "status": "freigegeben",
    "sensibel": False,
    "schlagwoerter": ["reklamation", "rücksendung", "retoure", "dhl", "rücksendeetikett"],
}


async def anlegen() -> None:
    async with SessionLocal() as session:
        eintrag = Wissenseintrag(**EINTRAG)
        session.add(eintrag)
        await session.commit()
        await session.refresh(eintrag)
        print(f"Wissenseintrag #{eintrag.id} angelegt: {eintrag.titel!r}")


if __name__ == "__main__":
    asyncio.run(anlegen())
