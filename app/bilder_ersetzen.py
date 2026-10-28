"""Journaled replacement of an existing v1 image across its channel assignments."""
import base64
import copy
import hashlib
import json
from uuid import UUID, uuid5
import httpx
from . import bilder_speicher as store
from .bilder_abgleich import bildantwort, bild_laden, vorschaubild, BildFehler
from .jtl_client import JtlFehler

SHOP = '2-2-1'


def zuordnungen(rows):
    result = set()
    items = set()
    for r in rows:
        if any(type(r.get(k)) is not int or r[k] <= 0 for k in ('ItemId','ImageId','SortNumber')):
            raise ValueError('Ungültige v1-Bildzuordnung.')
        if not isinstance(r.get('SalesChannelId'), str) or not r['SalesChannelId']:
            raise ValueError('v1-Bildkanal fehlt.')
        items.add(r['ItemId'])
        result.add((r['ItemId'],r['ImageId'],r['SalesChannelId'],r.get('EbayUserName') or '',r['SortNumber']))
    if len(items) != 1: raise ValueError('v1-Bildliste gehört nicht eindeutig zu einem Artikel.')
    return [list(v) for v in sorted(result)]


async def liste(c, article):
    rows = await c._request('GET','/v1/items/'+article+'/images',expected_type=list)
    zuordnungen(rows)
    return rows


async def bild(c, image_id, size=(240,180)):
    if type(image_id) is not int or image_id <= 0: raise ValueError('Ungültige v1-Bildnummer.')
    async with c.http.stream('GET',c.url+'/v1/items/imagedata/'+str(image_id)) as r:
        return await bildantwort(r,size)


def pixelgleich(a,b):
    from PIL import Image
    from io import BytesIO
    with Image.open(BytesIO(a)) as left, Image.open(BytesIO(b)) as right:
        return left.size==right.size and left.convert('RGBA').tobytes()==right.convert('RGBA').tobytes()


async def sichern_original(c, job_id, image_id, preview):
    async with c.http.stream('GET',c.url+'/v1/items/imagedata/'+str(image_id)) as r:
        r.raise_for_status()
        data=bytearray()
        async for chunk in r.aiter_bytes():
            data.extend(chunk)
            if len(data)>28_000_000: raise ValueError('Originalbild zu groß für die Sicherung.')
        if 'json' in r.headers.get('content-type','').lower():
            value=json.loads(data)
            if not isinstance(value,str): raise ValueError('Ungültige Originalbildantwort.')
            raw=base64.b64decode(value,validate=True)
        else: raw=bytes(data)
    if len(raw)>20*1024*1024 or not pixelgleich(vorschaubild(raw),preview):
        raise ValueError('Originalbild während der Vorbereitung verändert.')
    with store.datenbank() as db:
        db.execute('CREATE TABLE IF NOT EXISTS bildsicherungen (auftrag TEXT PRIMARY KEY, daten BLOB NOT NULL)')
        db.execute('INSERT INTO bildsicherungen VALUES (?, ?)',(job_id,raw))


def lokale_id(article, image):
    # A local UI key, never sent to Wawi as a blobIdentifier.
    return str(uuid5(UUID(article),'krautl-v1-image-'+str(image)))


async def bestand(c, a, rows=None, fehlertolerant=False):
    rows = await liste(c,a['id']) if rows is None else rows
    pairs = sorted({(r['SortNumber'],r['ImageId']) for r in rows if r['SalesChannelId']==SHOP})
    if [p for p,i in pairs] != list(range(1,len(pairs)+1)) or len({i for p,i in pairs})!=len(pairs):
        raise ValueError('Shop-Positionen in v1 sind nicht eindeutig.')
    result=[]
    for pos, image in pairs:
        error = None
        try:
            thumb = store.thumb_speichern(await bild(c,image))
        except BildFehler as exc:
            if not fehlertolerant: raise
            thumb = None
            error = str(exc)
        row=next(r for r in rows if r['ImageId']==image and r['SalesChannelId']==SHOP)
        result.append({'id':lokale_id(a['id'],image),'v1_id':image,'thumb':thumb,
                       'fehler':error,'version':None,'position':pos,'hauptbild':pos==1,
                       'dateiname':str(row.get('Filename') or '').replace('\\','/').rsplit('/',1)[-1],
                       'quelle':'wawi-v1'})
    return result


