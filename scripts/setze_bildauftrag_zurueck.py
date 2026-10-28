"""Reset only Krautl's state after a user has manually removed an extra Wawi image."""
import argparse
import asyncio
import copy
import json
from app import bilder_speicher as store
from app.bilder_upload import auftraege, detail_lesen
from app.bilder_ersetzen import liste, bestand, zuordnungen
from app.jtl_onprem import OnPremClient


async def zuruecksetzen(c, sku, entfernt):
    data=store.lesen()
    matches=[a for a in data['artikel'] if a['sku']==sku]
    if len(matches)!=1:raise ValueError('Artikel nicht eindeutig im Krautl-Bestand.')
    a=matches[0]
    if a['ausgeblendet']:raise ValueError('Artikel ist ausgeblendet.')
    if data.get('api_ziel')!=c.url:raise ValueError('Wawi-Ziel passt nicht zum Bestand.')
    jobs=[j for j in auftraege(a['id']) if j['status'] in ('sendet','unklar')]
    if any(j.get('api_ziel')!=c.url for j in jobs):raise ValueError('Auftrag gehört zu einem anderen Wawi-Ziel.')
    if any(j.get('bereinigung_id') not in (None,entfernt) for j in jobs):
        raise ValueError('Der angegebene entfernte Upload passt nicht zum Auftrag.')
    await detail_lesen(c,a['id'],sku)
    rows=await liste(c,a['id'])
    if any(r['ImageId']==entfernt for r in rows):
        raise ValueError('Das zusätzliche Bild ist noch in Wawi zugeordnet. Kein Reset ausgeführt.')
    refreshed=copy.deepcopy(a)
    refreshed.update(bild_api='v1',bilder=await bestand(c,a,rows),aktualisiert_am=store.jetzt())
    if zuordnungen(await liste(c,a['id']))!=zuordnungen(rows):
        raise ValueError('Wawi-Bestand während des Lesens verändert. Kein Reset ausgeführt.')
    now=store.jetzt()
    with store.datenbank() as db:
        db.execute('BEGIN IMMEDIATE')
        current=db.execute('SELECT daten,revision,ausgeblendet FROM artikel WHERE id=?',(a['id'],)).fetchone()
        if not current or current[1]!=a['revision'] or current[2]:raise ValueError('Artikel lokal verändert.')
        current_jobs=[json.loads(r[0]) for r in db.execute('SELECT daten FROM bildauftraege WHERE artikel=?',(a['id'],))]
        if sorted((j for j in current_jobs if j['status'] in ('sendet','unklar')),key=lambda j:j['id'])!=sorted(jobs,key=lambda j:j['id']):
            raise ValueError('Auftragsstand lokal verändert.')
        refreshed.pop('revision',None);refreshed.pop('ausgeblendet',None)
        db.execute('UPDATE artikel SET daten=?,revision=revision+1,geaendert=?,nutzer=? WHERE id=?',
                   (json.dumps(refreshed),now,'manueller Bilderreset',a['id']))
        for j in jobs:
            j['ruecksetzung']={'zeit':now,'vorher_status':j['status'],'vorher_meldung':j.get('meldung'),
                               'grund':'Nutzer hat Zusatzbild in Wawi entfernt; aktuellen Bestand neu eingelesen.',
                               'entferntes_v1_bild':entfernt}
            j.update(status='abgelehnt',meldung='Alter Auftrag nach manueller Wawi-Korrektur beendet. Neuer Test möglich.')
            db.execute('UPDATE bildauftraege SET daten=? WHERE id=?',(json.dumps(j),j['id']))
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='shoppruefung'").fetchone():
            db.execute('DELETE FROM shoppruefung WHERE artikel=?',(a['id'],))
        status=store.status_lesen(db)
        if any(u['id']==a['id'] for u in status.get('ungeprueft',[])):
            status['ungeprueft']=[u for u in status['ungeprueft'] if u['id']!=a['id']]
            db.execute('INSERT OR REPLACE INTO status VALUES (1,?)',(json.dumps(status),))
    return f'Artikel {sku}: {len(refreshed["bilder"])} aktuelle Shopbilder eingelesen; {len(jobs)} alte Aufträge beendet. Neuer Test möglich. Wawi unverändert.'


async def main(sku,entfernt):
    with store.Laufsperre():
        async with OnPremClient.aus_umgebung() as c:
            print(await zuruecksetzen(c,sku,entfernt))

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('sku');p.add_argument('--entfernt',type=int,required=True)
    a=p.parse_args()
    if a.entfernt<=0:p.error('Bildnummer muss positiv sein.')
    asyncio.run(main(a.sku,a.entfernt))
