import os
import unittest

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_anthropic_mailregel.db")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")

from sqlalchemy import select

from app.db import SessionLocal, engine
from app.models import Base, Klassifikation, KlassifikationAufgabe
from scripts.aktualisiere_anthropic_mailregel import aktualisiere


class AnthropicMailregelTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        async with SessionLocal() as session:
            session.add(Klassifikation(
                klassifikation_id="SYSTEM_TECHNIK",
                hauptkategorie="System",
                unterkategorie="Technische Warnung oder Störung",
                beschreibung="Automatische technische Warnung.",
                standard_prio="hoch",
                zielordner="System/Technik",
                aktion_id="SYSTEMMELDUNG_BEARBEITEN",
            ))
            await session.commit()

    async def test_regel_ziel_und_aufgaben_werden_idempotent_gesetzt(self):
        async with SessionLocal() as session:
            await aktualisiere(session)
        async with SessionLocal() as session:
            await aktualisiere(session)

        async with SessionLocal() as session:
            klassifikation = await session.get(
                Klassifikation, "SYSTEM_TECHNIK"
            )
            aufgaben = (await session.execute(
                select(KlassifikationAufgabe)
                .where(
                    KlassifikationAufgabe.klassifikation_id
                    == "SYSTEM_TECHNIK"
                )
                .order_by(KlassifikationAufgabe.position)
            )).scalars().all()

        self.assertEqual("info@dreikraut.de", klassifikation.zielpostfach)
        self.assertEqual("service-Technik", klassifikation.zielordner)
        self.assertEqual("MAIL_VERSCHIEBEN", klassifikation.aktion_id)
        self.assertEqual(
            1, klassifikation.beschreibung.count("mail.anthropic.com")
        )
        self.assertEqual(
            ["BESTAETIGUNG_EINHOLEN", "MAIL_VERSCHIEBEN"],
            [aufgabe.aufgabe_typ for aufgabe in aufgaben],
        )
        self.assertTrue(all(
            aufgabe.parameter == {
                "zielpostfach": "info@dreikraut.de",
                "zielordner": "service-Technik",
            }
            for aufgabe in aufgaben
        ))


if __name__ == "__main__":
    unittest.main()
