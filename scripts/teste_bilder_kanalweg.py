"""Explicit one-shot channel diagnostics for the recorded small-image experiment."""
import asyncio,base64,json,sys
from pathlib import Path
from datetime import datetime,timezone
from app.jtl_client import JtlClient, ERP_URL
from app.jtl_onprem import OnPremClient
from app.jtl_faq_test import antwortdiagnose
from scripts.teste_bilder_cloud_inhalt import snapshot,digest,canonical,locked,save_once,base_url,headers_for,ARTICLE,SHOP,TENANT
FOLDER=Path('/app/var/bilder/cloud-kleindatei-1036')

def validate_cleanup(plan, rows, hashes, new):
    remaining=[r for r in rows if r['ImageId']!=new]
    if canonical(remaining)!=canonical(plan['rows']):raise ValueError('Originalzuordnungen fehlen')
    if {k:v for k,v in hashes.items() if k!=str(new)}!=plan['hashes']:raise ValueError('Originaldateien abweichend')
    extra=[r for r in rows if r['ImageId']==new]
    if len(extra)!=1 or extra[0]['SalesChannelId']!='1-1-1' or extra[0]['SortNumber']!=5:
        raise ValueError('Nicht die eigene zusaetzliche Testposition')
    if hashes[str(new)]!=plan['test_hash']:raise ValueError('Testinhalt abweichend')

async def main(mode):
    with locked(FOLDER):
        plan=json.loads((FOLDER/'plan.json').read_text())
        if (plan['article'],plan['tenant'],plan['url'])!=(ARTICLE,TENANT,ERP_URL):
            raise ValueError('Falscher Testplan')
        initial=json.loads((FOLDER/'ausfuehren.bestand.json').read_text())
        newrows=[r for r in initial['rows'] if r['SalesChannelId']==SHOP and r['SortNumber']==1]
        if len(newrows)!=1:raise ValueError('Testbild uneindeutig')
        new=newrows[0]['ImageId']
        if str(new) in plan['hashes'] or initial['hashes'][str(new)]!=plan['test_hash']:
            raise ValueError('Kein neues eigenes Testbild')
        predecessors={'standardkanal':'ausfuehren.bestand.json','standardkanal0':'standardkanal.bestand.json','shop-zurueck':'standardkanal0.bestand.json',
                      'standard-zurueck':'shop-zurueck.bestand.json','bereinigen':'standard-zurueck.bestand.json'}
        before=json.loads((FOLDER/predecessors[mode]).read_text())
        if (FOLDER/(mode+'.intent.json')).exists():raise ValueError('Versuch verbraucht')
        async with (JtlClient.aus_umgebung() if mode in ('standardkanal','standardkanal0') else OnPremClient.aus_umgebung()) as c:
            if isinstance(c,JtlClient) and c.tenant_id!=TENANT:raise ValueError('Falscher Tenant')
            rows,files=await snapshot(c)
            hashes={k:digest(v) for k,v in files.items()}
            if canonical(rows)!=canonical(before['rows']) or hashes!=before['hashes']:
                raise ValueError('Livebestand weicht vom geprueften Zwischenstand ab')
            for ident,sha in plan['hashes'].items():
                if digest((FOLDER/(ident+'.original')).read_bytes())!=sha:raise ValueError('Sicherung defekt')
            if mode in ('standardkanal','standardkanal0'):
                image_id=2729;channel='1-1-0' if mode=='standardkanal0' else '1-1-1';position=4
                raw=(FOLDER/'test.jpg').read_bytes();name='krautl-kleindateitest-1036.jpg'
                if digest(raw)!=plan['test_hash']:raise ValueError('Testdatei defekt')
            elif mode in ('shop-zurueck','standard-zurueck'):
                image_id=new;channel=SHOP if mode=='shop-zurueck' else '1-1-1'
                position=1 if channel==SHOP else 4
                raw=(FOLDER/'2729.original').read_bytes();name=plan['original_name']
                target=[r for r in rows if r['SalesChannelId']==channel and r['SortNumber']==position]
                if len(target)!=1:raise ValueError('Zuordnung uneindeutig')
                if target[0]['ImageId']==2729:
                    save_once(FOLDER/(mode+'.bestand.json'),before)
                    print(json.dumps({'bereits_original':True}));return
                if target[0]['ImageId']!=new:raise ValueError('Fremdes Bild')
            else:
                # Only the newly created fixture may be deleted, after all originals are restored.
                validate_cleanup(plan, rows, hashes, new)
                image_id=new
            headers=await headers_for(c)
            save_once(FOLDER/(mode+'.intent.json'),dict(image_id=image_id,zeit=datetime.now(timezone.utc).isoformat()))
            try:
                url=base_url(c)+'/v1/items/'+ARTICLE+'/images/'+str(image_id)
                if mode=='bereinigen':r=await c.http.delete(url,headers=headers)
                else:r=await c.http.patch(url,headers=headers,json=dict(SalesChannelId=channel,SortNumber=position,
                     ImageData=base64.b64encode(raw).decode(),Filename=name))
                auth=headers.get('Authorization') or c.http.headers.get('Authorization','')
                result=antwortdiagnose(r,[auth,auth.removeprefix('Bearer ').removeprefix('Wawi '),getattr(c,'client_secret','')])
            except Exception as exc:result={'transportfehler_typ':type(exc).__name__}
            save_once(FOLDER/(mode+'.antwort.json'),result)
            rows,files=await snapshot(c)
            after=dict(rows=rows,hashes={k:digest(v) for k,v in files.items()})
            save_once(FOLDER/(mode+'.bestand.json'),after)
            result['original']=canonical(rows)==canonical(plan['rows']) and after['hashes']==plan['hashes']
            result['entfernte_zeilen']=[r for r in before['rows'] if r not in rows]
            result['neue_zeilen']=[r for r in rows if r not in before['rows']]
            print(json.dumps(result))

if __name__=='__main__':asyncio.run(main(sys.argv[1]))
