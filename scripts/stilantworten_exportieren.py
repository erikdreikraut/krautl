"""Read-only Bestandsaufnahme und Export historischer Service-Antworten.

Der Standardlauf erzeugt nur einen Kontrollbericht ohne Mailinhalte:
    python -m scripts.stilantworten_exportieren

Nach Prüfung kann zusätzlich der bereinigte Text exportiert werden:
    python -m scripts.stilantworten_exportieren --export
"""
import argparse
import csv
import hashlib
import json
import re
import unicodedata
from collections import Counter
from datetime import datetime
from email import message_from_bytes, policy
from email.utils import parseaddr, parsedate_to_datetime
from pathlib import Path

from imapclient import IMAPClient

from app.imap_client import lade_postfaecher
from app.mail_parser import nachrichtentext

AUTOREN = ("Thomas Meier", "Erik Schweitzer")
AUSGESCHLOSSENE_AUTOREN = ("Gursewak",)
ORDNER_NAMEN = ("gesendet", "sent", "sent items", "sent messages")
ZITAT_START = (
    re.compile(r"^\s*>"),
    re.compile(r"^\s*Am .+ schrieb .+:\s*$", re.IGNORECASE),
    re.compile(r"^\s*On .+ wrote:\s*$", re.IGNORECASE),
    re.compile(r"^\s*-{2,}\s*(Ursprüngliche Nachricht|Original Message)", re.IGNORECASE),
    re.compile(r"^\s*(Von|From):\s+.+", re.IGNORECASE),
)


def _normalisieren(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in text if not unicodedata.combining(c)).casefold()


def _enthaelt_name(text: str, autor: str) -> bool:
    return re.search(rf"\b{re.escape(_normalisieren(autor))}\b", _normalisieren(text)) is not None


def antwort_ohne_zitate(text: str) -> str:
    """Entfernt den zitierten vorherigen Verlauf, behält aber die eigene Signatur."""
    zeilen = text.replace("\r\n", "\n").replace("\r", "\n").splitlines()
    eigene = []
    for zeile in zeilen:
        if any(muster.search(zeile) for muster in ZITAT_START):
            break
        eigene.append(zeile.rstrip())

    # Mehrfache Leerzeilen glätten und typische technische Fußzeilen abschneiden.
    ergebnis = []
    leer = False
    for zeile in eigene:
        if re.search(r"Diese E-Mail.*vertraulich|This e-mail.*confidential", zeile, re.IGNORECASE):
            break
        if not zeile.strip():
            if ergebnis and not leer:
                ergebnis.append("")
            leer = True
        else:
            ergebnis.append(zeile.strip())
            leer = False
    return "\n".join(ergebnis).strip()


def autor_bestimmen(msg, antworttext: str) -> tuple[str | None, str]:
    absender_name, _ = parseaddr(msg.get("From", ""))
    kopf_treffer = [a for a in AUTOREN if _enthaelt_name(absender_name, a)]
    signaturbereich = antworttext[-1600:]
    signatur_treffer = [a for a in AUTOREN if _enthaelt_name(signaturbereich, a)]

    # Bei persönlicher Du-Ansprache wird bewusst häufig nur mit dem Vornamen
    # unterschrieben. Nur eine alleinstehende Zeile nahe dem Mailende zählt,
    # damit ein zufällig im Fließtext erwähnter Vorname nicht genügt.
    letzte_zeilen = [
        zeile.strip() for zeile in signaturbereich.splitlines() if zeile.strip()
    ][-12:]
    vorname_treffer = [
        autor for autor in AUTOREN
        if any(
            _normalisieren(zeile) == _normalisieren(autor.split()[0])
            for zeile in letzte_zeilen
        )
    ]
    ausgeschlossen = [
        autor for autor in AUSGESCHLOSSENE_AUTOREN
        if _enthaelt_name(absender_name, autor)
        or any(
            _normalisieren(zeile) in {
                _normalisieren(autor),
                _normalisieren(autor.split()[0]),
            }
            for zeile in letzte_zeilen
        )
    ]
    if ausgeschlossen:
        return None, "ausgeschlossen"

    alle = set(kopf_treffer) | set(signatur_treffer) | set(vorname_treffer)
    if len(alle) == 1:
        autor = next(iter(alle))
        if kopf_treffer:
            grund = "Absendername"
        elif signatur_treffer:
            grund = "Signatur"
        else:
            grund = "Vorname in Signatur"
        return autor, grund
    if len(alle) > 1:
        return None, "widersprüchig"
    return None, "nicht erkannt"


def gesendet_ordner(client: IMAPClient) -> str:
    ordner = client.list_folders()
    for flags, _trenner, name in ordner:
        flagtexte = {
            f.decode(errors="replace") if isinstance(f, bytes) else str(f)
            for f in flags
        }
        if any(flag.casefold() == "\\sent" for flag in flagtexte):
            return name.decode() if isinstance(name, bytes) else name
    for _flags, _trenner, name in ordner:
        name = name.decode() if isinstance(name, bytes) else name
        letzter_teil = re.split(r"[/\\.]", name.casefold())[-1]
        if letzter_teil in ORDNER_NAMEN:
            return name
    sichtbar = ", ".join(
        (name.decode() if isinstance(name, bytes) else name)
        for _flags, _trenner, name in ordner
    )
    raise RuntimeError(f"Kein Gesendet-Ordner gefunden. Vorhanden: {sichtbar}")


