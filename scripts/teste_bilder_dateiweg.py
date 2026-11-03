"""Isolated small-file cloud acceptance, never replay an uncertain write."""
import argparse
import asyncio
import base64
import copy
import json
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from PIL import Image
from app.jtl_client import JtlClient
from app.jtl_faq_test import antwortdiagnose
from scripts.teste_bilder_cloud_inhalt import (
    ARTICLE, TARGET, SOURCE, META, SHOP, TENANT, snapshot, digest,
    base_url, headers_for, canonical, locked, save_once, backup)

FOLDER = Path('/app/var/bilder/cloud-kleindatei-1036')


def identify(plan, rows, files):
    hashes = {k: digest(v) for k, v in files.items()}
    if canonical(rows) == canonical(plan['rows']) and hashes == plan['hashes']:
        return 'ORIGINAL', TARGET
    shops = [r for r in rows if r['SalesChannelId'] == SHOP and r['SortNumber'] == 1]
    if len(shops) != 1:
        return 'ABWEICHUNG', None
    new = shops[0]
    ident = str(new['ImageId'])
    if ident in plan['hashes'] or hashes.get(ident) != plan['test_hash']:
        return 'ABWEICHUNG', None
    expected = copy.deepcopy(plan['rows'])
    for row in expected:
        if row['ImageId'] == TARGET and row['SalesChannelId'] == SHOP:
            row['ImageId'] = new['ImageId']
            for key in META:
                if key in new:
                    row[key] = new[key]
    expected_hashes = dict(plan['hashes'])
    expected_hashes[ident] = plan['test_hash']
    used = {str(r['ImageId']) for r in expected}
    expected_hashes = {k:v for k,v in expected_hashes.items() if k in used}
    if canonical(rows) == canonical(expected) and hashes == expected_hashes:
        return 'SHOP_TESTDATEI', new['ImageId']
    return 'ABWEICHUNG', None


async def run(c, folder, mode):
    if c.tenant_id != TENANT:
        raise ValueError('Falscher Tenant')
    with locked(folder):
        if mode == 'vorbereiten':
            if (folder/'plan.json').exists():
                raise ValueError('Plan vorhanden')
            rows, files = await snapshot(c)
            shops = [(r['ImageId'],r['SortNumber']) for r in rows if r['SalesChannelId']==SHOP]
            if sorted(shops) != [(2365,2),(2729,1)]:
                raise ValueError('Falscher Ausgangsbestand')
            for ident, raw in files.items():
                backup(folder/(ident+'.original'),raw)
            # Technical upload fixture: same product photograph, lower resolution.
            with Image.open(BytesIO(files[str(SOURCE)])) as im:
                im = im.convert('RGB')
                im.thumbnail((512,512))
                out = BytesIO()
                im.save(out,format='JPEG',quality=85)
            raw=out.getvalue()
            if len(raw)>100000 or digest(raw) in [digest(v) for v in files.values()]:
                raise ValueError('Testdatei nicht klein und neu')
            backup(folder/'test.jpg',raw)
            names={r['Filename'] for r in rows if r['ImageId']==TARGET}
            if len(names)!=1:
                raise ValueError('Uneindeutiger Originalname')
            save_once(folder/'plan.json',dict(article=ARTICLE,tenant=TENANT,url=base_url(c),
                created=datetime.now(timezone.utc).isoformat(),rows=rows,
                hashes={k:digest(v) for k,v in files.items()},test_hash=digest(raw),
                test_bytes=len(raw),original_name=names.pop()))
        plan=json.loads((folder/'plan.json').read_text())
        if (plan['article'],plan['tenant'],plan['url'])!=(ARTICLE,TENANT,base_url(c)):
            raise ValueError('Falscher Plan')
        for ident,sha in plan['hashes'].items():
            if digest((folder/(ident+'.original')).read_bytes())!=sha:
                raise ValueError('Sicherung defekt')
        if digest((folder/'test.jpg').read_bytes())!=plan['test_hash']:
            raise ValueError('Testdatei defekt')
        rows,files=await snapshot(c)
        current,image_id=identify(plan,rows,files)
        if mode in ('vorbereiten','pruefen'):
            return dict(zustand=current,test_bytes=plan['test_bytes'])
        restore=mode=='zuruecksetzen'
        if (folder/(mode+'.intent.json')).exists():
            raise ValueError('Schreibversuch verbraucht')
        if restore:
            if not (folder/'ausfuehren.intent.json').exists() or current!='SHOP_TESTDATEI':
                raise ValueError('Kein bekannter eigener Testzustand')
        else:
            age=(datetime.now(timezone.utc)-datetime.fromisoformat(plan['created'])).total_seconds()
            if current!='ORIGINAL' or not 0<=age<7200 or (folder/'zuruecksetzen.intent.json').exists():
                raise ValueError('Veralteter oder veraenderter Ausgangsstand')
        raw=(folder/(str(TARGET)+'.original' if restore else 'test.jpg')).read_bytes()
        headers=await headers_for(c)
        save_once(folder/(mode+'.intent.json'),dict(image_id=image_id,sha256=digest(raw),
            zeit=datetime.now(timezone.utc).isoformat()))
        result={}
        try:
            r=await c.http.patch(base_url(c)+'/v1/items/'+ARTICLE+'/images/'+str(image_id),
                headers=headers,json=dict(SalesChannelId=SHOP,ImageData=base64.b64encode(raw).decode(),
                Filename=plan['original_name'] if restore else 'krautl-kleindateitest-1036.jpg'))
            auth=headers.get('Authorization','')
            result['diagnose']=antwortdiagnose(r,[auth,auth.removeprefix('Bearer '),getattr(c,'client_secret','')])
            save_once(folder/(mode+'.antwort.json'),result['diagnose'])
        except Exception as exc:
            result['transportfehler_typ']=type(exc).__name__
        try:
            rows,files=await snapshot(c)
            result['zustand'],_=identify(plan,rows,files)
            save_once(folder/(mode+'.bestand.json'),dict(rows=rows,hashes={k:digest(v) for k,v in files.items()}))
        except Exception as exc:
            result['zustand']='UNGEPRUEFT'
            result['lesefehler_typ']=type(exc).__name__
        result['bestaetigt']=result['zustand']==('ORIGINAL' if restore else 'SHOP_TESTDATEI')
        save_once(folder/(mode+'.result.json'),result)
        return result


async def main(mode):
    async with JtlClient.aus_umgebung() as c:
        print(json.dumps(await run(c,FOLDER,mode)))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('mode',choices=['vorbereiten','ausfuehren','pruefen','zuruecksetzen'])
    asyncio.run(main(parser.parse_args().mode))
