"""One isolated, journaled Windows exchange and restoration for article 1036."""
import argparse
import base64
import copy
import hashlib
import json
import sys
from io import BytesIO
from pathlib import Path
from uuid import uuid4

# The downloaded script runs outside the installation directory.
if __name__ == '__main__':
    sys.path.insert(0, 'C:/Krautl-Bilddienst')

from PIL import Image
from bridge.sql import Database, shape
from bridge.worker import Journal, Wawi, preview, run_job, single_worker

ARTICLE = '770f139d-18dd-405c-9f84-322128000000'
TARGET = 2729
# Confirmed by the user's SQL export on 2026-11-03; absent from API images.
SQL_ONLY = {(2488, 8, 11, 1), (2488, 8, 13, 1), (2488, 8, 14, 1)}
HASHES = {
    2048: '6fd60fdf953624c062612b313d848b0959f70a3b272512eecc1b4f0afe6c36fc',
    2365: '3910d12665b5b9027ff004775bff6ce9e1bfd0a3e0bc84fc85e5ab5d5b2e20a9',
    2729: '15a13d83bd1524507575b6fb4a3e07efc1b620154ce53721dff74578927bffba',
    2731: '4c11db295885fd2864c91615c09be340de8d96afb343e42cbd395f33706ac343',
}


def assignments(rows):
    # Retain duplicate aliases in this independent check.
    return sorted([[r['ItemId'], r['ImageId'], r['SalesChannelId'],
                    r.get('EbayUserName') or '', r['SortNumber']] for r in rows])


def api_rows(api):
    r = api.http.get(api.url + '/v1/items/' + ARTICLE + '/images')
    r.raise_for_status()
    return assignments(r.json())


def sql_state(sql):
    db = sql.connect()
    try:
        c = db.cursor()
        rows = sql.rows(c, 40)
        files = {str(i): base64.b64encode(sql.data(c, i)).decode()
                 for i in set(HASHES) | {r[2] for r in rows}}
        return {'rows': rows, 'seo': sql.seo(c, 40), 'files': files}
    finally:
        db.rollback()
        db.close()


def verify_baseline(rows, state):
    if not rows or any(r[0] != 40 for r in rows):
        raise ValueError('Unerwarteter Artikelbestand')
    if sorted((r[1], r[4]) for r in rows if r[2] == '2-2-1') != [(2365, 2), (2729, 1)]:
        raise ValueError('Shopbilder haben sich seit der Vorbereitung geaendert')
    if {r[1] for r in rows} != set(HASHES) or {r[2] for r in state['rows']} != set(HASHES) | {2488}:
        raise ValueError('Unerwartete Bildnummern')
    extra = [(r[2], r[3], r[4], r[6]) for r in state['rows'] if r[2] not in HASHES]
    if len(extra) != len(SQL_ONLY) or set(extra) != SQL_ONLY or any(r[1] != 40 for r in state['rows']):
        raise ValueError('Zusaetzliche SQL-Zuordnungen weichen vom bestaetigten Bestand ab')
    if set(state['files']) != {str(r[2]) for r in state['rows']}:
        raise ValueError('Originalsicherung nicht vollstaendig')
    verify_files(state)


def verify_files(state):
    for ident, digest in HASHES.items():
        raw = base64.b64decode(state['files'][str(ident)], validate=True)
        if hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError('Originaldatei weicht ab: ' + str(ident))


def verify_result(rows, state, baseline, image):
    expected_api = copy.deepcopy(baseline['api'])
    expected_sql = copy.deepcopy(baseline['sql']['rows'])
    for r in expected_api:
        if r[1] == TARGET and r[2] != '9-7-8-0':
            r[1] = image
    for r in expected_sql:
        if r[2] == TARGET and tuple(r[3:5]) != (7, 8):
            r[2] = image
    if rows != sorted(expected_api) or shape(state['rows']) != shape(expected_sql):
        raise ValueError('Bildzuordnungen weichen vom exakten Ziel ab')
    if state['seo'] != baseline['sql']['seo']:
        raise ValueError('SEO-Daten wurden geaendert')
    verify_files(state)
    for ident, original in baseline['sql']['files'].items():
        if state['files'].get(ident) != original:
            raise ValueError('Gesicherte Originaldatei geaendert oder fehlt: ' + ident)


def job(api, rows, old, raw, original):
    ident = str(uuid4())
    return {'id': ident, 'artikel': ARTICLE, 'sku': '1036', 'api_ziel': api.url,
            'v1_id': old, 'v1_vorher': [list(r) for r in sorted(set(map(tuple, rows)))],
            'vorher_vorschau': base64.b64encode(preview(original)).decode(),
            'datei': base64.b64encode(raw).decode(), 'dateiname': 'krautl-test-' + ident + '.jpg',
            'bruecke_lieferungen': 1}


