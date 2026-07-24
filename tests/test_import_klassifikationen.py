import unittest

from scripts.import_klassifikationen import _bestaetigung_noetig


class KlassifikationsImportTest(unittest.TestCase):
    def test_spam_wird_ohne_bestaetigung_verschoben(self):
        self.assertFalse(_bestaetigung_noetig("Spam", "MAIL_VERSCHIEBEN"))
        self.assertFalse(_bestaetigung_noetig(" spam ", "MAIL_VERSCHIEBEN"))

    def test_alle_anderen_kategorien_bleiben_bestaetigungspflichtig(self):
        self.assertTrue(
            _bestaetigung_noetig("Kundenservice", "MAIL_VERSCHIEBEN")
        )
        self.assertTrue(
            _bestaetigung_noetig("Rechnung", "RECHNUNG_VERWALTEN")
        )


if __name__ == "__main__":
    unittest.main()
