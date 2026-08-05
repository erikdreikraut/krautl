import os
import unittest

os.environ.setdefault(
    "DATABASE_URL", "sqlite+aiosqlite:///./test_aktionslog_user.db"
)

from sqlalchemy import text

from app.db import engine
from app.models import Base
from scripts.migrate_aktionslog_user import migriere


class AktionslogUserMigrationTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.execute(text(
                'CREATE TABLE "aktionslog" ('
                '"id" integer PRIMARY KEY, '
                '"mail_id" integer, '
                '"ereignis" varchar(50) NOT NULL, '
                '"detail" text NOT NULL, '
                '"erstellt_am" datetime'
                ')'
            ))
            await conn.execute(text(
                'INSERT INTO "aktionslog" '
                '("id", "ereignis", "detail") VALUES '
                "(1, 'bestaetigt', 'Bestätigung erteilt durch Erik Schweitzer'), "
                "(2, 'klassifiziert', 'KUNDE_TEST')"
            ))

    async def test_migration_ergaenzt_benutzer_und_ist_wiederholbar(self):
        await migriere()
        await migriere()

        async with engine.begin() as conn:
            zeilen = (await conn.execute(text(
                'SELECT "ausgeloest_von" FROM "aktionslog" ORDER BY "id"'
            ))).scalars().all()

        self.assertEqual(["Erik Schweitzer", "Krautl"], list(zeilen))


if __name__ == "__main__":
    unittest.main()