def execute(sql, api, journal):
    existing = journal.get('abnahme-1036')
    if existing:
        print('Testjournal vorhanden: ' + existing['phase'] + '. Keine Wiederholung.', flush=True)
        if existing.get('baseline'):
            verify_result(api_rows(api), sql_state(sql), existing['baseline'], TARGET)
            print('Originalbestand erneut lesend bestaetigt.', flush=True)
        return
    sql.preflight()
    rows, initial = api_rows(api), sql_state(sql)
    verify_baseline(rows, initial)
    original = base64.b64decode(initial['files'][str(TARGET)])
    with Image.open(BytesIO(base64.b64decode(initial['files']['2731']))) as im:
        im = im.convert('RGB')
        im.thumbnail((512, 512))
        # A unique tiny test marker avoids deduplication against earlier test blobs.
        color = tuple(uuid4().bytes[:3])
        im.paste(color, (0, 0, min(8, im.width), min(8, im.height)))
        out = BytesIO()
        im.save(out, 'JPEG', quality=85)
        raw = out.getvalue()
    if len(raw) > 100000 or hashlib.sha256(raw).hexdigest() in HASHES.values():
        raise ValueError('Testdatei nicht eindeutig neu')
    forward = job(api, rows, TARGET, raw, original)
    api.check(forward)
    baseline = {'api': rows, 'sql': initial}
    state = {'phase': 'austausch_beauftragt', 'baseline': baseline, 'forward': forward}
    journal.save('abnahme-1036', state)
    print('Originale gesichert. Einmaliger Austausch wird ausgefuehrt.', flush=True)
    result = run_job(forward, sql, api, journal, ['1036'])
    image = result['bild']
    after_rows, after_sql = api_rows(api), sql_state(sql)
    verify_result(after_rows, after_sql, baseline, image)
    state.update(phase='austausch_bestaetigt', image=image)
    journal.save('abnahme-1036', state)
    print('Austausch bestaetigt; Zuordnungen und Originaldateien erhalten.', flush=True)

    # Restore the ORIGINAL blob, not a second upload of the original bytes.
    restore = job(api, after_rows, image, original, base64.b64decode(after_sql['files'][str(image)]))
    before = sql.prepare(restore)
    api.check(restore)
    imported = {'image': TARGET, 'rows': before['rows'], 'added': []}
    if shape(sql.expected(restore, before, imported)) != shape(initial['rows']):
        raise ValueError('Ruecknahme wuerde nicht den Originalbestand herstellen')
    state.update(phase='ruecknahme_beauftragt', restore=restore, restore_before=before,
                 restore_imported=imported)
    journal.save('abnahme-1036', state)
    try:
        sql.replace(restore, before, imported)
    except Exception:
        sql.confirm(restore, before, imported, original)  # Lost reply: read only.
    sql.confirm(restore, before, imported, original)
    verify_result(api_rows(api), sql_state(sql), baseline, TARGET)
    state['phase'] = 'original_wiederhergestellt'
    journal.save('abnahme-1036', state)
    print('TEST ERFOLGREICH: Austausch und Ruecknahme bestaetigt.', flush=True)
    print('Originalbilder, Zuordnungs-IDs, Kanaele, Positionen und SEO wiederhergestellt.', flush=True)
    print('Test-Bilddatensatz ' + str(image) + ' bleibt ohne Artikelzuordnung erhalten; keine Loeschung.', flush=True)
    print('Dauerbetrieb bleibt ausgeschaltet. Shop-Veroeffentlichung nicht getestet.', flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--ausfuehren', action='store_true')
    args = parser.parse_args()
    if not args.ausfuehren:
        raise ValueError('Einmaliger Schreibtest erfordert --ausfuehren')
    root = Path('C:/Krautl-Bilddienst')
    config = json.loads((root/'bridge/config.json').read_text(encoding='utf-8-sig'))
    if config.get('enable_writes') is not False or config.get('allowed_skus') != ['1036']:
        raise ValueError('Test verlangt ausgeschalteten Dauerbetrieb und nur Artikel 1036')
    # Use the regular worker lock, but store backups under the protected installation.
    with single_worker(Path(config['journal_dir'])):
        journal = Journal(root/'bildtest-1036.sqlite3')
        api = Wawi(config)
        try:
            execute(Database(config), api, journal)
        finally:
            api.http.close()
            journal.db.close()


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('TEST GESTOPPT: ' + (str(exc) if type(exc) is ValueError else type(exc).__name__), flush=True)
        print('Abgleiche pausiert lassen. Keine erneute Ausfuehrung; Journal zur Pruefung erhalten.', flush=True)
        sys.exit(1)
