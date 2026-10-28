import json
import unittest
from io import BytesIO
import httpx
from PIL import Image
from app.bilder_abgleich import vorschaubild
from app.jtl_onprem import OnPremClient
from scripts.pruefe_bild_upload_zuordnung import hinweise, pixelgleich, untersuchen

class AuditTest(unittest.IsolatedAsyncioTestCase):
    def test_hints_never_expose_signed_urls(self):
        result=hinweise({'blobIdentifier':None,'sortNumber':3,'url':'https://secret.host/v2/file/00000000-0000-0000-0000-000000000003?sig=SECRET','filename':'C:/private/file.png'})
        text=json.dumps(result)
        self.assertNotIn('SECRET',text);self.assertNotIn('private',text);self.assertNotIn('secret.host',text)
        self.assertEqual(result['url']['pfad_uuids'],['00000000-0000-0000-0000-000000000003'])

    async def test_audit_reads_only_and_does_not_match_other_picture(self):
        def image(color):
            out=BytesIO();Image.new('RGB',(20,20),color).save(out,'PNG');return out.getvalue()
        raw=image('red');calls=[];output=[]
        def response(req):
            calls.append(req.method);self.assertEqual(req.method,'GET')
            if req.url.path.endswith('/items/a'):
                return httpx.Response(200,json={'id':'a','identifiers':{'sku':'S'},'images':{'defaultImages':[{'blobIdentifier':None,'sortNumber':1}]}})
            if req.url.path.endswith('/images'):
                return httpx.Response(200,json=[{'ItemId':10,'ImageId':i,'SalesChannelId':'2-2-1' if i==2 else 'amazon','SortNumber':1} for i in (1,2)])
            return httpx.Response(200,content=raw if req.url.path.endswith('/2') else image('blue'))
        async with OnPremClient('https://wawi.test/api/eazybusiness','test',transport=httpx.MockTransport(response)) as c:
            matches=await untersuchen(c,{'api_ziel':c.url,'artikel':'a','sku':'S','v1_id':1,
                'v1_vorher':[[10,1,'2-2-1','',1],[10,1,'amazon','',1]]},vorschaubild(raw),output.append)
        self.assertEqual(matches,[2]);self.assertEqual(len(calls),5)
        diff=next(json.loads(line) for line in output if line.startswith('{') and 'auftrags_bild' in line)
        self.assertEqual(diff['fehlt'],[[10,1,'2-2-1','',1]])
        self.assertEqual(diff['hinzu'],[[10,2,'2-2-1','',1]])
        self.assertTrue(any('"v1_bild": 1' in line and 'amazon' in line for line in output))
        self.assertTrue(pixelgleich(vorschaubild(raw),vorschaubild(raw)))
