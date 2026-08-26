"""Einmalige, idempotente Schema-Migration für Fremdsprachen-Arbeitsfassungen.

Aufruf vom Projekt-Root:
    python -m scripts.migrate_uebersetzungen
"""

import asyncio

from sqlalchemy import inspect, text

from app.db import engine


MAIL_SPALTEN = {
    "originalsprache": "VARCHAR(80)",
    "betreff_deutsch": "TEXT",
    "text_deutsch": "TEXT",
}

ENTWURF_SPALTEN = {
    "text_final_deutsch": "TEXT",
}


def _vorhandene_spalten(sync_conn, tabelle: str) -> set[str]:
    return {spalte["name"] for spalte in inspect(sync_conn).get_columns(tabelle)}


async def migriere() -> None:
    async with engine.begin() as conn:
        for tabelle, spalten in (
            ("mail", MAIL_SPALTEN),
            ("entwurf", ENTWURF_SPALTEN),
        ):
            vorhanden = await conn.run_sync(_vorhandene_spalten, tabelle)
            for name, typ in spalten.items():
                if name not in vorhanden:
                    await conn.execute(text(
                        f'ALTER TABLE "{tabelle}" ADD COLUMN "{name}" {typ}'
                    ))
    print("Übersetzungsspalten: sichergestellt (angelegt oder bereits vorhanden).")


if __name__ == "__main__":
    asyncio.run(migriere())
