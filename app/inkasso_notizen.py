"""Local invoice notes, independent of worker snapshots."""
import os
from contextlib import closing
import sqlite3
from pathlib import Path


def pfad():
    return Path(os.getenv("INKASSO_NOTIZEN_DIR", "/app/var/inkasso-notizen")) / "notizen.sqlite3"


def lesen():
    path = pfad()
    if not path.exists():
        return {}
    with closing(sqlite3.connect(path)) as db:
        rows = db.execute("SELECT id, text, revision FROM notizen").fetchall()
    return {ident: {"hinweis": text, "hinweis_revision": revision} for ident, text, revision in rows}


def speichern(ident, text, revision):
    path = pfad()
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path, timeout=10)) as db, db:
        db.execute("CREATE TABLE IF NOT EXISTS notizen (id TEXT PRIMARY KEY, text TEXT NOT NULL, revision INTEGER NOT NULL)")
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT revision FROM notizen WHERE id = ?", (ident,)).fetchone()
        if (row[0] if row else 0) != revision:
            raise ValueError("revision conflict")
        text = text.strip()
        revision += 1
        db.execute("INSERT INTO notizen VALUES (?, ?, ?) ON CONFLICT(id) DO UPDATE SET text=excluded.text, revision=excluded.revision", (ident, text, revision))
    return {"hinweis": text, "hinweis_revision": revision}
