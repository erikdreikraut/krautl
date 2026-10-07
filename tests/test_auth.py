import os
import unittest
from unittest.mock import patch

from app.auth import anmelden, sitzung_erstellen, sitzung_lesen


class AuthTest(unittest.TestCase):
    umgebung = {
        "KRAUTL_SESSION_SECRET": "test-secret-mit-mehr-als-32-zeichen-123456",
        "KRAUTL_PASSWORD_ERIK": "erik-passwort",
        "KRAUTL_PASSWORD_GURSEWAK": "gursewak-passwort",
        "KRAUTL_PASSWORD_LUDWIG": "ludwig-passwort",
        "KRAUTL_PASSWORD_ANETA": "aneta-passwort",
        "KRAUTL_PASSWORD_MICHA": "micha-test-passwort",
    }

    def test_fuenf_feste_nutzer_koennen_sich_anmelden(self):
        with patch.dict(os.environ, self.umgebung, clear=False):
            erik = anmelden("erik", "erik-passwort")
            gursewak = anmelden("gursewak", "gursewak-passwort")
            ludwig = anmelden("ludwig", "ludwig-passwort")
            aneta = anmelden("aneta", "aneta-passwort")
            self.assertIsNotNone(anmelden("micha", "micha-test-passwort"))
            self.assertEqual(("Erik Schweitzer", "admin"), (erik["name"], erik["rolle"]))
            self.assertEqual(("Gursewak Singh", "sachbearbeiter"), (gursewak["name"], gursewak["rolle"]))
            self.assertEqual(("Ludwig Schnorrenberg", "sachbearbeiter"), (ludwig["name"], ludwig["rolle"]))
            self.assertEqual(("Aneta", "sachbearbeiter"), (aneta["name"], aneta["rolle"]))
            self.assertIsNone(aneta["titel"])
            self.assertIsNone(anmelden("erik", "falsch"))

    def test_micha_anmeldung_sitzung_und_fehlendes_passwort(self):
        with patch.dict(os.environ, self.umgebung, clear=False):
            micha = anmelden(" Micha ", "micha-test-passwort")
            self.assertEqual(("Micha", "sachbearbeiter"), (micha["name"], micha["rolle"]))
            self.assertIsNone(micha["titel"])
            self.assertEqual("micha", sitzung_lesen(sitzung_erstellen("micha"))["benutzername"])
            self.assertIsNone(anmelden("micha", "falsch"))
        with patch.dict(os.environ, {"KRAUTL_PASSWORD_MICHA": ""}):
            self.assertIsNone(anmelden("micha", ""))

    def test_signierte_sitzung_erkennt_manipulation(self):
        with patch.dict(os.environ, self.umgebung, clear=False):
            token = sitzung_erstellen("gursewak")
            benutzer = sitzung_lesen(token)
            self.assertEqual("Gursewak Singh", benutzer["name"])
            self.assertEqual("Auszubildender", benutzer["titel"])
            self.assertEqual("sachbearbeiter", benutzer["rolle"])
            self.assertIsNone(sitzung_lesen(token + "manipuliert"))


if __name__ == "__main__":
    unittest.main()
