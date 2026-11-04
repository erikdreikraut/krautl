"""Read-only Windows acceptance; no queue polling, service start or writes."""
import json
from pathlib import Path
import httpx
from .sql import Database
from .worker import Wawi, https, PROTOCOL_VERSION


def check(config):
    if config.get('enable_writes') is not False:
        raise ValueError('Diese Einrichtungspruefung verlangt enable_writes=false')
    print('Bilddienst-Protokoll:', PROTOCOL_VERSION, flush=True)
    Database(config).preflight()
    print('Datenbankstruktur: OK', flush=True)
    wawi = Wawi(config)
    try:
        r = wawi.http.get(wawi.url + '/v1/items/770f139d-18dd-405c-9f84-322128000000')
        r.raise_for_status()
        item = r.json()
        if item.get('Id') != 40 or item.get('SKU') != '1036':
            raise ValueError('Artikelidentitaet stimmt nicht')
    finally:
        wawi.http.close()
    print('Wawi-Zugang und Artikel 1036: OK', flush=True)
    with httpx.Client(verify=True, trust_env=False, follow_redirects=False, timeout=30) as c:
        r = c.get(https(config['krautl_url']) + '/api/health')
        r.raise_for_status()
    print('Krautl erreichbar: OK. Bilddienst nicht gestartet, Schreiben bleibt aus.', flush=True)


if __name__ == '__main__':
    try:
        check(json.loads(Path('bridge/config.json').read_text(encoding='utf-8-sig')))
    except Exception as exc:
        # Do not expose connection strings, response bodies or credentials.
        print('Pruefung gestoppt: ' + (str(exc) if type(exc) is ValueError else type(exc).__name__))
        raise SystemExit(1)