async def pruefen(c, job):
    from .bilder_upload import lokal, sichern, oeffentlich, bildinhalt_bestaetigt, detail_lesen
    if c.url != job['api_ziel']: raise ValueError('Wawi-Ziel stimmt nicht mit dem Auftrag überein.')
    await detail_lesen(c,job['artikel'],job['sku'])
    rows=await liste(c,job['artikel'])
    expected=job['v1_vorher']
    if zuordnungen(rows)!=expected:
        job.update(status='unklar',meldung='Kanalzuordnungen oder Positionen weichen ab. Kein weiterer Schreibversuch.')
        sichern(job);return oeffentlich(job)
    thumb=await bild(c,job['v1_id'])
    if not bildinhalt_bestaetigt(job,thumb):
        job.update(status='unklar',meldung='Der ausgetauschte Bildinhalt ist noch nicht bestätigt. Kein weiterer Schreibversuch.')
        sichern(job);return oeffentlich(job)
    if job.get('bereinigung_id') and not job.get('bereinigung_bestaetigt'):
        job.update(status='unklar',austausch_bestaetigt=True,
                   meldung='Austausch über alle bisherigen Kanäle bestätigt; zusätzliche Alt-Uploadkopie noch zu bereinigen.')
        sichern(job);return oeffentlich(job)
    a,_=lokal(job['artikel'],job['revision'])
    a=copy.deepcopy(a)
    a['bild_api']='v1'
    a['bilder']=await bestand(c,a,rows)
    # Verify again after downloads before publishing a new local snapshot.
    if zuordnungen(await liste(c,job['artikel']))!=expected:
        raise ValueError('Zuordnungen während des Rücklesens geändert.')
    a['aktualisiert_am']=store.jetzt()
    store.zwischenstand(a,a['revision'],c.url,abgleich=False)
    job.update(status='wawi',neu_id=lokale_id(a['id'],job['v1_id']),
               meldung='Bildinhalt in Wawi bestätigt; bisherige Kanalzuordnungen und Positionen erhalten. Shop-Veröffentlichung noch ungeprüft.')
    sichern(job);return oeffentlich(job)


