import os
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

os.environ.setdefault(
    "DATABASE_URL", "sqlite+aiosqlite:///./test_transkript_nachklassifizierung.db"
)
os.environ.setdefault("ANTHROPIC_API_KEY", "test")

from sqlalchemy import select

from app.db import SessionLocal, engine
from app.models import (
    Aktionslog, Base, Klassifikation, KlassifikationAufgabe, Mail, MailAufgabe,
    Postfach,
)
from scripts.klassifiziere_transkripte_nach import nachklassifizieren


class TranskriptNachklassifizierungTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)

    async def test_verstecktes_transkript_wird_als_tracking_sichtbar(self):
        async with SessionLocal() as session:
            postfach = Postfach(
                adresse="service@dreikraut.de",
                funktion="service",
                imap_host="imap.example.test",
            )
            tracking = Klassifikation(
                klassifikation_id="KUNDE_TRACKING",
                hauptkategorie="Kundenservice",
                unterkategorie="Versandstatus",
                beschreibung="Frage zum Lieferstatus",
                standard_prio="normal",
                aktion_id="MAIL_VERSCHIEBEN",
            )
            audio = Klassifikation(
                klassifikation_id="AUDIO_ANRUFBEANTWORTER",
                hauptkategorie="Kommunikation",
                unterkategorie="Sprachnachricht",
                beschreibung="Noch nicht transkribierte Audionachricht",
                standard_prio="normal",
                aktion_id="AUDIO_TRANSKRIBIEREN",
            )
            session.add_all([postfach, tracking, audio])
            await session.flush()
            session.add(KlassifikationAufgabe(
                klassifikation_id="KUNDE_TRACKING",
                position=1,
                aufgabe_typ="BESTAETIGUNG_EINHOLEN",
                bestaetiger_typ="alle",
            ))
            session.add(Mail(
                message_id="<krautl-audio-17@dreikraut.de>",
                imap_uid=4711,
                postfach_id=postfach.id,
                absender_name="Krautl",
                absender_adresse="service@dreikraut.de",
                betreff="Anruf transkribiert: Brien",
                text_auszug="Ich möchte wissen, wann meine Bestellung kommt.",
                empfangen_am=datetime.now(timezone.utc),
                anhang_dateinamen=["anruf.mp3"],
                im_krautl_posteingang=False,
            ))
            await session.commit()

        ergebnis_ki = {
            "klassifikation_id": "KUNDE_TRACKING",
            "aktion_erforderlich": True,
            "originalsprache": "Deutsch",
            "sicherheit": 0.97,
        }
        with patch(
            "scripts.klassifiziere_transkripte_nach.klassifiziere",
            return_value=ergebnis_ki,
        ) as klassifiziere:
            async with SessionLocal() as session:
                ergebnis = await nachklassifizieren(session)

        async with SessionLocal() as session:
            mail = (await session.execute(select(Mail))).scalar_one()
            aufgabe = (await session.execute(select(MailAufgabe))).scalar_one()
            log = (await session.execute(select(Aktionslog))).scalar_one()

        self.assertEqual(1, ergebnis["sichtbar_gemacht"])
        self.assertTrue(mail.im_krautl_posteingang)
        self.assertEqual("KUNDE_TRACKING", mail.klassifikation_id)
        self.assertEqual(["anruf.mp3"], mail.anhang_dateinamen)
        self.assertEqual("BESTAETIGUNG_EINHOLEN", aufgabe.aufgabe_typ)
        self.assertIn("Telefontranskript nachklassifiziert", log.detail)
        katalog_ids = [
            eintrag["klassifikation_id"]
            for eintrag in klassifiziere.call_args.args[1]
        ]
        self.assertNotIn("AUDIO_ANRUFBEANTWORTER", katalog_ids)

        with patch(
            "scripts.klassifiziere_transkripte_nach.klassifiziere"
        ) as zweiter_aufruf:
            async with SessionLocal() as session:
                wiederholung = await nachklassifizieren(session)
        self.assertEqual(0, wiederholung["gefunden"])
        zweiter_aufruf.assert_not_called()


if __name__ == "__main__":
    unittest.main()
