import copy
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
import httpx
from scripts.teste_bilder_cloud_v1 import run, TENANT, target

class TestCloudV1(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.rows = [{"ItemId":40,"ImageId":i,"SalesChannelId":c,"SortNumber":p,"Filename":"original"}
            for i,c,p in [(2729,"2-2-1",1),(2365,"2-2-1",2),(2365,"6-51-0",2)]]
        async def get(url, **kw):
            return httpx.Response(200,json=copy.deepcopy(self.rows) if url.endswith('/images') else {"Id":40,"SKU":"1036"})
        async def patch(url, **kw):
            self.assertEqual(len(list(self.folder.glob('*.intent.json'))), self.client.http.patch.await_count)
            self.assertEqual(kw['json'], {"SalesChannelId":"2-2-1","SortNumber":1})
            self.rows = target(self.rows)
            return httpx.Response(200)
        self.client = SimpleNamespace(tenant_id=TENANT,_token=AsyncMock(return_value='token'),
            http=SimpleNamespace(get=AsyncMock(side_effect=get),patch=AsyncMock(side_effect=patch)))

    async def test_roundtrip_and_intent_precedes_write(self):
        original=copy.deepcopy(self.rows)
        await run(self.client,self.folder,'vorbereiten')
        self.client.http.patch.assert_not_called()
        self.assertTrue((await run(self.client,self.folder,'ausfuehren'))['bestaetigt'])
        self.assertTrue((await run(self.client,self.folder,'zuruecksetzen'))['bestaetigt'])
        self.assertEqual(original,self.rows)
        with self.assertRaises(ValueError): await run(self.client,self.folder,'ausfuehren')
        self.assertEqual(self.client.http.patch.await_count,2)

    async def test_timeout_after_effect_readback_no_repeat(self):
        await run(self.client,self.folder,'vorbereiten')
        async def patch(*args,**kwargs):
            self.rows=target(self.rows)
            raise httpx.ReadTimeout('lost')
        self.client.http.patch.side_effect=patch
        self.assertTrue((await run(self.client,self.folder,'ausfuehren'))['bestaetigt'])
        with self.assertRaises(ValueError): await run(self.client,self.folder,'ausfuehren')
        self.assertEqual(self.client.http.patch.await_count,1)

    async def test_noop_200_is_not_success(self):
        await run(self.client,self.folder,'vorbereiten')
        self.client.http.patch.side_effect=None
        self.client.http.patch.return_value=httpx.Response(200)
        self.assertFalse((await run(self.client,self.folder,'ausfuehren'))['bestaetigt'])
        with self.assertRaises(ValueError): await run(self.client,self.folder,'zuruecksetzen')
        self.assertEqual(self.client.http.patch.await_count,1)

    async def test_external_change_blocks_write_and_restore(self):
        await run(self.client,self.folder,'vorbereiten')
        self.rows[2]['SortNumber']=7
        with self.assertRaises(ValueError): await run(self.client,self.folder,'ausfuehren')
        self.client.http.patch.assert_not_called()
        self.rows[2]['SortNumber']=2
        await run(self.client,self.folder,'ausfuehren')
        self.rows[2]['Filename']='changed'
        with self.assertRaises(ValueError): await run(self.client,self.folder,'zuruecksetzen')
        self.assertEqual(self.client.http.patch.await_count,1)

    async def test_stale_plan_and_wrong_tenant_block(self):
        await run(self.client,self.folder,'vorbereiten')
        p=self.folder/'plan.json';data=json.loads(p.read_text());data['created']='2000-01-01T00:00:00+00:00';p.write_text(json.dumps(data))
        with self.assertRaises(ValueError): await run(self.client,self.folder,'ausfuehren')
        self.client.tenant_id='other'
        with self.assertRaises(ValueError): await run(self.client,self.folder,'vorbereiten')
        self.client.http.patch.assert_not_called()

    async def test_duplicate_shop_image_blocks_preparation(self):
        self.rows[1]['ImageId']=2729
        with self.assertRaises(ValueError): await run(self.client,self.folder,'vorbereiten')
        self.client.http.patch.assert_not_called()