async def ersetzen(c, article, image_key, revision, request_id, raw, user):
    from .bilder_upload import auftraege, lokal, datei_pruefen, detail_lesen, sichern, oeffentlich
    digest=hashlib.sha256(raw).hexdigest()
    previous=next((j for j in auftraege() if j['id']==request_id),None)
    if previous:
        if (previous.get('artikel'),previous.get('bild_id'),previous.get('eingang_hash'))!=(article,image_key,digest):
            raise ValueError('Auftragskennung wurde bereits anders verwendet.')
        return oeffentlich(previous)
    a, data=lokal(article,revision)
    if data.get('api_ziel')!=c.url: raise ValueError('Wawi-Ziel passt nicht zum Bestand.')
    if any(j['status'] in ('sendet','unklar') for j in auftraege(article)):
        raise ValueError('Ein früherer Bildauftrag ist noch ungeklärt. Zuerst dessen Wawi-Stand prüfen.')
    target=next((b for b in a['bilder'] if b['id']==image_key),None)
    if not target: raise ValueError('Bild fehlt im lokalen Artikelbestand.')
    raw=datei_pruefen(raw)
    detail=await detail_lesen(c,article,a['sku'])
    rows=await liste(c,article)
    candidates={r['ImageId'] for r in rows if r['SalesChannelId']==SHOP and r['SortNumber']==target['position']}
    if len(candidates)!=1: raise ValueError('Shopbild lässt sich nicht eindeutig einer v1-Bildnummer zuordnen.')
    image=next(iter(candidates))
    before=await bild(c,image)
    if target.get('v1_id'):
        if target['v1_id']!=image: raise ValueError('Bildposition wurde inzwischen verändert.')
    else:
        matches=[b for g in detail.get('images',{}).get('saleschannelImages',[]) if g.get('saleschannelId')==SHOP
                 for b in g.get('images',[]) if b.get('blobIdentifier')==image_key and b.get('sortNumber')==target['position']]
        if len(matches)!=1: raise ValueError('v2-Ausgangsbild hat sich verändert.')
        if not pixelgleich(before,await bild_laden(c,image_key,matches[0])):
            raise ValueError('v1- und v2-Ausgangsbild stimmen nicht überein.')
    local=store.thumb_lesen(article,target.get('thumb'))
    if not local or not pixelgleich(local,before): raise ValueError('Bildinhalt wurde inzwischen verändert. Bitte aktualisieren.')
    assignments=zuordnungen(rows)
    if zuordnungen(await liste(c,article))!=assignments or not store.freigegeben(article,revision):
        raise ValueError('Artikel während der Vorbereitung geändert.')
    job={'id':request_id,'artikel':article,'sku':a['sku'],'bild_id':image_key,'eingang_hash':digest,
         'art':'ersetzen_alle','v1_id':image,'v1_vorher':assignments,
         'vorher_vorschau':base64.b64encode(before).decode(),'erstellt':store.jetzt(),'nutzer':user,
         'api_ziel':c.url,'dateiname':'krautl-'+request_id+'.png','revision':revision,
         'thumb_hash':hashlib.sha256(vorschaubild(raw)).hexdigest(),'status':'sendet',
         'phase':'ersetzen','meldung':'Bestehendes Bild wird für alle bisherigen Kanäle ersetzt.'}
    await sichern_original(c,request_id,image,before)
    sichern(job,raw)
    return await schreiben(c,job,raw)


async def schreiben(c,job,raw):
    from .bilder_upload import sichern, oeffentlich, ablehnungsdetails
    if job.get("ruecksetzung"): return oeffentlich(job)
    # Persisted BEFORE the single PATCH. Every later call only reads.
    if job.get('v1_schreibversuch'): return await pruefen(c,job)
    if zuordnungen(await liste(c,job['artikel']))!=job['v1_vorher'] or not store.freigegeben(job['artikel'],job['revision']):
        job.update(status='unklar',meldung='Artikel vor dem Austausch verändert. Kein Schreibzugriff ausgeführt.')
        sichern(job);return oeffentlich(job)
    job['v1_schreibversuch']=store.jetzt();sichern(job)
    try:
        r=await c.http.patch(c.url+'/v1/items/'+job['artikel']+'/images/'+str(job['v1_id']),json={
            'SalesChannelId':SHOP,'ImageData':base64.b64encode(raw).decode(),'Filename':job['dateiname']})
        job['v1_http_status']=r.status_code
        if r.status_code not in (200,201): job['diagnose']=ablehnungsdetails(r)
        sichern(job)
        return await pruefen(c,job)
    except (httpx.HTTPError,JtlFehler,ValueError,KeyError,TypeError) as exc:
        job.update(status='unklar',meldung='Austausch noch nicht bestätigt. Nur Wawi-Stand prüfen; nicht erneut senden.')
        sichern(job);return oeffentlich(job)

