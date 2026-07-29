import os
import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_antwortentwuerfe.db")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")

from sqlalchemy import select

from app.db import SessionLocal, engine
from app.main import mail_antwortentwurf_erzeugen
from app.aufgaben import wartende_aufgaben_ausfuehren
from app.models import Aktionslog, Base, Entwurf, Mail, MailAufgabe, Postfach


class AntwortentwurfTest(unittest.IsolatedAsyncioTestCase):
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
            mail = Mail(
                message_id="<antwort-test@example.test>",
                postfach_id=postfach.id,
                absender_name="Ada Beispiel",
                absender_adresse="ada@example.test",
                betreff="Eine Frage",
                text_auszug="Hallo, könnt Ihr mir helfen?",
                empfangen_am=datetime.now(timezone.utc),
                im_krautl_posteingang=True,
            )
            session.add(mail)
            await session.commit()
            self.mail_id = mail.id

    async def test_entwurf_wird_erzeugt_und_nicht_doppelt_angelegt(self):
        generator = AsyncMock(return_value="Hallo Ada,\n\nsehr gern.")
        with patch("app.antworten.antwortentwurf_erzeugen", generator):
            async with SessionLocal() as session:
                erstes = await mail_antwortentwurf_erzeugen(self.mail_id, session)
            async with SessionLocal() as session:
                zweites = await mail_antwortentwurf_erzeugen(self.mail_id, session)

        self.assertEqual("erzeugt", erstes["status"])
        self.assertEqual("vorhanden", zweites["status"])
        self.assertEqual(1, generator.await_count)
        async with SessionLocal() as session:
            entwuerfe = (await session.execute(select(Entwurf))).scalars().all()
            self.assertEqual(1, len(entwuerfe))
            self.assertEqual("Hallo Ada,\n\nsehr gern.", entwuerfe[0].text_ki)
            self.assertEqual("wartet", entwuerfe[0].status)

    async def test_klassifikationsaufgabe_erzeugt_entwurf_automatisch(self):
        async with SessionLocal() as session:
            session.add(MailAufgabe(
                mail_id=self.mail_id,
                position=1,
                aufgabe_typ="ANTWORTVORSCHLAG_ERSTELLEN",
                status="wartet",
            ))
            await session.commit()

        generator = AsyncMock(return_value="Guten Tag,\n\nvielen Dank für Ihre Nachricht.")
        with patch("app.antworten.antwortentwurf_erzeugen", generator):
            ergebnis = await wartende_aufgaben_ausfuehren(self.mail_id)

        self.assertEqual("keine_aufgabe_offen", ergebnis["status"])
        async with SessionLocal() as session:
            aufgabe = (await session.execute(select(MailAufgabe))).scalar_one()
            entwurf = (await session.execute(select(Entwurf))).scalar_one()
            log = (await session.execute(
                select(Aktionslog).where(
                    Aktionslog.ereignis == "antwortvorschlag_erstellt"
                )
            )).scalar_one()
            self.assertEqual("erledigt", aufgabe.status)
            self.assertEqual("wartet", entwurf.status)
            self.assertIn("Entwurf", log.detail)


if __name__ == "__main__":
    unittest.main()
