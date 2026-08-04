import os
import unittest

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_shopapotheke.db")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")

from sqlalchemy import select

from app.db import SessionLocal, engine
from app.models import Base, Klassifikation, KlassifikationAufgabe
from scripts.aktualisiere_shopapotheke_kategorien import aktualisiere


class ShopApothekeKategorienTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        async with SessionLocal() as session:
            session.add_all([
                Klassifikation(
                    klassifikation_id="AMAZON_STATUS",
                    hauptkategorie="Amazon",
                    unterkategorie="Status",
                    beschreibung="Amazon-Statusmeldung.",
                    standard_prio="normal",
                    aktion_id="MAIL_VERSCHIEBEN",
                ),
                Klassifikation(
                    klassifikation_id="AMAZON_WICHTIG",
                    hauptkategorie="Amazon",
                    unterkategorie="Wichtig",
                    beschreibung="Wichtige Amazon-Meldung.",
                    standard_prio="hoch",
                    aktion_id="MAIL_VERSCHIEBEN",
                ),
            ])
            await session.commit()

    async def test_kategorien_und_aufgaben_werden_idempotent_angelegt(self):
        async with SessionLocal() as session:
            await aktualisiere(session)
        async with SessionLocal() as session:
            await aktualisiere(session)

        async with SessionLocal() as session:
            bestellung = await session.get(
                Klassifikation, "SHOPAPOTHEKE_BESTELLUNG"
            )
            wichtig = await session.get(
                Klassifikation, "SHOPAPOTHEKE_WICHTIG"
            )
            self.assertEqual("service@dreikraut.de", bestellung.zielpostfach)
            self.assertEqual("Bestellungen Shopapotheke", bestellung.zielordner)
            self.assertEqual("INBOX", wichtig.zielordner)

            aufgaben = (await session.execute(
                select(KlassifikationAufgabe)
                .where(KlassifikationAufgabe.klassifikation_id.in_([
                    "SHOPAPOTHEKE_BESTELLUNG", "SHOPAPOTHEKE_WICHTIG",
                ]))
                .order_by(
                    KlassifikationAufgabe.klassifikation_id,
                    KlassifikationAufgabe.position,
                )
            )).scalars().all()
            nach_kategorie = {}
            for aufgabe in aufgaben:
                nach_kategorie.setdefault(aufgabe.klassifikation_id, []).append(
                    aufgabe.aufgabe_typ
                )
            self.assertEqual(
                ["BESTAETIGUNG_EINHOLEN", "MAIL_VERSCHIEBEN"],
                nach_kategorie["SHOPAPOTHEKE_BESTELLUNG"],
            )
            self.assertEqual(
                ["BESTAETIGUNG_EINHOLEN"],
                nach_kategorie["SHOPAPOTHEKE_WICHTIG"],
            )
            amazon = await session.get(Klassifikation, "AMAZON_WICHTIG")
            self.assertIn("gehören niemals", amazon.beschreibung)
            self.assertEqual(1, amazon.beschreibung.count("gehören niemals"))


if __name__ == "__main__":
    unittest.main()
