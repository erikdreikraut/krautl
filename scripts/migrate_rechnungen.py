"""Ergänzt das Rechnungsschema. Sicher mehrfach ausführbar."""
import asyncio

from sqlalchemy import inspect, text

from app.db import engine
from app.models import Base


SPALTEN = {
    "zahlungshinweis": "TEXT",
    "dateipfade": "JSON",
    "dublettenschluessel": "VARCHAR(64)",
}


async def migriere() -> None:
    async with engine.begin() as conn:
        def vorhandene(sync_conn):
            if "rechnung" not in inspect(sync_conn).get_table_names():
                return set()
            return {s["name"] for s in inspect(sync_conn).get_columns("rechnung")}

        spalten = await conn.run_sync(vorhandene)
        if not spalten:
            await conn.run_sync(Base.metadata.create_all)
            spalten = set(SPALTEN)
        for name, typ in SPALTEN.items():
            if name not in spalten:
                await conn.execute(text(f'ALTER TABLE "rechnung" ADD COLUMN "{name}" {typ}'))
        await conn.execute(text(
            'CREATE UNIQUE INDEX IF NOT EXISTS "uq_rechnung_dublette" '
            'ON "rechnung" ("dublettenschluessel")'
        ))
    print("Rechnungs-Migration abgeschlossen.")


if __name__ == "__main__":
    asyncio.run(migriere())
