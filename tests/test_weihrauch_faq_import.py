import json
import os
import unittest
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_weihrauch_faq.db")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")

from sqlalchemy import select

from app.db import SessionLocal, engine
from app.models import Base, FaqEintrag, Produkt
from scripts.importiere_weihrauch_kapseln_faq import importiere


class WeihrauchFaqImportTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        async with SessionLocal() as session:
            session.add(Produkt(
                name="Weihrauch Kapseln BIO",
                artikelnummer="30014",
                website_url="https://dreikraut.de/Weihrauch-Kapseln",
                aktiv=True,
            ))
            await session.commit()

    async def test_fehlende_faq_werden_einmalig_als_entwurf_angelegt(self):
        async with SessionLocal() as session:
            erstes_ergebnis = await importiere(session)
        async with SessionLocal() as session:
            zweites_ergebnis = await importiere(session)
            eintraege = (await session.execute(
                select(FaqEintrag).order_by(FaqEintrag.sortierung)
            )).scalars().all()

        daten = json.loads((
            Path(__file__).resolve().parent.parent
            / "data"
            / "weihrauch-kapseln-faq.json"
        ).read_text(encoding="utf-8"))
        self.assertEqual(len(daten), erstes_ergebnis["angelegt"])
        self.assertEqual(0, erstes_ergebnis["uebersprungen"])
        self.assertEqual(0, zweites_ergebnis["angelegt"])
        self.assertEqual(len(daten), zweites_ergebnis["uebersprungen"])
        self.assertEqual(len(daten), len(eintraege))
        self.assertTrue(all(eintrag.status == "entwurf" for eintrag in eintraege))
        self.assertEqual(
            ["Herkunft & Qualität", "Anwendung & Praktisches", "Hintergrundwissen"],
            list(dict.fromkeys(eintrag.kategorie for eintrag in eintraege)),
        )

    async def test_vorhandene_frage_bleibt_unveraendert(self):
        async with SessionLocal() as session:
            produkt = (await session.execute(select(Produkt))).scalar_one()
            session.add(FaqEintrag(
                produkt_id=produkt.id,
                kategorie="Eigene Rubrik",
                frage="Was ist Boswellia Serrata?",
                antwort="Bereits von Hand bearbeitet.",
                status="freigegeben",
                sortierung=1,
                aktiv=True,
            ))
            await session.commit()
            ergebnis = await importiere(session)
            eintraege = (await session.execute(
                select(FaqEintrag).order_by(FaqEintrag.sortierung)
            )).scalars().all()

        self.assertEqual(15, ergebnis["angelegt"])
        self.assertEqual(1, ergebnis["uebersprungen"])
        self.assertEqual("Bereits von Hand bearbeitet.", eintraege[0].antwort)


if __name__ == "__main__":
    unittest.main()
