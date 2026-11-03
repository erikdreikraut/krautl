import base64
import copy
import io
import unittest
import httpx
from PIL import Image
from tests import test_bilder_cloud_inhalt as fixtures
from scripts.teste_bilder_dateiweg import run


class TestSmallImage(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        fixtures.TestCloudContent.setUp(self)
        b=io.BytesIO()
        Image.new('RGB',(800,800),(40,80,120)).save(b,format='PNG')
        self.files['2731']=b.getvalue()
        self.original=copy.deepcopy(self.rows)
        self.code=201
        async def patch(url,**kwargs):
            self.assertEqual(len(list(self.folder.glob('*.intent.json'))),self.c.http.patch.await_count)
            if self.code==201 and self.effect:
                if url.endswith('/2729'):
                    self.rows[0]['ImageId']=7777
                    self.rows[0]['Filename']=kwargs['json']['Filename']
                    self.files['7777']=base64.b64decode(kwargs['json']['ImageData'])
                else:
                    self.assertTrue(url.endswith('/7777'))
                    self.rows[:]=copy.deepcopy(self.original)
            if self.timeout:
                raise httpx.ReadTimeout('after effect')
            return httpx.Response(self.code,headers={'content-type':'text/html'},text='denied')
        self.c.http.patch.side_effect=patch

    async def test_roundtrip_and_single_attempt(self):
        await run(self.c,self.folder,'vorbereiten')
        self.assertTrue((await run(self.c,self.folder,'ausfuehren'))['bestaetigt'])
        self.assertTrue((await run(self.c,self.folder,'zuruecksetzen'))['bestaetigt'])
        with self.assertRaises(ValueError):await run(self.c,self.folder,'ausfuehren')
        self.assertEqual(self.c.http.patch.await_count,2)

    async def test_rejection_preserves_original(self):
        await run(self.c,self.folder,'vorbereiten')
        self.code=403
        result=await run(self.c,self.folder,'ausfuehren')
        self.assertEqual(result['zustand'],'ORIGINAL')
        self.assertFalse(result['bestaetigt'])
        self.assertTrue((self.folder/'ausfuehren.antwort.json').exists())
        with self.assertRaises(ValueError):await run(self.c,self.folder,'ausfuehren')

    async def test_timeout_after_effect_readback(self):
        await run(self.c,self.folder,'vorbereiten')
        self.timeout=True
        self.assertTrue((await run(self.c,self.folder,'ausfuehren'))['bestaetigt'])
        with self.assertRaises(ValueError):await run(self.c,self.folder,'ausfuehren')

    async def test_changed_other_channel_blocks_restore(self):
        await run(self.c,self.folder,'vorbereiten')
        await run(self.c,self.folder,'ausfuehren')
        self.rows[-1]['SortNumber']=4
        with self.assertRaises(ValueError):await run(self.c,self.folder,'zuruecksetzen')
        self.assertEqual(self.c.http.patch.await_count,1)

    async def test_additional_default_assignment_blocks_naive_restore(self):
        await run(self.c,self.folder,'vorbereiten')
        original_patch=self.c.http.patch.side_effect
        async def patch(url,**kwargs):
            result=await original_patch(url,**kwargs)
            row=copy.deepcopy(self.rows[0])
            row.update(SalesChannelId='1-1-1',SortNumber=5)
            self.rows.append(row)
            return result
        self.c.http.patch.side_effect=patch
        result=await run(self.c,self.folder,'ausfuehren')
        self.assertEqual(result['zustand'],'ABWEICHUNG')
        with self.assertRaises(ValueError):await run(self.c,self.folder,'zuruecksetzen')
        self.assertEqual(self.c.http.patch.await_count,1)
