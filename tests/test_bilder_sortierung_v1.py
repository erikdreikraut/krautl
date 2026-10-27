import copy
import json
import os
import tempfile
import unittest
from unittest.mock import patch
import httpx
from app import bilder_speicher as store
from app.bilder_upload import sichern, auftraege
from app.jtl_onprem import OnPremClient
from scripts.repariere_bildreihenfolge_v1 import ausfuehren, schritt

A="770f139d-18dd-405c-9f84-3221e3000000"
URL="https://wawi.test/api/eazybusiness"


def image(n):
    return {"blobIdentifier":f"00000000-0000-0000-0000-{n:012d}","sortNumber":n,"isMainImage":n==1}


class V1OrderTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.env=patch.dict(os.environ,{"BILDER_DIR":self.temp.name});self.env.start()
        self.before={"defaultImages":[image(i) for i in (1,2,3)],"platformImages":[],"ebayImages":[],
                     "saleschannelImages":[{"saleschannelId":"2-2-1","images":[image(i) for i in (1,2,3)]}]}
        self.target=copy.deepcopy(self.before)
        self.target["saleschannelImages"][0]["images"]=[image(i) for i in (1,3,2)]
        for n,b in enumerate(self.target["saleschannelImages"][0]["images"],1):b["sortNumber"]=n
        self.current=copy.deepcopy(self.before)
        self.rows=[{"ItemId":227,"ImageId":100+i,"SalesChannelId":"2-2-1","SortNumber":i} for i in (1,2,3)]
        self.job={"id":"job","sku":"30501-002","artikel":A,"api_ziel":URL,"art":"reihenfolge",
                  "status":"unklar","revision":0,"vorher":self.before,"ziel":self.target}
        row={"id":A,"sku":"30501-002","bilder":[{"id":b["blobIdentifier"],"position":b["sortNumber"],"hauptbild":b["isMainImage"]} for b in self.before["defaultImages"]]}
        store.zwischenstand(row,0,URL);sichern(self.job,b"")
        self.calls=[];self.timeout=False;self.reject=False

    async def asyncTearDown(self):
        self.env.stop();self.temp.cleanup()

    def transport(self,req):
        self.calls.append(req.method)
        if req.method=="GET":
            if "/v1/" in req.url.path:return httpx.Response(200,json=self.rows)
            return httpx.Response(200,json={"id":A,"identifiers":{"sku":"30501-002"},"images":self.current})
        self.assertEqual(req.method,"PATCH")
        self.assertTrue(req.url.path.endswith("/images/103"))
        self.assertEqual(json.loads(req.content),{"SalesChannelId":"2-2-1","SortNumber":2})
        self.assertIn("v1_sortierversuch",auftraege()[0])
        if self.reject:return httpx.Response(400,json={"Detail":"rejected"})
        self.current=copy.deepcopy(self.target)
        if self.timeout:raise httpx.ReadTimeout("lost",request=req)
        return httpx.Response(201,json={})

    async def run_step(self):
        async with OnPremClient(URL,"secret",transport=httpx.MockTransport(self.transport)) as c:
            return await ausfuehren(c,auftraege()[0],lambda *a:None)

    async def test_single_write_readback_confirms_and_rerun_never_replays(self):
        self.assertEqual((await self.run_step())["status"],"wawi")
        self.assertEqual((await self.run_step())["status"],"wawi")
        self.assertEqual(self.calls.count("PATCH"),1)
        self.assertEqual([b["id"] for b in store.lesen()["artikel"][0]["bilder"]],
                         [image(i)["blobIdentifier"] for i in (1,3,2)])

    async def test_timeout_reconciles_without_replay(self):
        self.timeout=True
        self.assertEqual((await self.run_step())["status"],"wawi")
        self.assertEqual(self.calls.count("PATCH"),1)

    async def test_rejection_remains_unclear_and_rerun_only_reads(self):
        self.reject=True
        self.assertEqual((await self.run_step())["status"],"unklar")
        await self.run_step()
        self.assertEqual(self.calls.count("PATCH"),1)

    async def test_changed_state_prevents_write(self):
        self.current["defaultImages"][0]["sortNumber"]=9
        with self.assertRaisesRegex(ValueError,"weder Ausgang noch Ziel"):await self.run_step()
        self.assertNotIn("PATCH",self.calls)

    async def test_ambiguous_v1_mapping_prevents_write(self):
        self.rows.append({"ItemId":227,"ImageId":999,"SalesChannelId":"2-2-1","SortNumber":2})
        with self.assertRaises(ValueError):await self.run_step()
        self.assertNotIn("PATCH",self.calls)

    def test_main_image_change_and_unrelated_channel_changes_rejected(self):
        target=copy.deepcopy(self.target)
        target["defaultImages"][0]["sortNumber"]=9
        with self.assertRaises(ValueError):schritt(self.before,target,self.rows)
        target=copy.deepcopy(self.target)
        target["saleschannelImages"][0]["images"].reverse()
        for n,b in enumerate(target["saleschannelImages"][0]["images"],1):b.update(sortNumber=n,isMainImage=n==1)
        with self.assertRaises(ValueError):schritt(self.before,target,self.rows)
