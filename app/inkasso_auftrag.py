"""One durable admin-requested refresh, consumed by the Inkasso worker."""
import json
import os
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4
from .inkasso import jetzt


def ordner():
    return Path(os.getenv("INKASSO_AUFTRAG_DIR", "/app/var/inkasso-auftraege"))


@contextmanager
def sperre(warten=False):
    folder = ordner()
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (folder / "auftrag.lock").open("a+b") as lock:
        if os.name == "nt":
            import msvcrt
            if lock.tell() == 0:
                lock.write(b"0")
                lock.flush()
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK if warten else msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(lock, fcntl.LOCK_EX | (0 if warten else fcntl.LOCK_NB))
        try:
            yield
        finally:
            if os.name == "nt":
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)


def lesen():
    try:
        return json.loads((ordner() / "auftrag.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None


def speichern(data):
    path = ordner() / "auftrag.json"
    tmp = path.with_name(uuid4().hex + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    tmp.replace(path)


def anlegen(ids):
    with sperre():
        alt = lesen()
        if alt and alt["status"] in ("wartet", "laeuft"):
            raise BlockingIOError("Eine Auswahlaktualisierung ist bereits vorgemerkt oder läuft.")
        data = {"id": uuid4().hex, "ids": ids, "anzahl": len(ids), "status": "wartet",
                "angefordert_am": jetzt().isoformat(), "fehler": None}
        speichern(data)
        return oeffentlich(data)


def oeffentlich(data=None):
    data = data if data is not None else lesen()
    return {k: v for k, v in data.items() if k != "ids"} if data else None
