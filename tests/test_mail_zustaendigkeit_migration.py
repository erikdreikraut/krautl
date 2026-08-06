import os
import unittest

os.environ.setdefault(
    "DATABASE_URL", "sqlite+aiosqlite:///./test_mail_zustaendigkeit.db"
)

from sqlalchemy import text

from app.db import engine
from app.models import Base
from scripts.migrate_mail_zustaendigkeit import migriere


class MailZustaendigkeitMigrationTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.execute(text(
                'CREATE TABLE "klassifikation" ('
                '"klassifikation_id" varchar(50) PRIMARY KEY)'
            ))
            await conn.execute(text(
                'CREATE TABLE "rollen_mailzugriff" ('
                '"id" integer PRIMARY KEY, '
                '"rolle" varchar(50), '
                '"klassifikation_id" varchar(50), '
                '"darf_sehen" boolean)'
            ))
            await conn.execute(text(
                'CREATE TABLE "mail" ('
                '"id" integer PRIMARY KEY, '
                '"klassifikation_id" varchar(50) NULL)'
            ))
            await conn.execute(text(
                'INSERT INTO "klassifikation" ("klassifikation_id") '
                "VALUES ('KUNDE_TEST'), ('RECHT_TEST')"
            ))
            await conn.execute(text(
                'INSERT INTO "rollen_mailzugriff" '
                '("id", "rolle", "klassifikation_id", "darf_sehen") '
                "VALUES (1, 'sachbearbeiter', 'RECHT_TEST', false)"
            ))
            await conn.execute(text(
                'INSERT INTO "mail" ("id", "klassifikation_id") '
                "VALUES (1, 'KUNDE_TEST'), (2, 'RECHT_TEST')"
            ))

    async def test_migration_initialisiert_matrix_und_ist_wiederholbar(self):
        await migriere()
        await migriere()

        async with engine.begin() as conn:
            zeilen = (await conn.execute(text(
                'SELECT "zustaendig_admin", "zustaendig_sachbearbeiter", '
                '"zustaendigkeit_manuell" FROM "mail" ORDER BY "id"'
            ))).all()

        self.assertEqual([(1, 1, 0), (1, 0, 0)], [tuple(z) for z in zeilen])


if __name__ == "__main__":
    unittest.main()
