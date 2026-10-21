"""Dedicated read-only Inkasso credentials and explicit registration commands."""
import argparse
import asyncio
import json
import os
import secrets
from pathlib import Path
from urllib.parse import quote
from uuid import uuid4

from .jtl_client import JtlFehler
from .jtl_onprem import OnPremClient

APP_ID = "krautl-inkasso"
SCOPES = ["invoices.read", "salesorders.read", "saleschannels.read"]


def ordner():
    return Path(os.getenv("INKASSO_ZUGANG_DIR", "/app/var/inkasso-zugang"))


def sichern(path, data, exklusiv=False):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    ziel = path if exklusiv else path.with_name(path.name + "." + uuid4().hex + ".tmp")
    fd = os.open(ziel, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        if not exklusiv:
            os.replace(ziel, path)
    finally:
        if not exklusiv and ziel.exists():
            ziel.unlink()


def validieren(data):
    if (data.get("app_id") != APP_ID or not isinstance(data.get("api_key"), str)
            or not data["api_key"] or not set(SCOPES).issubset(data.get("scopes", []))
            or data.get("api_url") != os.getenv("JTL_LOCAL_URL", "").rstrip("/")):
        raise JtlFehler("Inkasso-Zugang, API-Ziel oder bestätigte Leserechte ungültig.")
    return data


def client_aus_umgebung():
    try:
        data = validieren(json.loads((ordner() / "zugang.json").read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError, AttributeError):
        raise JtlFehler("Separater Inkasso-Zugang fehlt oder ist nicht lesbar. Registrierung abschließen.") from None
    client = OnPremClient(data["api_url"], data["api_key"],
                          ca_file=os.getenv("JTL_LOCAL_CA_FILE") or None)
    client.http.headers["x-appid"] = APP_ID
    return client


async def registrieren(abholen=False):
    folder = ordner()
    request_path, response_path = folder / "anfrage.json", folder / "schluesselantwort.json"
    if not abholen:
        state = {"challenge": secrets.token_hex(12), "api_url": os.getenv("JTL_LOCAL_URL", "").rstrip("/"),
                 "phase": "vorbereitet", "request": {
            "appId": APP_ID, "displayName": "Krautl Inkasso",
            "description": "Offene JTL-Shop-Rechnungen lesen und zuordnen",
            "version": "0.1.0", "providerName": "dreikraut",
            "providerWebsite": "https://www.dreikraut.de", "registrationType": 0,
            "mandatoryApiScopes": SCOPES, "optionalApiScopes": [],
            "appIcon": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII="}}
        try:
            sichern(request_path, state, exklusiv=True)
        except FileExistsError:
            raise JtlFehler("Registrierungsversuch bereits vorhanden. Kein erneuter POST; Status zuerst prüfen.") from None
    else:
        state = json.loads(request_path.read_text(encoding="utf-8"))
        if state.get("http") != 201:
            raise JtlFehler("Keine bestätigte Registrierungsanfrage. Gespeicherten Versuch prüfen.")
        if (folder / "zugang.json").exists():
            validieren(json.loads((folder / "zugang.json").read_text(encoding="utf-8")))
            print("Inkasso-Zugang bereits gespeichert. Kein erneuter Schlüsselabruf.")
            return
    if state["api_url"] != os.getenv("JTL_LOCAL_URL", "").rstrip("/"):
        raise JtlFehler("API-Ziel seit Registrierung geändert.")
    # Constructor requires a key, but registration is explicitly unauthenticated.
    async with OnPremClient(state["api_url"], "registration",
                            ca_file=os.getenv("JTL_LOCAL_CA_FILE") or None) as client:
        client.http.headers.pop("Authorization", None)
        client.http.headers["x-appid"] = APP_ID
        headers = {"x-challengecode": state["challenge"]}
        if not abholen:
            response = await client.http.post(client.url + "/v2/authentication",
                                               headers=headers, json=state["request"])
            state.update(http=response.status_code, body=response.text, phase="antwort_erhalten")
            sichern(request_path, state)
            print("Registrierung HTTP:", response.status_code)
            if response.status_code != 201:
                raise JtlFehler("Anfrage nicht angenommen. Antwort geschützt gespeichert; keine automatische Wiederholung.")
            print("Jetzt die drei Leserechte im Wawi-Assistenten bestätigen, dann --abholen ausführen.")
            return
        result = None
        if response_path.exists():
            result = json.loads(response_path.read_text(encoding="utf-8"))
            if result.get("phase") == "abruf_gestartet":
                raise JtlFehler("Vorheriger Schlüsselabruf unklar. Nicht erneut abrufen; Datei prüfen.")
            data = json.loads(result.get("body", "{}"))
            if result.get("http") == 200 and data.get("requestStatusInfo", {}).get("status") == 0 and not data.get("token"):
                result = None
        if result is None:
            sichern(response_path, {"phase": "abruf_gestartet"})
            registration_id = json.loads(state["body"])["registrationRequestId"]
            response = await client.http.get(client.url + "/v2/authentication/" + quote(registration_id, safe=""), headers=headers)
            result = {"http": response.status_code, "body": response.text}
            sichern(response_path, result)
        print("Registrierungsstatus HTTP:", result["http"])
        if result["http"] != 200:
            raise JtlFehler("Keine erfolgreiche Schlüsselantwort. Geschützte Antwort zuerst prüfen.")
        data = json.loads(result["body"])
        status = data.get("requestStatusInfo", {}).get("status")
        print("Registrierungsstatus:", status)
        if status == 0:
            print("Noch ausstehend. Assistent abschließen, danach --abholen erneut ausführen.")
            return
        credentials = {"app_id": APP_ID, "api_url": state["api_url"],
                       "api_key": (data.get("token") or {}).get("apiKey"),
                       "scopes": data.get("grantedScopes", [])}
        if status != 2:
            raise JtlFehler("Registrierung nicht angenommen.")
        validieren(credentials)
        sichern(folder / "zugang.json", credentials, exklusiv=True)
        print("Inkasso-Zugang geschützt gespeichert. Leserechte:", ", ".join(credentials["scopes"]))


async def pruefen():
    async with client_aus_umgebung() as client:
        for path, expected, params in (("/v2/sales-channels", list, {}),
                ("/v1/invoices", dict, {"pageNumber": 1, "pageSize": 1, "paymentStatus": 0}),
                ("/v1/salesOrders", dict, {"pageNumber": 1, "pageSize": 1})):
            await client._request("GET", path, expected_type=expected, params=params)
            print(path, "HTTP 200")


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--anmelden", action="store_true")
    group.add_argument("--abholen", action="store_true")
    group.add_argument("--pruefen", action="store_true")
    args = parser.parse_args()
    import fcntl
    folder = ordner()
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (folder / "registrierung.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise JtlFehler("Ein Registrierungsprozess läuft bereits.") from None
        if args.pruefen:
            await pruefen()
        else:
            await registrieren(args.abholen)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except JtlFehler as exc:
        raise SystemExit(str(exc)) from None
    except Exception as exc:
        raise SystemExit("Technischer Fehler: " + type(exc).__name__ + ". Gespeicherten Zustand prüfen; keine blinde Wiederholung.") from None
