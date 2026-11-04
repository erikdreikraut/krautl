import io
import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app import bilder_einrichtung as setup
from app.auth import COOKIE_NAME, sitzung_erstellen, sitzung_lesen
from bridge.check_connection import check


class SetupTest(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {
            'BILDER_BRUECKE_TOKEN':'test-bridge-token-'*3,
            'BILDER_BRUECKE_WORKER_ID':'00000000-0000-0000-0000-000000000001',
            'JTL_LOCAL_API_KEY':'test-api-key', 'JTL_LOCAL_URL':'https://wawi.test/api/eazybusiness',
            'JTL_LOCAL_CA_FILE':'','KRAUTL_SESSION_SECRET':'session-test-'*5})
        self.env.start();self.addCleanup(self.env.stop)
        app=FastAPI()
        @app.middleware('http')
        async def user(request,call_next):
            request.state.benutzer=sitzung_lesen(request.cookies.get(COOKIE_NAME))
            return await call_next(request)
        app.include_router(setup.router)
        self.client=TestClient(app)
        self.addCleanup(self.client.close)

    def test_anonymous_staff_and_graphics_cannot_export(self):
        with patch.object(setup,'paket') as make:
            for user in [None,'gursewak','micha']:
                self.client.cookies.clear()
                if user:self.client.cookies.set(COOKIE_NAME,sitzung_erstellen(user))
                r=self.client.get('/admin/bilddienst-paket')
                self.assertEqual(r.status_code,403)
            make.assert_not_called()

    def test_admin_package_stable_identity_and_writes_disabled(self):
        self.client.cookies.set(COOKIE_NAME,sitzung_erstellen('erik'))
        r=self.client.get('/admin/bilddienst-paket')
        self.assertEqual(r.status_code,200)
        self.assertIn('no-store',r.headers['cache-control'])
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            c=json.loads(z.read('bridge/config.json'))
            self.assertFalse(c['enable_writes'])
            self.assertEqual(c['allowed_skus'],['1036'])
            self.assertEqual(c['wawi_key'],'test-api-key')
            self.assertEqual(c['worker_id'],os.environ['BILDER_BRUECKE_WORKER_ID'])
            self.assertIn('SERVER=lpc:.',c['sql_connection'])
            self.assertFalse(any('..' in n or n.startswith('/') for n in z.namelist()))
            self.assertIn('bridge/check_connection.py',z.namelist())
        self.assertNotIn('test-api-key',str(r.headers))

    def test_test_download_is_admin_only_and_has_no_configuration(self):
        for user in [None,'gursewak','micha','erik']:
            self.client.cookies.clear()
            if user:self.client.cookies.set(COOKIE_NAME,sitzung_erstellen(user))
            r=self.client.get('/admin/bilddienst-test')
            self.assertEqual(r.status_code,200 if user=='erik' else 403)
            self.assertNotIn('test-api-key',r.text)
            self.assertNotIn('test-bridge-token-',r.text)
        self.assertIn('no-store',r.headers['cache-control'])
        self.assertIn('Krautl-Bildtest.py',r.headers['content-disposition'])

    def test_missing_settings_and_invalid_tls_fail_without_secret_output(self):
        self.client.cookies.set(COOKIE_NAME,sitzung_erstellen('erik'))
        for settings in [{'BILDER_BRUECKE_TOKEN':''},{'JTL_LOCAL_URL':'http://wawi.test/api/eazybusiness'},
                         {'BILDER_BRUECKE_WORKER_ID':'invalid'}]:
            with patch.dict(os.environ,settings):
                r=self.client.get('/admin/bilddienst-paket')
                self.assertEqual(r.status_code,503)
                self.assertNotIn('test-api-key',r.text)

    def test_private_key_never_packaged(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'ca.pem';p.write_text('-----BEGIN PRIVATE KEY-----')
            with patch.dict(os.environ,{'JTL_LOCAL_CA_FILE':str(p)}):
                with self.assertRaises(ValueError):setup.paket()

    def test_check_never_starts_worker_or_polls_queue(self):
        c={'enable_writes':False,'krautl_url':'https://krautl.erikschweitzer.de'}
        w=Mock();w.url='https://wawi.test/api/eazybusiness'
        w.http.get.return_value.json.return_value={'Id':40,'SKU':'1036'}
        with patch('bridge.check_connection.Database') as db, patch('bridge.check_connection.Wawi',return_value=w), patch('bridge.check_connection.httpx.Client') as remote:
            check(c)
            db.return_value.preflight.assert_called_once()
            w.http.post.assert_not_called();w.http.patch.assert_not_called()
            self.assertEqual(w.http.get.call_count,1)
            remote.return_value.__enter__.return_value.get.assert_called_once_with('https://krautl.erikschweitzer.de/api/health')
        with self.assertRaises(ValueError):check({'enable_writes':True})


class LocalInstallerTest(unittest.TestCase):
    def test_secure_before_credentials_and_no_overwrite(self):
        from bridge.install_package import install, FILES
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/'target';(root/'.venv/Scripts').mkdir(parents=True)
            (root/'.venv/Scripts/python.exe').touch()
            package=Path(d)/'setup.zip'
            with zipfile.ZipFile(package,'w') as z:
                for name in FILES-{'bridge/wawi-ca.pem'}:
                    z.writestr(name,json.dumps({'enable_writes':False,'allowed_skus':['1036']}) if name.endswith('config.json') else 'test')
            called=[]
            def secure(path):
                self.assertFalse((path/'bridge/config.json').exists())
                called.append(path)
            install(package,root,secure)
            self.assertEqual(called,[root])
            original=(root/'bridge/config.json').read_bytes()
            with self.assertRaises(ValueError):install(package,root,secure)
            self.assertEqual((root/'bridge/config.json').read_bytes(),original)

    def test_unexpected_zip_paths_rejected_before_permissions_or_writes(self):
        from bridge.install_package import install
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/'target';(root/'.venv/Scripts').mkdir(parents=True)
            (root/'.venv/Scripts/python.exe').touch()
            p=Path(d)/'setup.zip'
            with zipfile.ZipFile(p,'w') as z:z.writestr('../outside','bad')
            secure=Mock()
            with self.assertRaises(ValueError):install(p,root,secure)
            secure.assert_not_called()


class UpdateInstallerTest(unittest.TestCase):
    def test_update_preserves_credentials_journal_and_rejects_enabled_worker(self):
        from bridge.install_package import install,FILES
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/'target';(root/'.venv/Scripts').mkdir(parents=True)
            (root/'.venv/Scripts/python.exe').touch()
            (root/'bridge').mkdir();journal=root/'journal';journal.mkdir()
            (journal/'proof').write_text('receipt')
            config=dict(enable_writes=False,allowed_skus=['1036'],journal_dir=str(journal),worker_id='id',bridge_token='token',krautl_url='url',wawi_url='wawi',wawi_key='key')
            raw=json.dumps(config).encode();(root/'bridge/config.json').write_bytes(raw)
            (root/'bridge/wawi-ca.pem').write_text('verified')
            package=Path(d)/'setup.zip'
            with zipfile.ZipFile(package,'w') as z:
                for name in FILES:z.writestr(name,raw if name.endswith('config.json') else 'updated')
            install(package,root,Mock(),update=True)
            self.assertEqual((root/'bridge/config.json').read_bytes(),raw)
            self.assertEqual((root/'bridge/wawi-ca.pem').read_text(),'verified')
            self.assertEqual((journal/'proof').read_text(),'receipt')
            self.assertEqual((root/'bridge/sql.py').read_text(),'updated')
            config['enable_writes']=True
            (root/'bridge/config.json').write_text(json.dumps(config))
            with self.assertRaises(ValueError):install(package,root,Mock(),update=True)
