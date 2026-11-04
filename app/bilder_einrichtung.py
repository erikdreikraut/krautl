"""Explicitly authorized, admin-only bridge configuration download."""
import base64
import io
import json
import os
import ssl
import zipfile
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID
from fastapi import APIRouter, HTTPException, Request, Response
from .berechtigungen import ist_admin

router = APIRouter()
ROOT = Path(__file__).resolve().parent.parent


@router.get('/admin/bilddienst-test')
def test_download(request: Request):
    user = getattr(request.state, 'benutzer', None)
    if not user or not ist_admin(user):
        raise HTTPException(403, 'Nur fuer Administratoren')
    return Response((ROOT/'bridge/acceptance.py').read_bytes(), media_type='text/plain', headers={
        'Content-Disposition': 'attachment; filename="Krautl-Bildtest.py"',
        'Cache-Control': 'no-store, private', 'X-Content-Type-Options': 'nosniff'})



@router.get('/admin/bilddienst-entfernen-pruefung')
def removal_test_download(request: Request):
    user = getattr(request.state, 'benutzer', None)
    if not user or not ist_admin(user):
        raise HTTPException(403, 'Nur fuer Administratoren')
    return Response((ROOT/'bridge/removal_check.py').read_bytes(), media_type='text/plain', headers={
        'Content-Disposition': 'attachment; filename="Krautl-Entfernen-Pruefung.py"',
        'Cache-Control': 'no-store, private', 'X-Content-Type-Options': 'nosniff'})



@router.get('/admin/bilddienst-dauerbetrieb')
def production_download(request: Request):
    user = getattr(request.state, 'benutzer', None)
    if not user or not ist_admin(user):
        raise HTTPException(403, 'Nur fuer Administratoren')
    script=(ROOT/'bridge/production.ps1').read_text(encoding='utf-8-sig')
    runner=base64.b64encode((ROOT/'bridge/service_runner.py').read_bytes()).decode('ascii')
    script=script.replace('__RUNNER_BASE64__',runner)
    return Response(script.encode('utf-8-sig'), media_type='text/plain', headers={
        'Content-Disposition': 'attachment; filename="Krautl-Dauerbetrieb.ps1"',
        'Cache-Control': 'no-store, private', 'X-Content-Type-Options': 'nosniff'})


def paket():
    token = os.getenv('BILDER_BRUECKE_TOKEN', '')
    key = os.getenv('JTL_LOCAL_API_KEY', '')
    url = os.getenv('JTL_LOCAL_URL', '').rstrip('/')
    u = urlsplit(url)
    worker = str(UUID(os.getenv('BILDER_BRUECKE_WORKER_ID', '')))
    if (len(token) < 32 or not key or u.scheme != 'https' or not u.hostname
            or u.username or u.password or u.query or u.fragment or u.path != '/api/eazybusiness'):
        raise ValueError('Unvollstaendige Einrichtung')
    ca_path = os.getenv('JTL_LOCAL_CA_FILE')
    ca = Path(ca_path).read_bytes() if ca_path else None
    if ca:
        if b'PRIVATE KEY' in ca:
            raise ValueError('Kein reines CA-Zertifikat')
        ssl.create_default_context(cadata=ca.decode('ascii'))
    config = dict(krautl_url='https://krautl.erikschweitzer.de', worker_id=worker,
        bridge_token=token, wawi_url=url, wawi_key=key,
        wawi_ca='C:/Krautl-Bilddienst/bridge/wawi-ca.pem' if ca else '',
        sql_connection=r'DRIVER={ODBC Driver 17 for SQL Server};SERVER=lpc:.\JTLWAWI;DATABASE=eazybusiness;Trusted_Connection=yes;',
        journal_dir='C:/ProgramData/Krautl-Bilddienst/journal', allowed_skus=['1036'], enable_writes=False)
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
        for name in ('__init__.py','worker.py','sql.py','schema.json','requirements.txt','check_connection.py'):
            z.writestr('bridge/'+name,(ROOT/'bridge'/name).read_bytes())
        z.writestr('einrichten.py',(ROOT/'bridge/install_package.py').read_bytes())
        z.writestr('bridge/config.json',json.dumps(config,ensure_ascii=False,indent=2))
        if ca:
            z.writestr('bridge/wawi-ca.pem',ca)
    return out.getvalue()


@router.get('/admin/bilddienst-paket')
def herunterladen(request: Request):
    user = getattr(request.state, 'benutzer', None)
    if not user or not ist_admin(user):
        raise HTTPException(403, 'Nur fuer Administratoren')
    try:
        data = paket()
    except (ValueError, OSError, ssl.SSLError):
        raise HTTPException(503, 'Bilddienst-Einrichtung noch nicht vorbereitet.') from None
    return Response(data, media_type='application/zip', headers={
        'Content-Disposition':'attachment; filename="Krautl-Bilddienst-Einrichtung.zip"',
        'Cache-Control':'no-store, private', 'Pragma':'no-cache',
        'X-Content-Type-Options':'nosniff'})
