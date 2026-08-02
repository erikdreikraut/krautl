import os
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_antwortentwuerfe.db")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")

from sqlalchemy import select

from app.db import SessionLocal, engine
from app.antworten import pruefergebnis_absichern
from app.main import (
    EntwurfFreigabe, entwurf_freigeben, mail_antwortentwurf_erzeugen,
)
from app.aufgaben import wartende_aufgaben_ausfuehren
from app.models import Aktionslog, Base, Entwurf, Mail, MailAufgabe, Postfach


TEST_BENUTZER = {
    "benutzername": "erik",
    "name": "Erik Schweitzer",
    "titel": None,
    "rolle": "admin",
}


def test_request():
    return SimpleNamespace(state=SimpleNamespace(benutzer=TEST_BENUTZER))


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
                erstes = await mail_antwortentwurf_erzeugen(self.mail_id, test_request(), session)
            async with SessionLocal() as session:
                zweites = await mail_antwortentwurf_erzeugen(self.mail_id, test_request(), session)

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

    async def test_freigabe_prueft_und_sendet_nur_testantwort(self):
        async with SessionLocal() as session:
            entwurf = Entwurf(
                mail_id=self.mail_id,
                text_ki="Guten Tag,\n\nvielen Dank.",
                status="wartet",
            )
            session.add(entwurf)
            await session.commit()
            entwurf_id = entwurf.id

        pruefung = AsyncMock(return_value={"freigabefaehig": True, "probleme": []})
        versand = AsyncMock(return_value={
            "message_id": "<test-1@dreikraut.de>",
            "empfaenger": "info@erikschweitzer.de",
        })
        with patch("app.main.antwort_vor_versand_pruefen", pruefung), \
             patch("app.main.testantwort_senden", versand):
            async with SessionLocal() as session:
                ergebnis = await entwurf_freigeben(
                    entwurf_id,
                    EntwurfFreigabe(finaler_text="Guten Tag,\n\nvielen Dank."),
                    test_request(),
                    session,
                )

        self.assertEqual("versendet", ergebnis["status"])
        self.assertEqual("info@erikschweitzer.de", ergebnis["empfaenger"])
        versand.assert_awaited_once()
        async with SessionLocal() as session:
            entwurf = await session.get(Entwurf, entwurf_id)
            self.assertEqual("versendet", entwurf.status)
            self.assertIsNotNone(entwurf.versendet_am)
            self.assertIn("\nErik Schweitzer\n-- \ndreikraut e.K.\n", entwurf.text_final)

    async def test_offene_punkte_blockieren_den_versand(self):
        async with SessionLocal() as session:
            entwurf = Entwurf(
                mail_id=self.mail_id,
                text_ki="[Vor Versand prüfen/ergänzen: Bestellnummer]",
                status="wartet",
            )
            session.add(entwurf)
            await session.commit()
            entwurf_id = entwurf.id

        pruefung = AsyncMock(return_value={
            "freigabefaehig": False,
            "probleme": ["Bestellnummer fehlt"],
        })
        versand = AsyncMock(return_value={
            "message_id": "<test-2@dreikraut.de>",
            "empfaenger": "info@erikschweitzer.de",
        })
        with patch("app.main.antwort_vor_versand_pruefen", pruefung), \
             patch("app.main.testantwort_senden", versand):
            async with SessionLocal() as session:
                ergebnis = await entwurf_freigeben(
                    entwurf_id,
                    EntwurfFreigabe(
                        finaler_text="[Vor Versand prüfen/ergänzen: Bestellnummer]"
                    ),
                    test_request(),
                    session,
                )

        self.assertEqual("pruefung_noetig", ergebnis["status"])
        versand.assert_not_awaited()
        async with SessionLocal() as session:
            entwurf = await session.get(Entwurf, entwurf_id)
            self.assertEqual("wartet", entwurf.status)

    async def test_dritter_versuch_sendet_ohne_weitere_ki_pruefung(self):
        async with SessionLocal() as session:
            entwurf = Entwurf(
                mail_id=self.mail_id,
                text_ki="Guten Tag,\n\nTestantwort.",
                status="wartet",
            )
            session.add(entwurf)
            await session.commit()
            entwurf_id = entwurf.id

        pruefung = AsyncMock(return_value={
            "freigabefaehig": False,
            "probleme": ["Kontroll-KI erhebt einen Einwand"],
        })
        versand = AsyncMock(return_value={
            "message_id": "<test-3@dreikraut.de>",
            "empfaenger": "info@erikschweitzer.de",
        })
        ergebnisse = []
        with patch("app.main.antwort_vor_versand_pruefen", pruefung), \
             patch("app.main.testantwort_senden", versand):
            for _ in range(3):
                async with SessionLocal() as session:
                    ergebnisse.append(await entwurf_freigeben(
                        entwurf_id,
                        EntwurfFreigabe(finaler_text="Guten Tag,\n\nTestantwort."),
                        test_request(),
                        session,
                    ))

        self.assertEqual(
            ["pruefung_noetig", "pruefung_noetig", "versendet"],
            [ergebnis["status"] for ergebnis in ergebnisse],
        )
        self.assertFalse(ergebnisse[0]["naechster_versuch_ohne_pruefung"])
        self.assertTrue(ergebnisse[1]["naechster_versuch_ohne_pruefung"])
        self.assertTrue(ergebnisse[2]["pruefung_uebersprungen"])
        self.assertEqual(2, pruefung.await_count)
        versand.assert_awaited_once()
        async with SessionLocal() as session:
            entwurf = await session.get(Entwurf, entwurf_id)
            self.assertEqual("versendet", entwurf.status)

    def test_eckige_klammern_blockieren_auch_bei_ki_fehlurteil(self):
        ergebnis = pruefergebnis_absichern(
            {"freigabefaehig": True, "probleme": []},
            "Hallo [Vor Versand prüfen/ergänzen: Versand anstoßen]",
        )
        self.assertFalse(ergebnis["freigabefaehig"])
        self.assertTrue(ergebnis["probleme"])


if __name__ == "__main__":
    unittest.main()
