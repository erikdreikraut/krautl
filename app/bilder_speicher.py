"""Lokaler Bilderbestand und unabhängige, revisionsgeschützte Ausblendungen."""
import hashlib
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


def jetzt():
    return datetime.now(timezone.utc).isoformat()


def ordner():
    return Path(os.getenv("BILDER_DIR", "/app/var/bilder"))


@contextmanager
def datenbank():
    ordner().mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(ordner() / "bilder.sqlite3", timeout=10)
    try:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS artikel (
                id TEXT PRIMARY KEY, daten TEXT NOT NULL,
                ausgeblendet INTEGER NOT NULL DEFAULT 0,
                revision INTEGER NOT NULL DEFAULT 0,
                nutzer TEXT, geaendert TEXT);
            CREATE TABLE IF NOT EXISTS thumbs (id TEXT PRIMARY KEY, daten BLOB NOT NULL);
            CREATE TABLE IF NOT EXISTS status (id INTEGER PRIMARY KEY CHECK(id=1), daten TEXT NOT NULL);
        """)
        with db:
            yield db
    finally:
        db.close()


def status_lesen(db):
    row = db.execute("SELECT daten FROM status WHERE id=1").fetchone()
    return json.loads(row[0]) if row else {"status": "unbekannt", "letzter_erfolg": None, "fehler": None}


def status_setzen(**werte):
    with datenbank() as db:
        db.execute("BEGIN IMMEDIATE")
        status = {**status_lesen(db), **werte}
        db.execute("INSERT OR REPLACE INTO status VALUES (1, ?)", (json.dumps(status),))
        return status


def lesen():
    with datenbank() as db:
        artikel = [{**json.loads(daten), "ausgeblendet": bool(hidden), "revision": rev}
                   for daten, hidden, rev in db.execute("SELECT daten, ausgeblendet, revision FROM artikel")]
        return {**status_lesen(db), "artikel": artikel}


def freigegeben(ident, revision):
    with datenbank() as db:
        row = db.execute("SELECT ausgeblendet, revision FROM artikel WHERE id=?", (ident,)).fetchone()
        return (row is None and revision == 0) or (row is not None and row == (0, revision))


def ausblenden(ident, hidden, revision, nutzer):
    with datenbank() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT revision FROM artikel WHERE id=?", (ident,)).fetchone()
        if row is None:
            raise KeyError(ident)
        if row[0] != revision:
            raise ValueError("Der Artikel wurde inzwischen geändert. Bitte Liste neu laden.")
        db.execute("UPDATE artikel SET ausgeblendet=?, revision=revision+1, nutzer=?, geaendert=? WHERE id=?",
                   (int(hidden), nutzer, jetzt(), ident))


def thumb_speichern(daten):
    ident = hashlib.sha256(daten).hexdigest()
    with datenbank() as db:
        db.execute("INSERT OR IGNORE INTO thumbs VALUES (?, ?)", (ident, daten))
    return ident


def thumb_lesen(artikel_id, thumb_id):
    with datenbank() as db:
        row = db.execute("SELECT daten FROM artikel WHERE id=?", (artikel_id,)).fetchone()
        if not row or thumb_id not in [b["thumb"] for b in json.loads(row[0])["bilder"]]:
            return None
        row = db.execute("SELECT daten FROM thumbs WHERE id=?", (thumb_id,)).fetchone()
        return row[0] if row else None


def uebernehmen(artikel, vorher, api_ziel):
    """Ein erfolgreicher Lauf ersetzt nur seit Laufbeginn unveränderte, sichtbare Artikel."""
    with datenbank() as db:
        db.execute("BEGIN IMMEDIATE")
        aktuell = {ident: (hidden, rev) for ident, hidden, rev in db.execute("SELECT id, ausgeblendet, revision FROM artikel")}
        for ident, daten in artikel.items():
            alt = vorher.get(ident, {})
            if aktuell.get(ident, (0, 0)) != (0, alt.get("revision", 0)):
                continue
            if ident in aktuell:
                db.execute("UPDATE artikel SET daten=? WHERE id=?", (json.dumps(daten), ident))
            else:
                db.execute("INSERT INTO artikel (id, daten) VALUES (?, ?)", (ident, json.dumps(daten)))
        for ident, alt in vorher.items():
            if ident not in artikel and aktuell.get(ident) == (0, alt["revision"]):
                db.execute("DELETE FROM artikel WHERE id=?", (ident,))
        bildfehler = sum(bool(b.get("fehler")) for (raw,) in
                         db.execute("SELECT daten FROM artikel WHERE ausgeblendet=0")
                         for b in json.loads(raw)["bilder"])
        status = {**status_lesen(db), "status": "warnung" if bildfehler else "ok", "bildfehler": bildfehler, "letzter_erfolg": jetzt(), "fehler": None, "api_ziel": api_ziel}
        db.execute("INSERT OR REPLACE INTO status VALUES (1, ?)", (json.dumps(status),))
        # Keep only previews still referenced by the final snapshot, including hidden rows.
        verwendet = {b["thumb"] for (raw,) in db.execute("SELECT daten FROM artikel") for b in json.loads(raw)["bilder"]}
        for (ident,) in db.execute("SELECT id FROM thumbs").fetchall():
            if ident not in verwendet:
                db.execute("DELETE FROM thumbs WHERE id=?", (ident,))


class Belegt(Exception):
    pass


class Laufsperre:
    """OS-Dateisperre über den gesamten Abruf, auch über mehrere Prozesse hinweg."""
    def __enter__(self):
        ordner().mkdir(parents=True, exist_ok=True)
        self.file = (ordner() / "lauf.lock").open("a+b")
        try:
            if os.name == "nt":
                import msvcrt
                if self.file.tell() == 0:
                    self.file.write(b"0")
                    self.file.flush()
                self.file.seek(0)
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.file.close()
            raise Belegt("Eine Bilderaktualisierung läuft bereits.") from None
        return self

    def __exit__(self, *args):
        if self.file.closed:
            return
        if os.name == "nt":
            import msvcrt
            self.file.seek(0)
            msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
        self.file.close()


def zustand():
    data = lesen()
    if data["status"] == "laeuft":
        try:
            with Laufsperre():
                data = lesen()
                if data["status"] == "laeuft":
                    status_setzen(status="fehler", fehler="Die letzte Aktualisierung wurde unterbrochen. Bitte erneut aktualisieren.")
                    data = lesen()
        except Belegt:
            pass
    return data
