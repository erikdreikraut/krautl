import unittest
from unittest.mock import MagicMock, patch

from app.imap_client import (
    PostfachConfig, mail_loeschen, mail_rohdaten_nach_message_id_laden,
    mail_verschieben, neue_mails_abrufen,
)


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

    def test_mail_wird_nur_nach_message_id_pruefung_geloescht(self):
        client = MagicMock()
        client.fetch.return_value = {7: {b"RFC822": self.eml}}
        with patch("app.imap_client.IMAPClient", new=_ClientKontext([client])):
            mail_loeschen(self.quelle, 7, "<test@example.test>")
        client.delete_messages.assert_called_once_with([7])
        client.expunge.assert_called_once_with()

    def test_verschobene_mail_wird_per_message_id_im_zielordner_gefunden(self):
        client = MagicMock()
        client.search.return_value = [42]
        client.fetch.return_value = {42: {b"RFC822": self.eml}}
        with patch("app.imap_client.IMAPClient", new=_ClientKontext([client])):
            ergebnis = mail_rohdaten_nach_message_id_laden(
                self.ziel, "<test@example.test>", "Rechnungen"
            )

        self.assertEqual(self.eml, ergebnis)
        client.select_folder.assert_called_once_with("Rechnungen", readonly=True)
        client.search.assert_called_once_with([
            "HEADER", "Message-ID", "<test@example.test>"
        ])

    def test_falsche_message_id_verhindert_das_loeschen(self):
        client = MagicMock()
        client.fetch.return_value = {7: {b"RFC822": self.eml}}
        with patch("app.imap_client.IMAPClient", new=_ClientKontext([client])):
            with self.assertRaises(RuntimeError):
                mail_loeschen(self.quelle, 7, "<andere@example.test>")
        client.delete_messages.assert_not_called()
        client.expunge.assert_not_called()

    def test_neue_uid_wird_auch_gelesen_abgerufen(self):
        client = MagicMock()
        client.search.side_effect = [[41, 42, 43], []]
        client.fetch.side_effect = lambda uids, _felder: {
            uids[0]: {b"RFC822": self.eml, b"FLAGS": (b"\\Seen",)}
        }
        with patch("app.imap_client.IMAPClient", new=_ClientKontext([client])):
            mails = neue_mails_abrufen(self.quelle, nach_uid=42)

        self.assertEqual(
            [(["UID", "43:*"],), (["UNSEEN"],)],
            [aufruf.args for aufruf in client.search.call_args_list],
        )
        self.assertEqual([43], [mail["uid"] for mail in mails])

    def test_aeltere_ungelesene_mail_kann_nachgeholt_werden(self):
        client = MagicMock()
        client.search.side_effect = [[43], [40]]
        client.fetch.side_effect = lambda uids, _felder: {
            uids[0]: {b"RFC822": self.eml, b"FLAGS": ()}
        }
        with patch("app.imap_client.IMAPClient", new=_ClientKontext([client])):
            mails = neue_mails_abrufen(self.quelle, nach_uid=42)
        self.assertEqual([40, 43], [mail["uid"] for mail in mails])

    def test_erster_abruf_bleibt_bei_ungelesenen_mails(self):
        client = MagicMock()
        client.search.return_value = []
        with patch("app.imap_client.IMAPClient", new=_ClientKontext([client])):
            self.assertEqual([], neue_mails_abrufen(self.quelle))
        client.search.assert_called_once_with(["UNSEEN"])


if __name__ == "__main__":
    unittest.main()
