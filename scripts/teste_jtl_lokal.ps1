# Einmaliger HTML-Test auf dem Wawi-Server. Windows PowerShell 5.1.
[CmdletBinding()]
param([switch]$Anwenden, [switch]$Pruefen)

$ErrorActionPreference = 'Stop'

function Get-KrautlSignatur($Attribute) {
    $map = [System.Collections.Generic.SortedDictionary[string,string]]::new([StringComparer]::Ordinal)
    foreach ($a in @($Attribute.values)) {
        if ($null -eq $a) { continue }
        if (-not $a.attributeId) { throw 'Attribut-ID fehlt.' }
        $map.Add(([string]$a.attributeId), 'vorhanden')
        $gruppen = @(@{Kanal=$null; Werte=@($a.defaultValues)})
        $kanaele = @{}
        foreach ($k in @($a.salesChannelValues)) {
            if ($null -eq $k) { continue }
            if (-not $k.salesChannelId -or $kanaele.ContainsKey($k.salesChannelId)) { throw 'Attributkanal fehlt oder ist doppelt.' }
            $kanaele[$k.salesChannelId] = $true
            $gruppen += @{Kanal=$k.salesChannelId; Werte=@($k.values)}
        }
        foreach ($g in $gruppen) {
            foreach ($w in $g.Werte) {
                if ($null -eq $w) { continue }
                $sprache = if ($w.languageIso) { $w.languageIso.ToLowerInvariant() } else { $null }
                $key = ConvertTo-Json -InputObject @($a.attributeId, $g.Kanal, $sprache) -Compress
                $map.Add($key, [string]$w.value)
            }
        }
    }
    return ,$map
}

function Compare-KrautlAttribute($Vorher, $Ziel, $Aktuell) {
    $alt = Get-KrautlSignatur $Vorher
    $soll = Get-KrautlSignatur $Ziel
    $ist = Get-KrautlSignatur $Aktuell
    $zielkey = ConvertTo-Json -InputObject @('29708817-225b-4208-9a57-5ff511000000','2-2-1','de') -Compress
    $andere = $true; $exakt = $ist.Count -eq $soll.Count; $unveraendert = $ist.Count -eq $alt.Count
    foreach ($key in $alt.Keys) {
        $gleich = $ist.ContainsKey($key) -and $ist[$key] -ceq $alt[$key]
        if (-not $gleich) { $unveraendert = $false; if ($key -cne $zielkey) { $andere = $false } }
    }
    foreach ($key in $soll.Keys) {
        if (-not $ist.ContainsKey($key) -or $ist[$key] -cne $soll[$key]) { $exakt = $false }
    }
    return [ordered]@{
        ziel_erreicht=($ist.ContainsKey($zielkey) -and $ist[$zielkey] -ceq $soll[$zielkey])
        andere_bestandswerte_erhalten=$andere
        exakter_zielstand=$exakt
        ausgangsstand_unveraendert=$unveraendert
    }
}

