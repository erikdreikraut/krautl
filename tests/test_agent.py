import os
import unittest

os.environ.setdefault("ANTHROPIC_API_KEY", "test")

from app.agent import (
    KLASSIFIZIERUNGS_SYSTEMPROMPT,
    marktplatz_zuordnung_absichern,
    technik_absender_zuordnung_absichern,
)


class KlassifizierungsPromptTest(unittest.TestCase):
    def test_formular_spam_ueberstimmt_serioesen_standardtext(self):
        prompt = KLASSIFIZIERUNGS_SYSTEMPROMPT
        self.assertIn("FORMULAR-SPAM", prompt)
        self.assertIn("mehrere klare Unsinnsmerkmale", prompt)
        self.assertIn("Nicht als Formular-Spam behandeln", prompt)
        self.assertIn("SPAM_WERBUNG", prompt)

    def test_shopapotheke_darf_nicht_als_amazon_eingeordnet_werden(self):
        prompt = KLASSIFIZIERUNGS_SYSTEMPROMPT
        self.assertIn("MARKTPLATZ-ZUORDNUNG", prompt)
        self.assertIn("dürfen niemals einer Amazon-Klassifikation", prompt)
        self.assertIn("SHOPAPOTHEKE_BESTELLUNG", prompt)
        self.assertIn("SHOPAPOTHEKE_WICHTIG", prompt)
        self.assertIn("UNGEKLAERT", prompt)

    def test_shopapotheke_bestellung_wird_technisch_abgesichert(self):
        ergebnis = marktplatz_zuordnung_absichern(
            {"klassifikation_id": "BESTELLUNG_EMAIL", "aktion_erforderlich": False},
            {
                "absender_name": "SHOP APOTHEKE",
                "betreff": "Zu versendende Bestellung COM-259577661-2-A",
                "text_auszug": "Bestellnummer COM-259577661-2-A; Lieferadresse Berlin",
            },
            [{"klassifikation_id": "SHOPAPOTHEKE_BESTELLUNG"}],
        )
        self.assertEqual("SHOPAPOTHEKE_BESTELLUNG", ergebnis["klassifikation_id"])
        self.assertTrue(ergebnis["aktion_erforderlich"])

    def test_shopapotheke_meldung_kann_nicht_amazon_bleiben(self):
        mail = {
            "absender_name": "SHOP APOTHEKE",
            "betreff": "EU Artificial Intelligence Act",
            "text_auszug": "Redcare Pharmacy Marketplace transparency requirements",
        }
        ergebnis = marktplatz_zuordnung_absichern(
            {"klassifikation_id": "AMAZON_WICHTIG"},
            mail,
            [{"klassifikation_id": "SHOPAPOTHEKE_WICHTIG"}],
        )
        self.assertEqual("SHOPAPOTHEKE_WICHTIG", ergebnis["klassifikation_id"])

        ohne_shopklasse = marktplatz_zuordnung_absichern(
            {"klassifikation_id": "AMAZON_WICHTIG"}, mail,
            [{"klassifikation_id": "UNGEKLAERT"}],
        )
        self.assertEqual("UNGEKLAERT", ohne_shopklasse["klassifikation_id"])

    def test_anthropic_systemmail_ist_niemals_spam(self):
        self.assertIn("mail.anthropic.com", KLASSIFIZIERUNGS_SYSTEMPROMPT)
        self.assertIn("kein\nSpam", KLASSIFIZIERUNGS_SYSTEMPROMPT)
        ergebnis = technik_absender_zuordnung_absichern(
            {
                "klassifikation_id": "SPAM_WERBUNG",
                "aktion_erforderlich": False,
            },
            {"absender_adresse": "news@mail.anthropic.com"},
            [
                {"klassifikation_id": "SPAM_WERBUNG"},
                {"klassifikation_id": "SYSTEM_TECHNIK"},
            ],
        )
        self.assertEqual("SYSTEM_TECHNIK", ergebnis["klassifikation_id"])
        self.assertTrue(ergebnis["aktion_erforderlich"])

    def test_nur_echte_anthropic_maildomain_wird_bevorzugt(self):
        ergebnis = technik_absender_zuordnung_absichern(
            {"klassifikation_id": "SPAM_WERBUNG"},
            {"absender_adresse": "news@mail.anthropic.com.example.org"},
            [{"klassifikation_id": "SYSTEM_TECHNIK"}],
        )
        self.assertEqual("SPAM_WERBUNG", ergebnis["klassifikation_id"])


if __name__ == "__main__":
    unittest.main()
