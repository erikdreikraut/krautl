import json
import os
import unittest
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_kurkuma_faq.db")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")

from sqlalchemy import select

from app.db import SessionLocal, engine
from app.models import Base, FaqEintrag, Produkt
from scripts.importiere_kurkuma_forte_faq import importiere


class KurkumaForteFaqImportTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        async with SessionLocal() as session:
            session.add(Produkt(
                name="Kurkuma Forte Bio, 160 Kapseln, 465mg",
                artikelnummer="30017",
                website_url=(
                    "https://dreikraut.de/"
                    "Kurkuma-Forte-Bio-160-Kapseln-465mg"
                ),
                aktiv=True,
            ))
            await session.commit()

    async def test_faq_werden_einmalig_freigegeben_und_aktiv_angelegt(self):
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
            / "kurkuma-forte-faq.json"
        ).read_text(encoding="utf-8"))
        self.assertEqual(len(daten), erstes_ergebnis["angelegt"])
        self.assertEqual(0, erstes_ergebnis["uebersprungen"])
        self.assertEqual(0, zweites_ergebnis["angelegt"])
        self.assertEqual(len(daten), zweites_ergebnis["uebersprungen"])
        self.assertEqual(len(daten), len(eintraege))
        self.assertTrue(all(eintrag.status == "freigegeben" for eintrag in eintraege))
        self.assertTrue(all(eintrag.aktiv for eintrag in eintraege))
        self.assertEqual(
            ["Herkunft & Qualität", "Nährstoffe & Wirkung", "Anwendung & Praktisches"],
            list(dict.fromkeys(eintrag.kategorie for eintrag in eintraege)),
        )

    async def test_vorhandene_frage_bleibt_unveraendert(self):
        async with SessionLocal() as session:
            produkt = (await session.execute(select(Produkt))).scalar_one()
            session.add(FaqEintrag(
                produkt_id=produkt.id,
                kategorie="Eigene Rubrik",
                frage="Was ist Curcumin eigentlich?",
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

        self.assertEqual(13, ergebnis["angelegt"])
        self.assertEqual(1, ergebnis["uebersprungen"])
        self.assertEqual("Bereits von Hand bearbeitet.", eintraege[0].antwort)


if __name__ == "__main__":
    unittest.main()
