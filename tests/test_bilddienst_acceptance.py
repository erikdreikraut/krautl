import base64
import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from bridge import acceptance as a
from bridge.worker import Journal
from tests.test_bilder_bruecke import image


class AcceptanceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.journal = Journal(Path(self.tmp.name)/'test.sqlite3')
        self.addCleanup(self.journal.db.close)
        self.rows = [[40, 2729, '2-2-1', '', 1], [40, 2729, '1-1-1', '', 4],
                     [40, 2365, '2-2-1', '', 2], [40, 2729, '9-7-8-0', '', 1]]
        self.rows.sort()
        sqlrows = [[1,40,2729,2,1,0,1,0,'name','a'],
                   [2,40,2729,1,0,0,4,0,'name','b'],
                   [3,40,2365,2,1,0,2,0,'name2','c'],
                   [4,40,2729,7,8,0,1,0,'pos','d']]
        raw = base64.b64encode(image()).decode()
        self.state = {'rows':sqlrows, 'seo':[[100,1,1,'alt','version']],
                      'files':{str(i):raw for i in [2048,2365,2729,2731,3000]}}
        self.changed = copy.deepcopy(self.state)
        for r in self.changed['rows'][:2]: r[2] = 3000
        self.after = copy.deepcopy(self.rows)
        for r in self.after:
            if r[1] == 2729 and r[2] != '9-7-8-0': r[1] = 3000
        self.after.sort()
        self.api = Mock(url='https://wawi.test/api/eazybusiness')
        self.sql = Mock()
        self.sql.prepare.return_value = {'rows':self.changed['rows'], 'original':'backup'}
        self.sql.expected.return_value = self.state['rows']

    def test_exact_comparison_retains_duplicate_aliases_positions_and_seo(self):
        baseline = {'api':self.rows,'sql':self.state}
        with patch.object(a,'verify_files'):
            a.verify_result(self.after,self.changed,baseline,3000)
            with self.assertRaises(ValueError):
                a.verify_result(self.after+self.after[:1],self.changed,baseline,3000)
            changed = copy.deepcopy(self.changed)
            changed['rows'][0][0] = 999
            with self.assertRaises(ValueError): a.verify_result(self.after,changed,baseline,3000)
            changed = copy.deepcopy(self.changed)
            changed['seo'] = []
            with self.assertRaises(ValueError): a.verify_result(self.after,changed,baseline,3000)

    def run_with_mocks(self, runner):
        with patch.object(a,'api_rows',side_effect=[self.rows,self.after,self.rows]), \
             patch.object(a,'sql_state',side_effect=[self.state,self.changed,self.state]), \
             patch.object(a,'verify_baseline'), patch.object(a,'verify_files'), \
             patch.object(a,'run_job',side_effect=runner):
            a.execute(self.sql,self.api,self.journal)

    def test_forward_intent_before_write_and_restore_intent_before_sql(self):
        def forward(*args):
            self.assertEqual(self.journal.get('abnahme-1036')['phase'],'austausch_beauftragt')
            return {'bild':3000,'erfolgreich':True}
        def restore(*args):
            self.assertEqual(self.journal.get('abnahme-1036')['phase'],'ruecknahme_beauftragt')
            self.assertEqual(args[2]['image'],2729)
            self.assertEqual(args[2]['added'],[])
        self.sql.replace.side_effect = restore
        self.run_with_mocks(forward)
        self.assertEqual(self.journal.get('abnahme-1036')['phase'],'original_wiederhergestellt')
        self.sql.replace.assert_called_once()
        self.api.upload.assert_not_called()  # Only production run_job may upload.

    def test_uncertain_forward_does_not_restore_or_repeat(self):
        with self.assertRaises(ConnectionError):
            self.run_with_mocks(lambda *args: (_ for _ in ()).throw(ConnectionError()))
        self.sql.replace.assert_not_called()
        with patch.object(a,'api_rows',return_value=self.rows), patch.object(a,'sql_state',return_value=self.state), \
             patch.object(a,'verify_files'), patch.object(a,'run_job') as runner:
            a.execute(self.sql,self.api,self.journal)
            runner.assert_not_called()

    def test_lost_restore_reply_only_confirms_never_repeats(self):
        self.sql.replace.side_effect = ConnectionError('lost')
        self.run_with_mocks(lambda *args: {'bild':3000,'erfolgreich':True})
        self.sql.replace.assert_called_once()
        self.assertEqual(self.sql.confirm.call_count,2)

    def test_original_hash_mismatch_blocks_before_write(self):
        with self.assertRaises(ValueError): a.verify_files(self.state)

    def test_changed_assignments_prevent_restoration_write(self):
        self.after.append([40,3000,'2-2-1','',3])
        self.after.sort()
        with self.assertRaises(ValueError):
            self.run_with_mocks(lambda *args: {'bild':3000,'erfolgreich':True})
        self.sql.replace.assert_not_called()
        self.assertNotEqual(self.journal.get('abnahme-1036')['phase'],'original_wiederhergestellt')

    def test_unconfirmed_restore_is_not_success_and_is_not_repeated(self):
        self.sql.replace.side_effect = ConnectionError('lost')
        self.sql.confirm.side_effect = ValueError('Quittung fehlt')
        with self.assertRaises(ValueError):
            self.run_with_mocks(lambda *args: {'bild':3000,'erfolgreich':True})
        self.sql.replace.assert_called_once()
        self.assertEqual(self.journal.get('abnahme-1036')['phase'],'ruecknahme_beauftragt')


if __name__ == '__main__':
    unittest.main()
