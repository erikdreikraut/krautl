import unittest
from unittest.mock import Mock, patch
from bridge.removal_check import RollbackConnection, RollbackDatabase, execute

class RemovalCheckTest(unittest.TestCase):
 def test_commit_is_replaced_by_rollback(self):
  raw=Mock();db=RollbackConnection(raw)
  db.commit()
  raw.commit.assert_not_called();raw.rollback.assert_called_once()
  self.assertTrue(db.rolled_back)
  self.assertIs(db.cursor(),raw.cursor.return_value)
  db.close();raw.close.assert_called_once()
 def test_all_connections_are_wrapped(self):
  with patch('bridge.sql.Database.connect',return_value=Mock()) as connect:
   db=RollbackDatabase({});one=db.connect();two=db.connect()
   self.assertIsInstance(one,RollbackConnection);self.assertIsInstance(two,RollbackConnection)
   self.assertEqual(db.connections,[one,two])
   one.commit();two.commit();connect.return_value.commit.assert_not_called()
 def test_enabled_service_and_wider_skus_are_rejected_before_connect(self):
  for config in [dict(enable_writes=True,allowed_skus=['1036']),dict(enable_writes=False,allowed_skus=['*'])]:
   with patch('bridge.removal_check.RollbackDatabase') as database:
    with self.assertRaises(ValueError):execute(config,Mock())
    database.assert_not_called()
