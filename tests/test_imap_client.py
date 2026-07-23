import unittest
from unittest.mock import MagicMock, patch

from app.imap_client import PostfachConfig, mail_verschieben


class _ClientKontext:
    def __init__(self, clients):
        self.clients = clients

    def __call__(self, *args, **kwargs):
        client = self.clients.pop(0)
        kontext = MagicMock()
        kontext.__enter__.return_value = client
        kontext.__exit__.return_value = False
        return kontext


class ImapVerschiebenTest(unittest.TestCase):
    def setUp(self):
        self.quelle = PostfachConfig("info", "imap.test", "info@test.de", "pw")
        self.ziel = PostfachConfig("marketing", "imap.test", "marketing@test.de", "pw")
        self.eml = b"Message-ID: <test@example.test>\r\nSubject: Test\r\n\r\nInhalt"

    def test_neue_mail_wird_angehaengt_entwurf_entfernt_und_quelle_geloescht(self):
        quell_lesen = MagicMock()
        quell_lesen.fetch.return_value = {7: {b"RFC822": self.eml}}
        ziel = MagicMock()
        ziel.search.side_effect = [[], [42]]
        quell_loeschen = MagicMock()

        with patch(
            "app.imap_client.IMAPClient",
            new=_ClientKontext([quell_lesen, ziel, quell_loeschen]),
        ):
            mail_verschieben(self.quelle, 7, self.ziel, "Newsletter")

        ziel.append.assert_called_once()
        ziel.remove_flags.assert_called_once_with([42], [b"\\Draft"])
        quell_loeschen.delete_messages.assert_called_once_with([7])

    def test_wiederholung_verwendet_vorhandene_zielmail_ohne_dublette(self):
        quell_lesen = MagicMock()
        quell_lesen.fetch.return_value = {7: {b"RFC822": self.eml}}
        ziel = MagicMock()
        ziel.search.return_value = [42]
        quell_loeschen = MagicMock()

        with patch(
            "app.imap_client.IMAPClient",
            new=_ClientKontext([quell_lesen, ziel, quell_loeschen]),
        ):
            mail_verschieben(self.quelle, 7, self.ziel, "Newsletter")

        ziel.append.assert_not_called()
        ziel.remove_flags.assert_called_once_with([42], [b"\\Draft"])
        quell_loeschen.delete_messages.assert_called_once_with([7])


if __name__ == "__main__":
    unittest.main()
