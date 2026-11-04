$ErrorActionPreference = 'Stop'
$root = 'C:\Krautl-Bilddienst'
$python = Join-Path $root '.venv\Scripts\python.exe'
$taskName = 'Krautl-Bilddienst'
$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object System.Security.Principal.WindowsPrincipal($identity)
if (-not $principal.IsInRole([System.Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'PowerShell bitte als Administrator unter dem bisherigen Windows-Konto oeffnen.'
}
if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
    throw 'Aufgabe Krautl-Bilddienst existiert bereits. Bitte Zustand pruefen lassen; keine zweite Einrichtung.'
}
Set-Location -LiteralPath $root
$preflight = @"
import json
from pathlib import Path
from bridge.worker import single_worker, PROTOCOL_VERSION
from bridge.sql import Database
p=Path('bridge/config.json')
c=json.loads(p.read_text(encoding='utf-8-sig'))
assert PROTOCOL_VERSION==2, 'Bilddienst-Update fehlt'
assert c.get('allowed_skus') in (['1036'],['*']), 'Unerwartete Artikelfreigabe'
with single_worker(Path(c['journal_dir'])):
    Database(c).preflight()
print('Dienst angehalten; Datenbankstruktur OK.')
"@
& $python -c $preflight
if ($LASTEXITCODE -ne 0) { throw 'Vorpruefung fehlgeschlagen. Laufenden Bilddienst zuerst mit Strg+C beenden.' }
$credential = Get-Credential -UserName $identity.Name -Message 'Windows-Kennwort fuer den automatischen Krautl-Bilddienst (bleibt lokal in Windows).'
if (-not $credential) { throw 'Einrichtung abgebrochen; nichts freigegeben.' }
$credentialSid = (New-Object System.Security.Principal.NTAccount($credential.UserName)).Translate([System.Security.Principal.SecurityIdentifier]).Value
if ($credentialSid -ne $identity.User.Value) { throw 'Bitte das bisherige Windows-Konto verwenden, dessen Wawi-Zugang geprueft wurde.' }
$runner = Join-Path $root 'service_runner.py'
[System.IO.File]::WriteAllBytes($runner,[Convert]::FromBase64String('__RUNNER_BASE64__'))
$action = New-ScheduledTaskAction -Execute $python -Argument '-u C:\Krautl-Bilddienst\service_runner.py' -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -AtStartup
$settings = New-ScheduledTaskSettingsSet -Disable -StartWhenAvailable -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$registered = $false
try {
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -User $identity.Name -Password ($credential.GetNetworkCredential().Password) -RunLevel Highest -Description 'Krautl Bilddienst: bestaetigte Bildauftraege, Original- und Auftragsjournal erhalten.' | Out-Null
    $registered = $true
    $activate = @"
import json,os
from pathlib import Path
from bridge.worker import single_worker
p=Path('bridge/config.json')
raw=p.read_bytes()
c=json.loads(raw.decode('utf-8-sig'))
with single_worker(Path(c['journal_dir'])):
    backup=p.with_name('config.vor-dauerbetrieb.json')
    if backup.exists():raise ValueError('Dauerbetriebs-Sicherung bereits vorhanden; zuerst Zustand pruefen')
    with backup.open('xb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
    c['allowed_skus']=['*'];c['enable_writes']=True
    temporary=p.with_suffix('.dauerbetrieb.tmp')
    with temporary.open('x',encoding='utf-8') as f:json.dump(c,f,indent=2);f.flush();os.fsync(f.fileno())
    os.replace(temporary,p)
print('Windows-Freigabe fuer alle Artikel gespeichert. Zugangsdaten und Journal erhalten.')
"@
    & $python -c $activate
    if ($LASTEXITCODE -ne 0) { throw 'Konfigurationsaktivierung fehlgeschlagen; Aufgabe bleibt aus.' }
    Enable-ScheduledTask -TaskName $taskName | Out-Null
    Start-ScheduledTask -TaskName $taskName
    Start-Sleep -Seconds 8
    $task = Get-ScheduledTask -TaskName $taskName
    if ($task.State -ne 'Running') { throw 'Aufgabe ist nicht gestartet. Bitte C:\Krautl-Bilddienst\bilddienst.log pruefen lassen.' }
    Write-Host 'Dauerbetrieb gestartet. Aufgabe: Krautl-Bilddienst; Zustand: Running.'
    Write-Host 'Windows-Freigabe: alle Artikel. Serverfreigabe wird anschliessend durch Codex geprueft.'
    Write-Host 'Dieses PowerShell-Fenster darf geschlossen werden. Journale und Zugangsdaten wurden erhalten.'
} catch {
    if ($registered) {
        Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
        Disable-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue | Out-Null
    }
    throw
} finally {
    $credential = $null
}