async def reihenfolge(c, article, revision, request_id, order, before, user):
    from .bilder_upload import auftraege, lokal, sichern, oeffentlich, positionsstand, detail_lesen
    digest=hashlib.sha256(json.dumps([article,revision,order,before],sort_keys=True).encode()).hexdigest()
    previous=next((j for j in auftraege() if j['id']==request_id),None)
    if previous:
        if previous.get('art')!='reihenfolge_v1' or previous.get('eingang_hash')!=digest:raise ValueError('Auftragskennung bereits verwendet.')
        return oeffentlich(previous)
    a,data=lokal(article,revision)
    if data.get('api_ziel')!=c.url:raise ValueError('Wawi-Ziel passt nicht.')
    if any(j['status'] in ('sendet','unklar') for j in auftraege(article)):raise ValueError('Ein Bildauftrag ist noch ungeklärt.')
    mapping={b['id']:b['v1_id'] for b in a['bilder']}
    if len(order)!=len(mapping) or set(order)!=set(mapping) or positionsstand(before)!=positionsstand(a['bilder']):
        raise ValueError('Bildbestand wurde verändert.')
    await detail_lesen(c,article,a['sku'])
    rows=await liste(c,article);initial=zuordnungen(rows)
    current=sorted({(r['SortNumber'],r['ImageId']) for r in rows if r['SalesChannelId']==SHOP})
    if current!=sorted((b['position'],b['v1_id']) for b in a['bilder']):raise ValueError('Wawi-Reihenfolge wurde verändert.')
    target_ids=[mapping[key] for key in order]
    target=copy.deepcopy(initial)
    for r in target:
        if r[2]==SHOP:r[4]=target_ids.index(r[1])+1
    target.sort()
    job={'id':request_id,'artikel':article,'sku':a['sku'],'art':'reihenfolge_v1','revision':revision,
         'eingang_hash':digest,'api_ziel':c.url,'erstellt':store.jetzt(),'nutzer':user,
         'status':'sendet','meldung':'Shop-Reihenfolge wird übertragen.','reihenfolge':order,'v1_vorher':initial,'v1_ziel':target}
    if not store.freigegeben(article,revision):raise ValueError('Artikelrevision verändert.')
    sichern(job,b'')
    expected=initial
    try:
        for position,image_id in enumerate(target_ids,1):
            live=zuordnungen(await liste(c,article))
            if live!=expected or not store.freigegeben(article,revision):raise ValueError('Bestand während der Sortierung verändert.')
            oldpos=next(r[4] for r in expected if r[2]==SHOP and r[1]==image_id)
            if oldpos==position:continue
            step=copy.deepcopy(expected)
            for r in step:
                if r[2]!=SHOP:continue
                if r[1]==image_id:r[4]=position
                elif position<=r[4]<oldpos:r[4]+=1
            step.sort()
            job.setdefault('sortierschritte',[]).append({'bild':image_id,'position':position,'zeit':store.jetzt()})
            sichern(job)
            response=await c.http.patch(c.url+'/v1/items/'+article+'/images/'+str(image_id),json={'SalesChannelId':SHOP,'SortNumber':position})
            if response.status_code not in (200,201):raise ValueError('Wawi hat den Sortierschritt nicht bestätigt.')
            if zuordnungen(await liste(c,article))!=step:raise ValueError('Wawi-Sortierschritt weicht vom Ziel ab.')
            expected=step
        return await reihenfolge_pruefen(c,job)
    except (httpx.HTTPError,JtlFehler,ValueError):
        job.update(status='unklar',meldung='Reihenfolge noch nicht bestätigt. Nur Wawi-Stand prüfen; kein automatischer Neuversuch.')
        sichern(job);return oeffentlich(job)


async def reihenfolge_pruefen(c,job):
    from .bilder_upload import lokal, sichern, oeffentlich, detail_lesen
    if c.url!=job['api_ziel']:raise ValueError('Wawi-Ziel passt nicht.')
    await detail_lesen(c,job['artikel'],job['sku'])
    rows=await liste(c,job['artikel'])
    if zuordnungen(rows)!=job['v1_ziel']:
        job.update(status='unklar',meldung='Shop-Reihenfolge noch nicht bestätigt. Kein automatischer Neuversuch.')
    else:
        a,_=lokal(job['artikel'],job['revision']);a=copy.deepcopy(a)
        a['bild_api']='v1'
        a['bilder']=await bestand(c,a,rows)
        if zuordnungen(await liste(c,job['artikel']))!=job['v1_ziel']:raise ValueError('Bestand während des Rücklesens verändert.')
        store.zwischenstand(a,a['revision'],c.url,abgleich=False)
        job.update(status='wawi',meldung='Shop-Reihenfolge in Wawi bestätigt; andere Kanäle unverändert.')
    sichern(job);return oeffentlich(job)

