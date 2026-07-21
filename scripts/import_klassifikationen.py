"""
Importiert die Klassifikationstabelle aus einer CSV-Datei (Export-Format aus
n8n, siehe data/mail-klassifikationen.csv) in die klassifikation-Tabelle.

Idempotent: bestehende Klassifikation_IDs werden aktualisiert statt dupliziert,
das Skript kann also gefahrlos erneut laufen, wenn sich die CSV ändert.

Aufruf (vom Projekt-Root):
    python -m scripts.import_klassifikationen data/mail-klassifikationen.csv
"""
import asyncio
import csv
import sys

from app.db import SessionLocal
from app.models import Klassifikation


def _lese_csv(pfad: str) -> list[dict]:
    with open(pfad, encoding="utf-8-sig", newline="") as datei:
        return list(csv.DictReader(datei))


async def importiere(pfad: str) -> None:
    zeilen = _lese_csv(pfad)
    async with SessionLocal() as session:
        for zeile in zeilen:
            klassifikation_id = zeile["Klassifikation_ID"].strip()
            werte = {
                "hauptkategorie": zeile["Hauptkategorie"].strip(),
                "unterkategorie": zeile["Unterkategorie"].strip(),
                "beschreibung": zeile["Beschreibung"].strip(),
                "standard_prio": zeile["Standard_Prio"].strip(),
                "zielpostfach": zeile["Zielpostfach"].strip() or None,
                "zielordner": zeile["Zielordner"].strip() or None,
                "aktion_id": zeile["Aktion_ID"].strip(),
            }
            bestehende = await session.get(Klassifikation, klassifikation_id)
            if bestehende:
                for feld, wert in werte.items():
                    setattr(bestehende, feld, wert)
            else:
                session.add(Klassifikation(klassifikation_id=klassifikation_id, **werte))
        await session.commit()
    print(f"{len(zeilen)} Klassifikationen importiert/aktualisiert.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Aufruf: python -m scripts.import_klassifikationen <pfad-zur-csv>")
        sys.exit(1)
    asyncio.run(importiere(sys.argv[1]))
