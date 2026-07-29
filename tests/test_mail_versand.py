import os
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from app.mail_versand import _synchron_senden
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
    def test_empfaenger_ist_fest_auf_testadresse_begrenzt(self):
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
            _synchron_senden(mail, "Testantwort")

        self.assertEqual(
            "info@erikschweitzer.de",
            _SmtpAttrappe.nachricht["To"],
        )
        self.assertNotEqual(
            mail.absender_adresse,
            _SmtpAttrappe.nachricht["To"],
        )


if __name__ == "__main__":
    unittest.main()