async def hinzufuegen(c,article,revision,request_id,raw,user):
    from .bilder_upload import auftraege,lokal,datei_pruefen,sichern,oeffentlich,detail_lesen
    digest=hashlib.sha256(raw).hexdigest()
    previous=next((j for j in auftraege() if j['id']==request_id),None)
    if previous:
        if previous.get('art')!='hinzufuegen_v1' or previous.get('eingang_hash')!=digest or previous.get('artikel')!=article:
            raise ValueError('Auftragskennung bereits verwendet.')
        return oeffentlich(previous)
    a,data=lokal(article,revision)
    if data.get('api_ziel')!=c.url:raise ValueError('Wawi-Ziel passt nicht.')
    if any(j['status'] in ('unklar','sendet') for j in auftraege(article)):raise ValueError('Bildauftrag noch ungeklärt.')
    await detail_lesen(c,article,a['sku'])
    rows=await liste(c,article);before=zuordnungen(rows)
    current=sorted({(r['SortNumber'],r['ImageId']) for r in rows if r['SalesChannelId']==SHOP})
    if current!=sorted((b['position'],b['v1_id']) for b in a['bilder']):raise ValueError('Bildbestand wurde verändert.')
    raw=datei_pruefen(raw)
    job={'id':request_id,'artikel':article,'sku':a['sku'],'bild_id':None,'art':'hinzufuegen_v1','revision':revision,
         'eingang_hash':digest,'api_ziel':c.url,'erstellt':store.jetzt(),'nutzer':user,
         'thumb_hash':hashlib.sha256(vorschaubild(raw)).hexdigest(),'dateiname':'krautl-'+request_id+'.png',
         'v1_ausgang':before,'status':'sendet','meldung':'Zusätzliches Shopbild wird angelegt.'}
    if not store.freigegeben(article,revision):raise ValueError('Artikelrevision verändert.')
    sichern(job,raw)
    try:
        r=await c.http.post(c.url+'/v1/items/'+article+'/images',json={'SalesChannelId':SHOP,'Filename':job['dateiname'],'ImageData':base64.b64encode(raw).decode()})
        job['v1_http_status']=r.status_code;sichern(job)
        return await hinzufuegen_pruefen(c,job)
    except (httpx.HTTPError,JtlFehler,ValueError):
        job.update(status='unklar',meldung='Bildanlage noch nicht bestätigt. Nur Wawi-Stand prüfen; kein weiterer Upload.')
        sichern(job);return oeffentlich(job)


async def hinzufuegen_pruefen(c,job):
    from .bilder_upload import sichern, oeffentlich, bildinhalt_bestaetigt, detail_lesen
    if c.url!=job['api_ziel']:raise ValueError('Wawi-Ziel passt nicht.')
    await detail_lesen(c,job['artikel'],job['sku'])
    rows=await liste(c,job['artikel']);after=zuordnungen(rows);before=job['v1_ausgang']
    newids={r[1] for r in after}-{r[1] for r in before}
    if len(newids)!=1:raise ValueError('Neues Bild nicht eindeutig identifiziert.')
    image=next(iter(newids));added=[r for r in after if r[1]==image]
    if [r for r in after if r[1]!=image]!=before or any(r[2] not in (SHOP,'1-1-1') for r in added):
        raise ValueError('Weitere Bildzuordnungen wurden verändert.')
    positions=[r[4] for r in added if r[2]==SHOP]
    if positions!=[1+max((r[4] for r in before if r[2]==SHOP),default=0)]:raise ValueError('Neues Bild nicht am Shop-Ende.')
    if not bildinhalt_bestaetigt(job,await bild(c,image)):raise ValueError('Neuer Bildinhalt nicht bestätigt.')
    job.update(v1_id=image,v1_vorher=after);sichern(job)
    return await pruefen(c,job)
