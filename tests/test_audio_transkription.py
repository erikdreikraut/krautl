import os
import unittest
from datetime import datetime, timezone
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_audio_transkription.db")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")

from sqlalchemy import select

from app.audio_transkription import (
    _ausgabemail, _fallback_abschnitte, _vergleichstext, audioanhaenge,
)
from app.aufgaben import wartende_aufgaben_ausfuehren
from app.db import SessionLocal, engine
from app.models import Aktionslog, Base, Mail, MailAufgabe, Postfach


class AudioTranskriptionTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)

    def test_audioanhang_wird_erkannt_und_ausgabemail_enthaelt_original(self):
        eingang = EmailMessage()
        eingang["Subject"] = "Mailbox"
        eingang.set_content("Neue Sprachnachricht")
        eingang.add_attachment(
            b"fake-mp3", maintype="audio", subtype="mpeg", filename="anruf.mp3"
        )
        anhaenge = audioanhaenge(eingang.as_bytes())
        self.assertEqual(["anruf.mp3"], [a["dateiname"] for a in anhaenge])

        mail = Mail(
            id=17, betreff="Mailbox", empfangen_am=datetime.now(timezone.utc)
        )
        raw, message_id = _ausgabemail(
            mail, anhaenge,
            ["Frau **Müller** ruft wegen der **Bestellung 123** an.\n\nRückruf morgen."],
            "Frau Müller",
        )
        ausgang = BytesParser(policy=policy.default).parsebytes(raw)
        self.assertEqual("<krautl-audio-17@dreikraut.de>", message_id)
        self.assertEqual("audio-transcription", ausgang["X-Krautl-Generated"])
        self.assertEqual("service@dreikraut.de", ausgang["To"])
        self.assertEqual("Anruf transkribiert: Frau Müller", ausgang["Subject"])
        self.assertIn(
            "Anruf erhalten von Frau Müller, automatisch transkribiert:",
            ausgang.get_body(preferencelist=("html",)).get_content(),
        )
        self.assertIn("<strong>Müller</strong>", ausgang.get_body(preferencelist=("html",)).get_content())
        self.assertEqual(
            ["anruf.mp3"],
            [teil.get_filename() for teil in ausgang.iter_attachments()],
        )

    def test_fallback_gliedert_ohne_den_wortlaut_zu_veraendern(self):
        original = (
            "Hallo, hier ist Franz Müller. Ich rufe wegen der Bestellung an. "
            "Die Nummer ist 242989. Bitte drei Packungen senden."
        )
        gegliedert = "\n\n".join(_fallback_abschnitte(original))
        self.assertEqual(_vergleichstext(original), _vergleichstext(gegliedert))

    async def test_aufgabe_wird_ausgefuehrt_und_protokolliert(self):
        async with SessionLocal() as session:
            postfach = Postfach(
                adresse="info@dreikraut.de", funktion="info",
                imap_host="imap.example.test",
            )
            session.add(postfach)
            await session.flush()
            mail = Mail(
                message_id="<audio@example.test>", imap_uid=88,
                postfach_id=postfach.id, betreff="Neue Sprachnachricht",
                absender_name="Telefonanlage", absender_adresse="telefon@example.test",
                text_auszug="Audio", empfangen_am=datetime.now(timezone.utc),
            )
            session.add(mail)
            await session.flush()
            session.add(MailAufgabe(
                mail_id=mail.id, position=1, aufgabe_typ="AUDIO_TRANSKRIBIEREN",
                status="wartet",
            ))
            await session.commit()
            mail_id = mail.id

        ergebnis_mock = {
            "audio_dateien": 1, "neu_eingestellt": True,
            "ziel": "service@dreikraut.de/INBOX",
        }
        with patch(
            "app.aufgaben.audio_verarbeiten",
            new=AsyncMock(return_value=ergebnis_mock),
        ) as verarbeiten:
            ergebnis = await wartende_aufgaben_ausfuehren(mail_id)

        self.assertEqual("keine_aufgabe_offen", ergebnis["status"])
        verarbeiten.assert_awaited_once()
        async with SessionLocal() as session:
            aufgabe = (await session.execute(select(MailAufgabe))).scalar_one()
            log = (await session.execute(select(Aktionslog))).scalar_one()
            self.assertEqual("erledigt", aufgabe.status)
            self.assertEqual("audio_transkribiert", log.ereignis)
            self.assertIn("service@dreikraut.de/INBOX", log.detail)


if __name__ == "__main__":
    unittest.main()
