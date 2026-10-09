$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '../scripts/teste_jtl_lokal.ps1')

function Assert-Krautl($Bedingung, $Text) { if (-not $Bedingung) { throw $Text } }
function Import-Clixml { param($LiteralPath) return (ConvertTo-SecureString 'lokaler-testschluessel' -AsPlainText -Force) }
function Read-KrautlArtikel {
    param($Headers)
    return ([pscustomobject]@{id='770f139d-18dd-405c-9f84-322132010000';identifiers=@{sku='40047-1000'};attributes=($script:state | ConvertTo-Json -Depth 100 | ConvertFrom-Json)})
}
function Invoke-RestMethod {
    param($Method, $Uri, $Headers, $ContentType, $Body, $TimeoutSec)
    Assert-Krautl ($Method -eq 'Patch') 'Unerwarteter Aufruf'
    Assert-Krautl ($Uri -eq 'http://127.0.0.1:5883/api/eazybusiness/v2/items/770f139d-18dd-405c-9f84-322132010000') 'Falsches Ziel'
    Assert-Krautl (Test-Path $script:journalPfad) 'Sicherung fehlt'
    $script:aufrufe++
    $request = [Text.Encoding]::UTF8.GetString($Body) | ConvertFrom-Json
    Assert-Krautl ($request.attributes.values.Count -eq 1) 'Fremde Attribute gesendet'
    $attr = $request.attributes.values[0]
    Assert-Krautl ($attr.attributeId -eq '29708817-225b-4208-9a57-5ff511000000') 'Falsches Attribut'
    Assert-Krautl ($attr.salesChannelValues[0].values[0].value -ceq $script:erwartetesHtml) 'Falscher Inhalt'
    if ($script:modus -in @('erfolg','vollstaendig')) { $script:state.values[0].salesChannelValues[0].values[0].value = $attr.salesChannelValues[0].values[0].value }
    if ($script:modus -eq 'verlust') { $script:state = $request.attributes }
    if ($script:modus -eq 'netzfehler') { throw 'simulierter Netzwerkabbruch' }
    return @{item=@{id='770f139d-18dd-405c-9f84-322132010000'}}
}

$originalLocalAppData = $env:LOCALAPPDATA
$testRoot = Join-Path ([IO.Path]::GetTempPath()) ('krautl-ps-test-' + [guid]::NewGuid().ToString('N'))
try {
    foreach ($script:modus in @('erfolg','wirkungslos','verlust','netzfehler','vollstaendig')) {
        $env:LOCALAPPDATA = Join-Path $testRoot $script:modus
        New-Item -ItemType Directory -Path (Join-Path $env:LOCALAPPDATA 'Krautl') -Force | Out-Null
        $script:state = @{values=@(
            @{attributeId='29708817-225b-4208-9a57-5ff511000000';salesChannelValues=@(@{salesChannelId='2-2-1';values=@(@{languageIso='de';value='alter Inhalt'})})},
            @{attributeId='anderes';defaultValues=@(@{value='neutral'})}
        )}
        $script:aufrufe = 0
        $optionen = @{}
        $script:erwartetesHtml = '<p>Krautl FAQ Schreibtest 40047-1000</p>'
        $script:journalPfad = Join-Path $env:LOCALAPPDATA 'Krautl/jtl-lokal-html-40047-1000.json'
        if ($script:modus -eq 'vollstaendig') {
            # Langer Unicode-Inhalt muss bytegetreu durch Datei und JSON gelangen.
            $script:erwartetesHtml = ('<p>FAQ ' + [char]0x00e4 + ' &amp; Antwort</p>') * 800
            $htmlPfad = Join-Path $env:LOCALAPPDATA 'faq.html'
            [IO.File]::WriteAllText($htmlPfad, $script:erwartetesHtml, [Text.UTF8Encoding]::new($false))
            $optionen.HtmlDatei = $htmlPfad
            [IO.File]::WriteAllText($script:journalPfad, 'Alte Absatzsicherung erhalten')
            $script:journalPfad = Join-Path $env:LOCALAPPDATA 'Krautl/jtl-lokal-faq-vollstaendig-40047-1000.json'
        }
        $vorschau = Invoke-KrautlLokalTest @optionen
        Assert-Krautl ($script:aufrufe -eq 0 -and $vorschau.vorschau) 'Vorschau schreibt'
        $result = Invoke-KrautlLokalTest -Anwenden @optionen
        Assert-Krautl ($result.test_erfolgreich -eq ($script:modus -in @('erfolg','vollstaendig'))) 'Erfolgsbewertung falsch'
        Assert-Krautl ($result.ruecklesepruefung.andere_bestandswerte_erhalten -eq ($script:modus -ne 'verlust')) 'Verlusterkennung falsch'
        $check = Invoke-KrautlLokalTest -Pruefen @optionen
        Assert-Krautl ($check.exakter_zielstand -eq ($script:modus -in @('erfolg','vollstaendig'))) 'Ruecklesen falsch'
        if ($script:modus -eq 'vollstaendig') {
            Assert-Krautl (([IO.File]::ReadAllText((Join-Path $env:LOCALAPPDATA 'Krautl/jtl-lokal-html-40047-1000.json'))) -ceq 'Alte Absatzsicherung erhalten') 'Alte Sicherung veraendert'
        }
        $gesperrt = $false
        try { Invoke-KrautlLokalTest -Anwenden @optionen | Out-Null } catch { $gesperrt = $_.Exception.Message -like 'Journal existiert*' }
        Assert-Krautl ($gesperrt -and $script:aufrufe -eq 1) 'Wiederholung nicht gesperrt'
    }
    Write-Output 'OK: Vorschau, Sicherung, Erfolg, wirkungsloses Schreiben, Attributverlust, Netzwerkfehler und Wiederholungssperre.'
} finally {
    $env:LOCALAPPDATA = $originalLocalAppData
    # Nur die in diesem Test selbst erzeugten Dateien entfernen, nicht rekursiv.
    Get-ChildItem -LiteralPath $testRoot -File -Recurse | Remove-Item
    foreach ($folder in Get-ChildItem -LiteralPath $testRoot -Directory) {
        Remove-Item -LiteralPath (Join-Path $folder.FullName 'Krautl')
        Remove-Item -LiteralPath $folder.FullName
    }
    Remove-Item -LiteralPath $testRoot
}
