import os
import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

os.environ.setdefault(
    "DATABASE_URL", "sqlite+aiosqlite:///./test_bereinige_entwuerfe.db"
)
os.environ.setdefault("ANTHROPIC_API_KEY", "test")

from sqlalchemy import select

from app.db import SessionLocal, engine
from app.models import Aktionslog, Base, Entwurf, Mail, Postfach
from scripts.bereinige_fremdsprachige_entwuerfe import bereinige


class BestandsentwuerfeBereinigenTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        async with SessionLocal() as session:
            postfach = Postfach(
                adresse="service@dreikraut.de",
                funktion="service",
                imap_host="imap.example.test",
            )
            session.add(postfach)
            await session.flush()
            fremdsprachig = Mail(
                message_id="<franzoesisch@example.test>",
                postfach_id=postfach.id,
                absender_name="Jean Exemple",
                absender_adresse="kunde@example.test",
                betreff="Question",
                text_auszug="Bonjour",
                originalsprache="Französisch",
                empfangen_am=datetime.now(timezone.utc),
            )
            deutsch = Mail(
                message_id="<deutsch@example.test>",
                postfach_id=postfach.id,
                absender_name="Ada Beispiel",
                absender_adresse="kunde2@example.test",
                betreff="Frage",
                text_auszug="Guten Tag",
                originalsprache="Deutsch",
                empfangen_am=datetime.now(timezone.utc),
            )
            session.add_all([fremdsprachig, deutsch])
            await session.flush()
            session.add_all([
                Entwurf(
                    mail_id=fremdsprachig.id,
                    text_ki="Bonjour, merci.",
                    status="wartet",
                ),
                Entwurf(
                    mail_id=deutsch.id,
                    text_ki="Guten Tag, danke.",
                    status="wartet",
                ),
            ])
            await session.commit()

    async def test_nur_wartender_fremdsprachiger_entwurf_wird_bereinigt(self):
        uebersetzung = AsyncMock(return_value="Guten Tag, vielen Dank.")
        with patch(
            "scripts.bereinige_fremdsprachige_entwuerfe."
            "antwort_ins_deutsche_uebersetzen",
            uebersetzung,
        ):
            async with SessionLocal() as session:
                ergebnis = await bereinige(session)

        self.assertEqual(1, ergebnis["kandidaten"])
        self.assertEqual(1, ergebnis["aktualisiert"])
        self.assertEqual([], ergebnis["fehler"])
        uebersetzung.assert_awaited_once_with(
            "Bonjour, merci.", "Französisch"
        )
        async with SessionLocal() as session:
            entwuerfe = (await session.execute(
                select(Entwurf).order_by(Entwurf.id)
            )).scalars().all()
            log = (await session.execute(
                select(Aktionslog).where(
                    Aktionslog.ereignis
                    == "antwortentwurf_ins_deutsche_uebersetzt"
                )
            )).scalar_one()
        self.assertEqual("Guten Tag, vielen Dank.", entwuerfe[0].text_ki)
        self.assertEqual("Guten Tag, danke.", entwuerfe[1].text_ki)
        self.assertIn("Französisch", log.detail)


if __name__ == "__main__":
    unittest.main()
