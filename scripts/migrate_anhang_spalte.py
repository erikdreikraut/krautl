"""
Einmalige Schema-Migration: ergänzt die Spalte mail.anhang_dateinamen.

Hintergrund: Base.metadata.create_all() beim App-Start legt nur fehlende
Tabellen an, ändert aber nie Spalten einer bereits bestehenden Tabelle —
genau wie schon beim Zeitzonen-Fix (siehe migrate_zeitzone.py). Ohne diese
Migration schlägt jeder Zugriff auf die mail-Tabelle mit einem SQL-Fehler
fehl, sobald der neue Code versucht, die (in Postgres nicht existierende)
Spalte zu lesen oder zu schreiben.

Sicher mehrfach ausführbar (IF NOT EXISTS).

Aufruf (vom Projekt-Root):
    python -m scripts.migrate_anhang_spalte
"""
import asyncio

from sqlalchemy import text

from app.db import engine


async def migriere() -> None:
    async with engine.begin() as conn:
        await conn.execute(text(
            'ALTER TABLE "mail" ADD COLUMN IF NOT EXISTS "anhang_dateinamen" JSON'
        ))
    print("mail.anhang_dateinamen: sichergestellt (angelegt oder bereits vorhanden).")


if __name__ == "__main__":
    asyncio.run(migriere())
