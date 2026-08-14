"""
Einmalige Schema-Migration: ergänzt die Spalte mail.antwort_an_adresse.

Siehe migrate_anhang_spalte.py für den Hintergrund: create_all() beim
App-Start legt nur fehlende Tabellen an, ändert aber nie Spalten einer
bereits bestehenden Tabelle. Sicher mehrfach ausführbar (IF NOT EXISTS).

Aufruf (vom Projekt-Root):
    python -m scripts.migrate_antwort_an_spalte
"""
import asyncio

from sqlalchemy import text

from app.db import engine


async def migriere() -> None:
    async with engine.begin() as conn:
        await conn.execute(text(
            'ALTER TABLE "mail" ADD COLUMN IF NOT EXISTS "antwort_an_adresse" VARCHAR(255)'
        ))
    print("mail.antwort_an_adresse: sichergestellt (angelegt oder bereits vorhanden).")


if __name__ == "__main__":
    asyncio.run(migriere())
