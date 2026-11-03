import copy
import unittest
from scripts.teste_bilder_kanalweg import validate_cleanup


class TestFixtureCleanup(unittest.TestCase):
    def setUp(self):
        self.plan={'rows':[{'ImageId':2729,'SalesChannelId':'2-2-1','SortNumber':1}],
                   'hashes':{'2729':'original'},'test_hash':'fixture'}
        self.rows=copy.deepcopy(self.plan['rows'])+[{'ImageId':2732,'SalesChannelId':'1-1-1','SortNumber':5}]
        self.hashes={'2729':'original','2732':'fixture'}

    def test_own_unshared_fixture_only(self):
        validate_cleanup(self.plan,self.rows,self.hashes,2732)

    def test_original_never_deleted(self):
        with self.assertRaises(ValueError):validate_cleanup(self.plan,self.rows,self.hashes,2729)

    def test_shared_fixture_rejected(self):
        self.rows.append({'ImageId':2732,'SalesChannelId':'2-2-1','SortNumber':2})
        with self.assertRaises(ValueError):validate_cleanup(self.plan,self.rows,self.hashes,2732)

    def test_missing_original_rejected(self):
        self.rows.pop(0)
        with self.assertRaises(ValueError):validate_cleanup(self.plan,self.rows,self.hashes,2732)

    def test_changed_file_rejected(self):
        self.hashes['2732']='other'
        with self.assertRaises(ValueError):validate_cleanup(self.plan,self.rows,self.hashes,2732)
