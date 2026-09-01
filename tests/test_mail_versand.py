import os
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from app.mail_versand import _synchron_senden, antwort_mit_signatur
from app.models import Mail


class _SmtpAttrappe:
    nachricht = None

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def ehlo(self):
        pass

    def starttls(self, context):
        pass

    def login(self, user, password):
        pass

    def send_message(self, nachricht):
        type(self).nachricht = nachricht


class MailVersandTest(unittest.TestCase):
    erik = {"name": "Erik Schweitzer", "titel": None}
    gursewak = {"name": "Gursewak Singh", "titel": "Auszubildender"}
    aneta = {"name": "Aneta", "titel": None}

    def test_antwort_geht_an_kunden_und_kontrolladresse_nur_in_bcc(self):
        mail = Mail(
            message_id="<kunde@example.test>",
            postfach_id=1,
            absender_name="Kunde",
            absender_adresse="echter-kunde@example.test",
            betreff="Testfrage",
            text_auszug="Hallo",
            empfangen_am=datetime.now(timezone.utc),
        )
        umgebung = {
            "SMTP_SERVICE_HOST": "smtp.example.test",
            "SMTP_SERVICE_PORT": "587",
            "SMTP_SERVICE_USER": "service@dreikraut.de",
            "SMTP_SERVICE_PASSWORD": "secret",
        }
        with patch.dict(os.environ, umgebung, clear=False), \
             patch("app.mail_versand.smtplib.SMTP", _SmtpAttrappe):
            ergebnis = _synchron_senden(mail, "Testantwort", self.erik)

        self.assertEqual(
            "echter-kunde@example.test",
            _SmtpAttrappe.nachricht["To"],
        )
        self.assertEqual(
            "info@erikschweitzer.de",
            _SmtpAttrappe.nachricht["Bcc"],
        )
        self.assertEqual("Re: Testfrage", _SmtpAttrappe.nachricht["Subject"])
        self.assertNotIn("TEST", _SmtpAttrappe.nachricht["Subject"])
        self.assertIn("\nErik Schweitzer\n-- \ndreikraut e.K.\n", _SmtpAttrappe.nachricht.get_content())
        self.assertEqual("echter-kunde@example.test", ergebnis["empfaenger"])
        self.assertEqual("info@erikschweitzer.de", ergebnis["bcc"])
        self.assertTrue(ergebnis["message_id"].startswith("<"))

    def test_ungueltige_kundenadresse_wird_vor_smtp_blockiert(self):
        mail = Mail(
            message_id="<ungueltig@example.test>",
            postfach_id=1,
            absender_name="Unbekannt",
            absender_adresse="keine-adresse",
            betreff="Frage",
            text_auszug="Hallo",
            empfangen_am=datetime.now(timezone.utc),
        )
        umgebung = {
            "SMTP_SERVICE_HOST": "smtp.example.test",
            "SMTP_SERVICE_PORT": "587",
            "SMTP_SERVICE_USER": "service@dreikraut.de",
            "SMTP_SERVICE_PASSWORD": "secret",
        }
        with patch.dict(os.environ, umgebung, clear=False), \
             patch("app.mail_versand.smtplib.SMTP", _SmtpAttrappe):
            with self.assertRaisesRegex(RuntimeError, "ungültig"):
                _synchron_senden(mail, "Testantwort", self.erik)

    def test_antwortanhaenge_werden_mit_dateiname_und_mime_type_versendet(self):
        mail = Mail(
            message_id="<anhang@example.test>",
            postfach_id=1,
            absender_name="Kunde",
            absender_adresse="kunde@example.test",
            betreff="Unterlagen",
            text_auszug="Hallo",
            empfangen_am=datetime.now(timezone.utc),
        )
        umgebung = {
            "SMTP_SERVICE_HOST": "smtp.example.test",
            "SMTP_SERVICE_PORT": "587",
            "SMTP_SERVICE_USER": "service@dreikraut.de",
            "SMTP_SERVICE_PASSWORD": "secret",
        }
        with patch.dict(os.environ, umgebung, clear=False), \
             patch("app.mail_versand.smtplib.SMTP", _SmtpAttrappe):
            _synchron_senden(
                mail,
                "Anbei die Unterlagen.",
                self.erik,
                [{
                    "dateiname": "Hinweis.pdf",
                    "mime_type": "application/pdf",
                    "inhalt": b"%PDF-1.7 test",
                }],
            )

        anhaenge = list(_SmtpAttrappe.nachricht.iter_attachments())
        self.assertEqual(1, len(anhaenge))
        self.assertEqual("Hinweis.pdf", anhaenge[0].get_filename())
        self.assertEqual("application/pdf", anhaenge[0].get_content_type())
        self.assertEqual(b"%PDF-1.7 test", anhaenge[0].get_payload(decode=True))

    def test_signatur_fuer_auszubildende(self):
        text = antwort_mit_signatur("Mit bestem Gruß", self.gursewak)
        self.assertEqual(
            """Mit bestem Gruß

Gursewak Singh
Auszubildender
""" + "-- \n" + """dreikraut e.K.
Gräfrather Str. 74a
42329 Wuppertal

www.dreikraut.de
Fon +49 202 2727 7835
Fax +49 202 2531 2301
""",
            text,
        )

    def test_signatur_fuer_aneta_ohne_zusatztitel(self):
        text = antwort_mit_signatur("Viele Grüße", self.aneta)
        self.assertIn("\n\nAneta\n-- \ndreikraut e.K.\n", text)
        self.assertNotIn("Auszubildender", text)


if __name__ == "__main__":
    unittest.main()
