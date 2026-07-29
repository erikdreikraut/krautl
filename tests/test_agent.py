import os
import unittest

os.environ.setdefault("ANTHROPIC_API_KEY", "test")

from app.agent import KLASSIFIZIERUNGS_SYSTEMPROMPT


class KlassifizierungsPromptTest(unittest.TestCase):
    def test_formular_spam_ueberstimmt_serioesen_standardtext(self):
        prompt = KLASSIFIZIERUNGS_SYSTEMPROMPT
        self.assertIn("FORMULAR-SPAM", prompt)
        self.assertIn("mehrere klare Unsinnsmerkmale", prompt)
        self.assertIn("Nicht als Formular-Spam behandeln", prompt)
        self.assertIn("SPAM_WERBUNG", prompt)


if __name__ == "__main__":
    unittest.main()
