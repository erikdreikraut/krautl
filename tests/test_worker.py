import os
import unittest
from email.message import EmailMessage
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_worker.db")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")

from sqlalchemy import func, select

from app.db import SessionLocal, engine
from app.imap_client import PostfachConfig
from app.models import Aktionslog, Base, Klassifikation, Mail, MailAufgabe
from app.worker import (
    klassifizierungsdaten_fuer_transkript,
    postfach_abrufen_und_klassifizieren,
)


class WorkerInterneMailTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)

    async def test_transkriptionsmail_wird_nach_anliegen_klassifiziert(self):
        nachricht = EmailMessage()
        nachricht["Message-ID"] = "<krautl-audio-17@dreikraut.de>"
        nachricht["X-Krautl-Generated"] = "audio-transcription"
        nachricht["From"] = "Krautl <service@dreikraut.de>"
        nachricht["To"] = "service@dreikraut.de"
        nachricht["Subject"] = "[TRANSKRIPTION] Anruf von Brien"
        nachricht.set_content(
            "Ich habe vorige Woche bestellt und möchte wissen, wann es kommt."
        )
        nachricht.add_attachment(
            b"audio", maintype="audio", subtype="mpeg", filename="anruf.mp3"
        )
        config = PostfachConfig(
            "service", "imap.example.test", "service@dreikraut.de", "pw"
        )

        async with SessionLocal() as session:
            session.add_all([
                Klassifikation(
                    klassifikation_id="KUNDE_TRACKING",
                    hauptkategorie="Kundenservice",
                    unterkategorie="Versandstatus",
                    beschreibung="Frage zum Lieferstatus",
                    standard_prio="normal",
                    aktion_id="MAIL_VERSCHIEBEN",
                ),
                Klassifikation(
                    klassifikation_id="AUDIO_ANRUFBEANTWORTER",
                    hauptkategorie="Kommunikation",
                    unterkategorie="Sprachnachricht",
                    beschreibung="Noch nicht transkribierte Audionachricht",
                    standard_prio="normal",
                    aktion_id="AUDIO_TRANSKRIBIEREN",
                ),
                Klassifikation(
                    klassifikation_id="INTERN_AUFGABEN",
                    hauptkategorie="Intern",
                    unterkategorie="Aufgabe",
                    beschreibung="Interner Aufgabenhinweis",
                    standard_prio="normal",
                    aktion_id="BESTAETIGUNG_EINHOLEN",
                ),
            ])
            await session.commit()

        klassifikation = {
            "klassifikation_id": "KUNDE_TRACKING",
            "aktion_erforderlich": True,
            "originalsprache": "Deutsch",
            "sicherheit": 0.96,
        }

        with patch(
            "app.worker.neue_mails_abrufen",
            return_value=[{
                "uid": 4711,
                "postfach": "service",
                "eml": nachricht.as_bytes(),
            }],
        ), patch(
            "app.worker.klassifiziere", return_value=klassifikation
        ) as klassifiziere:
            anzahl = await postfach_abrufen_und_klassifizieren(config)

        async with SessionLocal() as session:
            mail = (await session.execute(select(Mail))).scalar_one()
            aufgaben = (await session.execute(
                select(func.count()).select_from(MailAufgabe)
            )).scalar_one()
            logs = (await session.execute(
                select(func.count()).select_from(Aktionslog)
            )).scalar_one()

        self.assertEqual(1, anzahl)
        self.assertTrue(mail.im_krautl_posteingang)
        self.assertEqual("KUNDE_TRACKING", mail.klassifikation_id)
        self.assertEqual(4711, mail.imap_uid)
        self.assertEqual(0, aufgaben)
        self.assertEqual(1, logs)
        klassifiziere.assert_called_once()
        klassifizierungs_mail, klassifizierungs_katalog, _beispiele = (
            klassifiziere.call_args.args
        )
        self.assertTrue(klassifizierungs_mail["krautl_generiert"])
        self.assertEqual([], klassifizierungs_mail["anhang_dateinamen"])
        self.assertEqual(
            ["KUNDE_TRACKING"],
            [eintrag["klassifikation_id"] for eintrag in klassifizierungs_katalog],
        )

    def test_normale_mail_bleibt_unveraendert(self):
        mail = {"betreff": "Kundenfrage", "anhang_dateinamen": ["datei.pdf"]}
        katalog = [{"klassifikation_id": "KUNDE_PRODUKTFRAGE"}]
        self.assertEqual(
            (mail, katalog),
            klassifizierungsdaten_fuer_transkript(mail, katalog),
        )

    async def test_verbotene_audio_antwort_des_modells_startet_keine_schleife(self):
        nachricht = EmailMessage()
        nachricht["Message-ID"] = "<krautl-audio-18@dreikraut.de>"
        nachricht["X-Krautl-Generated"] = "audio-transcription"
        nachricht["From"] = "Krautl <service@dreikraut.de>"
        nachricht["To"] = "service@dreikraut.de"
        nachricht["Subject"] = "[TRANSKRIPTION] Anruf von unbekannt"
        nachricht.set_content("Unverständliches Transkript")
        nachricht.add_attachment(
            b"audio", maintype="audio", subtype="mpeg", filename="anruf.mp3"
        )
        config = PostfachConfig(
            "service", "imap.example.test", "service@dreikraut.de", "pw"
        )
        async with SessionLocal() as session:
            session.add_all([
                Klassifikation(
                    klassifikation_id="AUDIO_ANRUFBEANTWORTER",
                    hauptkategorie="Kommunikation",
                    unterkategorie="Sprachnachricht",
                    beschreibung="Noch nicht transkribierte Audionachricht",
                    standard_prio="normal",
                    aktion_id="AUDIO_TRANSKRIBIEREN",
                ),
                Klassifikation(
                    klassifikation_id="KUNDE_TRACKING",
                    hauptkategorie="Kundenservice",
                    unterkategorie="Versandstatus",
                    beschreibung="Frage zum Lieferstatus",
                    standard_prio="normal",
                    aktion_id="MAIL_VERSCHIEBEN",
                ),
            ])
            await session.commit()

        with patch(
            "app.worker.neue_mails_abrufen",
            return_value=[{
                "uid": 4712,
                "postfach": "service",
                "eml": nachricht.as_bytes(),
            }],
        ), patch(
            "app.worker.klassifiziere",
            return_value={
                "klassifikation_id": "AUDIO_ANRUFBEANTWORTER",
                "aktion_erforderlich": True,
                "originalsprache": "Deutsch",
                "sicherheit": 0.5,
            },
        ):
            anzahl = await postfach_abrufen_und_klassifizieren(config)

        async with SessionLocal() as session:
            mail = (await session.execute(select(Mail))).scalar_one()
            aufgaben = (await session.execute(
                select(func.count()).select_from(MailAufgabe)
            )).scalar_one()
        self.assertEqual(1, anzahl)
        self.assertTrue(mail.im_krautl_posteingang)
        self.assertIsNone(mail.klassifikation_id)
        self.assertEqual(0, aufgaben)


if __name__ == "__main__":
    unittest.main()
