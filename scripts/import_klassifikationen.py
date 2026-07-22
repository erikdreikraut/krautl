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
from sqlalchemy import delete

from app.models import Klassifikation, KlassifikationAufgabe


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
                bestehende = Klassifikation(klassifikation_id=klassifikation_id, **werte)
                session.add(bestehende)

            # Das bisherige Einzel-Feld Aktion_ID bleibt vorerst als
            # Import-/Kompatibilitätsfeld erhalten. Die eigentliche Ausführung
            # läuft über diese geordnete Aufgabenliste.
            await session.execute(
                delete(KlassifikationAufgabe).where(
                    KlassifikationAufgabe.klassifikation_id == klassifikation_id
                )
            )
            aufgabe_typ = werte["aktion_id"]
            position = 1
            if aufgabe_typ == "MAIL_VERSCHIEBEN":
                session.add(KlassifikationAufgabe(
                    klassifikation_id=klassifikation_id,
                    position=position,
                    aufgabe_typ="BESTAETIGUNG_EINHOLEN",
                    bestaetiger_typ="alle",
                ))
                position += 1

            session.add(KlassifikationAufgabe(
                klassifikation_id=klassifikation_id,
                position=position,
                aufgabe_typ=aufgabe_typ,
                parameter={
                    "zielpostfach": werte["zielpostfach"],
                    "zielordner": werte["zielordner"],
                },
            ))
        await session.commit()
    print(f"{len(zeilen)} Klassifikationen importiert/aktualisiert.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Aufruf: python -m scripts.import_klassifikationen <pfad-zur-csv>")
        sys.exit(1)
    asyncio.run(importiere(sys.argv[1]))
