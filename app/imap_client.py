"""
IMAP-Anbindung.

WICHTIG zur Sicherheit: Dieses Modul liest ausschließlich Zugangsdaten aus
Umgebungsvariablen (siehe .env.example). Niemals Zugangsdaten hart codieren
oder in Logs/Prompts an die Claude API weitergeben.
"""
import os
from dataclasses import dataclass
from email import message_from_bytes, policy

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


def mail_rohdaten_laden(config: PostfachConfig, uid: int, ordner: str = "INBOX") -> bytes:
    """Lädt eine bereits bekannte Mail erneut, etwa zur Anhangsverarbeitung."""
    with IMAPClient(config.host, ssl=True) as client:
        client.login(config.user, config.password)
        client.select_folder(ordner)
        daten = client.fetch([uid], ["RFC822"])
        if uid not in daten:
            raise RuntimeError(f"Mail mit UID {uid} nicht mehr im Ordner {ordner} gefunden")
        return daten[uid][b"RFC822"]


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
    if quelle.user == ziel.user and quell_ordner == ziel_ordner:
        # Wie im n8n-Workflow ("Schon am Ziel?"): nichts zu tun, wenn Quelle
        # und Ziel identisch sind — verhindert unnötiges Download/Delete.
        return

    with IMAPClient(quelle.host, ssl=True) as q:
        q.login(quelle.user, quelle.password)
        q.select_folder(quell_ordner)
        eml = q.fetch([quell_uid], ["RFC822"])[quell_uid][b"RFC822"]

    # append() liefert nur die rohe Server-Antwort zurück, keine UID (siehe
    # imapclient-Quelltext) — die neue UID muss über die Message-ID gesucht
    # werden, sonst schickt remove_flags() einen unsinnigen Wert als uidset
    # ("UID command error: BAD ... Invalid uidset").
    message_id = message_from_bytes(eml, policy=policy.default).get("Message-ID")

    with IMAPClient(ziel.host, ssl=True) as z:
        z.login(ziel.user, ziel.password)
        z.select_folder(ziel_ordner)
        treffer = z.search(["HEADER", "Message-ID", message_id]) if message_id else []

        # Ein früherer Versuch kann die Mail bereits angehängt haben und erst
        # danach gescheitert sein. In diesem Fall nicht noch einmal anhängen.
        if not treffer:
            z.append(ziel_ordner, eml, flags=[b"\\Draft"])
            # STORE erfordert eine ausgewählte Mailbox. Nach APPEND erneut
            # auswählen, damit auch eigenwillige Serverzustände sauber sind.
            z.select_folder(ziel_ordner)
            treffer = z.search(["HEADER", "Message-ID", message_id]) if message_id else []
            if not treffer:
                # Nur direkt nach unserem APPEND auf die neueste UID
                # zurückfallen. Bei einem Wiederholungsversuch ohne Message-ID
                # wäre ein blindes Wiederverwenden einer fremden Mail riskant.
                alle = z.search(["ALL"])
                treffer = [max(alle)] if alle else []
        if treffer:
            # Signatur von IMAPClient: remove_flags(messages, flags).
            # Der Ordnername gehört hier nicht hinein; genau das verursachte
            # "expected str instance, int found".
            z.remove_flags(treffer, [b"\\Draft"])
        else:
            raise RuntimeError("Mail konnte im Zielordner nicht wiedergefunden werden")

    with IMAPClient(quelle.host, ssl=True) as q:
        q.login(quelle.user, quelle.password)
        q.select_folder(quell_ordner)
        q.delete_messages([quell_uid])
        q.expunge()
