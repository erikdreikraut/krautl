"""Resume a legacy replacement once; remove only its pixel-proven extra upload."""
import argparse
import asyncio
import copy
import hashlib
from app import bilder_speicher as store
from app.bilder_upload import auftraege, sichern, lokal, detail_lesen, bildinhalt_bestaetigt
from app.bilder_ersetzen import (liste, bild, zuordnungen, sichern_original, schreiben, pruefen, pixelgleich)
from app.bilder_abgleich import bild_laden
from app.jtl_onprem import OnPremClient


def bereinigungsziel(rows, duplicate):
    owned=[r for r in rows if r['ImageId']==duplicate]
    if not owned or any(r['SalesChannelId'] not in ('2-2-1','1-1-1') for r in owned):
        raise ValueError('Zusatzbild wird außerhalb von Shop/Standard verwendet; keine automatische Entfernung.')
    for r in owned:
        peers=[x['SortNumber'] for x in rows if x['SalesChannelId']==r['SalesChannelId']]
        if r['SortNumber']!=max(peers): raise ValueError('Zusatzbild ist nicht mehr am Ende; keine automatische Entfernung.')
    return zuordnungen([r for r in rows if r['ImageId']!=duplicate])


async def fortsetzen(c, job, execute=False):
    if job['api_ziel']!=c.url: raise ValueError('Wawi-Ziel passt nicht.')
    a,_=lokal(job['artikel'],job['revision'])
    detail=await detail_lesen(c,job['artikel'],job['sku'])
    with store.datenbank() as db:
        raw=db.execute('SELECT datei FROM bildauftraege WHERE id=?',(job['id'],)).fetchone()[0]
    rows=await liste(c,job['artikel'])
    if job.get('art')!='ersetzen_alle':
        if job.get('status')!='unklar' or not job.get('bild_id') or job.get('phase')!='upload':
            raise ValueError('Kein passender angehaltener Austauschauftrag.')
        target=next(b for b in a['bilder'] if b['id']==job['bild_id'])
        ids={r['ImageId'] for r in rows if r['SalesChannelId']=='2-2-1' and r['SortNumber']==target['position']}
        if len(ids)!=1: raise ValueError('Altes Shopbild nicht eindeutig.')
        original=next(iter(ids))
        old=await bild(c,original)
        source=[b for g in detail.get('images',{}).get('saleschannelImages',[]) if g.get('saleschannelId')=='2-2-1'
                for b in g.get('images',[]) if b.get('blobIdentifier')==job['bild_id'] and b.get('sortNumber')==target['position']]
        if len(source)!=1 or not pixelgleich(old,await bild_laden(c,job['bild_id'],source[0])):
            raise ValueError('Altes v1-/v2-Bild nicht eindeutig identifiziert.')
        cached=store.thumb_lesen(a['id'],target.get('thumb'))
        if not cached or not pixelgleich(cached,old): raise ValueError('Altes Bild seit Auftrag verändert.')
        candidates=[]
        for image in {r['ImageId'] for r in rows if r['SalesChannelId']=='2-2-1' and r['ImageId']!=original}:
            if bildinhalt_bestaetigt(job,await bild(c,image)): candidates.append(image)
        if len(candidates)!=1: raise ValueError('Uploadkopie nicht eindeutig anhand der Pixel identifiziert.')
        duplicate=candidates[0]
        clean=bereinigungsziel(rows,duplicate)
        # Exclude additional images or reordered shop images since the initial request.
        expected=sorted(b['position'] for b in a['bilder'])
        actual=sorted({r['SortNumber'] for r in rows if r['SalesChannelId']=='2-2-1' and r['ImageId']!=duplicate})
        if actual!=expected: raise ValueError('Shop-Bestand inzwischen verändert.')
        print('Vorbereitet: bestehendes Bild',original,'ersetzen; danach Uploadkopie',duplicate,'entfernen.')
        if not execute:return
        if zuordnungen(await liste(c,a['id']))!=zuordnungen(rows) or not store.freigegeben(a['id'],a['revision']):
            raise ValueError('Artikel während der Vorbereitung verändert.')
        await sichern_original(c,job['id'],original,old)
        previous=copy.deepcopy(job)
        job.update(art='ersetzen_alle',v1_id=original,v1_vorher=zuordnungen(rows),
                   bereinigung_id=duplicate,bereinigung_ziel=clean,altauftrag=previous,
                   status='unklar',phase='ersetzen',meldung='Bestehender Austausch wird kanalübergreifend fortgesetzt.')
        sichern(job)
    elif not execute:
        print('Bereits vorbereiteter Auftrag:',job['id'],job['status']);return
    if job.get('bereinigung_bestaetigt'):
        print((await pruefen(c,job))['meldung']);return
    if not job.get('bereinigung_versuch'):
        await schreiben(c,job,raw)
        if not job.get('austausch_bestaetigt'):
            print(job['meldung']);return
        rows=await liste(c,job['artikel'])
        if zuordnungen(rows)!=job['v1_vorher'] or bereinigungsziel(rows,job['bereinigung_id'])!=job['bereinigung_ziel']:
            raise ValueError('Bestand vor Bereinigung verändert.')
        if not bildinhalt_bestaetigt(job,await bild(c,job['v1_id'])) or not bildinhalt_bestaetigt(job,await bild(c,job['bereinigung_id'])):
            raise ValueError('Bildinhalt vor Bereinigung verändert.')
        if not store.freigegeben(job['artikel'],job['revision']):raise ValueError('Artikelrevision verändert.')
        job['bereinigung_versuch']=store.jetzt();sichern(job)
        # This ID is the redundant new upload, NEVER the shared original image.
        try:
            r=await c.http.delete(c.url+'/v1/items/'+job['artikel']+'/images/'+str(job['bereinigung_id']))
            job['bereinigung_http_status']=r.status_code;sichern(job)
        except Exception:
            print('Bereinigungsantwort unklar; es wird nur rückgelesen.')
    rows=await liste(c,job['artikel'])
    if zuordnungen(rows)!=job['bereinigung_ziel']:
        print('Bereinigung noch nicht bestätigt. Kein automatischer Neuversuch.');return
    job.update(bereinigung_bestaetigt=True,v1_vorher=job['bereinigung_ziel']);sichern(job)
    print((await pruefen(c,job))['meldung'])


async def main(sku,execute):
    with store.Laufsperre():
        jobs=sorted((j for j in auftraege() if j.get('sku')==sku and j.get('bild_id') and j.get('thumb_hash')),
                    key=lambda j:j.get('erstellt',''))
        if not jobs:raise ValueError('Kein Austauschauftrag gefunden.')
        async with OnPremClient.aus_umgebung() as c:
            await fortsetzen(c,jobs[-1],execute)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('sku');p.add_argument('--ausfuehren',action='store_true')
    args=p.parse_args();asyncio.run(main(args.sku,args.ausfuehren))
