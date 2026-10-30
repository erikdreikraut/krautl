"""Version-pinned SQL adapter. Native API creates blobs; SQL preserves relations."""
import base64
import hashlib
import json
import re
from pathlib import Path

from .worker import pixels, preview

COLS = 'kArtikelbildPlattform,kArtikel,kBild,kPlattform,kShop,kEbayUser,nNr,nInet,cBildname,bRowversion'


def signature(definition):
    # Exported comments can have codepage replacements; only SQL code is pinned.
    text = re.sub(r'--[^\r\n]*', '', definition)
    return hashlib.sha256(' '.join(text.split()).encode('utf-8')).hexdigest()


def shape(rows):
    # nInet and rowversion are sync state, not assignment identity.
    return sorted([r[:7] + [r[8]] for r in rows])


def targets(rows, image):
    # User excludes the known POS channel; no inferred exclusions.
    return [r for r in rows if r[2] == image and (r[3], r[4]) != (7, 8)]


class Database:
    def __init__(self, config):
        self.config = config
        self.pins = json.loads((Path(__file__).parent / 'schema.json').read_text(encoding='utf-8'))

    def connect(self):
        import pyodbc
        db = pyodbc.connect(self.config['sql_connection'], autocommit=False, timeout=10)
        db.timeout = 30
        return db

    def rows(self, cur, article, locked=False):
        hint = ' WITH (UPDLOCK,HOLDLOCK)' if locked else ''
        cur.execute('SELECT ' + COLS + ' FROM dbo.tArtikelbildPlattform' + hint + ' WHERE kArtikel=? ORDER BY kArtikelbildPlattform', article)
        return [list(r[:-1]) + [bytes(r[-1]).hex()] for r in cur.fetchall()]

    def data(self, cur, image):
        cur.execute('SELECT bBild FROM dbo.tBild WHERE kBild=?', image)
        row = cur.fetchone()
        if not row or row[0] is None or not 0 < len(row[0]) <= 20 * 1024 * 1024:
            raise ValueError('Bilddaten fehlen oder sind zu gross')
        return bytes(row[0])

    def seo(self, cur, article):
        cur.execute('SELECT s.kArtikelbildPlattformSeo,s.kArtikelbildPlattform,s.kSprache,s.cAlternativtext,s.bRowversion FROM dbo.tArtikelbildPlattformSeo s JOIN dbo.tArtikelbildPlattform p ON p.kArtikelbildPlattform=s.kArtikelbildPlattform WHERE p.kArtikel=? ORDER BY s.kArtikelbildPlattformSeo', article)
        return [list(r[:-1]) + [bytes(r[-1]).hex()] for r in cur.fetchall()]

    def preflight(self):
        db = self.connect()
        try:
            c = db.cursor()
            c.execute('SELECT DB_NAME()')
            if c.fetchone()[0] != 'eazybusiness':
                raise ValueError('Falsche Datenbank')
            c.execute("SELECT t.name,t.is_disabled,m.definition FROM sys.triggers t JOIN sys.sql_modules m ON m.object_id=t.object_id WHERE t.parent_id IN (OBJECT_ID('dbo.tBild'),OBJECT_ID('dbo.tArtikelbildPlattform'),OBJECT_ID('dbo.tArtikelbildPlattformSeo'))")
            actual = {r[0]: signature(r[2]) for r in c.fetchall() if not r[1] and r[2]}
            if actual != self.pins['triggers']:
                raise ValueError('Wawi-Trigger nicht freigegeben')
            c.execute("SELECT OBJECT_NAME(object_id),name,TYPE_NAME(user_type_id),max_length,is_nullable,is_identity,is_computed FROM sys.columns WHERE object_id IN (OBJECT_ID('dbo.tBild'),OBJECT_ID('dbo.tArtikelbildPlattform'),OBJECT_ID('dbo.tArtikelbildPlattformSeo'))")
            if sorted([list(r) for r in c.fetchall()]) != self.pins['columns']:
                raise ValueError('Wawi-Schema nicht freigegeben')
            c.execute("SELECT fk.name,OBJECT_SCHEMA_NAME(fk.parent_object_id),OBJECT_NAME(fk.parent_object_id),COL_NAME(f.parent_object_id,f.parent_column_id),OBJECT_SCHEMA_NAME(fk.referenced_object_id),OBJECT_NAME(fk.referenced_object_id),COL_NAME(f.referenced_object_id,f.referenced_column_id),fk.delete_referential_action_desc,fk.update_referential_action_desc FROM sys.foreign_keys fk JOIN sys.foreign_key_columns f ON f.constraint_object_id=fk.object_id WHERE fk.parent_object_id IN (OBJECT_ID('dbo.tBild'),OBJECT_ID('dbo.tArtikelbildPlattform'),OBJECT_ID('dbo.tArtikelbildPlattformSeo')) OR fk.referenced_object_id IN (OBJECT_ID('dbo.tBild'),OBJECT_ID('dbo.tArtikelbildPlattform'),OBJECT_ID('dbo.tArtikelbildPlattformSeo'))")
            if sorted([list(r) for r in c.fetchall()]) != self.pins['foreign_keys']:
                raise ValueError('Wawi-Fremdschluessel nicht freigegeben')
            c.execute("SELECT OBJECT_ID('dbo.spUpdateEbayBilderLaufendGeplant'),TYPE_ID('dbo.TYPE_spUpdateEbayBilderLaufendGeplant')")
            if not all(c.fetchone()):
                raise ValueError('Native eBay-Aktualisierung fehlt')
            c.execute('SELECT TOP(0) Auftrag,Artikel,Altbild,Neubild,Dateihash FROM KrautlBilddienst.Auftrag')
        finally:
            db.rollback()
            db.close()

    def prepare(self, job):
        article_ids = {r[0] for r in job['v1_vorher']}
        if len(article_ids) != 1:
            raise ValueError('Interner Artikel nicht eindeutig')
        article = next(iter(article_ids))
        db = self.connect()
        try:
            c = db.cursor()
            c.execute('SELECT cArtNr FROM dbo.tArtikel WHERE kArtikel=?', article)
            row = c.fetchone()
            if not row or row[0] != job['sku']:
                raise ValueError('SQL-Artikel stimmt nicht mit API ueberein')
            rows = self.rows(c, article)
            selected = targets(rows, job['v1_id'])
            if not selected or not any(r[3:5] == [2, 1] for r in selected):
                raise ValueError('Ausgangsbild fehlt im JTL-Shop')
            raw = self.data(c, job['v1_id'])
            if not pixels(preview(raw), base64.b64decode(job['vorher_vorschau'])):
                raise ValueError('Original wurde zwischenzeitlich geaendert')
            c.execute('SELECT ISNULL(MAX(kBild),0) FROM dbo.tBild')
            maximum = c.fetchone()[0]
            return {'article': article, 'rows': rows, 'max_image': maximum, 'seo': self.seo(c, article),
                    'original': base64.b64encode(raw).decode()}
        finally:
            db.rollback()
            db.close()

    def discover(self, job, before, raw):
        db = self.connect()
        try:
            c = db.cursor()
            rows = self.rows(c, before['article'])
            ids = {r[0] for r in before['rows']}
            if [r for r in rows if r[0] in ids] != before['rows']:
                raise ValueError('Zuordnungen beim Import geaendert')
            added = [r for r in rows if r[0] not in ids]
            images = {r[2] for r in added}
            if len(images) != 1:
                raise ValueError('Neues Bild noch nicht eindeutig; kein weiterer Upload')
            image = next(iter(images))
            if image <= before['max_image'] or not any(r[3:5] == [2, 1] for r in added):
                raise ValueError('Kein eindeutig neues Shopbild')
            for r in added:
                if (r[3], r[4], r[5]) not in ((1, 0, 0), (2, 1, 0)):
                    raise ValueError('Import hat unerwartete Kanaele angelegt')
                oldmax = max((b[6] for b in before['rows'] if b[3:6] == r[3:6]), default=0)
                if r[6] != oldmax + 1:
                    raise ValueError('Import nicht am Listenende')
            c.execute('SELECT COUNT(*) FROM dbo.tArtikelbildPlattform WHERE kBild=?', image)
            if c.fetchone()[0] != len(added) or not pixels(preview(self.data(c, image)), preview(raw)):
                raise ValueError('Importinhalt oder Verwendung nicht eindeutig')
            c.execute('SELECT cQuelle FROM dbo.tBild WHERE kBild=?', image)
            name = str(c.fetchone()[0]).replace('\\', '/').rsplit('/', 1)[-1]
            if name != job['dateiname']:
                raise ValueError('Importdatei nicht eindeutig diesem Auftrag zugeordnet')
            return {'image': image, 'rows': rows, 'added': added}
        finally:
            db.rollback()
            db.close()

    def expected(self, job, before, imported):
        selected = {r[0] for r in targets(before['rows'], job['v1_id'])}
        result = [list(r) for r in before['rows']]
        for r in result:
            if r[0] in selected:
                r[2] = imported['image']
        return result

    def replace(self, job, before, imported):
        self.preflight()
        db = self.connect()
        try:
            c = db.cursor()
            c.execute('SET XACT_ABORT ON; SET TRANSACTION ISOLATION LEVEL SERIALIZABLE; SET LOCK_TIMEOUT 10000;')
            c.execute('SELECT Auftrag FROM KrautlBilddienst.Auftrag WITH (UPDLOCK,HOLDLOCK) WHERE Auftrag=?', job['id'])
            if c.fetchone():
                raise ValueError('SQL-Auftrag bereits quittiert; ausschliesslich ruecklesen')
            if self.rows(c, before['article'], True) != imported['rows']:
                raise ValueError('Zuordnungen nach Import geaendert')
            if self.data(c, job['v1_id']) != base64.b64decode(before['original']):
                raise ValueError('Originaldaten wurden geaendert')
            if self.seo(c, before['article']) != before['seo']:
                raise ValueError('SEO-Daten wurden geaendert')
            if not pixels(preview(self.data(c, imported['image'])), preview(base64.b64decode(job['datei']))):
                raise ValueError('Importdaten wurden geaendert')
            # Only disposable new import rows; never delete a tBild or original relation.
            for r in imported['added']:
                c.execute('SELECT COUNT(*) FROM dbo.tArtikelbildPlattformSeo WITH (UPDLOCK,HOLDLOCK) WHERE kArtikelbildPlattform=?', r[0])
                if c.fetchone()[0]:
                    raise ValueError('Import hat inzwischen SEO-Daten')
                c.execute('SELECT COUNT(*) FROM FulfillmentNetwork.tProductPictureRef WITH (UPDLOCK,HOLDLOCK) WHERE kArtikelbildPlattform=?', r[0])
                if c.fetchone()[0]:
                    raise ValueError('Import wird inzwischen im Fulfillment verwendet')
                c.execute('DELETE FROM dbo.tArtikelbildPlattform WHERE kArtikelbildPlattform=? AND kArtikel=? AND kBild=?', r[0], before['article'], imported['image'])
            selected = targets(before['rows'], job['v1_id'])
            for r in selected:
                c.execute('UPDATE dbo.tArtikelbildPlattform SET kBild=?, nNr=nNr, nInet=? WHERE kArtikelbildPlattform=? AND kArtikel=? AND kBild=?',
                          imported['image'], 1 if r[4] > 0 else r[7], r[0], before['article'], job['v1_id'])
            if any(r[3] == 30 and r[6] <= 12 for r in selected):
                # Same native typed procedure used by the installed trigger, explicit for content-only changes.
                c.execute('DECLARE @Artikel dbo.TYPE_spUpdateEbayBilderLaufendGeplant; INSERT INTO @Artikel(kArtikel) VALUES (?); EXEC dbo.spUpdateEbayBilderLaufendGeplant @Artikel;', before['article'])
            if shape(self.rows(c, before['article'])) != shape(self.expected(job, before, imported)):
                raise ValueError('SQL-Zielvergleich fehlgeschlagen')
            if self.seo(c, before['article']) != before['seo']:
                raise ValueError('SEO-Daten nach Austausch veraendert')
            c.execute('INSERT INTO KrautlBilddienst.Auftrag(Auftrag,Artikel,Altbild,Neubild,Dateihash) VALUES (?,?,?,?,?)',
                      job['id'], before['article'], job['v1_id'], imported['image'],
                      hashlib.sha256(base64.b64decode(job['datei'])).hexdigest())
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def confirm(self, job, before, imported, raw):
        db = self.connect()
        try:
            c = db.cursor()
            c.execute('SELECT Artikel,Altbild,Neubild,Dateihash FROM KrautlBilddienst.Auftrag WHERE Auftrag=?', job['id'])
            receipt = c.fetchone()
            if not receipt or list(receipt) != [before['article'], job['v1_id'], imported['image'], hashlib.sha256(raw).hexdigest()]:
                raise ValueError('Transaktion einschliesslich Kanalaktualisierung nicht quittiert')
            if shape(self.rows(c, before['article'])) != shape(self.expected(job, before, imported)):
                raise ValueError('SQL-Ergebnis nicht bestaetigt; kein erneutes Schreiben')
            if not pixels(preview(self.data(c, imported['image'])), preview(raw)):
                raise ValueError('Bildinhalt nach Austausch nicht bestaetigt')
            if self.seo(c, before['article']) != before['seo']:
                raise ValueError('SEO-Daten nach Austausch nicht bestaetigt')
        finally:
            db.rollback()
            db.close()
