import os
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_rechnungen.db")
os.environ.setdefault("OPENAI_API_KEY", "test")
os.environ.setdefault("DROPBOX_ACCESS_TOKEN", "test")

from sqlalchemy import select

from app.db import SessionLocal, engine
from app.mail_parser import rechnungsanhaenge
from app.main import liste_rechnungen
from app.models import Aktionslog, Base, Mail, Postfach, Rechnung
from app.rechnungen import (
    _bild_mime_type,
    _ist_rechnung_verwertbar,
    _zahlungsdaten_aus_befund,
    _analysiere,
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

EML_ZWEI_ANHAENGE = b"""From: Lieferant <rechnung@example.test>\r
To: einkauf@dreikraut.de\r
Subject: Rechnung 4711\r
Message-ID: <rechnung-zwei@example.test>\r
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
--x\r
Content-Type: application/pdf\r
Content-Disposition: attachment; filename=anlage.pdf\r
Content-Transfer-Encoding: base64\r
\r
JVBERi0xLjU=\r
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

    def test_zahlungsstatus_folgt_belegbefund_statt_schlagwoertern(self):
        faelle = [
            ("mahnung", "mahnung_offen", "offen", "Wir bitten Sie den offenen Betrag zu überweisen. Kein Hinweis auf eine automatische Zahlung."),
            ("rechnung", "zahlung_gefordert", "offen", "Zahlungsart: PayPal oder Überweisung. Bitte überweisen."),
            ("rechnung", "zahlung_gefordert", "offen", "Lastschrifteinzug nicht umgesetzt. Bitte per Überweisung begleichen."),
            ("rechnung", "einzug_oder_verrechnung", "automatisch", "We will automatically deduct the amount from your credit card or bank account."),
            ("rechnung", "einzug_oder_verrechnung", "automatisch", "Rechnungsbetrag wird vom Guthaben abgezogen."),
            ("rechnung", "zahlung_bestaetigt", "bezahlt", "Payment received."),
            ("rechnung", "paypal_ebay_gewaehlt", "bezahlt", "Zahlart: PayPal"),
            ("gutschrift", "paypal_ebay_gewaehlt", "gutschrift", "Gutschrift. Zahlungsart: eBay."),
            ("rechnung", "widerspruch", "unklar", "Bitte überweisen. | Ihr Konto wird belastet."),
            ("rechnung", "kein_nachweis", "unklar", "Fällig am 18.11.2026. IBAN: ..."),
            ("mahnung", "einzug_oder_verrechnung", "unklar", "Direct debit"),
        ]
        for art, befund, status, hinweis in faelle:
            with self.subTest(art=art, befund=befund, hinweis=hinweis):
                daten = _zahlungsdaten_aus_befund({"belegart": art, "zahlungsbefund": befund,
                    "belegquelle": "anhang", "zahlungshinweis": hinweis})
                self.assertEqual(status, daten["zahlungsstatus"])
                self.assertEqual(hinweis, daten["zahlungshinweis"])

    def test_verdeckender_status_braucht_belegquelle_und_zitat(self):
        for quelle, zitat in [("keine", "Betrag eingezogen"), ("anhang", "")]:
            daten = _zahlungsdaten_aus_befund({"belegart": "rechnung",
                "zahlungsbefund": "einzug_oder_verrechnung", "belegquelle": quelle,
                "zahlungshinweis": zitat})
            self.assertEqual("unklar", daten["zahlungsstatus"])

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
            "belegart": "rechnung", "aussteller": "Test GmbH", "rechnungsnummer": "4711",
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

    async def test_zwei_anhaenge_derselben_rechnung_werden_zusammengefuehrt(self):
        netto = {
            "belegart": "rechnung", "aussteller": "VGL Publishing AG",
            "rechnungsnummer": "S26-17875772483926",
            "rechnungsdatum": "2026-08-24", "faellig_am": "2026-09-07",
            "bruttobetrag": 219.07, "waehrung": "EUR", "zahlungsstatus": "offen",
            "zahlungshinweis": "Bitte überweisen Sie den offenen Betrag.",
        }
        brutto = {
            **netto,
            "bruttobetrag": 260.69,
            "zahlungshinweis": "Gesamtbetrag einschließlich Umsatzsteuer: 260,69 EUR.",
        }
        dbx = MagicMock()
        with patch("app.rechnungen._analysiere", side_effect=[netto, brutto]), \
             patch("app.rechnungen._dropbox_client", return_value=dbx):
            async with SessionLocal() as session:
                mail = await session.get(Mail, self.mail_id)
                ergebnis = await rechnung_aus_rohdaten_verarbeiten(
                    session, mail, EML_ZWEI_ANHAENGE
                )
                await session.commit()

        self.assertEqual(1, len(ergebnis["rechnungen"]))
        self.assertEqual(2, dbx.files_upload.call_count)
        pfade = [aufruf.args[1] for aufruf in dbx.files_upload.call_args_list]
        self.assertEqual(2, len(set(pfade)))
        async with SessionLocal() as session:
            rechnungen = (await session.execute(select(Rechnung))).scalars().all()
        self.assertEqual(1, len(rechnungen))
        self.assertEqual(260.69, rechnungen[0].bruttobetrag)
        self.assertEqual("offen", rechnungen[0].zahlungsstatus)
        self.assertEqual(2, len(rechnungen[0].dateipfade))

    async def test_spaetere_mahnung_aktualisiert_automatik_dublette_auf_offen(self):
        rechnung = {
            "belegart": "rechnung", "aussteller": "VGL Publishing AG",
            "rechnungsnummer": "S26-17875772483926",
            "rechnungsdatum": "2026-08-24", "faellig_am": "2026-09-07",
            "bruttobetrag": 260.69, "waehrung": "EUR",
            "zahlungsstatus": "automatisch",
            "zahlungshinweis": "Der Betrag wird per Lastschrift eingezogen.",
        }
        mahnung = {
            **rechnung,
            "belegart": "mahnung",
            "rechnungsdatum": "",
            "zahlungsbefund": "mahnung_offen",
            "zahlungsstatus": "offen",
            "zahlungshinweis": "Die Rechnung ist überfällig. Bitte überweisen Sie innerhalb von 7 Tagen.",
        }
        dbx = MagicMock()
        with patch("app.rechnungen._analysiere", side_effect=[rechnung, mahnung]), \
             patch("app.rechnungen._dropbox_client", return_value=dbx):
            async with SessionLocal() as session:
                mail = await session.get(Mail, self.mail_id)
                await rechnung_aus_rohdaten_verarbeiten(session, mail, EML)
                await session.commit()
            async with SessionLocal() as session:
                mail = await session.get(Mail, self.mail_id)
                ergebnis = await rechnung_aus_rohdaten_verarbeiten(session, mail, EML)
                await session.commit()

        self.assertTrue(ergebnis["rechnungen"][0]["dublette"])
        self.assertEqual(1, dbx.files_upload.call_count)
        async with SessionLocal() as session:
            gespeichert = (await session.execute(select(Rechnung))).scalar_one()
        self.assertEqual("offen", gespeichert.zahlungsstatus)
        self.assertIn("überfällig", gespeichert.zahlungshinweis)

    async def test_neuere_mahnung_widerspricht_bezahlt_ohne_neue_rechnung(self):
        original = {"belegart": "rechnung", "aussteller": "Muster GmbH",
                    "rechnungsnummer": "4711", "rechnungsdatum": "2026-10-10",
                    "bruttobetrag": 229.08, "waehrung": "EUR",
                    "zahlungsstatus": "offen", "zahlungshinweis": "Bitte überweisen."}
        mahnung = _zahlungsdaten_aus_befund({**original, "belegart": "mahnung",
                    "rechnungsdatum": "", "zahlungsbefund": "mahnung_offen",
                    "belegquelle": "beide", "zahlungshinweis": "Wir haben noch keinen Zahlungseingang festgestellt. Bitte überweisen."})
        dbx = MagicMock()
        nur_mail = b"Subject: Mahnung\r\n\r\nKein Zahlungseingang. Bitte Rechnung 4711 ueberweisen."
        with patch("app.rechnungen._analysiere", side_effect=[
            original, mahnung, {**mahnung, "belegquelle": "mail"},
        ]) as analysiere, \
             patch("app.rechnungen._dropbox_client", return_value=dbx):
            async with SessionLocal() as session:
                mail = await session.get(Mail, self.mail_id)
                await rechnung_aus_rohdaten_verarbeiten(session, mail, EML)
                rechnung = await session.scalar(select(Rechnung))
                rechnung.zahlungsstatus = "bezahlt"
                session.add(Aktionslog(mail_id=mail.id, ereignis="rechnungsstatus_geaendert",
                    erstellt_am=mail.empfangen_am + timedelta(days=1),
                    detail="Rechnung 4711: offen → bezahlt; durch Test"))
                mahnmail = Mail(message_id="<mahnung@test>", postfach_id=mail.postfach_id,
                    absender_name="Muster GmbH", absender_adresse="muster@example.test",
                    betreff="Mahnung zu 4711", text_auszug="Bitte jetzt zahlen.",
                    empfangen_am=mail.empfangen_am + timedelta(days=2))
                session.add(mahnmail)
                await session.commit()
                mahnmail_id = mahnmail.id
            for rohmail in (EML, nur_mail):
                async with SessionLocal() as session:
                    mahnmail = await session.get(Mail, mahnmail_id)
                    await rechnung_aus_rohdaten_verarbeiten(session, mahnmail, rohmail)
                    await session.commit()
            async with SessionLocal() as session:
                rechnung = (await session.execute(select(Rechnung))).scalar_one()
                self.assertEqual(rechnung.mail_id, self.mail_id)
                self.assertEqual(rechnung.zahlungsstatus, "unklar")
                self.assertIn("bisherigen Status Bezahlt", rechnung.zahlungshinweis)
                protokoll = (await session.execute(select(Aktionslog).where(
                    Aktionslog.ereignis == "rechnung_mahnung_zugeordnet"))).scalars().all()
                self.assertEqual([eintrag.mail_id for eintrag in protokoll], [mahnmail_id])
        self.assertIsNone(analysiere.call_args.args[0])
        dbx.files_upload.assert_called_once()

    def test_analyse_durchlaeuft_strukturierten_befund_fuer_anhang_und_mail(self):
        mail = Mail(betreff="Mahnung", absender_adresse="test@example.test", text_auszug="Bitte überweisen.")
        befund = {"belegart": "mahnung", "rechnungsnummer": "4711", "rechnungsdatum": "",
                   "zahlungsbefund": "mahnung_offen", "belegquelle": "mail",
                   "zahlungshinweis": "Bitte überweisen."}
        antwort = SimpleNamespace(content=[SimpleNamespace(type="tool_use", input=befund)])
        with patch("app.rechnungen.KIClient") as client:
            client.return_value.erzeugen.return_value = antwort
            daten = _analysiere(rechnungsanhaenge(EML)[0], mail)
        request = client.return_value.erzeugen.call_args.kwargs
        self.assertEqual("offen", daten["zahlungsstatus"])
        self.assertEqual("", daten["rechnungsdatum"])
        self.assertIn("Bitte überweisen.", request["messages"][0]["content"][0]["text"])
        self.assertEqual("document", request["messages"][0]["content"][1]["type"])

    async def test_historischer_lauf_kann_direkten_eingangsordner_nutzen(self):
        analyse = {
            "belegart": "rechnung", "aussteller": "Test GmbH", "rechnungsnummer": "4711",
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
        analyse = {"belegart": "kein_beleg"}
        dropbox_client = MagicMock(side_effect=RuntimeError("Dropbox nicht verbunden"))
        with patch("app.rechnungen._analysiere", return_value=analyse), \
             patch("app.rechnungen._dropbox_client", dropbox_client):
            async with SessionLocal() as session:
                mail = await session.get(Mail, self.mail_id)
                with self.assertRaisesRegex(RuntimeError, "keine Rechnung"):
                    await rechnung_aus_rohdaten_verarbeiten(session, mail, EML)

        dropbox_client.assert_not_called()

    async def test_ausdruecklich_erkannte_agb_werden_nicht_als_rechnung_angelegt(self):
        analyse = {
            "belegart": "kein_beleg",
            "aussteller": "Hamburger Gewürz-Mühle Hermann Schulz GmbH",
            "rechnungsnummer": "260134",
            "rechnungsdatum": "",
            "faellig_am": "",
            "bruttobetrag": None,
            "waehrung": "EUR",
            "zahlungsstatus": "unklar",
            "zahlungshinweis": (
                "Der Anhang enthält ausschließlich die Allgemeinen "
                "Verkaufsbedingungen (3 Seiten), keine eigentliche Rechnung "
                "mit Betrag, Datum oder Zahlungsangaben."
            ),
        }
        self.assertFalse(_ist_rechnung_verwertbar(analyse))
        dropbox_client = MagicMock()
        with patch("app.rechnungen._analysiere", return_value=analyse), \
             patch("app.rechnungen._dropbox_client", dropbox_client):
            async with SessionLocal() as session:
                mail = await session.get(Mail, self.mail_id)
                with self.assertRaisesRegex(RuntimeError, "keine Rechnung"):
                    await rechnung_aus_rohdaten_verarbeiten(session, mail, EML)

        dropbox_client.assert_not_called()
        async with SessionLocal() as session:
            rechnungen = (await session.execute(select(Rechnung))).scalars().all()
        self.assertEqual([], rechnungen)

    async def test_fehlendes_rechnungsdatum_nutzt_nachvollziehbar_eingangsdatum(self):
        analyse = {
            "belegart": "rechnung", "aussteller": "Test GmbH", "rechnungsnummer": "99",
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
