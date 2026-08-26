import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault("ANTHROPIC_API_KEY", "test")

from app.uebersetzungen import (
    antwort_in_originalsprache_uebersetzen, ist_deutsche_sprache,
    mail_ins_deutsche_uebersetzen, uebersetzung_fuer_mail_sicherstellen,
)


class UebersetzungenTest(unittest.IsolatedAsyncioTestCase):
    def test_deutsche_sprachvarianten_werden_erkannt(self):
        self.assertTrue(ist_deutsche_sprache("Deutsch"))
        self.assertTrue(ist_deutsche_sprache("de-DE"))
        self.assertFalse(ist_deutsche_sprache("Englisch"))

    async def test_erkannte_deutsche_mail_braucht_keinen_ki_aufruf(self):
        with patch(
            "app.uebersetzungen._synchron_mail_uebersetzen"
        ) as uebersetzer:
            ergebnis = await mail_ins_deutsche_uebersetzen(
                "Frage", "Guten Tag", "Deutsch"
            )
        uebersetzer.assert_not_called()
        self.assertEqual("Deutsch", ergebnis["originalsprache"])
        self.assertIsNone(ergebnis["text_deutsch"])

    async def test_fremdsprachige_mail_erhaelt_deutsche_arbeitsfassung(self):
        mail = SimpleNamespace(
            betreff="Question",
            text_auszug="Where is my parcel?",
            originalsprache="Englisch",
            betreff_deutsch=None,
            text_deutsch=None,
        )
        ergebnis = {
            "originalsprache": "Englisch",
            "betreff_deutsch": "Frage",
            "text_deutsch": "Wo ist mein Paket?",
        }
        with patch(
            "app.uebersetzungen.mail_ins_deutsche_uebersetzen",
            AsyncMock(return_value=ergebnis),
        ):
            geaendert = await uebersetzung_fuer_mail_sicherstellen(mail)
        self.assertTrue(geaendert)
        self.assertEqual("Wo ist mein Paket?", mail.text_deutsch)

    async def test_antwort_wird_nur_fuer_fremdsprache_uebersetzt(self):
        with patch(
            "app.uebersetzungen._synchron_antwort_uebersetzen",
            return_value="Thank you.",
        ) as uebersetzer:
            deutsch = await antwort_in_originalsprache_uebersetzen(
                "Vielen Dank.", "Deutsch"
            )
            englisch = await antwort_in_originalsprache_uebersetzen(
                "Vielen Dank.", "Englisch"
            )
        self.assertEqual("Vielen Dank.", deutsch)
        self.assertEqual("Thank you.", englisch)
        uebersetzer.assert_called_once_with("Vielen Dank.", "Englisch")


if __name__ == "__main__":
    unittest.main()
