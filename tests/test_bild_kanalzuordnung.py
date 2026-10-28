import hashlib
import json
import unittest
import httpx
import test_bilder_ersetzen as fixtures
from test_bilder_ersetzen import A, B, J, URL
from app.bilder_abgleich import vorschaubild
from app.bilder_ersetzen import zuordnungen
from app.bilder_upload import sichern, auftraege
from scripts.pruefe_bild_kanalzuordnung import pruefen


class ChannelProbeTest(unittest.IsolatedAsyncioTestCase):
    tearDown = fixtures.ReplaceTest.tearDown
    client = fixtures.ReplaceTest.client

    def setUp(self):
        fixtures.ReplaceTest.setUp(self)
        self.job = dict(id=J, artikel=A, sku='X', bild_id=B, revision=0, api_ziel=URL,
                        status='unklar', art='ersetzen_alle', v1_id=20,
                        v1_vorher=zuordnungen(self.rows),
                        thumb_hash=hashlib.sha256(vorschaubild(self.new)).hexdigest())
        sichern(self.job, self.new)
        self.rows[0]['ImageId'] = 21
        self.rows.append(dict(ItemId=10, ImageId=21, SalesChannelId='1-1-1', SortNumber=4))
        self.mode = 'replace'

    def response(self, req):
        self.calls.append(req.method)
        if req.method == 'GET':
            if req.url.path.endswith('/items/'+A):return httpx.Response(200, json=self.detail)
            if req.url.path.endswith('/images'):return httpx.Response(200, json=self.rows)
            return httpx.Response(200, content=self.new if req.url.path.endswith('/21') else self.old)
        self.assertEqual(req.method, 'PATCH')
        self.assertTrue(req.url.path.endswith('/images/21'))
        self.assertEqual(json.loads(req.content), {'SalesChannelId':'amazon', 'SortNumber':3})
        self.assertIn('kanaltest', auftraege()[0])
        if self.mode in ('replace', 'timeout'):
            next(r for r in self.rows if r['SalesChannelId']=='amazon')['ImageId'] = 21
        if self.mode == 'timeout':raise httpx.ReadTimeout('lost', request=req)
        return httpx.Response(201)

    async def test_dry_run_never_writes(self):
        async with self.client() as c:await pruefen(c,self.job,'amazon')
        self.assertEqual(set(self.calls), {'GET'})
        self.assertNotIn('kanaltest',auftraege()[0])

    async def test_one_step_without_image_data_and_no_replay(self):
        async with self.client() as c:
            await pruefen(c,self.job,'amazon',True)
            await pruefen(c,auftraege()[0],'amazon',True)
        self.assertTrue(auftraege()[0]['kanaltest']['ziel_bestaetigt'])
        self.assertEqual(self.calls.count('PATCH'),1)
        self.assertEqual(auftraege()[0]['status'],'unklar')

    async def test_http_success_without_change_is_not_success_or_retry(self):
        self.mode='noop'
        async with self.client() as c:
            await pruefen(c,self.job,'amazon',True)
            await pruefen(c,auftraege()[0],'amazon',True)
        self.assertFalse(auftraege()[0]['kanaltest']['ziel_bestaetigt'])
        self.assertEqual(self.calls.count('PATCH'),1)

    async def test_response_loss_only_reads_back(self):
        self.mode='timeout'
        async with self.client() as c:
            await pruefen(c,self.job,'amazon',True)
            await pruefen(c,auftraege()[0],'amazon',True)
        self.assertTrue(auftraege()[0]['kanaltest']['ziel_bestaetigt'])
        self.assertEqual(self.calls.count('PATCH'),1)

    async def test_unrelated_change_blocks_write(self):
        self.rows[-1]['SalesChannelId']='unexpected'
        async with self.client() as c:
            with self.assertRaises(ValueError):await pruefen(c,self.job,'amazon',True)
        self.assertNotIn('PATCH',self.calls)

    async def test_ambiguous_standard_channel_is_rejected(self):
        async with self.client() as c:
            with self.assertRaises(ValueError):await pruefen(c,self.job,'1-1-1',True)
        self.assertEqual(self.calls,[])
