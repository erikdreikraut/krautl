"""Unabhängiger Google-FAQ-Zusatzfeed; keine JTL-Ausgabe wird verändert.

TSV-Gruppenquotierung gemäß https://support.google.com/merchants/answer/14998273
und https://support.google.com/merchants/answer/17085211.
"""
import asyncio
import hashlib
import html
import json
import logging
import os
import re
import tempfile
from collections import Counter
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

from sqlalchemy import select

from .models import FaqEintrag, Produkt

FEED_PFAD = "/feeds/google-product-faq.tsv"
MAX_PAARE = 30
MAX_TEXT = 1000
MAX_GESAMT = 10000
POLL_INTERVAL_SECONDS = 30
logger = logging.getLogger(__name__)


class _Plaintext(HTMLParser):
    BLOCK = {"p", "br", "div", "li", "ul", "ol", "h1", "h2", "h3", "tr", "td"}
    IGNORIEREN = {"script", "style", "template"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.teile = []
        self.verborgen = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.IGNORIEREN:
            self.verborgen += 1
        if tag in self.BLOCK and not self.verborgen:
            self.teile.append(" ")

    def handle_endtag(self, tag):
        if tag in self.IGNORIEREN:
            self.verborgen = max(0, self.verborgen - 1)
        if tag in self.BLOCK and not self.verborgen:
            self.teile.append(" ")

    def handle_data(self, data):
        if not self.verborgen:
            self.teile.append(data)


def plaintext(text: str) -> str:
    parser = _Plaintext()
    parser.feed(html.unescape(text or ""))
    parser.close()
    text = "".join(parser.teile)
    # Die im FAQ-Editor verwendeten Markdown-Elemente als lesbaren Text ausgeben.
    text = re.sub(r"!?\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"(?m)^\s*(?:#{1,6}\s+|[-*+]\s+|\d+\.\s+|>\s*)", "", text)
    for marker in ("**", "__", "~~", "`", "*", "_"):
        text = re.sub(re.escape(marker) + r"(.+?)" + re.escape(marker), r"\1", text)
    text = re.sub(r"[\x00-\x1f\x7f-\x9f]", " ", text)
    return " ".join(text.split())


def _quotieren(text: str) -> str:
    # Keine Backslash-Escapes und KEINE zweite CSV-Quotierung der Gruppen-Zelle.
    return '"' + text.replace('"', '""') + '"'


def feed_bauen(zeilen: list[dict]) -> dict:
    gruppen = {}
    for zeile in sorted(zeilen, key=lambda z: (z["sortierung"], z["faq_id"])):
        pid = zeile["produkt_id"]
        if pid not in gruppen:
            gruppen[pid] = {
                "produkt_id": pid, "name": zeile["produkt_name"] or "Allgemeine FAQ",
                "artikelnummer": zeile["artikelnummer"], "faq": [],
                "anzahl_qa": 0, "zeichen": 0, "_paare": [],
            }
        gruppen[pid]["faq"].append(zeile)
    id_anzahl = Counter(
        g["artikelnummer"] for g in gruppen.values()
        if g["artikelnummer"] and any(f["include_in_google_product_qa"] for f in g["faq"])
    )
    warnungen = []
    tsv = ["id\tquestion_and_answer"]
    for gruppe in sorted(gruppen.values(), key=lambda g: (g["artikelnummer"] or "", g["produkt_id"] or 0)):
        vorschau = []
        artikelnummer = gruppe["artikelnummer"]
        for eintrag in gruppe["faq"]:
            ausgewaehlt = bool(eintrag["include_in_google_product_qa"])
            frage, antwort = plaintext(eintrag["frage"]), plaintext(eintrag["antwort"])
            gruende = []
            paar = f"{_quotieren(frage)}:{_quotieren(antwort)}"
            # Der Google-Haken ist die einzige redaktionelle Auswahl.
            # Status und Aktiv-Merkmale gehören zu anderen Verwendungen der FAQ.
            if ausgewaehlt:
                if gruppe["produkt_id"] is None:
                    gruende.append("Keinem Produkt zugeordnet")
                if not artikelnummer or not artikelnummer.strip():
                    gruende.append("Artikelnummer fehlt")
                elif len(artikelnummer) > 50 or re.search(r"[\x00-\x1f\x7f-\x9f]", artikelnummer):
                    gruende.append("Artikelnummer ungültig: maximal 50 Zeichen, keine Steuerzeichen")
                elif artikelnummer != " ".join(artikelnummer.split()):
                    gruende.append("Artikelnummer enthält Leerraum, den Google verändern würde")
                elif id_anzahl[artikelnummer] > 1:
                    gruende.append("Artikelnummer mehrfach vergeben")
                if not frage or not antwort:
                    gruende.append("Frage oder Antwort ist als Plaintext leer")
                if len(frage) > MAX_TEXT or len(antwort) > MAX_TEXT:
                    gruende.append("Frage oder Antwort überschreitet 1.000 Zeichen")
                if not gruende:
                    if gruppe["anzahl_qa"] >= MAX_PAARE:
                        gruende.append("Produktlimit von 30 Q&A erreicht")
                    elif gruppe["zeichen"] + bool(gruppe["_paare"]) + len(paar) > MAX_GESAMT:
                        gruende.append("Produktlimit von 10.000 Zeichen überschritten")
            exportiert = ausgewaehlt and not gruende
            if exportiert:
                gruppe["_paare"].append(paar)
                gruppe["anzahl_qa"] += 1
                gruppe["zeichen"] = len(",".join(gruppe["_paare"]))
            elif ausgewaehlt:
                warnungen.append({
                    "produkt_id": gruppe["produkt_id"], "artikelnummer": artikelnummer,
                    "faq_id": eintrag["faq_id"],
                    "meldung": f"{gruppe['name']} · FAQ #{eintrag['faq_id']}: {'; '.join(gruende)}",
                })
            vorschau.append({
                "faq_id": eintrag["faq_id"], "frage": frage, "antwort": antwort,
                "ausgewaehlt": ausgewaehlt, "exportiert": exportiert, "gruende": gruende,
                "zeichen_frage": len(frage), "zeichen_antwort": len(antwort),
            })
        paare = gruppe.pop("_paare")
        gruppe["faq"] = vorschau
        if paare:
            # IDs werden niemals ergänzt, numerisch konvertiert oder normalisiert.
            id_feld = _quotieren(artikelnummer) if '"' in artikelnummer else artikelnummer
            tsv.append(id_feld + "\t" + ",".join(paare))
    return {
        "tsv": "\n".join(tsv) + "\n",
        "anzahl_produkte": len(tsv) - 1,
        "anzahl_qa": sum(g["anzahl_qa"] for g in gruppen.values()),
        "warnungen": warnungen, "produkte": list(gruppen.values()),
    }


def atomar_schreiben(pfad: Path, inhalt: str):
    pfad.parent.mkdir(parents=True, exist_ok=True)
    temp = None
    try:
        with tempfile.NamedTemporaryFile(dir=pfad.parent, prefix=".google-faq-", delete=False) as datei:
            temp = Path(datei.name)
            datei.write(inhalt.encode("utf-8"))
            datei.flush()
            os.fsync(datei.fileno())
        os.replace(temp, pfad)
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)


class GoogleProductQaFeed:
    """Serialisiert Generatoren im bestehenden einzelnen Uvicorn-App-Prozess.

    Erst nach erfolgreichem atomarem Dateiaustausch wird der zugehörige Status
    veröffentlicht. Jeder öffentliche Abruf prüft vorher den aktuellen DB-Stand.
    """
    def __init__(self, session_factory, verzeichnis=None):
        self.session_factory = session_factory
        self.pfad = Path(verzeichnis or os.environ.get("GOOGLE_PRODUCT_QA_DIR", "var/feeds")) / "google-product-faq.tsv"
        self.lock = asyncio.Lock()
        self.snapshot = None
        self.fingerprint = None
        self.fehler = None

    async def aktualisieren(self, erzwingen=False):
        async with self.lock:
            try:
                async with self.session_factory() as session:
                    # Eine Abfrage: FAQ und Artikelnummer aus demselben DB-Snapshot.
                    zeilen = (await session.execute(select(
                        FaqEintrag.id.label("faq_id"), FaqEintrag.produkt_id,
                        FaqEintrag.frage, FaqEintrag.antwort,
                        FaqEintrag.sortierung,
                        FaqEintrag.include_in_google_product_qa,
                        Produkt.name.label("produkt_name"), Produkt.artikelnummer,
                    ).outerjoin(Produkt, Produkt.id == FaqEintrag.produkt_id)
                        .order_by(FaqEintrag.id))).mappings().all()
                zeilen = [dict(z) for z in zeilen]
                fingerprint = hashlib.sha256(json.dumps(zeilen, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
                if erzwingen or fingerprint != self.fingerprint or not self.pfad.exists():
                    snapshot = feed_bauen(zeilen)
                    await asyncio.to_thread(atomar_schreiben, self.pfad, snapshot["tsv"])
                    snapshot["letzte_generierung"] = datetime.now(timezone.utc).isoformat()
                    self.snapshot, self.fingerprint = snapshot, fingerprint
                self.fehler = None
                return self.snapshot
            except Exception:
                self.fehler = "Feed konnte nicht aktualisiert werden. Bitte neu erzeugen oder Serverprotokoll prüfen."
                logger.exception("Google-FAQ-Feed konnte nicht erzeugt werden")
                raise

    def status(self):
        snapshot = self.snapshot or {}
        return {
            "feed_pfad": FEED_PFAD,
            "letzte_generierung": snapshot.get("letzte_generierung"),
            "anzahl_produkte": snapshot.get("anzahl_produkte", 0),
            "anzahl_qa": snapshot.get("anzahl_qa", 0),
            "warnungen": snapshot.get("warnungen", []),
            "fehler": self.fehler,
            "aktuell": self.snapshot is not None and not self.fehler,
        }

    async def ueberwachen(self):
        # Erfasst auch Änderungen durch Importskripte, Worker und direkte SQL-Writes.
        while True:
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
            try:
                await self.aktualisieren()
            except Exception:
                pass  # protokolliert; Status zeigt Fehler, nächste Runde versucht erneut
