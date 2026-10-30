import base64
import copy
import os
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch, Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
import httpx

from app import bilder_bruecke as bridge, bilder_speicher as store
from app.bilder_upload import sichern, auftraege
from bridge.worker import Journal, run_job
from bridge.sql import Database, shape, targets

ID = '00000000-0000-0000-0000-000000000001'
WORKER = '00000000-0000-0000-0000-000000000002'
OTHER = '00000000-0000-0000-0000-000000000003'


def image():
    out = BytesIO()
    Image.new('RGB', (30, 30), 'blue').save(out, 'PNG')
    return out.getvalue()


class QueueTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {'BILDER_DIR': self.tmp.name,
            'BILDER_BRUECKE_AKTIV': '1', 'BILDER_BRUECKE_TOKEN': 'x' * 40})
        self.env.start()
        app = FastAPI()
        app.include_router(bridge.router)
        self.client = TestClient(app)
        self.headers = {'Authorization': 'Bearer ' + 'x' * 40}
        self.job = {'id': ID, 'artikel': ID, 'sku': '1036', 'api_ziel': 'https://example.org/api/eazybusiness',
                    'v1_id': 2488, 'v1_vorher': [[40, 2488, '2-2-1', '', 1]],
                    'vorher_vorschau': '', 'dateiname': 'krautl-' + ID + '.png',
                    'status': 'sendet', 'revision': 0, 'bruecke': True}
        store.zwischenstand({'id': ID, 'bilder': []}, 0, self.job['api_ziel'])
        sichern(self.job, image())

    def tearDown(self):
        self.client.close()
        self.env.stop()
        self.tmp.cleanup()

    def poll(self, worker=WORKER):
        return self.client.post('/bilder-bruecke/poll', json={'worker': worker}, headers=self.headers)

    def test_separate_token_required_even_with_cookie(self):
        self.assertEqual(self.client.post('/bilder-bruecke/poll', json={'worker': WORKER},
            headers={'Cookie': 'session=fake'}).status_code, 401)
        with patch.dict(os.environ, {'BILDER_BRUECKE_AKTIV': '0'}):
            self.assertEqual(self.poll().status_code, 401)

    def test_claim_is_persistent_and_not_reassigned(self):
        self.assertEqual(self.poll().json()['auftrag']['bruecke_lieferungen'], 1)
        self.assertIsNone(self.poll(OTHER).json()['auftrag'])
        self.assertEqual(self.poll().json()['auftrag']['bruecke_lieferungen'], 2)
        bridge.bereit()

    def test_hidden_or_revised_article_never_delivered(self):
        with store.datenbank() as db:
            db.execute('UPDATE artikel SET revision=1 WHERE id=?', (ID,))
        self.assertIsNone(self.poll().json()['auftrag'])
        self.assertEqual(auftraege()[0]['status'], 'unklar')

    def test_worker_cannot_complete_someone_elses_job(self):
        self.poll()
        r = self.client.post('/bilder-bruecke/ergebnis', headers=self.headers,
            json={'worker': OTHER, 'auftrag': ID, 'erfolgreich': True, 'bild': 2731})
        self.assertEqual(r.status_code, 409)

    def test_failure_is_not_requeued(self):
        self.poll()
        r = self.client.post('/bilder-bruecke/ergebnis', headers=self.headers,
            json={'worker': WORKER, 'auftrag': ID, 'erfolgreich': False})
        self.assertEqual(r.json()['status'], 'unklar')
        self.assertIsNone(self.poll().json()['auftrag'])

    def test_no_false_success_on_readback_failure(self):
        self.poll()
        with patch('app.bilder_bruecke.bestaetigen', side_effect=ValueError('not confirmed')):
            r = self.client.post('/bilder-bruecke/ergebnis', headers=self.headers,
                json={'worker': WORKER, 'auftrag': ID, 'erfolgreich': True, 'bild': 2731})
        self.assertEqual(r.json()['status'], 'unklar')
        self.assertIsNotNone(self.poll().json()['auftrag'])


class WorkerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.journal = Journal(Path(self.tmp.name) / 'jobs.sqlite3')
        self.job = {'id': ID, 'sku': '1036', 'datei': base64.b64encode(image()).decode(),
                    'bruecke_lieferungen': 1}
        self.sql = Mock()
        self.sql.prepare.return_value = {'original': 'backup'}
        self.sql.discover.return_value = {'image': 2731}
        self.api = Mock()

    def tearDown(self):
        self.journal.db.close()
        self.tmp.cleanup()

    def runjob(self):
        return run_job(self.job, self.sql, self.api, self.journal, ['1036'])

    def test_success_and_repeat_do_not_duplicate_any_write(self):
        self.assertTrue(self.runjob()['erfolgreich'])
        self.job['bruecke_lieferungen'] += 1
        self.assertTrue(self.runjob()['erfolgreich'])
        self.api.upload.assert_called_once()
        self.sql.replace.assert_called_once()

    def test_lost_upload_response_can_be_read_back(self):
        self.api.upload.side_effect = httpx.ReadTimeout('lost')
        self.assertTrue(self.runjob()['erfolgreich'])
        self.api.upload.assert_called_once()

    def test_uncertain_import_never_replayed(self):
        self.sql.discover.side_effect = ValueError('not yet found')
        with self.assertRaises(ValueError): self.runjob()
        self.sql.discover.side_effect = None
        self.assertTrue(self.runjob()['erfolgreich'])
        self.api.upload.assert_called_once()

    def test_lost_sql_commit_only_reads_on_resume(self):
        self.sql.replace.side_effect = ConnectionError('commit response lost')
        self.sql.confirm.side_effect = [ValueError('not yet visible'), None]
        with self.assertRaises(ValueError): self.runjob()
        self.assertTrue(self.runjob()['erfolgreich'])
        self.sql.replace.assert_called_once()

    def test_missing_journal_refuses_old_delivery(self):
        self.job['bruecke_lieferungen'] = 2
        with self.assertRaises(ValueError): self.runjob()
        self.api.upload.assert_not_called()
        self.sql.replace.assert_not_called()

    def test_changed_payload_and_unapproved_sku_refused(self):
        self.runjob()
        self.job['sku'] = 'OTHER'
        with self.assertRaises(ValueError): self.runjob()
        self.job['sku'] = '1036'
        self.job['datei'] += 'AAAA'
        with self.assertRaises(ValueError): self.runjob()

    def test_sql_target_preserves_ids_accounts_positions_and_pos(self):
        rows = [[1,40,2488,2,1,0,1,0,'name','a'],
                [2,40,2488,30,0,1,1,0,'name','b'],
                [3,40,2488,30,0,2,2,0,'name','c'],
                [4,40,2488,7,8,0,1,0,'name','d'],
                [5,40,2365,2,1,0,2,0,'name','e']]
        result = Database({}).expected({'v1_id': 2488}, {'rows': rows}, {'image': 2731})
        self.assertEqual([r[2] for r in result], [2731,2731,2731,2488,2365])
        for old, new in zip(rows,result):
            self.assertEqual(old[:2]+old[3:], new[:2]+new[3:])
        self.assertEqual(len(targets(rows,2488)),3)

    def test_sql_commit_contains_receipt_and_native_ebay_update(self):
        adapter=Database({})
        adapter.preflight=Mock()
        db=Mock();cur=db.cursor.return_value
        adapter.connect=Mock(return_value=db)
        cur.fetchone.side_effect=[None, (0,), (0,)]
        before={'article':40,'rows':[[1,40,2488,30,0,2,2,0,'name','v']],
                'original':base64.b64encode(image()).decode(),'seo':[]}
        imported={'image':2731,'rows':before['rows']+[[2,40,2731,2,1,0,1,0,'','w']],
                  'added':[[2,40,2731,2,1,0,1,0,'','w']]}
        job={**self.job,'v1_id':2488}
        adapter.rows=Mock(side_effect=[imported['rows'],adapter.expected(job,before,imported)])
        adapter.seo=Mock(return_value=[]);adapter.data=Mock(return_value=image())
        adapter.replace(job,before,imported)
        statements=[call.args[0] for call in cur.execute.call_args_list]
        self.assertTrue(any('EXEC dbo.spUpdateEbayBilderLaufendGeplant' in s for s in statements))
        self.assertTrue(any('INSERT INTO KrautlBilddienst.Auftrag' in s for s in statements))
        self.assertFalse(any('DELETE FROM dbo.tBild ' in s for s in statements))
        db.commit.assert_called_once();db.rollback.assert_not_called()

    def test_concurrent_sql_change_rolls_back_without_assignment_writes(self):
        adapter=Database({});adapter.preflight=Mock()
        db=Mock();cur=db.cursor.return_value;cur.fetchone.return_value=None
        adapter.connect=Mock(return_value=db);adapter.rows=Mock(return_value=['changed'])
        with self.assertRaises(ValueError):
            adapter.replace(self.job,{'article':40},{'rows':[]})
        db.rollback.assert_called_once();db.commit.assert_not_called()
        self.assertFalse(any(call.args[0].startswith(('DELETE','UPDATE')) for call in cur.execute.call_args_list))


if __name__ == '__main__':
    unittest.main()
