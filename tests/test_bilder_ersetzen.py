import base64
import copy
import json
import os
import tempfile
import unittest
from io import BytesIO
from unittest.mock import patch
from PIL import Image
import httpx
from app import bilder_speicher as store
from app.bilder_abgleich import vorschaubild
from app.bilder_upload import uebertragen, pruefen, auftraege
from app.bilder_ersetzen import zuordnungen
from app.jtl_onprem import OnPremClient

A='00000000-0000-0000-0000-000000000001'
B='00000000-0000-0000-0000-000000000002'
J='00000000-0000-0000-0000-000000000003'
URL='https://wawi.test/api/eazybusiness'

def picture(color):
    buf=BytesIO();Image.new('RGB',(50,60),color).save(buf,'PNG');return buf.getvalue()

class ReplaceTest(unittest.IsolatedAsyncioTestCase):
    async def test_bridge_queues_without_api_write_and_confirms_new_id_independently(self):
        from app.bilder_bruecke import bestaetigen
        with patch.dict(os.environ, {'BILDER_BRUECKE_AKTIV':'1','BILDER_BRUECKE_SKUS':'X'}), patch('app.bilder_bruecke.bereit'):
            async with self.client() as c:
                result=await uebertragen(c,A,B,0,J,self.new,'user')
                self.assertEqual(result['status'],'sendet')
                self.assertTrue(all(method=='GET' for method in self.calls))
                job=auftraege()[0]
                self.assertTrue(job['bruecke'])
                job.update(bruecke_bestaetigt=True,bruecke_bild=21)
                for row in self.rows:
                    if row['SalesChannelId']!='9-7-8-0':row['ImageId']=21
                self.actual=self.new
                result=await bestaetigen(c,job)
                self.assertEqual(result['status'],'wawi')
                self.assertEqual(store.lesen()['artikel'][0]['bilder'][0]['v1_id'],21)

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.env=patch.dict(os.environ,{'BILDER_DIR':self.tmp.name});self.env.start()
        self.old=picture('red');self.new=picture('blue');self.actual=self.old;self.calls=[];self.timeout=False;self.change=False
        self.rows=[{'ItemId':10,'ImageId':20,'SalesChannelId':ch,'SortNumber':pos,'Filename':'old.png'} for ch,pos in [('2-2-1',1),('amazon',3),('9-7-8-0',2)]]
        self.detail={'id':A,'identifiers':{'sku':'X'},'images':{'saleschannelImages':[{'saleschannelId':'2-2-1','images':[{'blobIdentifier':B,'sortNumber':1,'isMainImage':True}]}]}}
        store.zwischenstand({'id':A,'sku':'X','bilder':[{'id':B,'position':1,'hauptbild':True,'thumb':store.thumb_speichern(vorschaubild(self.old))}]},0,URL)
    def tearDown(self):self.env.stop();self.tmp.cleanup()
    def response(self,r):
        self.calls.append(r.method)
        if r.method=='GET':
            if r.url.path.endswith('/items/'+A):return httpx.Response(200,json=self.detail)
            if r.url.path.endswith('/images'):return httpx.Response(200,json=self.rows)
            return httpx.Response(200,content=self.actual)
        self.assertEqual(r.method,'PATCH');self.assertTrue(r.url.path.endswith('/images/20'))
        body=json.loads(r.content);self.assertNotIn('SortNumber',body);self.assertEqual(body['SalesChannelId'],'2-2-1')
        with store.datenbank() as db:self.assertEqual(db.execute('SELECT daten FROM bildsicherungen WHERE auftrag=?',(body['Filename'][7:-4],)).fetchone()[0],self.old)
        self.actual=base64.b64decode(body['ImageData'])
        if self.change:self.rows[-1]['SortNumber']=4
        if self.timeout:raise httpx.ReadTimeout('lost',request=r)
        return httpx.Response(201,json={})
    def client(self):return OnPremClient(URL,'test',transport=httpx.MockTransport(self.response))
    async def test_existing_image_replaced_without_create_or_delete_preserves_every_channel(self):
        before=zuordnungen(self.rows)
        async with self.client() as c:
            result=await uebertragen(c,A,B,0,J,self.new,'user')
            self.assertEqual(result['status'],'wawi',result)
            await uebertragen(c,A,B,0,J,self.new,'user')
        self.assertEqual(self.actual,self.new);self.assertEqual(zuordnungen(self.rows),before)
        self.assertEqual(self.calls.count('PATCH'),1);self.assertNotIn('POST',self.calls);self.assertNotIn('DELETE',self.calls)
        self.assertEqual(store.lesen()['artikel'][0]['bilder'][0]['v1_id'],20)
    async def test_lost_response_only_readbacks_on_retry(self):
        self.timeout=True
        async with self.client() as c:
            result=await uebertragen(c,A,B,0,J,self.new,'user');self.assertEqual(result['status'],'unklar')
            await uebertragen(c,A,B,0,J,self.new,'user')
            self.assertEqual((await pruefen(c,auftraege()[0]))['status'],'wawi')
        self.assertEqual(self.calls.count('PATCH'),1)
    async def test_other_channel_change_prevents_success(self):
        self.change=True
        async with self.client() as c:
            result=await uebertragen(c,A,B,0,J,self.new,'user')
        self.assertEqual(result['status'],'unklar');self.assertNotIn('v1_id',store.lesen()['artikel'][0]['bilder'][0])
        job=auftraege()[0]
        self.assertTrue(job['bildinhalt_bestaetigt'])
        self.assertIn('Neuer Bildinhalt',result['meldung'])
        self.assertEqual(job['zuordnungsabweichung']['fehlt'],[[10,20,'9-7-8-0','',2]])
        self.assertEqual(job['zuordnungsabweichung']['hinzu'],[[10,20,'9-7-8-0','',4]])
    async def test_ambiguous_position_never_writes(self):
        self.rows.append({**self.rows[0],'ImageId':21})
        async with self.client() as c:
            with self.assertRaises(ValueError):await uebertragen(c,A,B,0,J,self.new,'user')
        self.assertNotIn('PATCH',self.calls)
    async def test_subsequent_replace_works_without_v2_blob(self):
        async with self.client() as c:
            await uebertragen(c,A,B,0,J,self.new,'user')
            b=store.lesen()['artikel'][0]['bilder'][0]
            self.detail['images']['saleschannelImages'][0]['images'][0].pop('blobIdentifier')
            # Backup assertion in transport belongs to first call; use new expected old data.
            self.old=self.new
            result=await uebertragen(c,A,b['id'],0,'00000000-0000-0000-0000-000000000004',picture('green'),'user')
        self.assertEqual(result['status'],'wawi',result)

