"""Install the admin-downloaded package locally; preserve existing config/journals."""
import json
import os
from pathlib import Path
import subprocess
import zipfile

FILES = {'bridge/__init__.py','bridge/worker.py','bridge/sql.py','bridge/schema.json',
         'bridge/requirements.txt','bridge/check_connection.py','bridge/config.json','bridge/wawi-ca.pem'}


def protect(root):
    # The fixed destination avoids shell interpolation of arbitrary paths.
    if str(root.resolve()).replace('\\','/').lower() != 'c:/krautl-bilddienst':
        raise ValueError('Unerwarteter Zielordner')
    script = r"""
$ErrorActionPreference='Stop'
$acl=New-Object System.Security.AccessControl.DirectorySecurity
$acl.SetAccessRuleProtection($true,$false)
$owner=[System.Security.Principal.WindowsIdentity]::GetCurrent().User
$acl.SetOwner($owner)
foreach($sid in @($owner.Value,'S-1-5-18','S-1-5-32-544')) {
 $id=New-Object System.Security.Principal.SecurityIdentifier($sid)
 $rule=New-Object System.Security.AccessControl.FileSystemAccessRule($id,'FullControl','ContainerInherit,ObjectInherit','None','Allow')
 $acl.AddAccessRule($rule)
}
Set-Acl -LiteralPath 'C:\Krautl-Bilddienst' -AclObject $acl
"""
    subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',script],check=True)


def install(package, root, secure=protect):
    if not (root/'.venv/Scripts/python.exe').is_file():
        raise ValueError('Vorbereitete Python-Umgebung fehlt')
    if (root/'bridge/config.json').exists():
        raise ValueError('Konfiguration vorhanden; sie wird nicht ueberschrieben')
    with zipfile.ZipFile(package) as z:
        names=z.namelist()
        if len(set(names))!=len(names) or set(names)-FILES-{'einrichten.py'}:
            raise ValueError('Unerwarteter Paketinhalt')
        if not FILES-{'bridge/wawi-ca.pem'} <= set(names):
            raise ValueError('Paket unvollstaendig')
        if sum(i.file_size for i in z.infolist())>5_000_000:
            raise ValueError('Paket zu gross')
        config=json.loads(z.read('bridge/config.json'))
        if config.get('enable_writes') is not False or config.get('allowed_skus')!=['1036']:
            raise ValueError('Schreibfreigabe im Einrichtungspaket unzulaessig')
        payload={name:z.read(name) for name in names if name in FILES}
    secure(root)  # Restrict local access before creating any credential file.
    for name,raw in payload.items():
        target=root/name
        target.parent.mkdir(parents=True,exist_ok=True)
        with target.open('xb' if name=='bridge/config.json' else 'wb') as f:
            f.write(raw)
            f.flush()
            os.fsync(f.fileno())


if __name__=='__main__':
    root=Path('C:/Krautl-Bilddienst')
    package=Path.home()/'Downloads/Krautl-Bilddienst-Einrichtung.zip'
    try:
        install(package,root)
        package.unlink()
        print('Einrichtung gespeichert. Schreibfreigabe bleibt aus.',flush=True)
        result=subprocess.run([str(root/'.venv/Scripts/python.exe'),'-m','bridge.check_connection'],cwd=root)
        raise SystemExit(result.returncode)
    except Exception as exc:
        print('Einrichtung gestoppt: '+(str(exc) if type(exc) is ValueError else type(exc).__name__))
        raise SystemExit(1)
