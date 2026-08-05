import unittest
from email.message import EmailMessage

from app.mail_parser import _text_aus_html, parse_eml


class MailParserTest(unittest.TestCase):
    def test_css_skripte_und_html_entitaeten_werden_bereinigt(self):
        html = """
        <html>
          <head><style>body { color: red; } .wing { display:none }</style></head>
          <body>
            <h1>Ein neuer Zustellversuch &amp; mehr</h1>
            <script>alert('nicht anzeigen')</script>
            <p>Hallo,&nbsp;deine Sendung kommt am Freitag.</p>
          </body>
        </html>
        """
        text = _text_aus_html(html)
        self.assertNotIn("color: red", text)
        self.assertNotIn("alert", text)
        self.assertIn("Ein neuer Zustellversuch & mehr", text)
        self.assertIn("Hallo, deine Sendung kommt am Freitag.", text)
        self.assertIn("\n\n", text)

    def test_mail_ohne_message_id_erhaelt_stabile_kennung(self):
        mail = EmailMessage()
        mail["From"] = "export@example.test"
        mail["To"] = "einkauf@dreikraut.de"
        mail["Date"] = "Wed, 5 Aug 2026 16:54:00 +0200"
        mail["Subject"] = "Herbs for Export"
        mail.set_content("We offer herbs, spices and seeds.")
        raw = mail.as_bytes()

        erste = parse_eml(raw)
        zweite = parse_eml(raw)

        self.assertEqual(erste["message_id"], zweite["message_id"])
        self.assertTrue(erste["message_id"].startswith("<generiert-"))

    def test_unterschiedliche_mails_ohne_message_id_bleiben_unterscheidbar(self):
        def raw_mail(text):
            mail = EmailMessage()
            mail["From"] = "export@example.test"
            mail["Subject"] = "Angebot"
            mail.set_content(text)
            return mail.as_bytes()

        self.assertNotEqual(
            parse_eml(raw_mail("Angebot A"))["message_id"],
            parse_eml(raw_mail("Angebot B"))["message_id"],
        )

    def test_interne_transkriptionsmail_wird_erkannt(self):
        mail = EmailMessage()
        mail["Message-ID"] = "<krautl-audio-17@dreikraut.de>"
        mail["X-Krautl-Generated"] = "audio-transcription"
        mail["Subject"] = "Anruf transkribiert: unbekannt"
        mail.set_content("Transkript")

        self.assertTrue(parse_eml(mail.as_bytes())["krautl_generiert"])


if __name__ == "__main__":
    unittest.main()
