import html
import json
import os
import tempfile
import time
import unittest
from io import BytesIO
from unittest.mock import patch
import httpx
from PIL import Image, ImageDraw
from app import bilder_shop as shop, bilder_speicher as store


def picture(color, shape=0):
    im=Image.new('RGB',(100,100),'white');d=ImageDraw.Draw(im)
    if shape:d.ellipse((10,10,90,90),fill=color)
    else:d.rectangle((20,10,80,90),fill=color)
    f=BytesIO();im.save(f,format='PNG');return f.getvalue()


def page(sku, images=(), variants=()):
    return '<span itemprop="sku">'+sku+'</span><div id="gallery"><div>'+''.join(
        '<img data-list="'+html.escape(json.dumps({'md':{'src':u}}),quote=True)+'">' for u in images
    )+'</div></div>'+''.join('<option data-ref="'+v+'"></option>' for v in variants)


class ShopTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.env=patch.dict(os.environ,{'BILDER_DIR':self.temp.name});self.env.start()
        self.raw=[picture('red'),picture('blue',1)]
        self.a={'id':'a','sku':'child','parent_id':'parent','bilder':[
            {'id':str(i),'thumb':store.thumb_speichern(raw),'position':i+1,'hauptbild':i==0} for i,raw in enumerate(self.raw)]}
        store.zwischenstand(self.a,0,'api');self.data=store.lesen();self.a=self.data['artikel'][0]
    def tearDown(self):self.env.stop();self.temp.cleanup()

    def test_match_reorder_missing_and_ambiguous(self):
        self.assertTrue(shop.vergleichen(self.raw,self.raw)[0])
        self.assertFalse(shop.vergleichen(self.raw,self.raw[::-1])[0])
        self.assertFalse(shop.vergleichen(self.raw,self.raw[:1])[0])
        self.assertFalse(shop.vergleichen([self.raw[0]]*2,[self.raw[0]]*2)[0])
        self.assertFalse(shop.vergleichen([self.raw[0]],[picture('green')])[0])

    def test_snapshot_expiry_target_and_position_invalidate(self):
        status={'signatur':shop.signatur(self.a,'api'),'status':'bestaetigt','zeit':time.time()}
        self.assertEqual(shop.aktuell(self.a,'api',status)['status'],'bestaetigt')
        self.assertEqual(shop.aktuell(self.a,'other',status)['status'],'wartet')
        self.assertEqual(shop.aktuell(self.a,'api',{**status,'zeit':time.time()-21601})['status'],'wartet')
        self.a['bilder'][0]['position']=3
        self.assertEqual(shop.aktuell(self.a,'api',status)['status'],'wartet')

    async def test_variant_discovery_uses_exact_sku_and_observed_id(self):
        calls=[]
        def response(req):
            calls.append(str(req.url));self.assertEqual(req.method,'GET')
            if req.url.path=='/old':return httpx.Response(404)
            if req.url.params.get('qs')=='parent':return httpx.Response(200,text=page('parent',variants=['227','228']))
            if req.url.params.get('a')=='227':return httpx.Response(200,text=page('wrong',['https://dreikraut.de/wrong.jpg']))
            if req.url.params.get('a')=='228':return httpx.Response(200,text=page('child',['https://dreikraut.de/image.jpg']))
            return httpx.Response(200,text='no product')
        async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as c:
            url,imgs=await shop.seite(c,self.a,[self.a,{'id':'parent','sku':'parent'}],'https://dreikraut.de/old')
        self.assertTrue(url.endswith('a=228'));self.assertEqual(imgs,['https://dreikraut.de/image.jpg'])

    async def test_redirect_off_origin_is_never_fetched(self):
        calls=[]
        def response(req):calls.append(str(req.url));return httpx.Response(302,headers={'location':'https://evil.test/x'})
        async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as c:
            with self.assertRaises(ValueError):await shop.laden(c,shop.ORIGIN,1000)
        self.assertEqual(len(calls),1)

    async def test_full_check_persists_and_failure_revokes_confirmation(self):
        broken=False
        def response(req):
            self.assertEqual(req.method,'GET')
            if req.url.path=='/':return httpx.Response(200,text=page('child',[shop.ORIGIN+'/0.jpg',shop.ORIGIN+'/1.jpg']))
            if broken:return httpx.Response(503)
            self.assertIn('krautl_check',req.url.params)
            return httpx.Response(200,content=self.raw[int(req.url.path[1])])
        async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as c:
            r=await shop.artikel_pruefen(c,self.a,self.data,{})
            self.assertEqual(r['status'],'bestaetigt');self.assertEqual(shop.staende()['a']['status'],'bestaetigt')
            broken=True
            await shop.artikel_pruefen(c,self.a,self.data,r)
        self.assertEqual(shop.staende()['a']['status'],'wartet')

    async def test_changed_snapshot_during_fetch_is_discarded(self):
        def response(req):
            if req.url.path=='/':return httpx.Response(200,text=page('child',[shop.ORIGIN+'/0.jpg',shop.ORIGIN+'/1.jpg']))
            store.ausblenden('a',True,0,'tester') if not store.lesen()['artikel'][0]['ausgeblendet'] else None
            return httpx.Response(200,content=self.raw[int(req.url.path[1])])
        async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as c:
            await shop.artikel_pruefen(c,self.a,self.data,{})
        self.assertEqual(shop.staende(),{})

    async def test_hidden_and_unresolved_jobs_are_not_checked(self):
        with patch('app.bilder_upload.auftraege',return_value=[{'artikel':'a','status':'unklar'}]),patch.object(shop,'artikel_pruefen') as check:
            await shop.durchlauf();check.assert_not_called()
        store.ausblenden('a',True,0,'tester')
        with patch('app.bilder_upload.auftraege',return_value=[]),patch.object(shop,'artikel_pruefen') as check:
            await shop.durchlauf();check.assert_not_called()

    def test_gallery_excludes_other_product_thumbnails(self):
        p=shop.Galerie();p.feed(page('child',[shop.ORIGIN+'/a.jpg'])+page('other',[]).replace('id="gallery"','id="other"'))
        self.assertEqual(p.anzahl,1);self.assertEqual(p.bilder,[shop.ORIGIN+'/a.jpg'])

    async def test_public_http_does_not_hold_wawi_lock(self):
        def response(req):
            with store.Laufsperre():
                pass
            if req.url.path=='/':return httpx.Response(200,text=page('child',[shop.ORIGIN+'/0.jpg',shop.ORIGIN+'/1.jpg']))
            return httpx.Response(200,content=self.raw[int(req.url.path[1])])
        async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as c:
            r=await shop.artikel_pruefen(c,self.a,self.data,{})
        self.assertEqual(r['status'],'bestaetigt')

    async def test_fresh_confirmation_is_not_refetched(self):
        shop.speichern('a',{'signatur':shop.signatur(self.a,'api'),'status':'bestaetigt','zeit':time.time()})
        with patch('app.bilder_upload.auftraege',return_value=[]),patch.object(shop,'artikel_pruefen') as check:
            await shop.durchlauf();check.assert_not_called()
