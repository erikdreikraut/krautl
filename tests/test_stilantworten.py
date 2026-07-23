import unittest
from email import message_from_string, policy

from scripts.stilantworten_exportieren import antwort_ohne_zitate, autor_bestimmen


class StilantwortenTest(unittest.TestCase):
    def test_autor_aus_absendername(self):
        msg = message_from_string(
            "From: Erik Schweitzer <service@dreikraut.de>\n\nHallo!",
            policy=policy.default,
        )
        self.assertEqual(("Erik Schweitzer", "Absendername"), autor_bestimmen(msg, "Hallo!"))

    def test_autor_aus_signatur(self):
        msg = message_from_string(
            "From: dreikraut Kundenservice <service@dreikraut.de>\n\nHallo!",
            policy=policy.default,
        )
        text = "Hallo,\n\ndas bekommen wir hin.\n\nViele Grüße\nThomas Meier"
        self.assertEqual(("Thomas Meier", "Signatur"), autor_bestimmen(msg, text))

    def test_autor_aus_vorname_in_signatur(self):
        msg = message_from_string(
            "From: dreikraut Kundenservice <service@dreikraut.de>\n\nHallo!",
            policy=policy.default,
        )
        text = "Hallo Anna,\n\ndas bekommen wir hin.\n\nLiebe Grüße\nErik"
        self.assertEqual(
            ("Erik Schweitzer", "Vorname in Signatur"),
            autor_bestimmen(msg, text),
        )

    def test_vorname_im_fliesstext_genuegt_nicht(self):
        msg = message_from_string(
            "From: dreikraut Kundenservice <service@dreikraut.de>\n\nHallo!",
            policy=policy.default,
        )
        text = "Hallo,\n\nErik kümmert sich morgen darum.\n\nViele Grüße"
        self.assertEqual((None, "nicht erkannt"), autor_bestimmen(msg, text))

    def test_gursewak_wird_ausgeschlossen(self):
        msg = message_from_string(
            "From: dreikraut Kundenservice <service@dreikraut.de>\n\nHallo!",
            policy=policy.default,
        )
        text = "Hallo,\n\ndas bekommen wir hin.\n\nViele Grüße\nGursewak"
        self.assertEqual((None, "ausgeschlossen"), autor_bestimmen(msg, text))

    def test_zitierter_verlauf_wird_entfernt(self):
        text = (
            "Hallo,\n\ngern helfen wir weiter.\n\nViele Grüße\nErik Schweitzer\n\n"
            "Am 23.07.2026 schrieb Kundin:\n> Meine ursprüngliche Frage"
        )
        bereinigt = antwort_ohne_zitate(text)
        self.assertIn("gern helfen wir weiter", bereinigt)
        self.assertNotIn("ursprüngliche Frage", bereinigt)

    def test_widerspruechliche_namen_bleiben_unklar(self):
        msg = message_from_string(
            "From: Erik Schweitzer <service@dreikraut.de>\n\nHallo!",
            policy=policy.default,
        )
        self.assertEqual(
            (None, "widersprüchig"),
            autor_bestimmen(msg, "Viele Grüße\nThomas Meier"),
        )


if __name__ == "__main__":
    unittest.main()
