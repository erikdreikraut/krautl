import json
import unittest
import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.jtl_client import JtlClient, JtlFehler
from scripts.pruefe_jtl_faq_anbindung import diagnose
from scripts.migrate_faq_freigabe import migriere

TENANT = "11111111-1111-4111-8111-111111111111"
ITEM = "22222222-2222-4222-8222-222222222222"


class JtlTest(unittest.IsolatedAsyncioTestCase):
    def client(self, handler):
        return JtlClient("krautl-test", "test-secret", TENANT, transport=httpx.MockTransport(handler))

    async def test_exact_sku_and_read_only_with_token_cache(self):
        aufrufe = []
        def antwort(req):
            aufrufe.append((req.method, req.url.path))
            if req.url.path.endswith('/token'):
                self.assertIn(b'grant_type=client_credentials', req.content)
                return httpx.Response(200, json={"access_token": "test-token", "expires_in": 3600})
            self.assertEqual(req.headers['X-Tenant-ID'], TENANT)
            if req.url.path.endswith('/graphql'):
                self.assertEqual(json.loads(req.content)['variables'], {'sku': '001-02'})
                return httpx.Response(200, json={'data': {'QueryItems': {'nodes': [{'id': ITEM, 'sku': '001-02'}], 'pageInfo': {'hasNextPage': False}}}})
            self.assertEqual(req.method, 'GET')
            self.assertEqual(req.url.path, '/erp/v2/items/' + ITEM)
            return httpx.Response(200, json={'id': ITEM, 'identifiers': {'sku': '001-02'}, 'attributes': {'values': []}})
        async with self.client(antwort) as client:
            for _ in range(2): self.assertEqual((await client.artikel_lesen('001-02'))['id'], ITEM)
        self.assertEqual(sum(p.endswith('/token') for _, p in aufrufe), 1)
        self.assertFalse(any(m in ['PATCH','DELETE','PUT'] for m, _ in aufrufe))

    async def test_ambiguous_missing_and_graphql_errors_are_not_items(self):
        for data in [
            {'errors':[{'message':'secret'}]},
            {'data':{'QueryItems':{'nodes':[], 'pageInfo':{'hasNextPage':False}}}},
            {'data':{'QueryItems':{'nodes':[{'id':ITEM,'sku':'001'}], 'pageInfo':{'hasNextPage':True}}}},
            {'data':{'QueryItems':{'nodes':[{'id':ITEM,'sku':'WRONG'}], 'pageInfo':{'hasNextPage':False}}}},
        ]:
            def antwort(req):
                if req.url.path.endswith('/token'): return httpx.Response(200,json={'access_token':'t','expires_in':3600})
                self.assertTrue(req.url.path.endswith('/graphql'))
                return httpx.Response(200,json=data)
            async with self.client(antwort) as client:
                with self.assertRaises(JtlFehler) as cm: await client.artikel_lesen('001')
                self.assertNotIn('secret', str(cm.exception))

    async def test_401_refresh_once_and_403_no_retry(self):
        for status, anzahl in [(401, 4), (403, 2)]:
            aufrufe=[]
            def antwort(req):
                aufrufe.append(req.url.path)
                if req.url.path.endswith('/token'): return httpx.Response(200,json={'access_token':'t','expires_in':3600})
                return httpx.Response(status,json={'error':'private upstream detail'})
            async with self.client(antwort) as client:
                with self.assertRaises(JtlFehler) as cm: await client.artikel_lesen('001')
                self.assertNotIn('private',str(cm.exception))
            self.assertEqual(len(aufrufe),anzahl)

    def test_diagnosis_redacts_values(self):
        data=diagnose({'id':ITEM,'identifiers':{'sku':'001'},'attributes':{'values':[{'attributeId':'a','defaultValues':[{'languageIso':'EN','value':'private text'}],'salesChannelValues':[{'salesChannelId':'2-2-1','values':[{'languageIso':'DE','value':'Fragen / Antworten'}]}]}]}})
        self.assertNotIn('private text',json.dumps(data))
        self.assertTrue(data['attribute'][0]['werte'][1]['faq_titel'])
        self.assertEqual(data['attribute'][0]['werte'][1]['kanal'],'2-2-1')


class MigrationTest(unittest.IsolatedAsyncioTestCase):
    async def test_only_old_exported_drafts_promoted_once(self):
        engine=create_async_engine('sqlite+aiosqlite:///:memory:')
        try:
            async with engine.begin() as conn:
                await conn.execute(text('CREATE TABLE faq_eintrag (id INTEGER PRIMARY KEY, aktiv BOOLEAN, status TEXT)'))
                await conn.execute(text("INSERT INTO faq_eintrag VALUES (1,TRUE,'entwurf'),(2,FALSE,'entwurf'),(3,TRUE,'veraltet'),(4,TRUE,'freigegeben')"))
                self.assertEqual((await migriere(conn))['freigegeben'],1)
                daten=dict((await conn.execute(text('SELECT id,status FROM faq_eintrag'))).all())
                self.assertEqual(daten,{1:'freigegeben',2:'entwurf',3:'veraltet',4:'freigegeben'})
                await conn.execute(text("INSERT INTO faq_eintrag VALUES (5,TRUE,'entwurf')"))
                self.assertTrue((await migriere(conn))['bereits_ausgefuehrt'])
                self.assertEqual((await conn.execute(text('SELECT status FROM faq_eintrag WHERE id=5'))).scalar_one(),'entwurf')
        finally: await engine.dispose()
