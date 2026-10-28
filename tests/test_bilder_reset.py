import unittest
import test_bilder_ersetzen as fixtures
from test_bilder_ersetzen import A, B, J, URL
from app import bilder_speicher as store
from app.bilder_upload import sichern, auftraege
from scripts.setze_bildauftrag_zurueck import zuruecksetzen


class ResetTest(unittest.IsolatedAsyncioTestCase):
    setUp = fixtures.ReplaceTest.setUp
    tearDown = fixtures.ReplaceTest.tearDown
    client = fixtures.ReplaceTest.client
    response = fixtures.ReplaceTest.response

    def prepare(self):
        job = dict(id=J, artikel=A, sku='X', bild_id=B, revision=0,
                   api_ziel=URL, status='unklar', bereinigung_id=21,
                   meldung='Nicht bestätigt', art='ersetzen_alle')
        sichern(job, self.new)
        with store.datenbank() as db:
            db.execute('CREATE TABLE shoppruefung (artikel TEXT PRIMARY KEY, daten TEXT)')
            db.execute('INSERT INTO shoppruefung VALUES (?,?)', (A, '{}'))
        return job

    async def test_reset_refreshes_and_preserves_journal_without_wawi_writes(self):
        self.prepare()
        async with self.client() as c:
            await zuruecksetzen(c, 'X', 21)
        a = store.lesen()['artikel'][0]
        self.assertEqual(a['revision'], 1)
        self.assertEqual(a['bilder'][0]['v1_id'], 20)
        job = auftraege()[0]
        self.assertEqual(job['status'], 'abgelehnt')
        self.assertEqual(job['ruecksetzung']['vorher_status'], 'unklar')
        with store.datenbank() as db:
            self.assertEqual(db.execute('SELECT datei FROM bildauftraege').fetchone()[0], self.new)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM shoppruefung').fetchone()[0], 0)
        self.assertEqual(set(self.calls), {'GET'})
        from scripts.repariere_bildaustausch_v1 import fortsetzen
        async with self.client() as c:
            with self.assertRaisesRegex(ValueError, 'manuell beendet'):
                await fortsetzen(c, job, True)

    async def test_still_assigned_image_blocks_reset_even_in_other_channel(self):
        job = self.prepare()
        before = store.lesen()
        self.rows.append(dict(ItemId=10, ImageId=21, SalesChannelId='amazon', SortNumber=4))
        async with self.client() as c:
            with self.assertRaisesRegex(ValueError, 'noch in Wawi'):
                await zuruecksetzen(c, 'X', 21)
        self.assertEqual(store.lesen(), before)
        self.assertEqual(auftraege()[0], job)

    async def test_changed_readback_does_not_publish_reset(self):
        from unittest.mock import patch
        from app.bilder_ersetzen import zuordnungen
        self.prepare()
        before = store.lesen()
        with patch('scripts.setze_bildauftrag_zurueck.zuordnungen', side_effect=[[], zuordnungen(self.rows)]):
            async with self.client() as c:
                with self.assertRaisesRegex(ValueError, 'während des Lesens'):
                    await zuruecksetzen(c, 'X', 21)
        self.assertEqual(store.lesen(), before)
        self.assertEqual(auftraege()[0]['status'], 'unklar')
