import os
import unittest

os.environ.setdefault(
    "DATABASE_URL", "sqlite+aiosqlite:///./test_uebersetzungen_migration.db"
)

from sqlalchemy import inspect, text

from app.db import engine
from scripts.migrate_uebersetzungen import migriere


def _spalten(sync_conn, tabelle):
    return {spalte["name"] for spalte in inspect(sync_conn).get_columns(tabelle)}


class UebersetzungenMigrationTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        async with engine.begin() as conn:
            await conn.execute(text('DROP TABLE IF EXISTS "entwurf"'))
            await conn.execute(text('DROP TABLE IF EXISTS "mail"'))
            await conn.execute(text('CREATE TABLE "mail" ("id" INTEGER PRIMARY KEY)'))
            await conn.execute(text('CREATE TABLE "entwurf" ("id" INTEGER PRIMARY KEY)'))

    async def test_migration_ergaenzt_spalten_und_ist_wiederholbar(self):
        await migriere()
        await migriere()
        async with engine.begin() as conn:
            mail_spalten = await conn.run_sync(_spalten, "mail")
            entwurf_spalten = await conn.run_sync(_spalten, "entwurf")
        self.assertTrue(
            {"originalsprache", "betreff_deutsch", "text_deutsch"}
            <= mail_spalten
        )
        self.assertIn("text_final_deutsch", entwurf_spalten)


if __name__ == "__main__":
    unittest.main()
