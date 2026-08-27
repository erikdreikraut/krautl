import os
import unittest

os.environ.setdefault("ANTHROPIC_API_KEY", "test")

from app.agent import (
    KLASSIFIZIERUNGS_SYSTEMPROMPT,
    amazon_absender_zuordnung_absichern,
    ebay_verkaufszuordnung_absichern,
    einkaufszuordnung_absichern,
    interne_aufgaben_zuordnung_absichern,
    marktplatz_zuordnung_absichern,
    steuer_absender_zuordnung_absichern,
    technik_absender_zuordnung_absichern,
)


class KlassifizierungsPromptTest(unittest.TestCase):
    def test_amazon_rechnungshinweis_ohne_anhang_ist_status(self):
        self.assertIn("AMAZON-ABSENDER", KLASSIFIZIERUNGS_SYSTEMPROMPT)
        ergebnis = amazon_absender_zuordnung_absichern(
            {
                "klassifikation_id": "RECHNUNG_EINGANG",
                "aktion_erforderlich": False,
            },
            {
                "absender_name": "Amazon Seller Central",
                "absender_adresse": "sellercentral@amazon.es",
                "betreff": "Your Amazon.es Factura Vendedor for 7/2026",
                "text_auszug": (
                    "Tu Factura Vendedor ya esta disponible en tu cuenta "
                    "de Seller Central. Alli podras descargar tu factura."
                ),
                "anhang_dateinamen": [],
            },
            [
                {"klassifikation_id": "RECHNUNG_EINGANG"},
                {"klassifikation_id": "AMAZON_STATUS"},
            ],
        )
        self.assertEqual("AMAZON_STATUS", ergebnis["klassifikation_id"])
        self.assertTrue(ergebnis["aktion_erforderlich"])

    def test_amazon_rechnung_mit_anhang_bleibt_rechnung(self):
        ergebnis = amazon_absender_zuordnung_absichern(
            {"klassifikation_id": "RECHNUNG_EINGANG"},
            {
                "absender_name": "Amazon Seller Central",
                "absender_adresse": "sellercentral@amazon.de",
                "anhang_dateinamen": ["Rechnung-2026-07.pdf"],
            },
            [
                {"klassifikation_id": "RECHNUNG_EINGANG"},
                {"klassifikation_id": "AMAZON_STATUS"},
            ],
        )
        self.assertEqual("RECHNUNG_EINGANG", ergebnis["klassifikation_id"])

    def test_blasse_amazon_erwaehnung_aendert_kundenmail_nicht(self):
        ergebnis = amazon_absender_zuordnung_absichern(
            {"klassifikation_id": "KUNDE_REZENSION_FEEDBACK"},
            {
                "absender_name": "Tobias Riess",
                "absender_adresse": "tobias@example.test",
                "text_auszug": "Ich habe Sie bei Amazon bewertet.",
            },
            [{"klassifikation_id": "AMAZON_STATUS"}],
        )
        self.assertEqual("KUNDE_REZENSION_FEEDBACK", ergebnis["klassifikation_id"])

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

    def test_einkaufsbestaetigung_ist_keine_eingangsrechnung(self):
        self.assertIn("EINKAUF UND RECHNUNG ABGRENZEN", KLASSIFIZIERUNGS_SYSTEMPROMPT)
        ergebnis = einkaufszuordnung_absichern(
            {
                "klassifikation_id": "RECHNUNG_EINGANG",
                "aktion_erforderlich": False,
            },
            {
                "absender_name": "eBay",
                "betreff": "Bestellung bestätigt: Tablet Halterung",
                "text_auszug": (
                    "Vielen Dank! Ihre Bestellung wurde bestätigt. "
                    "Ihre Bestellung wird verschickt an Erik Schweitzer. "
                    "Lieferung ca. Do, 06. Aug."
                ),
            },
            [
                {"klassifikation_id": "RECHNUNG_EINGANG"},
                {"klassifikation_id": "LIEFERANT_AUFTRAGSBESTAETIGUNG"},
            ],
        )
        self.assertEqual(
            "LIEFERANT_AUFTRAGSBESTAETIGUNG",
            ergebnis["klassifikation_id"],
        )
        self.assertTrue(ergebnis["aktion_erforderlich"])

    def test_echte_rechnung_in_bestellmail_bleibt_rechnung(self):
        ergebnis = einkaufszuordnung_absichern(
            {"klassifikation_id": "RECHNUNG_EINGANG"},
            {
                "betreff": "Bestellung bestätigt und Rechnung im Anhang",
                "text_auszug": "Rechnungsnummer 4711",
            },
            [{"klassifikation_id": "LIEFERANT_AUFTRAGSBESTAETIGUNG"}],
        )
        self.assertEqual("RECHNUNG_EINGANG", ergebnis["klassifikation_id"])

    def test_ebay_verkauf_wird_technisch_abgesichert(self):
        self.assertIn("EBAY-VERKAUFSBEST", KLASSIFIZIERUNGS_SYSTEMPROMPT)
        self.assertIn("BESTELLUNG_EBAY", KLASSIFIZIERUNGS_SYSTEMPROMPT)
        ergebnis = ebay_verkaufszuordnung_absichern(
            {
                "klassifikation_id": "UNGEKLAERT",
                "aktion_erforderlich": False,
            },
            {
                "absender_name": "eBay",
                "absender_adresse": "ebay@ebay.de",
                "betreff": "Artikel verkauft - Mistelkraut Bio",
                "text_auszug": (
                    "Verpacken Sie jetzt den Artikel und verschicken Sie ihn. "
                    "Ihr Käufer hat bezahlt."
                ),
            },
            [{"klassifikation_id": "BESTELLUNG_EBAY"}],
        )
        self.assertEqual("BESTELLUNG_EBAY", ergebnis["klassifikation_id"])
        self.assertTrue(ergebnis["aktion_erforderlich"])

    def test_ebay_einkauf_wird_nicht_zum_verkauf(self):
        ergebnis = ebay_verkaufszuordnung_absichern(
            {"klassifikation_id": "LIEFERANT_AUFTRAGSBESTAETIGUNG"},
            {
                "absender_name": "eBay",
                "absender_adresse": "ebay@ebay.de",
                "betreff": "Bestellung bestätigt: Tablet Halterung",
                "text_auszug": "Ihre Bestellung wird an Erik Schweitzer verschickt.",
            },
            [{"klassifikation_id": "BESTELLUNG_EBAY"}],
        )
        self.assertEqual(
            "LIEFERANT_AUFTRAGSBESTAETIGUNG",
            ergebnis["klassifikation_id"],
        )

    def test_countx_und_kineke_werden_als_steuern_abgesichert(self):
        self.assertIn("STEUERN:", KLASSIFIZIERUNGS_SYSTEMPROMPT)
        katalog = [
            {"klassifikation_id": "RECHT_BEHOERDE"},
            {"klassifikation_id": "RECHT_STEUERN"},
        ]
        for mail in (
            {
                "absender_name": "CountX",
                "absender_adresse": "notifications@countx.com",
            },
            {
                "absender_name": "Steuerberater Kineke",
                "absender_adresse": "kanzlei@example.test",
            },
        ):
            ergebnis = steuer_absender_zuordnung_absichern(
                {"klassifikation_id": "RECHT_BEHOERDE"}, mail, katalog
            )
            self.assertEqual("RECHT_STEUERN", ergebnis["klassifikation_id"])
            self.assertTrue(ergebnis["aktion_erforderlich"])

    def test_blasse_erwaehnung_von_countx_aendert_absender_nicht(self):
        ergebnis = steuer_absender_zuordnung_absichern(
            {"klassifikation_id": "LIEFERANT_DIVERSES"},
            {
                "absender_name": "Lieferant",
                "absender_adresse": "lieferant@example.test",
                "text_auszug": "Bitte stimmen Sie dies mit CountX ab.",
            },
            [{"klassifikation_id": "RECHT_STEUERN"}],
        )
        self.assertEqual("LIEFERANT_DIVERSES", ergebnis["klassifikation_id"])

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

    def test_dreikraut_bestandswarnung_wird_interne_aufgabe(self):
        self.assertIn("INTERNE AUFGABENHINWEISE", KLASSIFIZIERUNGS_SYSTEMPROMPT)
        ergebnis = interne_aufgaben_zuordnung_absichern(
            {"klassifikation_id": "SYSTEM_TECHNIK", "aktion_erforderlich": False},
            {
                "absender_adresse": "system@dreikraut.de",
                "betreff": "Bestandswarnung",
                "text_auszug": "Der Lagerbestand für Artikel 4711 ist niedrig.",
            },
            [{"klassifikation_id": "INTERN_AUFGABEN"}],
        )
        self.assertEqual("INTERN_AUFGABEN", ergebnis["klassifikation_id"])
        self.assertTrue(ergebnis["aktion_erforderlich"])

    def test_externer_absender_und_normale_interne_mail_bleiben_unveraendert(self):
        katalog = [{"klassifikation_id": "INTERN_AUFGABEN"}]
        for mail in (
            {
                "absender_adresse": "alarm@example.test",
                "betreff": "dreikraut Lagerbestand niedrig",
                "text_auszug": "Bitte prüfen.",
            },
            {
                "absender_adresse": "kollegin@dreikraut.de",
                "betreff": "Besprechung",
                "text_auszug": "Können wir uns morgen abstimmen?",
            },
        ):
            ergebnis = interne_aufgaben_zuordnung_absichern(
                {"klassifikation_id": "UNGEKLAERT"}, mail, katalog
            )
            self.assertEqual("UNGEKLAERT", ergebnis["klassifikation_id"])

    def test_fertiges_transkript_ist_keine_interne_aufgabe(self):
        self.assertIn("FERTIGE TELEFONTRANSKRIPTE", KLASSIFIZIERUNGS_SYSTEMPROMPT)
        ergebnis = interne_aufgaben_zuordnung_absichern(
            {"klassifikation_id": "KUNDE_TRACKING", "aktion_erforderlich": True},
            {
                "krautl_generiert": True,
                "absender_adresse": "service@dreikraut.de",
                "betreff": "[TRANSKRIPTION] Anruf von Brien",
                "text_auszug": "Wann kommt meine Bestellung?",
            },
            [{"klassifikation_id": "INTERN_AUFGABEN"}],
        )
        self.assertEqual("KUNDE_TRACKING", ergebnis["klassifikation_id"])


if __name__ == "__main__":
    unittest.main()
