import os
import json
import base64
import tempfile
import unittest
from io import BytesIO
from unittest.mock import patch
import httpx
from PIL import Image
from app import bilder_speicher as store
from app.bilder_upload import uebertragen, pruefen, auftraege, datei_pruefen, bildblock
from app.bilder_abgleich import vorschaubild
from app.jtl_onprem import OnPremClient

A="00000000-0000-0000-0000-000000000001"
OLD="00000000-0000-0000-0000-000000000002"
NEW="00000000-0000-0000-0000-000000000003"
JOB="00000000-0000-0000-0000-000000000004"
URL="https://wawi.test/api/eazybusiness"


def img(bid,pos=1,main=True):
    return {"blobIdentifier":bid,"sortNumber":pos,"isMainImage":main}


class BildUploadTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.env=patch.dict(os.environ,{"BILDER_DIR":self.temp.name})
        self.env.start()
        buf=BytesIO();Image.new("RGB",(300,250),"red").save(buf,"PNG")
        self.raw=buf.getvalue();self.sent=None;self.calls=[];self.timeout=False;self.reject=False
        self.detail={"id":A,"identifiers":{"sku":"X"},"images":{"defaultImages":[img(OLD)],"platformImages":[],"ebayImages":[],
            "saleschannelImages":[{"saleschannelId":"2-2-1","images":[img(OLD)]},{"saleschannelId":"amazon","images":[img(OLD)]}]}}
        row={"id":A,"sku":"X","name":"Test","parent_id":None,"bilder":[{"id":OLD,"position":1,"hauptbild":True,"thumb":store.thumb_speichern(vorschaubild(self.raw)),"fehler":None}]}
        store.zwischenstand(row,0,URL)

    async def asyncTearDown(self):
        self.env.stop();self.temp.cleanup()

    def transport(self,req):
        self.calls.append((req.method,req.url.path))
        path=req.url.path.removeprefix("/api/eazybusiness")
        if req.method=="GET" and path=="/v2/items/"+A:
            return httpx.Response(200,json=self.detail)
        if req.method=="GET" and path=="/v1/items/"+A+"/images":
            return httpx.Response(200,json=[])
        if req.method=="GET" and path=="/v2/items/image-data/"+NEW:
            return httpx.Response(200,json=base64.b64encode(self.sent).decode())
        if req.method=="POST":
            body=json.loads(req.content)
            self.assertEqual(body["SalesChannelId"],"2-2-1")
            self.assertTrue(body["Filename"].isascii())
            if self.reject:return httpx.Response(403)
            self.sent=base64.b64decode(body["ImageData"])
            self.detail["images"]["saleschannelImages"][0]["images"].append(img(NEW,2,False))
            return httpx.Response(201,json={"ImageId":123})
        if req.method=="PATCH":
            body=json.loads(req.content)
            self.assertEqual(set(body),{"images"})
            self.assertEqual(body["images"]["defaultImages"],[img(OLD)])
            self.assertEqual(body["images"]["saleschannelImages"][1]["images"],[img(OLD)])
            self.detail["images"]=body["images"]
            if self.timeout:raise httpx.ReadTimeout("lost",request=req)
            return httpx.Response(200,json={"item":self.detail})
        raise AssertionError((req.method,path))

    def client(self):
        return OnPremClient(URL,"test",transport=httpx.MockTransport(self.transport))

    async def test_replace_preserves_shared_binary_and_all_other_channels(self):
        async with self.client() as c:
            result=await uebertragen(c,A,OLD,0,JOB,self.raw,"erik")
            self.assertEqual(result["status"],"wawi",result)
            self.assertEqual(self.detail["images"]["saleschannelImages"][0]["images"],[img(NEW)])
            await uebertragen(c,A,OLD,0,JOB,self.raw,"erik")
        self.assertEqual(sum(m=="POST" for m,p in self.calls),1)
        self.assertEqual(store.lesen()["artikel"][0]["bilder"][0]["id"],NEW)
        self.assertFalse(any(m=="DELETE" for m,p in self.calls))

    async def test_append_retains_existing_order_and_main_image(self):
        async with self.client() as c:
            result=await uebertragen(c,A,None,0,JOB,self.raw,"micha")
        self.assertEqual(result["status"],"wawi")
        self.assertEqual(self.detail["images"]["saleschannelImages"][0]["images"],[img(OLD),img(NEW,2,False)])

    async def test_lost_patch_response_only_reads_back_never_replays(self):
        self.timeout=True
        async with self.client() as c:
            result=await uebertragen(c,A,OLD,0,JOB,self.raw,"erik")
            self.assertEqual(result["status"],"unklar")
            result=await pruefen(c,auftraege()[0])
            self.assertEqual(result["status"],"wawi")
        self.assertEqual(sum(m=="PATCH" for m,p in self.calls),1)

    async def test_rejected_upload_is_explicit_and_same_request_is_not_replayed(self):
        self.reject=True
        async with self.client() as c:
            result=await uebertragen(c,A,OLD,0,JOB,self.raw,"erik")
            self.assertEqual(result["status"],"abgelehnt")
            self.assertIn("403",result["meldung"])
            await uebertragen(c,A,OLD,0,JOB,self.raw,"erik")
        self.assertEqual(sum(m=="POST" for m,p in self.calls),1)

    async def test_stale_hidden_and_invalid_file_never_write(self):
        async with self.client() as c:
            with self.assertRaises(ValueError):await uebertragen(c,A,OLD,1,JOB,self.raw,"erik")
            with self.assertRaises(ValueError):await uebertragen(c,A,OLD,0,JOB,b"not an image","erik")
            store.ausblenden(A,True,0,"erik")
            with self.assertRaises(ValueError):await uebertragen(c,A,OLD,1,JOB,self.raw,"erik")
        self.assertEqual(self.calls,[])


    async def test_concurrent_channel_change_stops_before_assignment(self):
        original=self.transport
        def changed(req):
            result=original(req)
            if req.method=="POST":
                self.detail["images"]["saleschannelImages"][1]["images"][0]["sortNumber"]=9
            return result
        async with OnPremClient(URL,"test",transport=httpx.MockTransport(changed)) as c:
            result=await uebertragen(c,A,OLD,0,JOB,self.raw,"erik")
        self.assertEqual(result["status"],"unklar")
        self.assertFalse(any(m=="PATCH" for m,p in self.calls))
        self.assertEqual(self.detail["images"]["saleschannelImages"][1]["images"][0]["sortNumber"],9)


    def order_fixture(self):
        self.detail["images"]["saleschannelImages"][0]["images"].append(img(NEW,2,False))
        a=store.lesen()["artikel"][0]
        a["bilder"].append({**a["bilder"][0],"id":NEW,"position":2,"hauptbild":False})
        store.zwischenstand(a,0,URL)
        return [{"id":b["id"],"position":b["position"],"hauptbild":b["hauptbild"]} for b in a["bilder"]]

    async def test_reorder_sets_first_main_preserves_channels_without_loading_images(self):
        from app.bilder_upload import umordnen
        before=self.order_fixture()
        async with self.client() as c:
            result=await umordnen(c,A,0,JOB,[NEW,OLD],before,"micha")
            self.assertEqual(result["status"],"wawi",result)
            await umordnen(c,A,0,JOB,[NEW,OLD],before,"micha")
        self.assertEqual(self.detail["images"]["saleschannelImages"][0]["images"],[img(NEW),img(OLD,2,False)])
        local=store.lesen()["artikel"][0]["bilder"]
        self.assertEqual([(b["id"],b["hauptbild"]) for b in local],[(NEW,True),(OLD,False)])
        self.assertEqual(sum(m=="PATCH" for m,p in self.calls),1)
        self.assertFalse(any(m=="POST" or "image-data" in p for m,p in self.calls))

    async def test_reorder_lost_response_is_reconciled_without_second_write(self):
        from app.bilder_upload import umordnen
        before=self.order_fixture();self.timeout=True
        async with self.client() as c:
            result=await umordnen(c,A,0,JOB,[NEW,OLD],before,"micha")
            self.assertEqual(result["status"],"unklar")
            self.assertEqual((await pruefen(c,auftraege()[0]))["status"],"wawi")
        self.assertEqual(sum(m=="PATCH" for m,p in self.calls),1)

    async def test_reorder_rejects_missing_duplicate_foreign_and_stale_images(self):
        from app.bilder_upload import umordnen
        before=self.order_fixture()
        async with self.client() as c:
            for ids in ([OLD],[NEW,NEW],[OLD,JOB]):
                with self.assertRaises(ValueError):await umordnen(c,A,0,JOB,ids,before,"micha")
            stale=[dict(b) for b in before];stale[0]["position"]=4
            with self.assertRaises(ValueError):await umordnen(c,A,0,JOB,[NEW,OLD],stale,"micha")
            self.detail["images"]["saleschannelImages"][0]["images"][0]["sortNumber"]=3
            with self.assertRaises(ValueError):await umordnen(c,A,0,JOB,[NEW,OLD],before,"micha")
        self.assertFalse(any(m!="GET" for m,p in self.calls))


    async def test_single_change_preserves_global_sync_status(self):
        from app.bilder_upload import umordnen
        before=self.order_fixture()
        store.status_setzen(status="ok",teilstand=False,letzter_erfolg="2026-10-26T09:00:00Z",fehler=None)
        original={k:store.lesen().get(k) for k in ("status","teilstand","letzter_erfolg","fehler")}
        async with self.client() as c:
            result=await umordnen(c,A,0,JOB,[NEW,OLD],before,"micha")
        self.assertEqual(result["status"],"wawi")
        self.assertEqual({k:store.lesen().get(k) for k in original},original)


    def test_channel_errors_identify_block_without_guessing_assignment(self):
        import copy
        bad=copy.deepcopy(self.detail)
        bad["images"]["platformImages"]=[{"images":[]}]
        with self.assertRaisesRegex(ValueError,"platformImages: platformId fehlt"):
            bildblock(bad)
        bad=copy.deepcopy(self.detail)
        bad["images"]["saleschannelImages"].append(copy.deepcopy(bad["images"]["saleschannelImages"][0]))
        with self.assertRaisesRegex(ValueError,"saleschannelImages: saleschannelId ist mehrfach"):
            bildblock(bad)


    async def test_reorder_preserves_repeated_non_shop_groups_exactly(self):
        import copy
        from app.bilder_upload import umordnen
        before=self.order_fixture()
        block=self.detail["images"]
        block["saleschannelImages"].extend([
            {"saleschannelId":"1-1-0","images":[img(OLD)]},
            {"saleschannelId":"1-1-0","images":[img(NEW,3,False)]},
        ])
        block["platformImages"]=[{"platformId":"platform","images":[img(OLD)]}]*2
        block["ebayImages"]=[{"ebayAccountId":"account","images":[img(OLD)]}]*2
        original=copy.deepcopy(block)
        async with self.client() as c:
            result=await umordnen(c,A,0,JOB,[NEW,OLD],before,"micha")
        self.assertEqual(result["status"],"wawi",result)
        actual=self.detail["images"]
        self.assertEqual(actual["saleschannelImages"][1:],original["saleschannelImages"][1:])
        for field in ("defaultImages","platformImages","ebayImages"):
            self.assertEqual(actual[field],original[field])
        self.assertEqual(actual["saleschannelImages"][0]["images"],[img(NEW),img(OLD,2,False)])
        self.assertEqual(sum(m=="PATCH" for m,p in self.calls),1)

    async def test_reorder_duplicate_shop_blocks_before_any_write(self):
        import copy
        from app.bilder_upload import umordnen
        before=self.order_fixture()
        self.detail["images"]["saleschannelImages"].append(
            copy.deepcopy(self.detail["images"]["saleschannelImages"][0]))
        async with self.client() as c:
            with self.assertRaisesRegex(ValueError,"saleschannelId ist mehrfach"):
                await umordnen(c,A,0,JOB,[NEW,OLD],before,"micha")
        self.assertFalse(any(m!="GET" for m,p in self.calls))
        self.assertEqual(auftraege(),[])
