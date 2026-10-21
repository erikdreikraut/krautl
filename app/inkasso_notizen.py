"""Append-only local invoice history, separate from JTL snapshots."""
import os
from contextlib import closing
from datetime import datetime, timezone
import sqlite3
from pathlib import Path


def pfad():
    return Path(os.getenv("INKASSO_NOTIZEN_DIR", "/app/var/inkasso-notizen")) / "notizen.sqlite3"


def eintraege(db):
    tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    result = {}
    # Existing notes remain intact; unknown historical author/time are never invented.
    if "notizen" in tables:
        for ident, text in db.execute("SELECT id, text FROM notizen WHERE text != ''"):
            result.setdefault(ident, []).append({"text": text, "nutzer": None, "zeit": None})
    if "eintraege" in tables:
        for ident, text, user, timestamp in db.execute("SELECT rechnung, text, nutzer, zeit FROM eintraege ORDER BY rowid"):
            result.setdefault(ident, []).append({"text": text, "nutzer": user, "zeit": timestamp})
    return {ident: {"hinweis": True, "hinweise": rows} for ident, rows in result.items()}


def lesen():
    path = pfad()
    if not path.exists():
        return {}
    with closing(sqlite3.connect(path)) as db:
        return eintraege(db)


def speichern(ident, text, nutzer, anfrage_id):
    text = text.strip()
    if not text:
        raise ValueError("empty note")
    path = pfad()
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path, timeout=10)) as db, db:
        db.execute("CREATE TABLE IF NOT EXISTS eintraege (anfrage TEXT PRIMARY KEY, rechnung TEXT NOT NULL, text TEXT NOT NULL, nutzer TEXT NOT NULL, zeit TEXT NOT NULL)")
        db.execute("BEGIN IMMEDIATE")
        old = db.execute("SELECT rechnung, text, nutzer FROM eintraege WHERE anfrage=?", (anfrage_id,)).fetchone()
        if old and old != (ident, text, nutzer):
            raise ValueError("request conflict")
        if not old:
            db.execute("INSERT INTO eintraege VALUES (?, ?, ?, ?, ?)",
                       (anfrage_id, ident, text, nutzer, datetime.now(timezone.utc).isoformat()))
        return eintraege(db)[ident]
