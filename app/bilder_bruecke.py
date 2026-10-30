"""Outbound Windows bridge queue. Separate machine credential, no browser session."""
import base64
import copy
import hmac
import json
import os
import time
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from pydantic import BaseModel, StrictBool, StrictInt

from . import bilder_speicher as store
from .bilder_upload import auftraege, sichern, oeffentlich, tabelle, lokal

PATHS = frozenset({'/bilder-bruecke/poll', '/bilder-bruecke/ergebnis'})


def aktiv():
    return os.getenv('BILDER_BRUECKE_AKTIV') == '1'


def artikel_erlaubt(sku):
    allowed = {s.strip() for s in os.getenv('BILDER_BRUECKE_SKUS', '1036').split(',') if s.strip()}
    if sku not in allowed and '*' not in allowed:
        raise ValueError('Der Bilddienst ist für diesen Artikel noch nicht freigegeben.')


def authentifizieren(authorization: str = Header(default='')):
    secret = os.getenv('BILDER_BRUECKE_TOKEN', '')
    if not aktiv() or len(secret) < 32 or not hmac.compare_digest(authorization, 'Bearer ' + secret):
        raise HTTPException(401, 'Brückenzugang ungültig.')


router = APIRouter(prefix='/bilder-bruecke', dependencies=[Depends(authentifizieren)])


def bereit():
    with store.datenbank() as db:
        db.execute('CREATE TABLE IF NOT EXISTS bildbruecke (id INTEGER PRIMARY KEY, zeit REAL NOT NULL)')
        row = db.execute('SELECT zeit FROM bildbruecke WHERE id=1').fetchone()
    if not row or not 0 <= time.time() - row[0] < 90:
        raise ValueError('Der Bilddienst ist nicht erreichbar. Bitte später erneut versuchen.')


def laufend(artikel=None):
    return any(j.get('bruecke') and j['status'] == 'sendet' for j in auftraege(artikel))


class Poll(BaseModel):
    worker: UUID


class Ergebnis(Poll):
    auftrag: UUID
    erfolgreich: StrictBool
    bild: StrictInt | None = None


@router.post('/poll')
def poll(body: Poll, response: Response):
    response.headers['Cache-Control'] = 'no-store'
    with store.datenbank() as db:
        tabelle(db)
        db.execute('CREATE TABLE IF NOT EXISTS bildbruecke (id INTEGER PRIMARY KEY, zeit REAL NOT NULL)')
        db.execute('BEGIN IMMEDIATE')
        db.execute('INSERT OR REPLACE INTO bildbruecke VALUES (1, ?)', (time.time(),))
        for value, raw in db.execute('SELECT daten,datei FROM bildauftraege ORDER BY rowid'):
            job = json.loads(value)
            if not job.get('bruecke') or not (job['status'] == 'sendet' or
                    (job['status'] == 'unklar' and job.get('bruecke_bestaetigt'))):
                continue
            if job.get('bruecke_worker', str(body.worker)) != str(body.worker):
                continue  # Never reassign an uncertain write to another machine.
            row = db.execute('SELECT ausgeblendet,revision FROM artikel WHERE id=?', (job['artikel'],)).fetchone()
            if row != (0, job['revision']):
                job.update(status='unklar', meldung='Artikel während des Bildauftrags geändert; Prüfung erforderlich.')
                db.execute('UPDATE bildauftraege SET daten=? WHERE id=?', (json.dumps(job), job['id']))
                continue
            job['bruecke_worker'] = str(body.worker)
            job['bruecke_lieferungen'] = job.get('bruecke_lieferungen', 0) + 1
            db.execute('UPDATE bildauftraege SET daten=? WHERE id=?', (json.dumps(job), job['id']))
            return {'auftrag': {**{k: job[k] for k in ('id','artikel','sku','api_ziel','v1_id',
                'v1_vorher','vorher_vorschau','dateiname','bruecke_lieferungen')},
                'datei': base64.b64encode(raw).decode()}}
    return {'auftrag': None}


async def bestaetigen(c, job):
    """Independent API readback; a worker success alone is never a UI success."""
    from .bilder_ersetzen import liste, zuordnungen, bild, bestand, lokale_id
    from .bilder_upload import detail_lesen, bildinhalt_bestaetigt
    if not job.get('bruecke_bestaetigt'):
        return oeffentlich(job)
    if c.url != job['api_ziel']:
        raise ValueError('Wawi-Ziel geändert.')
    await detail_lesen(c, job['artikel'], job['sku'])
    expected = copy.deepcopy(job['v1_vorher'])
    for row in expected:
        if row[1] == job['v1_id'] and row[2] != '9-7-8-0':
            row[1] = job['bruecke_bild']
    expected.sort()
    rows = await liste(c, job['artikel'])
    if zuordnungen(rows) != expected or not bildinhalt_bestaetigt(job, await bild(c, job['bruecke_bild'])):
        raise ValueError('Bilddienst und Wawi-Rücklesung stimmen noch nicht überein.')
    a, _ = lokal(job['artikel'], job['revision'])
    a = copy.deepcopy(a)
    a['bild_api'] = 'v1'
    a['bilder'] = await bestand(c, a, rows)
    if zuordnungen(await liste(c, job['artikel'])) != expected or not store.freigegeben(a['id'], job['revision']):
        raise ValueError('Bestand während der Bestätigung geändert.')
    store.zwischenstand(a, job['revision'], c.url, abgleich=False)
    job.update(status='wawi', neu_id=lokale_id(a['id'], job['bruecke_bild']),
               meldung='Bild in Wawi ersetzt; Kanalpositionen erhalten. Shop-Veröffentlichung wird getrennt geprüft.')
    sichern(job)
    return oeffentlich(job)


@router.post('/ergebnis')
async def ergebnis(body: Ergebnis):
    from .jtl_onprem import OnPremClient
    from .jtl_client import JtlFehler
    import httpx
    try:
        with store.Laufsperre():
            job = next((j for j in auftraege() if j['id'] == str(body.auftrag)), None)
            if not job or not job.get('bruecke') or job.get('bruecke_worker') != str(body.worker):
                raise HTTPException(409, 'Auftrag gehört nicht zu diesem Bilddienst.')
            if job['status'] == 'wawi':
                return oeffentlich(job)
            if job.get('ruecksetzung') or job['status'] == 'abgelehnt':
                raise HTTPException(409, 'Auftrag wurde beendet.')
            if not body.erfolgreich:
                job.update(status='unklar', meldung='Bilddienst konnte den Austausch nicht bestätigen. Kein erneuter Upload; Administrator prüft das Auftragsjournal.')
                sichern(job)
                return oeffentlich(job)
            if body.bild is None or body.bild <= 0 or body.bild == job['v1_id']:
                raise HTTPException(422, 'Neue Bildnummer fehlt.')
            if job.get('bruecke_bild') not in (None, body.bild):
                raise HTTPException(409, 'Widersprüchliches Ergebnis.')
            job.update(bruecke_bestaetigt=True, bruecke_bild=body.bild, status='unklar',
                       meldung='Bilddienst fertig; unabhängige Wawi-Bestätigung steht aus.')
            sichern(job)
            try:
                async with OnPremClient.aus_umgebung() as c:
                    return await bestaetigen(c, job)
            except (ValueError, JtlFehler, httpx.HTTPError):
                return oeffentlich(job)
    except store.Belegt as exc:
        raise HTTPException(409, str(exc)) from None
