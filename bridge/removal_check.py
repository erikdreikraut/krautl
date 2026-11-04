"""Exercise shop removal inside a transaction that always rolls back."""
import argparse
import base64
import copy
import json
import sys
from pathlib import Path
from uuid import uuid4

if __name__ == '__main__':
    sys.path.insert(0, 'C:/Krautl-Bilddienst')

from bridge.sql import Database
from bridge.worker import Journal, Wawi, preview, single_worker, PROTOCOL_VERSION

ARTICLE = '770f139d-18dd-405c-9f84-322128000000'


class RollbackConnection:
    """The tested adapter can request commit, but cannot commit through this proxy."""
    def __init__(self, connection):
        self.connection = connection
        self.rolled_back = False

    def cursor(self):
        return self.connection.cursor()

    def commit(self):
        self.connection.rollback()
        self.rolled_back = True

    def rollback(self):
        self.connection.rollback()

    def close(self):
        self.connection.close()


class RollbackDatabase(Database):
    def __init__(self, config):
        super().__init__(config)
        self.connections = []

    def connect(self):
        connection = RollbackConnection(super().connect())
        self.connections.append(connection)
        return connection


def snapshot(sql):
    db = sql.connect()
    try:
        c = db.cursor()
        c.execute('SELECT cArtNr FROM dbo.tArtikel WHERE kArtikel=40')
        if c.fetchone()[0] != '1036':
            raise ValueError('Testartikel stimmt nicht')
        rows = sql.rows(c, 40)
        return dict(rows=rows, seo=sql.seo(c, 40), files={str(i):base64.b64encode(sql.data(c,i)).decode() for i in {r[2] for r in rows}})
    finally:
        db.rollback()
        db.close()


def api_rows(api):
    r = api.http.get(api.url+'/v1/items/'+ARTICLE+'/images')
    r.raise_for_status()
    return [list(v) for v in sorted(set((r['ItemId'],r['ImageId'],r['SalesChannelId'],r.get('EbayUserName') or '',r['SortNumber']) for r in r.json()))]


def execute(config, journal):
    if PROTOCOL_VERSION != 2 or config.get('enable_writes') is not False or config.get('allowed_skus') != ['1036']:
        raise ValueError('Protokoll 2, ausgeschalteter Dienst und Freigabe nur 1036 erforderlich')
    sql = RollbackDatabase(config)
    sql.preflight()
    api = Wawi(config)
    try:
        initial = snapshot(sql)
        rows = api_rows(api)
        shop = sorted((r[4],r[1]) for r in rows if r[2]=='2-2-1')
        if len(shop)<2 or [p for p,_ in shop] != list(range(1,len(shop)+1)):
            raise ValueError('Mindestens zwei eindeutige Shopbilder fuer Aufruecktest erforderlich')
        target = shop[0][1]
        raw = base64.b64decode(initial['files'][str(target)])
        ident = str(uuid4())
        job = dict(id=ident,artikel=ARTICLE,sku='1036',api_ziel=api.url,v1_id=target,v1_vorher=rows,
                   vorher_vorschau=base64.b64encode(preview(raw)).decode(),operation='entfernen_shop')
        before = sql.prepare(job)
        if before['rows'] != initial['rows'] or before['seo'] != initial['seo']:
            raise ValueError('Bestand waehrend Vorbereitung geaendert')
        api.check(job)
        state=dict(phase='rollback_test_vorbereitet',job=job,before=copy.deepcopy(initial))
        journal.save(ident,state)
        # This executes the production SQL path, including triggers and receipt,
        # but the connection substitutes ROLLBACK for its final commit.
        sql.remove_shop(job,before)
        if not any(c.rolled_back for c in sql.connections):
            raise ValueError('Transaktion nicht bis zur Ruecknahme durchgelaufen')
        if snapshot(sql)!=initial or api_rows(api)!=rows:
            raise ValueError('Originalbestand nach Ruecknahme nicht vollstaendig bestaetigt')
        db=sql.connect()
        try:
            c=db.cursor()
            c.execute('SELECT COUNT(*) FROM KrautlBilddienst.Auftrag WHERE Auftrag=?',ident)
            if c.fetchone()[0]!=0:
                raise ValueError('Testquittung wurde unerwartet gespeichert')
        finally:
            db.rollback();db.close()
        state['phase']='rollback_und_originalbestand_bestaetigt'
        journal.save(ident,state)
        print('TEST ERFOLGREICH: Shop-Zuordnung entfernen und Positionen aufruecken geprueft.')
        print('Testtransaktion zurueckgenommen. Bilder, Zuordnungen und SEO unveraendert.')
        print('SQL- und API-Bestand bestaetigt. Dauerbetrieb bleibt ausgeschaltet.')
    finally:
        api.http.close()


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--pruefen',action='store_true')
    args=parser.parse_args()
    if not args.pruefen:raise ValueError('--pruefen erforderlich')
    root=Path('C:/Krautl-Bilddienst')
    config=json.loads((root/'bridge/config.json').read_text(encoding='utf-8-sig'))
    with single_worker(Path(config['journal_dir'])):
        journal=Journal(root/'entfernen-pruefung.sqlite3')
        try:execute(config,journal)
        finally:journal.db.close()


if __name__=='__main__':
    try:main()
    except Exception as exc:
        print('TEST GESTOPPT: '+(str(exc) if type(exc) is ValueError else type(exc).__name__))
        print('Dienst ausgeschaltet lassen; Ausgabe zur Pruefung senden.')
        sys.exit(1)
