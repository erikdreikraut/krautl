"""Explicit, bridge-only removal of one shop assignment; never delete image bytes."""
import base64
import copy
import hashlib
import json
from . import bilder_speicher as store
from .bilder_upload import auftraege, lokal, sichern, oeffentlich, detail_lesen
from .bilder_ersetzen import liste, bild, zuordnungen, pixelgleich, bestand, sichern_original, sortierung_v1_vorbereiten
from .bilder_bruecke import aktiv, bereit, artikel_erlaubt


def ziel(before,image):
    selected=[r for r in before if r[1]==image and r[2]=='2-2-1']
    if len(selected)!=1:raise ValueError('Shopbild nicht eindeutig.')
    positions=sorted(r[4] for r in before if r[2]=='2-2-1')
    if positions!=list(range(1,len(positions)+1)):raise ValueError('Shop-Positionen nicht eindeutig.')
    result=copy.deepcopy([r for r in before if r!=selected[0]])
    for r in result:
        if r[2]=='2-2-1' and r[4]>selected[0][4]:r[4]-=1
    return sorted(result)


async def beauftragen(c,article,image_key,revision,request_id,user):
    digest=hashlib.sha256(json.dumps([article,image_key,revision]).encode()).hexdigest()
    previous=next((j for j in auftraege() if j['id']==request_id),None)
    if previous:
        if previous.get('art')!='entfernen_shop' or previous.get('eingang_hash')!=digest:raise ValueError('Auftragskennung bereits verwendet.')
        return oeffentlich(previous)
    if not aktiv():raise ValueError('Entfernen ist erst nach Inbetriebnahme des Bilddienstes verfügbar.')
    bereit(entfernen=True)
    a,data=lokal(article,revision);artikel_erlaubt(a['sku'])
    if data.get('api_ziel')!=c.url:raise ValueError('Wawi-Ziel passt nicht.')
    if any(j['status'] in ('sendet','unklar') for j in auftraege(article)):raise ValueError('Vorheriger Bildauftrag noch ungeklärt.')
    if any(not b.get('v1_id') for b in a['bilder']):
        await sortierung_v1_vorbereiten(c,article,revision,[b['id'] for b in a['bilder']],a['bilder'])
        a,_=lokal(article,revision)
    target=next((b for b in a['bilder'] if b['id']==image_key),None)
    if not target:raise ValueError('Bildbestand geändert. Bitte neu laden.')
    await detail_lesen(c,article,a['sku'])
    rows=await liste(c,article);before=zuordnungen(rows)
    pairs=sorted((r['SortNumber'],r['ImageId']) for r in rows if r['SalesChannelId']=='2-2-1')
    if pairs!=sorted((b['position'],b['v1_id']) for b in a['bilder']):raise ValueError('Shop-Bestand geändert.')
    preview=await bild(c,target['v1_id'])
    local=store.thumb_lesen(article,target.get('thumb'))
    if not local or not pixelgleich(local,preview):raise ValueError('Bildinhalt geändert. Bitte aktualisieren.')
    expected=ziel(before,target['v1_id'])
    if zuordnungen(await liste(c,article))!=before or not store.freigegeben(article,revision):raise ValueError('Artikel inzwischen geändert.')
    await sichern_original(c,request_id,target['v1_id'],preview)
    job=dict(id=request_id,artikel=article,sku=a['sku'],bild_id=image_key,art='entfernen_shop',operation='entfernen_shop',
             eingang_hash=digest,revision=revision,nutzer=user,erstellt=store.jetzt(),api_ziel=c.url,
             v1_id=target['v1_id'],v1_vorher=before,v1_ziel=expected,vorher_vorschau=base64.b64encode(preview).decode(),
             dateiname='',bruecke=True,status='sendet',meldung='Bild wird aus dem JTL-Shop entfernt.')
    sichern(job,b'')
    return oeffentlich(job)


async def bestaetigen(c,job):
    if not job.get('bruecke_bestaetigt'):return oeffentlich(job)
    if c.url!=job['api_ziel']:raise ValueError('Wawi-Ziel geändert.')
    await detail_lesen(c,job['artikel'],job['sku'])
    rows=await liste(c,job['artikel'])
    if zuordnungen(rows)!=job['v1_ziel']:raise ValueError('Entfernung noch nicht vollständig bestätigt.')
    if not pixelgleich(await bild(c,job['v1_id']),base64.b64decode(job['vorher_vorschau'])):raise ValueError('Originalbild nicht bestätigt.')
    a,_=lokal(job['artikel'],job['revision']);a=copy.deepcopy(a)
    a['bilder']=await bestand(c,a,rows)
    if zuordnungen(await liste(c,job['artikel']))!=job['v1_ziel'] or not store.freigegeben(a['id'],job['revision']):raise ValueError('Bestand während Bestätigung geändert.')
    a.update(bild_api='v1',aktualisiert_am=store.jetzt())
    store.zwischenstand(a,a['revision'],c.url,abgleich=False)
    job.update(status='wawi',meldung='Bild aus dem JTL-Shop entfernt; Originaldatei und andere Kanäle erhalten.')
    sichern(job);return oeffentlich(job)
