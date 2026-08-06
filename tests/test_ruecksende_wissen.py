import os
import unittest

os.environ.setdefault(
    "DATABASE_URL", "sqlite+aiosqlite:///./test_ruecksende_wissen.db"
)
os.environ.setdefault("ANTHROPIC_API_KEY", "test")

from sqlalchemy import func, select

from app.db import SessionLocal, engine
from app.models import Base, Wissenseintrag
from scripts.aktualisiere_ruecksende_wissen import QUELLE, aktualisiere


class RuecksendeWissenTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)

    async def test_wissen_wird_freigegeben_und_idempotent_aktualisiert(self):
        async with SessionLocal() as session:
            await aktualisiere(session)
            await aktualisiere(session)

        async with SessionLocal() as session:
            anzahl = (await session.execute(
                select(func.count(Wissenseintrag.id)).where(
                    Wissenseintrag.quelle == QUELLE
                )
            )).scalar_one()
            eintrag = (await session.execute(
                select(Wissenseintrag).where(Wissenseintrag.quelle == QUELLE)
            )).scalar_one()

        self.assertEqual(1, anzahl)
        self.assertEqual("ablauf", eintrag.wissensart)
        self.assertEqual("freigegeben", eintrag.status)
        kompakter_inhalt = " ".join(eintrag.inhalt.split())
        self.assertIn("ungeöffnete Packungen", kompakter_inhalt)
        self.assertIn("selbst verantwortlich", kompakter_inhalt)
        self.assertIn("Gräfrather Str. 74a", kompakter_inhalt)
        self.assertIn("Qualitätsmangel", kompakter_inhalt)


if __name__ == "__main__":
    unittest.main()
