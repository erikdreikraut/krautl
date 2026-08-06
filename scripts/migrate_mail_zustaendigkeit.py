"""Ergänzt die rollenbasierte Zuständigkeit eingegangener Mails.

Aufruf nach dem Container-Neubau:
    docker compose run --rm app python -m scripts.migrate_mail_zustaendigkeit

Sicher mehrfach ausführbar.
"""
import asyncio

from sqlalchemy import inspect, text

from app.db import engine
from app.models import Base


async def migriere() -> None:
    async with engine.begin() as conn:
        def tabellen_und_spalten(sync_conn):
            inspektor = inspect(sync_conn)
            if "mail" not in inspektor.get_table_names():
                return False, set()
            return True, {
                spalte["name"] for spalte in inspektor.get_columns("mail")
            }

        mail_vorhanden, spalten = await conn.run_sync(tabellen_und_spalten)
        if not mail_vorhanden:
            await conn.run_sync(Base.metadata.create_all)
            print("Mail-Zuständigkeiten mit dem Datenbankschema angelegt.")
            return
        sachbearbeiter_neu = "zustaendig_sachbearbeiter" not in spalten

        ergaenzungen = {
            "zustaendig_admin": "boolean NOT NULL DEFAULT true",
            "zustaendig_sachbearbeiter": "boolean NOT NULL DEFAULT true",
            "zustaendigkeit_manuell": "boolean NOT NULL DEFAULT false",
        }
        for name, definition in ergaenzungen.items():
            if name not in spalten:
                await conn.execute(text(
                    f'ALTER TABLE "mail" ADD COLUMN "{name}" {definition}'
                ))

        await conn.run_sync(Base.metadata.create_all)
        if sachbearbeiter_neu:
            await conn.execute(text(
                'UPDATE "mail" SET "zustaendig_sachbearbeiter" = false '
                'WHERE "klassifikation_id" IN ('
                'SELECT "klassifikation_id" FROM "rollen_mailzugriff" '
                "WHERE \"rolle\" = 'sachbearbeiter' AND \"darf_sehen\" = false"
                ')'
            ))

    print("Mail-Zuständigkeiten angelegt und aus der Rollen-Matrix initialisiert.")


if __name__ == "__main__":
    asyncio.run(migriere())
