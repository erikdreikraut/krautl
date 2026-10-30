"""One outbound worker. Every external mutation has durable intent before I/O."""
import argparse
import base64
import hashlib
import json
import os
import sqlite3
import ssl
import time
from contextlib import contextmanager
from io import BytesIO
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from PIL import Image, ImageOps


def preview(raw):
    with Image.open(BytesIO(raw)) as im:
        if im.width * im.height > 40_000_000:
            raise ValueError('Bild zu gross')
        im = ImageOps.exif_transpose(im)
        im.thumbnail((240, 180))
        rgba = im.convert('RGBA')
        result = Image.new('RGB', rgba.size, 'white')
        result.paste(rgba, mask=rgba.getchannel('A'))
        out = BytesIO()
        result.save(out, 'JPEG', quality=82)
        return out.getvalue()


def pixels(a, b):
    with Image.open(BytesIO(a)) as left, Image.open(BytesIO(b)) as right:
        return left.size == right.size and left.convert('RGBA').tobytes() == right.convert('RGBA').tobytes()


def https(url):
    u = urlsplit(url)
    if u.scheme != 'https' or not u.hostname or u.username or u.password or u.query or u.fragment:
        raise ValueError('HTTPS-Adresse ohne Zugangsdaten erforderlich')
    return url.rstrip('/')


@contextmanager
def single_worker(folder):
    """OS releases the lock on crash; journal survives. No second local writer."""
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / 'worker.lock').open('a+b') as f:
        f.seek(0)
        f.write(b'0')
        f.flush()
        f.seek(0)
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            if os.name == 'nt':
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)


class Journal:
    def __init__(self, path):
        self.db = sqlite3.connect(path)
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.execute('CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, daten TEXT NOT NULL)')

    def get(self, ident):
        row = self.db.execute('SELECT daten FROM jobs WHERE id=?', (ident,)).fetchone()
        return json.loads(row[0]) if row else None

    def save(self, ident, state):
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO jobs VALUES (?,?)', (ident, json.dumps(state)))


def run_job(job, sql, api, journal, allowed_skus):
    """API import once; SQL once; interrupted phases are read back, never replayed."""
    ident = str(UUID(job['id']))
    if job['sku'] not in allowed_skus and '*' not in allowed_skus:
        raise ValueError('Artikel nicht fuer diesen Bilddienst freigegeben')
    payload = {k: v for k, v in job.items() if k != 'bruecke_lieferungen'}
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    state = journal.get(ident)
    if state is None:
        if job['bruecke_lieferungen'] != 1:
            raise ValueError('Lokales Journal fehlt fuer bereits ausgelieferten Auftrag')
        state = {'digest': digest, 'phase': 'vorbereitung'}
        journal.save(ident, state)
    if state['digest'] != digest:
        raise ValueError('Auftragsinhalt wurde geaendert')
    if state.get('result'):
        return state['result']
    raw = base64.b64decode(job['datei'], validate=True)
    if not 0 < len(raw) <= 20 * 1024 * 1024:
        raise ValueError('Ungueltige Bildgroesse')
    if state['phase'] == 'vorbereitung':
        # Includes complete original bytes and exact SQL row versions.
        state['before'] = sql.prepare(job)
        api.check(job)
        state['phase'] = 'import_versucht'
        journal.save(ident, state)
        try:
            api.upload(job)
        except httpx.HTTPError:
            pass  # Unknown outcome: discover below, never upload twice.
    if state['phase'] == 'import_versucht':
        imported = sql.discover(job, state['before'], raw)
        state['imported'] = imported
        state['phase'] = 'sql_versucht'
        journal.save(ident, state)
        try:
            sql.replace(job, state['before'], imported)
        except Exception:
            # A lost commit reply is checked through the transactional receipt only.
            sql.confirm(job, state['before'], imported, raw)
    # Also used after a lost SQL commit response: read only.
    sql.confirm(job, state['before'], state['imported'], raw)
    state['result'] = {'erfolgreich': True, 'bild': state['imported']['image']}
    state['phase'] = 'bestaetigt'
    journal.save(ident, state)
    return state['result']


