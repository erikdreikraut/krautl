"""
IMAP-Anbindung.

WICHTIG zur Sicherheit: Dieses Modul liest ausschließlich Zugangsdaten aus
Umgebungsvariablen (siehe .env.example). Niemals Zugangsdaten hart codieren
oder in Logs/Prompts an die Claude API weitergeben.
"""
import os
from dataclasses import dataclass
from imapclient import IMAPClient


@dataclass
class PostfachConfig:
    funktion: str  # "info", "service", "einkauf", "marketing", ...
    host: str
    user: str
    password: str


def lade_postfaecher() -> list[PostfachConfig]:
    """Liest alle IMAP_<NAME>_HOST/USER/PASSWORD Tripel aus der Umgebung."""
    namen = set()
    for key in os.environ:
        if key.startswith("IMAP_") and key.endswith("_HOST"):
            namen.add(key[len("IMAP_"):-len("_HOST")])

    postfaecher = []
    for name in sorted(namen):
        host = os.environ.get(f"IMAP_{name}_HOST")
        user = os.environ.get(f"IMAP_{name}_USER")
        password = os.environ.get(f"IMAP_{name}_PASSWORD")
        if host and user and password:
            postfaecher.append(PostfachConfig(name.lower(), host, user, password))
    return postfaecher


def neue_mails_abrufen(config: PostfachConfig, ordner: str = "INBOX") -> list[dict]:
    """Holt neue (ungelesene) Mails aus einem Postfach als rohe EML + Metadaten."""
    with IMAPClient(config.host, ssl=True) as client:
        client.login(config.user, config.password)
        client.select_folder(ordner)
        uids = client.search(["UNSEEN"])

        ergebnisse = []
        for uid in uids:
            raw = client.fetch([uid], ["RFC822", "FLAGS"])
            ergebnisse.append({
                "uid": uid,
                "postfach": config.funktion,
                "eml": raw[uid][b"RFC822"],
            })
        return ergebnisse


def mail_verschieben(
    quelle: PostfachConfig,
    quell_uid: int,
    ziel: PostfachConfig,
    ziel_ordner: str,
    quell_ordner: str = "INBOX",
) -> None:
    """
    Verschiebt eine Mail zwischen unterschiedlichen IMAP-Konten.

    IMAP kennt kein natives Verschieben zwischen verschiedenen Konten — daher,
    wie im ursprünglichen n8n-Workflow MAIL_VERSCHIEBEN gelöst:
    EML herunterladen -> im Zielpostfach als Entwurf anlegen -> Draft-Flag
    entfernen -> im Quellpostfach löschen.
    """
    with IMAPClient(quelle.host, ssl=True) as q:
        q.login(quelle.user, quelle.password)
        q.select_folder(quell_ordner)
        eml = q.fetch([quell_uid], ["RFC822"])[quell_uid][b"RFC822"]

    with IMAPClient(ziel.host, ssl=True) as z:
        z.login(ziel.user, ziel.password)
        neue_uid = z.append(ziel_ordner, eml, flags=[b"\\Draft"])
        z.remove_flags(ziel_ordner, [neue_uid], [b"\\Draft"])

    with IMAPClient(quelle.host, ssl=True) as q:
        q.login(quelle.user, quelle.password)
        q.select_folder(quell_ordner)
        q.delete_messages([quell_uid])
        q.expunge()
