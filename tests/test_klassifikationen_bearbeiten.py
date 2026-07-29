import os
import unittest

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_klassifikationen.db")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")

from sqlalchemy import select

from app.db import SessionLocal, engine
from app.main import KlassifikationAenderung, klassifikation_aktualisieren
from app.models import Base, Klassifikation, KlassifikationAufgabe


class KlassifikationenBearbeitenTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        async with SessionLocal() as session:
            session.add_all([
                Klassifikation(
                    klassifikation_id="KUNDE_TEST",
                    hauptkategorie="Kundenservice",
                    unterkategorie="Test",
                    beschreibung="Test",
                    standard_prio="normal",
                    zielpostfach="service@dreikraut.de",
                    zielordner="INBOX",
                    aktion_id="MAIL_VERSCHIEBEN",
                ),
                Klassifikation(
                    klassifikation_id="SPAM_TEST",
                    hauptkategorie="Spam",
                    unterkategorie="Test",
                    beschreibung="Test",
                    standard_prio="spam",
                    zielpostfach="info@dreikraut.de",
                    zielordner="KI-Spam",
                    aktion_id="MAIL_VERSCHIEBEN",
                ),
            ])
            await session.commit()

    async def test_bestaetigung_ist_editierbar_und_reihenfolge_bleibt_erhalten(self):
        async with SessionLocal() as session:
            await klassifikation_aktualisieren(
                "KUNDE_TEST",
                KlassifikationAenderung(
                    zielordner="Service/Neu",
                    aufgaben=[
                        "BESTAETIGUNG_EINHOLEN",
                        "MAIL_VERSCHIEBEN",
                        "MAIL_VERSCHIEBEN",
                    ],
                ),
                session,
            )
        async with SessionLocal() as session:
            klassifikation = await session.get(Klassifikation, "KUNDE_TEST")
            aufgaben = (await session.execute(
                select(KlassifikationAufgabe)
                .where(KlassifikationAufgabe.klassifikation_id == "KUNDE_TEST")
                .order_by(KlassifikationAufgabe.position)
            )).scalars().all()
            self.assertEqual("Service/Neu", klassifikation.zielordner)
            self.assertEqual(
                ["BESTAETIGUNG_EINHOLEN", "MAIL_VERSCHIEBEN", "MAIL_VERSCHIEBEN"],
                [a.aufgabe_typ for a in aufgaben],
            )

    async def test_bestaetigung_kann_auch_bei_nicht_spam_entfernt_werden(self):
        async with SessionLocal() as session:
            await klassifikation_aktualisieren(
                "KUNDE_TEST",
                KlassifikationAenderung(
                    zielordner="Service/Neu",
                    aufgaben=["MAIL_VERSCHIEBEN"],
                ),
                session,
            )
        async with SessionLocal() as session:
            aufgaben = (await session.execute(
                select(KlassifikationAufgabe)
                .where(KlassifikationAufgabe.klassifikation_id == "KUNDE_TEST")
            )).scalars().all()
            self.assertEqual(["MAIL_VERSCHIEBEN"], [a.aufgabe_typ for a in aufgaben])

    async def test_bestaetigung_kann_auch_bei_spam_hinzugefuegt_werden(self):
        async with SessionLocal() as session:
            await klassifikation_aktualisieren(
                "SPAM_TEST",
                KlassifikationAenderung(
                    zielordner="KI-Spam",
                    aufgaben=["BESTAETIGUNG_EINHOLEN", "MAIL_VERSCHIEBEN"],
                ),
                session,
            )
        async with SessionLocal() as session:
            aufgaben = (await session.execute(
                select(KlassifikationAufgabe)
                .where(KlassifikationAufgabe.klassifikation_id == "SPAM_TEST")
                .order_by(KlassifikationAufgabe.position)
            )).scalars().all()
            self.assertEqual(
                ["BESTAETIGUNG_EINHOLEN", "MAIL_VERSCHIEBEN"],
                [a.aufgabe_typ for a in aufgaben],
            )


if __name__ == "__main__":
    unittest.main()