class Wawi:
    def __init__(self, config):
        self.url = https(config['wawi_url'])
        if urlsplit(self.url).path != '/api/eazybusiness':
            raise ValueError('Falscher Wawi-Pfad')
        verify = ssl.create_default_context(cafile=config.get('wawi_ca') or None)
        self.http = httpx.Client(verify=verify, trust_env=False, follow_redirects=False, timeout=60,
            headers={'Authorization': 'Wawi ' + config['wawi_key'], 'x-appid': 'krautl-lokal', 'x-appversion': '0.1.0'})

    def check(self, job):
        if job['api_ziel'] != self.url:
            raise ValueError('Wawi-Ziel stimmt nicht ueberein')
        article = str(UUID(job['artikel']))
        r = self.http.get(self.url + '/v2/items/' + article)
        r.raise_for_status()
        data = r.json()
        if data.get('id') != article or data.get('identifiers', {}).get('sku') != job['sku']:
            raise ValueError('Artikelidentitaet stimmt nicht ueberein')
        r = self.http.get(self.url + '/v1/items/' + article + '/images')
        r.raise_for_status()
        values = sorted(set((v['ItemId'], v['ImageId'], v['SalesChannelId'], v.get('EbayUserName') or '', v['SortNumber']) for v in r.json()))
        if [list(v) for v in values] != job['v1_vorher']:
            raise ValueError('API-Bestand vor Import geaendert')

    def upload(self, job):
        r = self.http.post(self.url + '/v1/items/' + str(UUID(job['artikel'])) + '/images',
            json={'SalesChannelId': '2-2-1', 'Filename': job['dateiname'], 'ImageData': job['datei']})
        r.raise_for_status()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True)
    parser.add_argument('--check', action='store_true', help='Nur Konfiguration und SQL-Struktur pruefen')
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text(encoding='utf-8-sig'))
    from .sql import Database
    base = https(config['krautl_url'])
    worker = str(UUID(config['worker_id']))
    if len(config['bridge_token']) < 32 or not config.get('allowed_skus'):
        raise ValueError('Token oder Artikelfreigabe fehlt')
    sql = Database(config)
    sql.preflight()
    if args.check:
        print('SQL-Struktur und Trigger passen. Keine Bildaenderung ausgefuehrt.')
        return
    if config.get('enable_writes') is not True:
        raise ValueError('enable_writes ist nicht freigegeben')
    folder = Path(config['journal_dir']).resolve()
    with single_worker(folder):
        journal = Journal(folder / 'auftraege.sqlite3')
        wawi = Wawi(config)
        with httpx.Client(headers={'Authorization': 'Bearer ' + config['bridge_token']},
                          timeout=120, trust_env=False, follow_redirects=False) as remote:
            while True:
                try:
                    sql.preflight()
                    response = remote.post(base + '/api/bilder-bruecke/poll', json={'worker': worker})
                    response.raise_for_status()
                    job = response.json()['auftrag']
                    if job:
                        try:
                            result = run_job(job, sql, wawi, journal, config['allowed_skus'])
                        except Exception as exc:
                            # Never put SQL text, credentials or original paths into remote output.
                            reason = str(exc) if type(exc) is ValueError else type(exc).__name__
                            print('Auftrag', job['id'], 'nicht bestaetigt:', reason, flush=True)
                            result = {'erfolgreich': False}
                        response = remote.post(base + '/api/bilder-bruecke/ergebnis',
                            json={'worker': worker, 'auftrag': job['id'], **result})
                        response.raise_for_status()
                        print('Auftrag', job['id'], 'Rueckmeldung:', response.json()['status'], flush=True)
                except Exception as exc:
                    print('Bilddienst wartet:', str(exc) if type(exc) is ValueError else type(exc).__name__, flush=True)
                if args.once:
                    break
                time.sleep(10)


if __name__ == '__main__':
    main()
