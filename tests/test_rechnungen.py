import os
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_rechnungen.db")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")
os.environ.setdefault("DROPBOX_ACCESS_TOKEN", "test")

from sqlalchemy import select

from app.db import SessionLocal, engine
from app.mail_parser import rechnungsanhaenge
from app.main import liste_rechnungen
from app.models import Base, Mail, Postfach, Rechnung
from app.rechnungen import (
    _bild_mime_type,
    _zahlungsstatus_absichern,
    rechnungsdatei_aus_mail_laden,
    rechnung_aus_rohdaten_verarbeiten,
    rechnung_verarbeiten,
)


EML = b"""From: Lieferant <rechnung@example.test>\r
To: einkauf@dreikraut.de\r
Subject: Rechnung 4711\r
Message-ID: <rechnung@example.test>\r
MIME-Version: 1.0\r
Content-Type: multipart/mixed; boundary=x\r
\r
--x\r
Content-Type: text/plain; charset=utf-8\r
\r
Ihre Rechnung.\r
--x\r
Content-Type: application/pdf\r
Content-Disposition: attachment; filename=rechnung.pdf\r
Content-Transfer-Encoding: base64\r
\r
JVBERi0xLjQ=\r
--x--\r
"""


class RechnungenTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        async with SessionLocal() as session:
            postfach = Postfach(adresse="einkauf@dreikraut.de", funktion="einkauf", imap_host="imap.test")
            session.add(postfach)
            await session.flush()
            mail = Mail(
                message_id="<rechnung@example.test>", imap_uid=7, postfach_id=postfach.id,
                absender_name="Lieferant", absender_adresse="rechnung@example.test",
                betreff="Rechnung 4711", text_auszug="Ihre Rechnung",
                empfangen_am=datetime.now(timezone.utc),
            )
            session.add(mail)
            await session.commit()
            self.mail_id = mail.id

    def test_pdf_anhang_wird_extrahiert(self):
        anhaenge = rechnungsanhaenge(EML)
        self.assertEqual(1, len(anhaenge))
        self.assertEqual(".pdf", anhaenge[0]["endung"])

    def test_bildformat_wird_anhand_des_inhalts_statt_des_headers_erkannt(self):
        jpeg = {"inhalt": b"\xff\xd8\xff\xe0daten", "mime_type": "image/png"}
        png = {
            "inhalt": b"\x89PNG\r\n\x1a\ndaten",
            "mime_type": "application/octet-stream",
        }
        self.assertEqual("image/jpeg", _bild_mime_type(jpeg))
        self.assertEqual("image/png", _bild_mime_type(png))

    def test_verrechnung_mit_guthaben_ist_nicht_offen(self):
        daten = _zahlungsstatus_absichern({
            "zahlungsstatus": "offen",
            "zahlungshinweis": "Seite 2: Rechnungsbetrag wird vom Guthaben abgezogen; Rest wird ausgezahlt.",
        })
        self.assertEqual("automatisch", daten["zahlungsstatus"])

    def test_unbelegte_automatik_bleibt_zur_pruefung_sichtbar(self):
        daten = _zahlungsstatus_absichern({
            "zahlungsstatus": "automatisch",
            "zahlungshinweis": "Zahlbar innerhalb von 14 Tagen.",
        })
        self.assertEqual("unklar", daten["zahlungsstatus"])

    def test_verneinte_abbuchung_macht_offene_rechnung_nicht_automatisch(self):
        daten = _zahlungsstatus_absichern({
            "zahlungsstatus": "offen",
            "zahlungshinweis": "Der Betrag wird nicht automatisch abgebucht. Bitte überweisen.",
        })
        self.assertEqual("offen", daten["zahlungsstatus"])

    async def test_rechnungsansicht_laed_original_aus_verschobener_mail(self):
        async with SessionLocal() as session:
            mail = await session.get(Mail, self.mail_id)
        rechnung = Rechnung(
            aussteller="Test GmbH",
            rechnungsnummer="4711",
            waehrung="EUR",
            dateipfad="/Rechnungen/2026/2026-07-21-Test-GmbH-4711.pdf",
        )
        ziel = type("Config", (), {"user": "erik@dreikraut.de"})()
        with patch("app.rechnungen.lade_postfaecher", return_value=[ziel]), \
             patch(
                 "app.rechnungen.mail_rohdaten_nach_message_id_laden",
                 return_value=EML,
             ) as laden:
            dateiname, inhalt = await rechnungsdatei_aus_mail_laden(
                rechnung,
                mail,
                "einkauf@dreikraut.de",
                "erik@dreikraut.de",
                "Rechnungen",
            )

        self.assertEqual("rechnung.pdf", dateiname)
        self.assertEqual(b"%PDF-1.4", inhalt)
        laden.assert_called_once_with(
            ziel, "<rechnung@example.test>", "Rechnungen"
        )

    async def test_rechnung_wird_abgelegt_und_dedupliziert(self):
        config = type("Config", (), {"user": "einkauf@dreikraut.de"})()
        analyse = {
            "ist_rechnung": True, "aussteller": "Test GmbH", "rechnungsnummer": "4711",
            "rechnungsdatum": "2026-07-21", "faellig_am": "2026-08-04",
            "bruttobetrag": 119.0, "waehrung": "EUR", "zahlungsstatus": "offen",
            "zahlungshinweis": "Bitte überweisen",
        }
        dbx = MagicMock()
        with patch("app.rechnungen.lade_postfaecher", return_value=[config]), \
             patch("app.rechnungen.mail_rohdaten_laden", return_value=EML), \
             patch("app.rechnungen._analysiere", return_value=analyse), \
             patch("app.rechnungen._dropbox_client", return_value=dbx):
            async with SessionLocal() as session:
                mail = await session.get(Mail, self.mail_id)
                erstes = await rechnung_verarbeiten(session, mail)
                await session.commit()
            async with SessionLocal() as session:
                mail = await session.get(Mail, self.mail_id)
                zweites = await rechnung_verarbeiten(session, mail)
                await session.commit()

        self.assertFalse(erstes["rechnungen"][0]["dublette"])
        self.assertTrue(zweites["rechnungen"][0]["dublette"])
        dbx.files_upload.assert_called_once()
        pfad = dbx.files_upload.call_args.args[1]
        self.assertEqual("/Rechnungen/2026/2026-07-21-Test-GmbH-4711.pdf", pfad)
        async with SessionLocal() as session:
            rechnungen = (await session.execute(select(Rechnung))).scalars().all()
            self.assertEqual(1, len(rechnungen))
            self.assertEqual("offen", rechnungen[0].zahlungsstatus)

    async def test_historischer_lauf_kann_direkten_eingangsordner_nutzen(self):
        analyse = {
            "ist_rechnung": True, "aussteller": "Test GmbH", "rechnungsnummer": "4711",
            "rechnungsdatum": "2026-02-03", "faellig_am": "2026-02-17",
            "bruttobetrag": 119.0, "waehrung": "EUR", "zahlungsstatus": "offen",
            "zahlungshinweis": "Bitte überweisen",
        }
        dbx = MagicMock()
        with patch("app.rechnungen._analysiere", return_value=analyse), \
             patch("app.rechnungen._dropbox_client", return_value=dbx):
            async with SessionLocal() as session:
                mail = await session.get(Mail, self.mail_id)
                await rechnung_aus_rohdaten_verarbeiten(
                    session,
                    mail,
                    EML,
                    zielordner="/Rechnungen/Eingang",
                    jahresordner=False,
                )
                await session.commit()

        pfad = dbx.files_upload.call_args.args[1]
        self.assertEqual(
            "/Rechnungen/Eingang/2026-02-03-Test-GmbH-4711.pdf",
            pfad,
        )

    async def test_negativer_rechnungsbefund_benoetigt_keine_dropbox_verbindung(self):
        analyse = {"ist_rechnung": False}
        dropbox_client = MagicMock(side_effect=RuntimeError("Dropbox nicht verbunden"))
        with patch("app.rechnungen._analysiere", return_value=analyse), \
             patch("app.rechnungen._dropbox_client", dropbox_client):
            async with SessionLocal() as session:
                mail = await session.get(Mail, self.mail_id)
                with self.assertRaisesRegex(RuntimeError, "keine Rechnung"):
                    await rechnung_aus_rohdaten_verarbeiten(session, mail, EML)

        dropbox_client.assert_not_called()

    async def test_fehlendes_rechnungsdatum_nutzt_nachvollziehbar_eingangsdatum(self):
        analyse = {
            "ist_rechnung": True, "aussteller": "Test GmbH", "rechnungsnummer": "99",
            "rechnungsdatum": "", "faellig_am": "", "bruttobetrag": 10.0,
            "waehrung": "EUR", "zahlungsstatus": "offen",
            "zahlungshinweis": "Bitte ueberweisen",
        }
        dbx = MagicMock()
        with patch("app.rechnungen._analysiere", return_value=analyse), \
             patch("app.rechnungen._dropbox_client", return_value=dbx):
            async with SessionLocal() as session:
                mail = await session.get(Mail, self.mail_id)
                mail.empfangen_am = datetime(2026, 2, 4, 12, 0, tzinfo=timezone.utc)
                await rechnung_aus_rohdaten_verarbeiten(
                    session,
                    mail,
                    EML,
                    zielordner="/Rechnungen/Eingang",
                    jahresordner=False,
                )
                await session.commit()

        pfad = dbx.files_upload.call_args.args[1]
        self.assertTrue(pfad.startswith("/Rechnungen/Eingang/2026-02-04-"))
        async with SessionLocal() as session:
            rechnung = (await session.execute(select(Rechnung))).scalar_one()
        self.assertIn("Eingangsdatum", rechnung.zahlungshinweis)

    async def test_komplettliste_sortiert_nach_mail_eingang_und_liefert_zeitpunkt(self):
        neuer_eingang = datetime(2026, 8, 5, 15, 0, tzinfo=timezone.utc)
        alter_eingang = neuer_eingang - timedelta(days=4)
        async with SessionLocal() as session:
            neue_mail = await session.get(Mail, self.mail_id)
            neue_mail.empfangen_am = neuer_eingang
            postfach = await session.get(Postfach, neue_mail.postfach_id)
            alte_mail = Mail(
                message_id="<alte-rechnung@example.test>",
                imap_uid=6,
                postfach_id=postfach.id,
                absender_name="Alter Lieferant",
                absender_adresse="alt@example.test",
                betreff="Alte Rechnung",
                text_auszug="Alte Rechnung",
                empfangen_am=alter_eingang,
            )
            session.add(alte_mail)
            await session.flush()
            neue_rechnung = Rechnung(
                mail_id=neue_mail.id,
                aussteller="Neuer Lieferant",
                rechnungsnummer="NEU",
                rechnungsdatum=neuer_eingang,
                faellig_am=neuer_eingang + timedelta(days=30),
                waehrung="EUR",
                zahlungsstatus="automatisch",
            )
            alte_rechnung = Rechnung(
                mail_id=alte_mail.id,
                aussteller="Alter Lieferant",
                rechnungsnummer="ALT",
                rechnungsdatum=alter_eingang,
                # Die alte Rechnung ist früher fällig. Das darf die
                # chronologische Eingangssortierung nicht mehr überstimmen.
                faellig_am=alter_eingang + timedelta(days=1),
                waehrung="EUR",
                zahlungsstatus="automatisch",
            )
            session.add_all([neue_rechnung, alte_rechnung])
            await session.commit()

        request = SimpleNamespace(state=SimpleNamespace(
            benutzer={"rolle": "admin", "name": "Test Admin"}
        ))
        async with SessionLocal() as session:
            liste = await liste_rechnungen(request, session)

        self.assertEqual(["NEU", "ALT"], [r["rechnungsnummer"] for r in liste])
        self.assertEqual(
            neuer_eingang.replace(tzinfo=None),
            liste[0]["eingegangen_am"].replace(tzinfo=None),
        )


if __name__ == "__main__":
    unittest.main()
