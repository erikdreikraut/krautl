import os
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import select

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_mail_loeschen.db")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")

from app.db import SessionLocal, engine
from app.imap_client import PostfachConfig
from app.main import mail_loeschen
from app.models import (
    Aktionslog, Base, Klassifikation, Mail, MailAufgabe, Postfach,
    RollenMailzugriff,
)


ADMIN_REQUEST = SimpleNamespace(state=SimpleNamespace(benutzer={
    "benutzername": "erik", "name": "Erik Schweitzer", "rolle": "admin",
}))
SACHBEARBEITER_REQUEST = SimpleNamespace(state=SimpleNamespace(benutzer={
    "benutzername": "gursewak", "name": "Gursewak Singh",
    "rolle": "sachbearbeiter",
}))


class MailLoeschenTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        async with SessionLocal() as session:
            postfach = Postfach(
                adresse="service@dreikraut.de",
                funktion="service",
                imap_host="imap.test",
            )
            klassifikation = Klassifikation(
                klassifikation_id="KUNDE_TEST",
                hauptkategorie="Kundenservice",
                unterkategorie="Test",
                beschreibung="Test",
                standard_prio="normal",
                zielpostfach="service@dreikraut.de",
                zielordner="INBOX",
                aktion_id="BESTAETIGUNG_EINHOLEN",
            )
            session.add_all([postfach, klassifikation])
            await session.flush()
            mail = Mail(
                message_id="<loeschen@example.test>",
                imap_uid=17,
                postfach_id=postfach.id,
                absender_name="Testkunde",
                absender_adresse="kunde@example.test",
                betreff="Bitte löschen",
                text_auszug="Test",
                empfangen_am=datetime.now(timezone.utc),
                klassifikation_id=klassifikation.klassifikation_id,
                im_krautl_posteingang=True,
            )
            session.add(mail)
            await session.flush()
            session.add(MailAufgabe(
                mail_id=mail.id,
                position=1,
                aufgabe_typ="BESTAETIGUNG_EINHOLEN",
                status="wartet",
            ))
            await session.commit()
            self.mail_id = mail.id
        self.config = PostfachConfig(
            "service", "imap.test", "service@dreikraut.de", "pw"
        )

    async def test_loeschen_entfernt_imap_mail_und_blendet_krautl_eintrag_aus(self):
        async with SessionLocal() as session:
            with (
                patch("app.main.lade_postfaecher", return_value=[self.config]),
                patch("app.main.mail_imap_loeschen") as imap_loeschen,
            ):
                ergebnis = await mail_loeschen(
                    self.mail_id, ADMIN_REQUEST, session
                )
            imap_loeschen.assert_called_once_with(
                self.config, 17, "<loeschen@example.test>"
            )
        self.assertEqual(
            {"status": "geloescht", "imap_geloescht": True}, ergebnis
        )

        async with SessionLocal() as session:
            mail = await session.get(Mail, self.mail_id)
            aufgabe = (await session.execute(
                select(MailAufgabe).where(MailAufgabe.mail_id == self.mail_id)
            )).scalar_one()
            log = (await session.execute(
                select(Aktionslog).where(
                    Aktionslog.mail_id == self.mail_id,
                    Aktionslog.ereignis == "mail_geloescht",
                )
            )).scalar_one()
            self.assertFalse(mail.im_krautl_posteingang)
            self.assertEqual("abgebrochen", aufgabe.status)
            self.assertIn("Erik Schweitzer", log.detail)

    async def test_imap_fehler_wird_protokolliert_aber_mail_ausgeblendet(self):
        async with SessionLocal() as session:
            with (
                patch("app.main.lade_postfaecher", return_value=[self.config]),
                patch(
                    "app.main.mail_imap_loeschen",
                    side_effect=RuntimeError("Mail bereits verschoben"),
                ),
            ):
                ergebnis = await mail_loeschen(
                    self.mail_id, ADMIN_REQUEST, session
                )
        self.assertEqual("ausgeblendet", ergebnis["status"])
        self.assertFalse(ergebnis["imap_geloescht"])

        async with SessionLocal() as session:
            mail = await session.get(Mail, self.mail_id)
            aufgabe = (await session.execute(
                select(MailAufgabe).where(MailAufgabe.mail_id == self.mail_id)
            )).scalar_one()
            log = (await session.execute(
                select(Aktionslog).where(
                    Aktionslog.mail_id == self.mail_id,
                    Aktionslog.ereignis == "mail_loeschen_fehlgeschlagen",
                )
            )).scalar_one()
            self.assertFalse(mail.im_krautl_posteingang)
            self.assertEqual("abgebrochen", aufgabe.status)
            self.assertIn("Mail bereits verschoben", log.detail)
            self.assertIn("trotzdem aus Krautl-Posteingang entfernt", log.detail)

    async def test_rollensperre_verhindert_auch_das_loeschen(self):
        async with SessionLocal() as session:
            session.add(RollenMailzugriff(
                rolle="sachbearbeiter",
                klassifikation_id="KUNDE_TEST",
                darf_sehen=False,
            ))
            await session.commit()
            with patch("app.main.mail_imap_loeschen") as imap_loeschen:
                with self.assertRaises(HTTPException) as fehler:
                    await mail_loeschen(
                        self.mail_id, SACHBEARBEITER_REQUEST, session
                    )
            imap_loeschen.assert_not_called()
        self.assertEqual(403, fehler.exception.status_code)


if __name__ == "__main__":
    unittest.main()
