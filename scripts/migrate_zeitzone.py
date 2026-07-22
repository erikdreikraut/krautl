"""
Einmalige Schema-Migration: bestehende DateTime-Spalten (ohne Zeitzone, aber
faktisch immer UTC befüllt) auf timestamptz umstellen.

Hintergrund: Ohne Zeitzonen-Info liefert Postgres/asyncpg Zeitstempel ohne
Offset aus, und der Browser interpretiert sie dann fälschlich als lokale Zeit
statt als UTC — daher die falsch angezeigten Uhrzeiten in der Oberfläche.

Sicher mehrfach ausführbar: Spalten, die schon timestamptz sind, werden
übersprungen.

Aufruf (vom Projekt-Root):
    python -m scripts.migrate_zeitzone
"""
import asyncio

from sqlalchemy import text

from app.db import engine

SPALTEN = [
    ("mail", "empfangen_am"),
    ("korrektur", "erstellt_am"),
    ("entwurf", "erstellt_am"),
    ("entwurf", "versendet_am"),
    ("rechnung", "rechnungsdatum"),
    ("rechnung", "faellig_am"),
    ("faq_vorschlag", "erstellt_am"),
    ("aktionslog", "erstellt_am"),
]


async def _ist_bereits_timestamptz(conn, tabelle: str, spalte: str) -> bool:
    result = await conn.execute(text(
        "SELECT data_type FROM information_schema.columns "
        "WHERE table_name = :tabelle AND column_name = :spalte"
    ), {"tabelle": tabelle, "spalte": spalte})
    zeile = result.first()
    return zeile is not None and zeile[0] == "timestamp with time zone"


async def migriere() -> None:
    async with engine.begin() as conn:
        for tabelle, spalte in SPALTEN:
            if await _ist_bereits_timestamptz(conn, tabelle, spalte):
                print(f"{tabelle}.{spalte}: schon timestamptz, übersprungen")
                continue
            await conn.execute(text(
                f'ALTER TABLE "{tabelle}" ALTER COLUMN "{spalte}" '
                f"TYPE timestamptz USING \"{spalte}\" AT TIME ZONE 'UTC'"
            ))
            print(f"{tabelle}.{spalte}: umgestellt auf timestamptz")


if __name__ == "__main__":
    asyncio.run(migriere())