class RecoveryTest(unittest.IsolatedAsyncioTestCase):
    setUp=ReplaceTest.setUp
    tearDown=ReplaceTest.tearDown
    client=ReplaceTest.client

    def response(self,r):
        if r.method=='GET' and r.url.path.endswith('/imagedata/21'):
            self.calls.append('GET');return httpx.Response(200,content=self.new)
        if r.method=='DELETE':
            self.calls.append('DELETE');self.assertTrue(r.url.path.endswith('/images/21'))
            if getattr(self,'reject_delete',False):return httpx.Response(500)
            self.rows=[row for row in self.rows if row['ImageId']!=21]
            return httpx.Response(204)
        return ReplaceTest.response(self,r)

    def prepare(self):
        import hashlib
        from app.bilder_upload import sichern
        self.rows += [{'ItemId':10,'ImageId':21,'SalesChannelId':ch,'SortNumber':pos} for ch,pos in [('2-2-1',2),('1-1-1',4)]]
        job={'id':J,'artikel':A,'sku':'X','bild_id':B,'revision':0,'api_ziel':URL,'phase':'upload','status':'unklar',
             'erstellt':store.jetzt(),'dateiname':'krautl-'+J+'.png','thumb_hash':hashlib.sha256(vorschaubild(self.new)).hexdigest()}
        sichern(job,self.new);return job

    async def test_recovery_replaces_original_then_deletes_only_duplicate_and_rerun_reads(self):
        from scripts.repariere_bildaustausch_v1 import fortsetzen
        job=self.prepare()
        async with self.client() as c:
            await fortsetzen(c,job,False)
            self.assertNotIn('PATCH',self.calls)
            await fortsetzen(c,job,True)
            self.assertEqual(job['status'],'wawi')
            self.assertEqual([r['ImageId'] for r in self.rows],[20,20,20])
            await fortsetzen(c,auftraege()[0],True)
        self.assertEqual(self.calls.count('PATCH'),1);self.assertEqual(self.calls.count('DELETE'),1)

    async def test_unclear_cleanup_never_repeats_delete_or_replace(self):
        from scripts.repariere_bildaustausch_v1 import fortsetzen
        self.reject_delete=True;job=self.prepare()
        async with self.client() as c:
            await fortsetzen(c,job,True)
            self.assertEqual(job['status'],'unklar')
            await fortsetzen(c,auftraege()[0],True)
        self.assertEqual(self.calls.count('PATCH'),1);self.assertEqual(self.calls.count('DELETE'),1)

    async def test_duplicate_in_another_channel_is_not_deleted(self):
        from scripts.repariere_bildaustausch_v1 import fortsetzen
        job=self.prepare();self.rows.append({'ItemId':10,'ImageId':21,'SalesChannelId':'amazon','SortNumber':5})
        async with self.client() as c:
            with self.assertRaises(ValueError):await fortsetzen(c,job,True)
        self.assertNotIn('PATCH',self.calls);self.assertNotIn('DELETE',self.calls)

