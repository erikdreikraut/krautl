import json
import os
import unittest
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_chlorella_faq.db")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")

from sqlalchemy import select

from app.db import SessionLocal, engine
from app.models import Base, FaqEintrag, Produkt
from scripts.importiere_chlorella_faq_entwuerfe import importiere


class ChlorellaFaqImportTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        async with SessionLocal() as session:
            session.add(Produkt(
                name="Bio-Chlorella-Tabletten aus kontrollierter Aquakultur",
                artikelnummer="40046",
                website_url="https://dreikraut.de/bio-chlorella-tabletten-presslinge",
                aktiv=True,
            ))
            await session.commit()

    async def test_entwuerfe_werden_nur_bei_leerem_faq_angelegt(self):
        async with SessionLocal() as session:
            erstes_ergebnis = await importiere(session)
        async with SessionLocal() as session:
            zweites_ergebnis = await importiere(session)
            eintraege = (await session.execute(
                select(FaqEintrag).order_by(FaqEintrag.sortierung)
            )).scalars().all()

        daten = json.loads((
            Path(__file__).resolve().parent.parent
            / "data" / "chlorella-faq-entwuerfe.json"
        ).read_text(encoding="utf-8"))
        self.assertEqual(len(daten), erstes_ergebnis["angelegt"])
        self.assertTrue(zweites_ergebnis["uebersprungen"])
        self.assertEqual(len(daten), len(eintraege))
        self.assertTrue(all(eintrag.status == "entwurf" for eintrag in eintraege))
        self.assertEqual(
            list(range(10, 10 * (len(daten) + 1), 10)),
            [eintrag.sortierung for eintrag in eintraege],
        )

    async def test_vorhandenes_faq_bleibt_unberuehrt(self):
        async with SessionLocal() as session:
            produkt = (await session.execute(select(Produkt))).scalar_one()
            session.add(FaqEintrag(
                produkt_id=produkt.id,
                kategorie="Eigene Gruppe",
                frage="Bereits redaktionell gepflegt?",
                antwort="Ja.",
                status="freigegeben",
                sortierung=1,
                aktiv=True,
            ))
            await session.commit()
            ergebnis = await importiere(session)
            eintraege = (await session.execute(select(FaqEintrag))).scalars().all()

        self.assertTrue(ergebnis["uebersprungen"])
        self.assertEqual(["Bereits redaktionell gepflegt?"], [e.frage for e in eintraege])


if __name__ == "__main__":
    unittest.main()
