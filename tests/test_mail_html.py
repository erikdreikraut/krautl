import unittest
from email.message import EmailMessage

from app.mail_html import html_teil_aus_mail


class MailHTMLTest(unittest.TestCase):
    def test_tabellen_und_formatierung_bleiben_erhalten(self):
        mail = EmailMessage()
        mail["Subject"] = "HTML-Test"
        mail.set_content("Text-Fallback")
        mail.add_alternative(
            """
            <html>
              <head>
                <meta charset="utf-8">
                <style>body { display: none }</style>
              </head>
              <body>
                <table cellpadding="4" style="width: 100%; color: #123456">
                  <tr><th>Kennzahl</th><th>Status</th></tr>
                  <tr><td>Pakete</td><td><strong>Bestanden</strong></td></tr>
                </table>
              </body>
            </html>
            """,
            subtype="html",
        )

        html = html_teil_aus_mail(mail.as_bytes())

        self.assertIsNotNone(html)
        self.assertIn("<table", html)
        self.assertIn("<th>Kennzahl</th>", html)
        self.assertIn("<td><strong>Bestanden</strong></td>", html)
        self.assertIn("width: 100%", html)
        self.assertNotIn("display: none", html)

    def test_aktive_inhalte_tracking_und_gefaehrliche_attribute_fallen_weg(self):
        mail = EmailMessage()
        mail.set_content("Text-Fallback")
        mail.add_alternative(
            """
            <html><body>
              <script>alert('boese')</script>
              <form><input value="absenden"></form>
              <a href="javascript:alert(1)" onclick="alert(2)">Weiter</a>
              <img src="https://tracker.example/pixel.gif" onerror="alert(3)">
              <p style="color: red; background-image: url(https://tracker.example/x)">Sicher</p>
            </body></html>
            """,
            subtype="html",
        )

        html = html_teil_aus_mail(mail.as_bytes())

        self.assertIsNotNone(html)
        self.assertIn(">Weiter</a>", html)
        self.assertIn("color: red", html)
        self.assertIn("Sicher", html)
        self.assertNotIn("alert(", html)
        self.assertNotIn("<form", html)
        self.assertNotIn("<input", html)
        self.assertNotIn("href=", html)
        self.assertNotIn("tracker.example", html)
        self.assertNotIn("background-image", html)
        self.assertIn("default-src 'none'", html)

    def test_absolute_web_links_oeffnen_geschuetzt_im_neuen_tab(self):
        mail = EmailMessage()
        mail.set_content("Portal")
        mail.add_alternative(
            '<a href="https://portal.example.test/a?x=1&amp;y=2" target="_top" '
            'rel="opener" ping="https://tracker.example.test/" download>Portal</a>'
            '<a href="http://example.test/">HTTP</a>', subtype="html",
        )

        html = html_teil_aus_mail(mail.as_bytes())

        self.assertIn('<a href="https://portal.example.test/a?x=1&amp;y=2" '
                      'target="_blank" rel="noopener noreferrer">Portal</a>', html)
        self.assertIn('<a href="http://example.test/" target="_blank" '
                      'rel="noopener noreferrer">HTTP</a>', html)
        self.assertNotIn('tracker.example.test', html)
        self.assertNotIn('target="_top"', html)
        self.assertNotIn(' download', html)

    def test_andere_linkziele_bleiben_text(self):
        for ziel in ("java&#x09;script:alert(1)", "data:text/html,test", "file:///test",
                     "//example.test", "/api/mails", "https:///example.test",
                     "https://portal.example.test@other.example.test"):
            with self.subTest(ziel=ziel):
                mail = EmailMessage()
                mail.set_content(f'<a href="{ziel}">Linktext</a>', subtype="html")
                html = html_teil_aus_mail(mail.as_bytes())
                self.assertIn("<a>Linktext</a>", html)
                self.assertNotIn("href=", html)

    def test_reine_textmail_hat_keine_html_ansicht(self):
        mail = EmailMessage()
        mail.set_content("Nur Text")

        self.assertIsNone(html_teil_aus_mail(mail.as_bytes()))


if __name__ == "__main__":
    unittest.main()