class V1FollowupTest(unittest.IsolatedAsyncioTestCase):
    setUp=ReplaceTest.setUp
    tearDown=ReplaceTest.tearDown
    client=ReplaceTest.client
    def response(self,r):
        if r.method=='POST':
            self.calls.append('POST');body=json.loads(r.content)
            self.extra=base64.b64decode(body['ImageData'])
            self.rows.append({'ItemId':10,'ImageId':21,'SalesChannelId':'2-2-1','SortNumber':2})
            return httpx.Response(201)
        if r.method=='GET' and r.url.path.endswith('/imagedata/21'):
            self.calls.append('GET');return httpx.Response(200,content=self.extra)
        if r.method=='PATCH' and 'ImageData' not in json.loads(r.content):
            self.calls.append('PATCH');body=json.loads(r.content);image=int(r.url.path.rsplit('/',1)[-1])
            old=next(x['SortNumber'] for x in self.rows if x['ImageId']==image and x['SalesChannelId']=='2-2-1')
            for row in self.rows:
                if row['SalesChannelId']!='2-2-1':continue
                if row['ImageId']==image:row['SortNumber']=body['SortNumber']
                elif body['SortNumber']<=row['SortNumber']<old:row['SortNumber']+=1
            return httpx.Response(201)
        return ReplaceTest.response(self,r)
    async def test_add_and_reorder_after_replacement_preserve_other_channels(self):
        from app.bilder_upload import umordnen
        async with self.client() as c:
            await uebertragen(c,A,B,0,J,self.new,'user')
            result=await uebertragen(c,A,None,0,'00000000-0000-0000-0000-000000000004',picture('green'),'user')
            self.assertEqual(result['status'],'wawi',result)
            a=store.lesen()['artikel'][0];before=[{k:b[k] for k in ('id','position','hauptbild')} for b in a['bilder']]
            order=[b['id'] for b in reversed(a['bilder'])]
            result=await umordnen(c,A,0,'00000000-0000-0000-0000-000000000005',order,before,'user')
            self.assertEqual(result['status'],'wawi',result)
        self.assertEqual([b['v1_id'] for b in store.lesen()['artikel'][0]['bilder']],[21,20])
        self.assertEqual([(r['SalesChannelId'],r['SortNumber']) for r in self.rows if r['SalesChannelId']!='2-2-1'],[('amazon',3),('9-7-8-0',2)])