function Save-KrautlJournal($Pfad, $Daten) {
    $bytes = [Text.Encoding]::UTF8.GetBytes(($Daten | ConvertTo-Json -Depth 100))
    $stream = [IO.File]::Open($Pfad, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
    try { $stream.Write($bytes, 0, $bytes.Length); $stream.Flush($true) } finally { $stream.Dispose() }
}

function Read-KrautlArtikel($Headers) {
    $a = Invoke-RestMethod -Method Get -Uri 'http://127.0.0.1:5883/api/eazybusiness/v2/items/770f139d-18dd-405c-9f84-322132010000' -Headers $Headers -TimeoutSec 30
    if ($a.id -ne '770f139d-18dd-405c-9f84-322132010000' -or $a.identifiers.sku -cne '40047-1000') {
        throw 'Artikel-ID oder Artikelnummer stimmt nicht. Kein Schreibzugriff.'
    }
    return $a
}

function Invoke-KrautlLokalTest {
    param([switch]$Anwenden, [switch]$Pruefen)
    if ($Anwenden -and $Pruefen) { throw 'Nur Anwenden oder Pruefen verwenden.' }
    $ordner = Join-Path $env:LOCALAPPDATA 'Krautl'
    $journal = Join-Path $ordner 'jtl-lokal-html-40047-1000.json'
    $secureKey = Import-Clixml -LiteralPath (Join-Path $ordner 'jtl-lokal-key.xml')
    $headers = @{'Authorization'=('Wawi ' + ([Net.NetworkCredential]::new('', $secureKey)).Password); 'x-appid'='krautl-lokal'; 'x-appversion'='0.1.0'}
    try {
        if ($Pruefen) {
            $daten = Get-Content -LiteralPath $journal -Raw | ConvertFrom-Json
            if ($daten.artikelnummer -cne '40047-1000' -or $daten.artikel_id -ne '770f139d-18dd-405c-9f84-322132010000') { throw 'Falsches Journal.' }
            $aktuell = Read-KrautlArtikel $headers
            return (Compare-KrautlAttribute $daten.vorher $daten.ziel $aktuell.attributes)
        }
        if ($Anwenden -and (Test-Path -LiteralPath $journal)) { throw 'Journal existiert. Nur -Pruefen verwenden; nicht erneut schreiben.' }
        $artikel = Read-KrautlArtikel $headers
        $ziel = $artikel.attributes | ConvertTo-Json -Depth 100 | ConvertFrom-Json
        $a = @($ziel.values | Where-Object attributeId -eq '29708817-225b-4208-9a57-5ff511000000')
        if ($a.Count -ne 1) { throw 'FAQ-Inhaltsattribut nicht eindeutig vorhanden.' }
        $kanal = @($a[0].salesChannelValues | Where-Object salesChannelId -eq '2-2-1')
        if ($kanal.Count -ne 1) { throw 'Shopkanal nicht eindeutig vorhanden.' }
        $wert = @($kanal[0].values | Where-Object languageIso -eq 'de')
        if ($wert.Count -ne 1) { throw 'Deutscher Shopwert nicht eindeutig vorhanden.' }
        $html = '<p>Krautl FAQ Schreibtest 40047-1000</p>'
        $wert[0].value = $html
        $request = @{attributes=@{values=@(@{attributeId='29708817-225b-4208-9a57-5ff511000000';salesChannelValues=@(@{salesChannelId='2-2-1';values=@(@{languageIso='de';value=$html})})})}}
        if (-not $Anwenden) { return @{artikelnummer='40047-1000';vorschau=$true;inhalt=$html;journal=$journal} }
        $aktuell = Read-KrautlArtikel $headers
        if (-not (Compare-KrautlAttribute $artikel.attributes $ziel $aktuell.attributes).ausgangsstand_unveraendert) { throw 'Attribute inzwischen veraendert; Abbruch.' }
        if ((Compare-KrautlAttribute $artikel.attributes $ziel $aktuell.attributes).exakter_zielstand) { return @{bereits_vorhanden=$true;geschrieben=$false} }
        $daten = @{artikelnummer='40047-1000';artikel_id=$artikel.id;vorher=$artikel.attributes;ziel=$ziel;request=$request;zeitpunkt=[DateTimeOffset]::Now.ToString('o')}
        Save-KrautlJournal $journal $daten
        $antwortId = $null; $fehler = $null
        try {
            $body = [Text.Encoding]::UTF8.GetBytes(($request | ConvertTo-Json -Depth 20 -Compress))
            $antwort = Invoke-RestMethod -Method Patch -Uri 'http://127.0.0.1:5883/api/eazybusiness/v2/items/770f139d-18dd-405c-9f84-322132010000' -Headers $headers -ContentType 'application/json; charset=utf-8' -Body $body -TimeoutSec 30
            $antwortId = $antwort.item.id
        } catch {
            $fehler = if ($_.Exception.Response) { 'HTTP ' + [int]$_.Exception.Response.StatusCode } else { 'Verbindungsfehler; Versandergebnis unklar.' }
        }
        $bericht = [ordered]@{artikelnummer='40047-1000';antwort_artikel_id=$antwortId;fehler=$fehler;journal=$journal}
        Save-KrautlJournal ($journal + '.antwort.json') $bericht
        $aktuell = Read-KrautlArtikel $headers
        $vergleich = Compare-KrautlAttribute $artikel.attributes $ziel $aktuell.attributes
        $bericht.ruecklesepruefung = $vergleich
        $bericht.test_erfolgreich = (-not $fehler -and $antwortId -eq $artikel.id -and $vergleich.exakter_zielstand)
        Save-KrautlJournal ($journal + '.ergebnis.json') $bericht
        return $bericht
    } finally { $headers.Clear() }
}

if ($MyInvocation.InvocationName -ne '.') {
    try {
        $result = Invoke-KrautlLokalTest -Anwenden:$Anwenden -Pruefen:$Pruefen
        $result | ConvertTo-Json -Depth 10
        if ($result.Contains('test_erfolgreich') -and -not $result.test_erfolgreich) { exit 1 }
    } catch {
        Write-Output ('Test abgebrochen: ' + $_.Exception.Message + ' Bei vorhandenem Journal nur -Pruefen verwenden.')
        exit 1
    }
}
