"""
Parst rohe EML-Bytes (wie von imap_client.neue_mails_abrufen geliefert) in die
Felder, die Mail-Modell und agent.klassifiziere() erwarten.
"""
import re
import hashlib
from pathlib import Path
from html.parser import HTMLParser
from datetime import datetime, timezone
from email import message_from_bytes, policy
from email.utils import parseaddr, parsedate_to_datetime

TEXT_AUSZUG_MAX_LAENGE = 4000

_SPAM_SCORE_MUSTER = re.compile(r"score=(-?\d+(?:\.\d+)?)")
_BLOCK_ELEMENTE = {
    "address", "article", "aside", "blockquote", "br", "div", "footer",
    "h1", "h2", "h3", "h4", "h5", "h6", "header", "hr", "li", "main",
    "nav", "p", "section", "table", "tr",
}
_UNSICHTBARE_ELEMENTE = {"head", "style", "script", "noscript", "template", "svg"}


class _LesbarerHTMLText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.teile: list[str] = []
        self.unsichtbar_tiefe = 0

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in _UNSICHTBARE_ELEMENTE:
            self.unsichtbar_tiefe += 1
        elif not self.unsichtbar_tiefe and tag in _BLOCK_ELEMENTE:
            self.teile.append("\n")

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in _UNSICHTBARE_ELEMENTE:
            self.unsichtbar_tiefe = max(0, self.unsichtbar_tiefe - 1)
        elif not self.unsichtbar_tiefe and tag in _BLOCK_ELEMENTE:
            self.teile.append("\n")

    def handle_data(self, data):
        if not self.unsichtbar_tiefe:
            self.teile.append(data)


def _text_aus_html(html: str) -> str:
    parser = _LesbarerHTMLText()
    parser.feed(html)
    parser.close()
    zeilen = []
    for zeile in "".join(parser.teile).splitlines():
        bereinigt = re.sub(r"[^\S\r\n]+", " ", zeile).strip()
        if bereinigt and (not zeilen or bereinigt != zeilen[-1]):
            zeilen.append(bereinigt)
    return "\n\n".join(zeilen)


def nachrichtentext(msg) -> str:
    """Liefert den vollständigen, lesbaren Text einer E-Mail-Nachricht."""
    body_teil = msg.get_body(preferencelist=("plain", "html"))
    if body_teil is None:
        return ""
    inhalt = body_teil.get_content()
    if body_teil.get_content_type() == "text/html":
        return _text_aus_html(inhalt)
    return inhalt


def _spam_score(msg) -> float | None:
    for header in ("X-Spam-Score", "X-Spam-Status", "X-Spam-Level"):
        wert = msg.get(header)
        if not wert:
            continue
        treffer = _SPAM_SCORE_MUSTER.search(wert)
        if treffer:
            return float(treffer.group(1))
    return None


def _stabile_ersatz_message_id(msg, inhalt: str) -> str:
    """Erzeugt für Mails ohne Message-ID eine reproduzierbare Kennung.

    Eine Zufalls-ID würde dieselbe auf dem Server verbliebene Mail bei jedem
    Abruf wie eine neue Nachricht aussehen lassen. Verwendet werden nur
    inhaltlich stabile Kopfzeilen, der lesbare Text und Anhänge. IMAP-Flags
    oder vom Server ergänzte Transportkopfzeilen beeinflussen die Kennung
    damit nicht.
    """
    hasher = hashlib.sha256()
    for header in ("From", "To", "Cc", "Date", "Subject"):
        hasher.update(str(msg.get(header, "")).strip().encode("utf-8", "replace"))
        hasher.update(b"\0")
    hasher.update(inhalt.encode("utf-8", "replace"))
    for teil in msg.iter_attachments():
        hasher.update(str(teil.get_filename() or "").encode("utf-8", "replace"))
        hasher.update(b"\0")
        hasher.update(teil.get_payload(decode=True) or b"")
        hasher.update(b"\0")
    return f"<generiert-{hasher.hexdigest()}@krautl.local>"


def parse_eml(raw: bytes) -> dict:
    msg = message_from_bytes(raw, policy=policy.default)

    absender_name, absender_adresse = parseaddr(msg.get("From", ""))

    empfangen_am: datetime
    try:
        empfangen_am = parsedate_to_datetime(msg.get("Date"))
        if empfangen_am.tzinfo is None:
            empfangen_am = empfangen_am.replace(tzinfo=timezone.utc)
        else:
            empfangen_am = empfangen_am.astimezone(timezone.utc)
    except (TypeError, ValueError):
        empfangen_am = datetime.now(timezone.utc)

    inhalt = nachrichtentext(msg)

    message_id = (msg.get("Message-ID") or "").strip()
    if not message_id:
        message_id = _stabile_ersatz_message_id(msg, inhalt)

    krautl_generiert = (
        str(msg.get("X-Krautl-Generated", "")).strip().casefold()
        == "audio-transcription"
        or message_id.casefold().startswith("<krautl-audio-")
    )

    return {
        "message_id": message_id,
        "absender_name": absender_name or absender_adresse,
        "absender_adresse": absender_adresse,
        "betreff": msg.get("Subject", "(kein Betreff)"),
        "text_auszug": inhalt[:TEXT_AUSZUG_MAX_LAENGE],
        "empfangen_am": empfangen_am,
        "spam_score": _spam_score(msg),
        "krautl_generiert": krautl_generiert,
    }


ERLAUBTE_RECHNUNGSENDUNGEN = {
    ".pdf", ".xml", ".jpg", ".jpeg", ".png", ".gif", ".webp",
}


def rechnungsanhaenge(raw: bytes) -> list[dict]:
    """Extrahiert gängige, tatsächlich angehängte Rechnungsdateien aus EML."""
    msg = message_from_bytes(raw, policy=policy.default)
    ergebnis = []
    for teil in msg.iter_attachments():
        dateiname = teil.get_filename() or "anhang"
        endung = Path(dateiname).suffix.lower()
        if endung not in ERLAUBTE_RECHNUNGSENDUNGEN:
            continue
        inhalt = teil.get_payload(decode=True)
        if not inhalt:
            continue
        ergebnis.append({
            "dateiname": dateiname,
            "endung": endung,
            "mime_type": teil.get_content_type(),
            "inhalt": inhalt,
            "sha256": hashlib.sha256(inhalt).hexdigest(),
        })
    return ergebnis
