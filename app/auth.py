"""Einfache feste Nutzerkonten und signierte Sitzungen für Krautl."""
import base64
import hashlib
import hmac
import json
import os
import time


COOKIE_NAME = "krautl_session"
SESSION_DAUER_SEKUNDEN = 7 * 24 * 60 * 60

BENUTZER = {
    "erik": {
        "benutzername": "erik",
        "name": "Erik Schweitzer",
        "titel": None,
        "rolle": "vollzugriff",
        "passwort_env": "KRAUTL_PASSWORD_ERIK",
    },
    "gursewak": {
        "benutzername": "gursewak",
        "name": "Gursewak Singh",
        "titel": "Auszubildender",
        "rolle": "vollzugriff",
        "passwort_env": "KRAUTL_PASSWORD_GURSEWAK",
    },
    "ludwig": {
        "benutzername": "ludwig",
        "name": "Ludwig Schnorrenberg",
        "titel": "Auszubildender",
        "rolle": "vollzugriff",
        "passwort_env": "KRAUTL_PASSWORD_LUDWIG",
    },
}


def _secret() -> bytes:
    wert = os.environ.get("KRAUTL_SESSION_SECRET")
    if not wert:
        raise RuntimeError("KRAUTL_SESSION_SECRET ist nicht konfiguriert")
    return wert.encode("utf-8")


def _kodieren(daten: bytes) -> str:
    return base64.urlsafe_b64encode(daten).decode("ascii").rstrip("=")


def _dekodieren(wert: str) -> bytes:
    return base64.urlsafe_b64decode(wert + "=" * (-len(wert) % 4))


def sitzung_erstellen(benutzername: str) -> str:
    inhalt = _kodieren(json.dumps({
        "sub": benutzername,
        "exp": int(time.time()) + SESSION_DAUER_SEKUNDEN,
    }, separators=(",", ":")).encode("utf-8"))
    signatur = _kodieren(hmac.new(
        _secret(), inhalt.encode("ascii"), hashlib.sha256
    ).digest())
    return f"{inhalt}.{signatur}"


def sitzung_lesen(token: str | None) -> dict | None:
    if not token:
        return None
    try:
        inhalt, signatur = token.split(".", 1)
        erwartet = _kodieren(hmac.new(
            _secret(), inhalt.encode("ascii"), hashlib.sha256
        ).digest())
        if not hmac.compare_digest(signatur, erwartet):
            return None
        daten = json.loads(_dekodieren(inhalt))
        if int(daten["exp"]) < int(time.time()):
            return None
        return BENUTZER.get(str(daten["sub"]).casefold())
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        return None


def anmelden(benutzername: str, passwort: str) -> dict | None:
    benutzer = BENUTZER.get(benutzername.strip().casefold())
    if not benutzer:
        return None
    erwartet = os.environ.get(benutzer["passwort_env"])
    if not erwartet or not hmac.compare_digest(passwort, erwartet):
        return None
    return benutzer


def oeffentliche_daten(benutzer: dict) -> dict:
    return {
        "benutzername": benutzer["benutzername"],
        "name": benutzer["name"],
        "titel": benutzer["titel"],
        "rolle": benutzer["rolle"],
    }
