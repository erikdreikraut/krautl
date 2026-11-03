import base64
import copy
import json
import os
import tempfile
import unittest
from io import BytesIO
from unittest.mock import patch
import httpx
from PIL import Image
from app import bilder_speicher as store
from app.bilder_upload import uebertragen, auftraege
from app.jtl_onprem import OnPremClient
from app.bilder_ersetzen import zuordnungen

A="00000000-0000-0000-0000-000000000001"
URL="https://wawi.test/api/eazybusiness"

class AddV1Test(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.env=patch.dict(os.environ,{"BILDER_DIR":self.tmp.name});self.env.start()
        b=BytesIO();Image.new("RGB",(300,250),"red").save(b,"PNG");self.raw=b.getvalue()
        self.rows=[];self.posts=0;self.foreign=False
        store.zwischenstand({"id":A,"sku":"X","bilder":[]},0,URL)

    async def asyncTearDown(self):
        self.env.stop();self.tmp.cleanup()

    def transport(self,req):
        if req.method=="GET":
            if "imagedata" in req.url.path:return httpx.Response(200,content=self.raw,headers={"content-type":"image/png"})
            if "/v1/" in req.url.path:return httpx.Response(200,json=self.rows)
            # v2 omits the newly imported blob identifier, exactly as the live API.
            images={"defaultImages":[],"platformImages":[],"ebayImages":[],"saleschannelImages":[]}
            if self.posts:images["defaultImages"]=[{"sortNumber":1,"isMainImage":True}]
            return httpx.Response(200,json={"id":A,"identifiers":{"sku":"X"},"images":images})
        self.assertEqual(req.method,"POST")
        self.assertEqual(len(auftraege()),1)
        self.posts+=1
        pos=1+max((r["SortNumber"] for r in self.rows if r["SalesChannelId"]=="2-2-1"),default=0)
        # Existing global image ID, e.g. already used by the parent: no new blob ID required.
        self.rows += [{"ItemId":42,"ImageId":2734,"SalesChannelId":ch,"SortNumber":pos} for ch in ("2-2-1","1-1-1")]
        if self.foreign:self.rows.append({"ItemId":42,"ImageId":999,"SalesChannelId":"amazon","SortNumber":1})
        return httpx.Response(201,json={})

    async def run_upload(self):
        async with OnPremClient(URL,"secret",transport=httpx.MockTransport(self.transport)) as c:
            return await uebertragen(c,A,None,0,"job",self.raw,"user")

    async def test_empty_article_confirms_despite_missing_v2_blob_and_never_reuploads(self):
        self.assertEqual((await self.run_upload())["status"],"wawi")
        self.assertEqual((await self.run_upload())["status"],"wawi")
        self.assertEqual(self.posts,1)
        a=store.lesen()["artikel"][0]
        self.assertEqual(a["bilder"][0]["v1_id"],2734)
        self.assertEqual(a["bild_api"],"v1")

    async def test_shared_image_added_after_existing_picture(self):
        self.rows=[{"ItemId":42,"ImageId":2707,"SalesChannelId":"2-2-1","SortNumber":1}]
        store.zwischenstand({"id":A,"sku":"X","bild_api":"v1","bilder":[{"id":"old","v1_id":2707,"position":1,"hauptbild":True}]},0,URL)
        self.assertEqual((await self.run_upload())["status"],"wawi")
        self.assertEqual([b["v1_id"] for b in store.lesen()["artikel"][0]["bilder"]],[2707,2734])

    async def test_unrelated_change_stays_blocked_without_repeat(self):
        self.foreign=True
        self.assertEqual((await self.run_upload())["status"],"unklar")
        await self.run_upload()
        self.assertEqual(self.posts,1)

    def test_empty_list_allowed_but_mixed_items_rejected(self):
        self.assertEqual(zuordnungen([]),[])
        with self.assertRaises(ValueError):
            zuordnungen([{"ItemId":i,"ImageId":7,"SalesChannelId":"2-2-1","SortNumber":1} for i in (1,2)])