def _datum(msg) -> str:
    try:
        return parsedate_to_datetime(msg.get("Date")).date().isoformat()
    except (TypeError, ValueError):
        return ""


def _service_config():
    for config in lade_postfaecher():
        if config.funktion == "service" or config.user.casefold() == "service@dreikraut.de":
            return config
    raise RuntimeError("IMAP-Zugang für service@dreikraut.de ist nicht konfiguriert")


def analysieren(ausgabe: Path, export: bool, limit: int | None) -> dict:
    config = _service_config()
    ausgabe.mkdir(parents=True, exist_ok=True)
    zaehler = Counter()
    kontrollzeilen = []
    exportzeilen = []

    with IMAPClient(config.host, ssl=True) as client:
        client.login(config.user, config.password)
        ordner = gesendet_ordner(client)
        client.select_folder(ordner, readonly=True)
        uids = list(client.search(["ALL"]))
        if limit:
            uids = uids[-limit:]

        for start in range(0, len(uids), 50):
            paket = uids[start:start + 50]
            # BODY.PEEK verändert auch bei ungewöhnlichen Servern nicht den
            # Gelesen-Status; readonly verhindert zusätzliche Änderungen.
            daten = client.fetch(paket, ["BODY.PEEK[]"])
            for uid in paket:
                roh = daten.get(uid, {}).get(b"BODY[]")
                if not roh:
                    zaehler["Lesefehler"] += 1
                    continue
                msg = message_from_bytes(roh, policy=policy.default)
                antwort = antwort_ohne_zitate(nachrichtentext(msg))
                autor, grund = autor_bestimmen(msg, antwort)
                kategorie = autor or (
                    "Ausgeschlossen" if grund == "ausgeschlossen" else "Unklar"
                )
                zaehler[kategorie] += 1
                kontrollzeilen.append({
                    "kennung": hashlib.sha256(
                        (msg.get("Message-ID") or str(uid)).encode("utf-8")
                    ).hexdigest()[:12],
                    "datum": _datum(msg),
                    "autor": kategorie,
                    "erkannt_durch": grund,
                    "zeichen": len(antwort),
                })
                if export and autor and len(antwort) >= 30:
                    exportzeilen.append({
                        "message_id_hash": kontrollzeilen[-1]["kennung"],
                        "datum": kontrollzeilen[-1]["datum"],
                        "autor": autor,
                        "text": antwort,
                    })

    with (ausgabe / "autoren-kontrolle.csv").open("w", encoding="utf-8-sig", newline="") as datei:
        writer = csv.DictWriter(
            datei, fieldnames=["kennung", "datum", "autor", "erkannt_durch", "zeichen"]
        )
        writer.writeheader()
        writer.writerows(kontrollzeilen)

    if export:
        with (ausgabe / "stilantworten.jsonl").open("w", encoding="utf-8") as datei:
            for zeile in exportzeilen:
                datei.write(json.dumps(zeile, ensure_ascii=False) + "\n")

    bericht = [
        "# Vorschau der Stilantworten",
        "",
        f"- Erstellt: {datetime.now().astimezone().isoformat(timespec='seconds')}",
        f"- Postfach: {config.user}",
        f"- Gesendet-Ordner: `{ordner}`",
        f"- Untersuchte Nachrichten: {len(kontrollzeilen)}",
        f"- Thomas Meier: {zaehler['Thomas Meier']}",
        f"- Erik Schweitzer: {zaehler['Erik Schweitzer']}",
        f"- Unklar oder widersprüchlich: {zaehler['Unklar']}",
        f"- Ausdrücklich ausgeschlossen: {zaehler['Ausgeschlossen']}",
        f"- Lesefehler: {zaehler['Lesefehler']}",
        "",
        "Der Vorschau-Bericht enthält keine Mailtexte oder Empfängeradressen.",
    ]
    if export:
        bericht += ["", f"Bereinigte, eindeutig zugeordnete Antworten exportiert: {len(exportzeilen)}"]
    (ausgabe / "analysebericht.md").write_text("\n".join(bericht) + "\n", encoding="utf-8")
    return {
        "ordner": ordner,
        "untersucht": len(kontrollzeilen),
        "thomas": zaehler["Thomas Meier"],
        "erik": zaehler["Erik Schweitzer"],
        "unklar": zaehler["Unklar"],
        "ausgeschlossen": zaehler["Ausgeschlossen"],
        "exportiert": len(exportzeilen),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--export", action="store_true", help="bereinigte Antworttexte exportieren")
    parser.add_argument(
        "--limit", type=int, default=500,
        help="nur die neuesten N Nachrichten untersuchen (Standard: 500)",
    )
    parser.add_argument(
        "--ausgabe", type=Path, default=Path("/tmp/krautl-stilanalyse"),
        help="Ausgabeverzeichnis",
    )
    args = parser.parse_args()
    ergebnis = analysieren(args.ausgabe, args.export, args.limit)
    print(json.dumps(ergebnis, ensure_ascii=False, indent=2))
    print(f"Bericht gespeichert unter: {args.ausgabe}")


if __name__ == "__main__":
    main()
