"""Ergänzt den Auslöser im Aktionslog.

Aufruf nach dem Container-Neubau:
    docker compose exec app python -m scripts.migrate_aktionslog_user

Sicher mehrfach ausführbar.
"""
import asyncio

from sqlalchemy import inspect, text

from app.db import engine
from app.models import Base


BEKANNTE_BENUTZER = (
    "Erik Schweitzer",
    "Gursewak Singh",
    "Ludwig Schnorrenberg",
)


async def migriere() -> None:
    async with engine.begin() as conn:
        def hat_spalte(sync_conn):
            inspektor = inspect(sync_conn)
            if "aktionslog" not in inspektor.get_table_names():
                return True
            return "ausgeloest_von" in {
                spalte["name"] for spalte in inspektor.get_columns("aktionslog")
            }

        if not await conn.run_sync(hat_spalte):
            await conn.execute(text(
                'ALTER TABLE "aktionslog" ADD COLUMN "ausgeloest_von" '
                "varchar(100) NOT NULL DEFAULT 'Krautl'"
            ))
        await conn.run_sync(Base.metadata.create_all)

        # Bei historischen manuellen Einträgen stand der Name bereits im
        # Beschreibungstext. Diese Information wird soweit möglich übernommen.
        for name in BEKANNTE_BENUTZER:
            await conn.execute(text(
                'UPDATE "aktionslog" SET "ausgeloest_von" = :name '
                'WHERE lower("detail") LIKE :suchtext'
            ), {
                "name": name,
                "suchtext": f"%durch {name.casefold()}%",
            })

    print("Aktionslog-Auslöser angelegt und historische Einträge ergänzt.")


if __name__ == "__main__":
    asyncio.run(migriere())
