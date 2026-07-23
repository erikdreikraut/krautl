import unittest

from app.mail_parser import _text_aus_html


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


if __name__ == "__main__":
    unittest.main()
