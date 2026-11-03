import base64
import copy
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx

from scripts.teste_bilder_cloud_inhalt import run, TENANT


class TestCloudContent(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name)
        self.rows = [dict(ItemId=40, ImageId=i, SalesChannelId=c, SortNumber=p,
                          Filename='original.png') for i, c, p in
                     [(2729, '2-2-1', 1), (2365, '2-2-1', 2),
                      (2731, '1-1-0', 1), (2729, '6-51-0', 2)]]
        self.files = {'2729': b'original', '2365': b'other', '2731': b'test'}
        self.effect = True
        self.timeout = False
        async def get(url, **kwargs):
            if '/imagedata/' in url:
                return httpx.Response(200, content=self.files[url.rsplit('/', 1)[1]])
            return httpx.Response(200, json=copy.deepcopy(self.rows) if url.endswith('/images')
                                  else {'Id': 40, 'SKU': '1036'})
        async def patch(url, **kwargs):
            self.assertEqual(len(list(self.folder.glob('*.intent.json'))), self.c.http.patch.await_count)
            self.assertEqual(url.rsplit('/', 1)[1], '2729')
            data = kwargs['json']
            self.assertEqual(set(data), {'SalesChannelId', 'ImageData', 'Filename'})
            if self.effect:
                self.files['2729'] = base64.b64decode(data['ImageData'])
                for row in self.rows:
                    if row['ImageId'] == 2729:
                        row['Filename'] = data['Filename']
            if self.timeout:
                raise httpx.ReadTimeout('unknown outcome')
            return httpx.Response(201)
        self.c = SimpleNamespace(tenant_id=TENANT, _token=AsyncMock(return_value='token'),
             http=SimpleNamespace(get=AsyncMock(side_effect=get), patch=AsyncMock(side_effect=patch)))

    async def test_roundtrip_and_repeat_protection(self):
        original = copy.deepcopy(self.rows)
        await run(self.c, self.folder, 'vorbereiten')
        self.c.http.patch.assert_not_called()
        self.assertTrue((await run(self.c, self.folder, 'ausfuehren'))['bestaetigt'])
        self.assertTrue((await run(self.c, self.folder, 'zuruecksetzen'))['bestaetigt'])
        self.assertEqual(self.rows, original)
        for mode in ['ausfuehren', 'zuruecksetzen']:
            with self.assertRaises(ValueError): await run(self.c, self.folder, mode)
        self.assertEqual(self.c.http.patch.await_count, 2)

    async def test_timeout_after_effect_is_read_and_never_replayed(self):
        await run(self.c, self.folder, 'vorbereiten')
        self.timeout = True
        self.assertTrue((await run(self.c, self.folder, 'ausfuehren'))['bestaetigt'])
        with self.assertRaises(ValueError): await run(self.c, self.folder, 'ausfuehren')
        self.assertEqual(self.c.http.patch.await_count, 1)

    async def test_no_effect_is_not_success(self):
        await run(self.c, self.folder, 'vorbereiten')
        self.effect = False
        self.assertFalse((await run(self.c, self.folder, 'ausfuehren'))['bestaetigt'])
        with self.assertRaises(ValueError): await run(self.c, self.folder, 'zuruecksetzen')

    async def test_other_image_change_blocks_restore(self):
        await run(self.c, self.folder, 'vorbereiten')
        await run(self.c, self.folder, 'ausfuehren')
        self.files['2365'] = b'external'
        with self.assertRaises(ValueError): await run(self.c, self.folder, 'zuruecksetzen')
        self.assertEqual(self.c.http.patch.await_count, 1)

    async def test_channel_or_backup_changes_block_write(self):
        await run(self.c, self.folder, 'vorbereiten')
        self.rows[-1]['SortNumber'] = 3
        with self.assertRaises(ValueError): await run(self.c, self.folder, 'ausfuehren')
        self.rows[-1]['SortNumber'] = 2
        (self.folder / '2729.original').write_bytes(b'corrupt')
        with self.assertRaises(ValueError): await run(self.c, self.folder, 'ausfuehren')
        self.c.http.patch.assert_not_called()

    async def test_wrong_tenant_and_old_plan(self):
        await run(self.c, self.folder, 'vorbereiten')
        p = self.folder / 'plan.json'
        plan = json.loads(p.read_text())
        plan['created'] = '2020-01-01T00:00:00+00:00'
        p.write_text(json.dumps(plan))
        with self.assertRaises(ValueError): await run(self.c, self.folder, 'ausfuehren')
        self.c.tenant_id = 'wrong'
        with self.assertRaises(ValueError): await run(self.c, self.folder, 'pruefen')
        self.c.http.patch.assert_not_called()
