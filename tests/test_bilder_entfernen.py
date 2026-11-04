import base64
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from bridge.sql import Database
from bridge.worker import Journal, run_job
from app.bilder_entfernen import ziel

class RemovalTest(unittest.TestCase):
 def setUp(self):
  self.job={'id':'00000000-0000-0000-0000-000000000001','sku':'1036','operation':'entfernen_shop','v1_id':10,'bruecke_lieferungen':1}
  self.before={'article':40,'original':base64.b64encode(b'original').decode(),'rows':[[1,40,10,2,1,0,1,0,'a','v'],[2,40,20,2,1,0,2,0,'b','v'],[3,40,10,1,0,0,3,0,'a','v']],'seo':[[1,1,1,'alt','v'],[2,3,1,'other','v']]}
 def test_target_preserves_other_channels_and_last_image(self):
  d=Database({});removed,rows,seo=d.removal_expected(self.job,self.before)
  self.assertEqual(removed[0],1);self.assertEqual(rows[0][6],1)
  self.assertEqual(rows[1],self.before['rows'][2]);self.assertEqual(seo,[self.before['seo'][1]])
  self.assertEqual(ziel([[40,10,'2-2-1','',1]],10),[])
  self.assertEqual(ziel([[40,10,'2-2-1','',1],[40,10,'1-1-1','',3],[40,20,'2-2-1','',2]],10),[[40,10,'1-1-1','',3],[40,20,'2-2-1','',1]])
 def test_commit_preserves_blob_and_receipt_atomic(self):
  d=Database({});d.preflight=Mock();db=Mock();d.connect=Mock(return_value=db)
  db.cursor.return_value.fetchone.side_effect=[None,(0,)]
  _,rows,seo=d.removal_expected(self.job,self.before)
  d.rows=Mock(side_effect=[self.before['rows'],rows]);d.seo=Mock(side_effect=[self.before['seo'],seo]);d.data=Mock(return_value=b'original')
  d.remove_shop(self.job,self.before)
  statements=[c.args[0] for c in db.cursor.return_value.execute.call_args_list]
  self.assertTrue(any('INSERT INTO KrautlBilddienst.Auftrag' in s for s in statements))
  self.assertFalse(any('DELETE FROM dbo.tBild ' in s for s in statements))
  db.commit.assert_called_once();db.rollback.assert_not_called()
 def test_original_loss_rolls_back(self):
  d=Database({});d.preflight=Mock();db=Mock();d.connect=Mock(return_value=db)
  db.cursor.return_value.fetchone.side_effect=[None,(0,)]
  _,rows,seo=d.removal_expected(self.job,self.before)
  d.rows=Mock(side_effect=[self.before['rows'],rows]);d.seo=Mock(side_effect=[self.before['seo'],seo]);d.data=Mock(side_effect=[b'original',b'changed'])
  with self.assertRaises(ValueError):d.remove_shop(self.job,self.before)
  db.commit.assert_not_called();db.rollback.assert_called_once()
 def test_uncertain_commit_never_deletes_twice_or_uploads(self):
  with tempfile.TemporaryDirectory() as folder:
   journal=Journal(Path(folder)/'journal.sqlite');sql=Mock();api=Mock()
   sql.prepare.return_value=self.before;sql.remove_shop.side_effect=ConnectionError()
   sql.confirm_removal.side_effect=[ValueError('unknown'),None]
   with self.assertRaises(ValueError):run_job(self.job,sql,api,journal,['1036'])
   self.job['bruecke_lieferungen']=2
   self.assertTrue(run_job(self.job,sql,api,journal,['1036'])['erfolgreich'])
   sql.remove_shop.assert_called_once();api.upload.assert_not_called();sql.replace.assert_not_called()
   journal.db.close()

from tests import test_bilder_ersetzen as fixtures
A,B,J,URL=fixtures.A,fixtures.B,fixtures.J,fixtures.URL
from unittest.mock import patch
import os
from app.bilder_upload import auftraege
from app import bilder_speicher as store
from app.bilder_entfernen import beauftragen,bestaetigen

class RemovalIntegrationTest(unittest.IsolatedAsyncioTestCase):
 setUp=fixtures.ReplaceTest.setUp
 tearDown=fixtures.ReplaceTest.tearDown
 client=fixtures.ReplaceTest.client
 response=fixtures.ReplaceTest.response
 async def test_remove_queue_and_confirm_last_shop_image(self):
  with patch.dict(os.environ,{'BILDER_BRUECKE_AKTIV':'1','BILDER_BRUECKE_SKUS':'X'}),patch('app.bilder_entfernen.bereit'):
   async with self.client() as c:
    result=await beauftragen(c,A,B,0,J,'user')
    self.assertEqual(result['status'],'sendet')
    self.assertTrue(all(m=='GET' for m in self.calls))
    self.assertEqual(len(auftraege()),1)
    repeated=await beauftragen(c,A,B,0,J,'user')
    self.assertEqual(result,repeated)
    job=auftraege()[0];job['bruecke_bestaetigt']=True
    with self.assertRaises(ValueError):await bestaetigen(c,job)
    self.rows=[r for r in self.rows if r['SalesChannelId']!='2-2-1']
    result=await bestaetigen(c,job)
    self.assertEqual(result['status'],'wawi')
    self.assertEqual(store.lesen()['artikel'][0]['bilder'],[])
    self.assertTrue(all(m=='GET' for m in self.calls))
 async def test_disabled_bridge_cannot_queue_removal(self):
  with patch.dict(os.environ,{'BILDER_BRUECKE_AKTIV':'0'}):
   async with self.client() as c:
    with self.assertRaises(ValueError):await beauftragen(c,A,B,0,J,'user')
    self.assertEqual(auftraege(),[]);self.assertEqual(self.calls,[])
