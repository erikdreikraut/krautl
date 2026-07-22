"""
Parst rohe EML-Bytes (wie von imap_client.neue_mails_abrufen geliefert) in die
Felder, die Mail-Modell und agent.klassifiziere() erwarten.
"""
import re
import uuid
import hashlib
from pathlib import Path
from datetime import datetime, timezone
from email import message_from_bytes, policy
from email.utils import parseaddr, parsedate_to_datetime

TEXT_AUSZUG_MAX_LAENGE = 4000

_SPAM_SCORE_MUSTER = re.compile(r"score=(-?\d+(?:\.\d+)?)")
_HTML_TAG_MUSTER = re.compile(r"<[^>]+>")


def _text_aus_html(html: str) -> str:
    return re.sub(r"\s+", " ", _HTML_TAG_MUSTER.sub(" ", html)).strip()


def _spam_score(msg) -> float | None:
    for header in ("X-Spam-Score", "X-Spam-Status", "X-Spam-Level"):
        wert = msg.get(header)
        if not wert:
            continue
        treffer = _SPAM_SCORE_MUSTER.search(wert)
        if treffer:
            return float(treffer.group(1))
    return None


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

    body_teil = msg.get_body(preferencelist=("plain", "html"))
    if body_teil is not None:
        inhalt = body_teil.get_content()
        if body_teil.get_content_type() == "text/html":
            inhalt = _text_aus_html(inhalt)
    else:
        inhalt = ""

    message_id = (msg.get("Message-ID") or "").strip()
    if not message_id:
        message_id = f"<generiert-{uuid.uuid4()}@krautl.local>"

    return {
        "message_id": message_id,
        "absender_name": absender_name or absender_adresse,
        "absender_adresse": absender_adresse,
        "betreff": msg.get("Subject", "(kein Betreff)"),
        "text_auszug": inhalt[:TEXT_AUSZUG_MAX_LAENGE],
        "empfangen_am": empfangen_am,
        "spam_score": _spam_score(msg),
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
