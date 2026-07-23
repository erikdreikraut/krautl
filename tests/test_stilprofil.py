import json
import tempfile
import unittest
from pathlib import Path

from scripts.stilprofil_erstellen import (
    antworten_buendeln, batch_prompt, export_laden, gesamt_prompt, in_bloecke,
)


class StilprofilTest(unittest.TestCase):
    def test_export_filtert_fremde_autoren_und_leere_texte(self):
        with tempfile.TemporaryDirectory() as tmp:
            pfad = Path(tmp) / "antworten.jsonl"
            zeilen = [
                {"autor": "Erik Schweitzer", "text": "Hallo und willkommen.", "datum": "2026-01-01"},
                {"autor": "Gursewak", "text": "Nicht verwenden", "datum": "2026-01-02"},
                {"autor": "Thomas Meier", "text": "  ", "datum": "2026-01-03"},
            ]
            pfad.write_text(
                "".join(json.dumps(z, ensure_ascii=False) + "\n" for z in zeilen),
                encoding="utf-8",
            )
            ergebnis = export_laden(pfad)
        self.assertEqual(1, len(ergebnis))
        self.assertEqual("Erik Schweitzer", ergebnis[0]["autor"])

    def test_identische_antworten_werden_mit_haeufigkeit_gebuendelt(self):
        eintraege = [
            {"autor": "Erik Schweitzer", "text": "Hallo   Welt", "datum": "2026-01-01"},
            {"autor": "Erik Schweitzer", "text": "Hallo Welt", "datum": "2026-02-01"},
        ]
        ergebnis = antworten_buendeln(eintraege)
        self.assertEqual(1, len(ergebnis))
        self.assertEqual(2, ergebnis[0]["haeufigkeit"])
        self.assertEqual("2026-02-01", ergebnis[0]["neuestes_datum"])

    def test_bloecke_verlieren_keine_eintraege(self):
        eintraege = [{"nummer": i} for i in range(41)]
        bloecke = in_bloecke(eintraege, 18)
        self.assertEqual([18, 18, 5], [len(b) for b in bloecke])

    def test_prompts_verbieten_kundendaten_und_zitate(self):
        batch = batch_prompt(
            "Erik Schweitzer",
            [{"text": "Beispiel", "haeufigkeit": 1}],
        )
        gesamt = gesamt_prompt(
            "Ansprache spiegeln",
            {"Erik Schweitzer": "Profil", "Thomas Meier": "Profil"},
            {"exportierte_antworten": 2},
        )
        self.assertIn("keine wörtlichen", batch.casefold())
        self.assertIn("keine kundendaten", gesamt.casefold())
        self.assertIn("verbindliche regeln", gesamt.casefold())


if __name__ == "__main__":
    unittest.main()
