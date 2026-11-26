$ErrorActionPreference = 'Stop'
$root = 'C:\Krautl-Bilddienst'
$python = Join-Path $root '.venv\Scripts\python.exe'
$taskName = 'Krautl-Bilddienst'
$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object System.Security.Principal.WindowsPrincipal($identity)
if (-not $principal.IsInRole([System.Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Dieses Skript auf dem Wawi-Rechner in einer PowerShell als Administrator starten.'
}
$task = Get-ScheduledTask -TaskName $taskName -TaskPath '\'
if ($task.State -eq 'Disabled') {
    throw 'Die bestehende Aufgabe ist deaktiviert. Bitte zuerst den Betriebszustand pruefen lassen.'
}

$updates = [ordered]@{
    'worker.py' = '__WORKER_BASE64__'
    'sql.py' = '__SQL_BASE64__'
}
$tag = [Guid]::NewGuid().ToString('N')
$files = @()
$replaced = @()
$taskStopped = $false
Push-Location -LiteralPath $root
try {
    foreach ($name in $updates.Keys) {
        $target = Join-Path (Join-Path $root 'bridge') $name
        if (-not (Test-Path -LiteralPath $target -PathType Leaf)) { throw "Datei fehlt: $name" }
        $entry = @{ Target = $target; Stage = "$target.$tag.tmp"; Backup = "$target.$tag.bak" }
        $files += $entry
        [IO.File]::WriteAllBytes($entry.Stage, [Convert]::FromBase64String($updates[$name]))
    }
    $check = @'
import sys
from pathlib import Path
for name in sys.argv[1:]:
    compile(Path(name).read_bytes(), name, 'exec')
'@
    $stagePaths = @($files | ForEach-Object { $_.Stage })
    & $python -c $check @stagePaths
    if ($LASTEXITCODE -ne 0) { throw 'Update-Dateien sind nicht ausfuehrbar.' }

    $maintenance = @'
import json
from pathlib import Path
import httpx
from bridge.worker import https, PROTOCOL_VERSION
c = json.loads(Path('bridge/config.json').read_text(encoding='utf-8-sig'))
if PROTOCOL_VERSION >= 3:
    raise SystemExit(3)
r = httpx.post(https(c['krautl_url']) + '/api/bilder-bruecke/update-vorbereiten',
    headers={'Authorization': 'Bearer ' + c['bridge_token']},
    json={'worker': c['worker_id'], 'protokoll': PROTOCOL_VERSION},
    timeout=15, trust_env=False, follow_redirects=False)
if r.status_code != 200:
    try:
        print(r.json().get('detail', 'Wartung konnte nicht eingerichtet werden.'))
    except ValueError:
        print('Wartung konnte nicht eingerichtet werden: HTTP', r.status_code)
    raise SystemExit(1)
'@
    & $python -c $maintenance
    if ($LASTEXITCODE -eq 3) { Write-Host 'Bilddienst-Update ist bereits installiert.'; return }
    if ($LASTEXITCODE -ne 0) { throw 'Wartung konnte nicht vorbereitet werden. Der laufende Dienst bleibt aktiv.' }

    Disable-ScheduledTask -TaskName $taskName -TaskPath '\' | Out-Null
    $taskStopped = $true
    Stop-ScheduledTask -TaskName $taskName -TaskPath '\' -ErrorAction SilentlyContinue
    $lockCheck = @'
import json, time
from pathlib import Path
from bridge.worker import single_worker
c = json.loads(Path('bridge/config.json').read_text(encoding='utf-8-sig'))
for attempt in range(10):
    try:
        with single_worker(Path(c['journal_dir'])):
            break
    except OSError:
        time.sleep(1)
else:
    raise SystemExit('Der bisherige Bilddienst haelt noch die Dateisperre.')
'@
    & $python -c $lockCheck
    if ($LASTEXITCODE -ne 0) { throw 'Der bisherige Bilddienst konnte nicht sicher gestoppt werden.' }
    foreach ($entry in $files) {
        [IO.File]::Replace($entry.Stage, $entry.Target, $entry.Backup)
        $replaced += $entry
    }
    & $python -c 'from bridge.worker import PROTOCOL_VERSION; from bridge.sql import Database; assert PROTOCOL_VERSION == 3'
    if ($LASTEXITCODE -ne 0) { throw 'Der aktualisierte Bilddienst konnte nicht geladen werden.' }
    Enable-ScheduledTask -TaskName $taskName -TaskPath '\' | Out-Null
    Start-ScheduledTask -TaskName $taskName -TaskPath '\'
    Start-Sleep -Seconds 5
    if ((Get-ScheduledTask -TaskName $taskName -TaskPath '\').State -ne 'Running') {
        throw 'Der aktualisierte Dienst wurde nicht als laufend angezeigt.'
    }
    $taskStopped = $false
    Write-Host 'Bilddienst 3 laeuft. Krautl kann die vorbereiteten Auftraege weiterverarbeiten.'
} catch {
    if ($taskStopped) {
        Disable-ScheduledTask -TaskName $taskName -TaskPath '\' -ErrorAction SilentlyContinue | Out-Null
        Stop-ScheduledTask -TaskName $taskName -TaskPath '\' -ErrorAction SilentlyContinue
        foreach ($entry in $replaced) {
            [IO.File]::Replace($entry.Backup, $entry.Target, $null)
        }
        Enable-ScheduledTask -TaskName $taskName -TaskPath '\' | Out-Null
        Start-ScheduledTask -TaskName $taskName -TaskPath '\'
    }
    throw
} finally {
    foreach ($entry in $files) {
        if (Test-Path -LiteralPath $entry.Stage) { Remove-Item -LiteralPath $entry.Stage }
    }
    Pop-Location
}
