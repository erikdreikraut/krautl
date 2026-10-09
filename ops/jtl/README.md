# JTL-FAQ-Anbindung: Einrichtung und Abnahme

Stand: 09.10.2026. Eigene interne Krautl-App; Werkel bleibt unverändert.

## Dauerabgleich: HTTPS, alle fünf Minuten, nur Änderungen

Der vollständige FAQ-HTML-Export wurde am 09.10.2026 am Kind `40047-1000`
lokal erfolgreich geschrieben und exakt zurückgelesen; alle übrigen Attributwerte
blieben erhalten. Nutzer hat auch die Darstellung in Wawi bestätigt.

Implementiert ist ein eigener Docker-Dienst `jtl-sync` (Profil gleichen Namens).
Aktivierung steht noch aus: öffentliche HTTPS-Adresse, Zertifikat, Firewall mit
Krautl-IP als einzig erlaubter Quelle und Übergabe des lokalen API-Keys fehlen.
Kein automatischer Wechsel zurück zum Cloud-Weg. Kein Windows-Pull-Dienst.

- Ein Lauf, anschließend 300 Sekunden Pause; keine Überlappung oder Nachholschleife.
- Ein Datenbankabruf der ausgewählten FAQ pro Lauf. Maßgeblich ist der HTML-Inhalt,
  nicht bloß ein Bearbeitungszeitstempel. Entwürfe und Google-Auswahl sind unabhängig.
- Ohne Exportänderung keine JTL-Anfrage. Bei geändertem Export wird der paginierte
  Artikelkatalog einmal für den gesamten Lauf gelesen, um SKU und echte
  `parentItemId`-Beziehungen zu bestimmen. Keine Präfixannahmen.
- FAQ gehen an gleiche SKU und ihre Varianten. Eigene ausgewählte Varianten-FAQ
  haben Vorrang; werden sie entfernt, gelten wieder vorhandene Vater-FAQ.
- Nur tatsächlich geänderte Zielartikel werden gelesen und nötigenfalls geschrieben.
  Bereits gleiche Zielwerte werden ohne PATCH als bestätigt gespeichert.
- Beim ersten Start werden vorhandene ausgewählte FAQ einmalig abgeglichen.
  Entfällt eine Quelle, werden nur zuvor verwaltete, nun nicht mehr zugeordnete
  Zielartikel geleert (beide deutsche Shopwerte). Unverwaltete Artikel bleiben frei.
- Neue JTL-Varianten werden beim nächsten geänderten FAQ-Export erkannt. Kein
  zusätzlicher Katalog-Poll bei unveränderten FAQ; bewusst zur Lastbegrenzung.
- Vor jedem PATCH vollständige Attribut-Sicherung und zweiter Lesestand gegen
  zwischenzeitliche Änderungen. PATCH enthält nur zwei deutsche Shopwerte.
  Rücklesen prüft sämtliche Attributwerte. Das ist kein atomarer serverseitiger
  Vergleich; gleichzeitige externe Änderungen zwischen Prüfung und PATCH sind möglich.
- Bei unklarem PATCH-Ausgang wird nur rückgelesen. Exakter gesicherter Zielstand
  löst den offenen Versuch auf. Abweichungen sperren weitere Schreibläufe bis zur
  manuellen Prüfung; keine automatische Wiederholung/Wiederherstellung.

Zustand, letzter Lauf/Fehler und Sicherungen liegen dauerhaft in `var/jtl-sync/`.
Nicht löschen oder zurücksetzen, um einen Fehler zu übergehen. Verzeichnis sichern;
es enthält Artikelattribute, keine API-Schlüssel. Eine Dateisperre schützt vor
mehreren Diensten auf derselben Arbeitskopie. `var/jtl-tls/` enthält optional das
vertrauenswürdige PEM-Zertifikat. Beide Verzeichnisse sind aus Git/Build ausgeschlossen.

### Einrichtung und Aktivierung

1. Wawi-API als HTTPS-Endpunkt einrichten. Zertifikat muss für den gewählten
   DNS-Namen bzw. die IP gültig sein. Selbstsigniertes Zertifikat nur mit explizit
   vertrautem PEM-Zertifikat in Krautl verwenden; niemals TLS-Prüfung abschalten.
   Firewall/Provider-Firewall auf die öffentliche ausgehende Krautl-Server-IP
   beschränken; keine allgemein erlaubende JTL-Regel daneben stehen lassen.
   Der bisherige lokale Testdienst kann bis zur Abnahme bestehen bleiben.
2. Lokalen App-Key aus der DPAPI-Sicherung im ursprünglichen Windows-Konto
   sicher in die Server-`.env` übertragen, nicht im Chat oder Git ablegen.
   `JTL_LOCAL_URL=https://HOST:PORT/api/eazybusiness`, `JTL_LOCAL_API_KEY=...`,
   zunächst `JTL_SYNC_ENABLED=false`. Optional
   `JTL_LOCAL_CA_FILE=/app/var/jtl-tls/ca.pem`. `.env` nur für Serveradministration lesbar.
3. Code holen und Image bauen; bestehende Mail-/WhatsApp-Dienste müssen dafür
   nicht neu gestartet werden. Keine Datenbankmigration erforderlich:

```bash
cd /opt/app/krautl &&
git remote set-url origin https://github.com/erikdreikraut/krautl.git &&
git switch main &&
git pull --ff-only origin main &&
mkdir -p var/jtl-sync var/jtl-tls &&
chmod 700 var/jtl-sync var/jtl-tls &&
docker compose build app
```

4. Lesende Vorschau über die echte HTTPS-Verbindung (kein PATCH, kein Fortschreiben
   des Abgleichstands), Liste einschließlich Varianten und Leerungen prüfen:

```bash
docker compose --profile jtl-sync run --rm --no-deps jtl-sync python -m app.jtl_sync_service --vorschau
```

5. Danach `JTL_SYNC_ENABLED=true` in `.env` setzen und starten:

```bash
docker compose --profile jtl-sync up -d --no-deps jtl-sync
docker compose logs --tail=40 jtl-sync
```

Pausieren: `docker compose stop jtl-sync`. Status: Logs und `var/jtl-sync/stand.json`.
Bei Updates des aktiven Abgleichs das Image neu bauen und nur `jtl-sync` neu erstellen.
Die folgenden Abschnitte dokumentieren die vorherigen manuellen Abnahmeschritte.

## Direkter lokaler Test auf dem Wawi-Server

Am 09.10.2026 nach Cloud-Diagnose eingerichtet: Windows-Dienst `Krautl-API-lokal`,
Profil Standard, Mandant eB-Standard / eazybusiness, nur `127.0.0.1:5883`.
`/api/eazybusiness/info` meldet `2.1.1+Sha.6aebf42`. Cloud-Dienst bleibt bestehen.
Eigene lokale App `krautl-lokal`, Version `0.1.0`, eigener gleichnamiger Benutzer,
Scopes `items.read` und `items.write`. Registrierung abgeschlossen. API-Key liegt
auf dem Wawi-Server als Windows-DPAPI-geschützter SecureString in
`%LOCALAPPDATA%\Krautl\jtl-lokal-key.xml`, nur für den dortigen Benutzer/Rechner.
Keine Schlüssel in Chat, Git oder Diagnoseausgaben kopieren.

Zunächst HTTP 402 mit `No license available, rejecting request.` Nutzer hat die
REST-API bestellt, Lizenz in Wawi aktualisiert; inzwischen authentifizierter GET
des Kindes mit exakter ID/SKU bestätigt. Konkreter Abrechnungsbeginn nicht geprüft.
Cloud-HTML-Versuch um 13:47:14 lieferte 403 text/html; zeitgleiche lokale Logs zeigen
vorher/nachher GETs und GraphQL-Leseaufrufe, keinen PATCH. Verdacht auf Ablehnung
vor lokaler Verarbeitung, genaue Cloud-Komponente weiterhin unbekannt.

`scripts/teste_jtl_lokal.ps1` auf den Desktop des Wawi-Servers kopieren. Kein
Krautl-App-Neubau erforderlich. Ausführung im Windows-Benutzerkonto der Registrierung:

```powershell
powershell.exe -NoProfile -File "$env:USERPROFILE\Desktop\teste_jtl_lokal.ps1" -Anwenden
```

Nur Kind `40047-1000`, feste UUID, nur bestehender Shopwert des Inhaltsattributs,
Kanal `2-2-1`, Deutsch; Ziel `<p>Krautl FAQ Schreibtest 40047-1000</p>`.
Der Titel wird nicht geschrieben. Vollständige Attribut-Sicherung und Zielzustand
liegen in `%LOCALAPPDATA%\Krautl\jtl-lokal-html-40047-1000.json`; exklusive Erstellung
vor PATCH, kein automatischer Retry/Restore. Danach Vergleich aller Attributwerte,
inklusive anderer Sprachen und Kanäle. Bei vorhandenem Journal ausschließlich
`-Pruefen` statt `-Anwenden`; ohne beide Flags nur Vorschau. Journale nicht löschen,
um erneut zu schreiben. Ein erfolgreicher Absatztest ist noch keine Abnahme des
vollständigen FAQ-Exports oder der erstmaligen Attributzuordnung.

Der lokale Absatztest wurde am 09.10.2026 live erfolgreich abgenommen: exakter
Zielstand und alle anderen Attributwerte erhalten, Antwort mit korrekter Artikel-ID.
Das gleiche Absatz-HTML war zuvor im Cloud-Weg mit 403 abgelehnt worden.
Die dauerhafte Verbindung vom Krautl-Server zur lokalen
Wawi-API ist ebenfalls noch nicht eingerichtet. Keine öffentliche Portfreigabe erfolgt.

### Vollständiges FAQ-HTML auf demselben Kind testen

Aktuelles `scripts/teste_jtl_lokal.ps1` auf dem Wawi-Desktop ersetzen. In Krautl
beim Vaterprodukt `40047-000` unter FAQ „Aktuelles JTL-HTML kopieren“ wählen.
Den kopierten HTML-Text über die RDP-Zwischenablage auf dem Wawi-Server als UTF-8
speichern (die PowerShell-Befehlszeile zuerst vorbereiten, danach HTML kopieren):

```powershell
[IO.File]::WriteAllText((Join-Path $env:USERPROFILE 'Desktop\krautl-faq.html'), (Get-Clipboard -Raw), [Text.UTF8Encoding]::new($false))
```

Alternativ den vollständigen kopierten HTML-Text mit einem Editor als UTF-8 in
`krautl-faq.html` auf dem Wawi-Desktop speichern. Vor dem Schreiben Datei prüfen.

```powershell
powershell.exe -NoProfile -File "$env:USERPROFILE\Desktop\teste_jtl_lokal.ps1" -HtmlDatei "$env:USERPROFILE\Desktop\krautl-faq.html" -Anwenden
```

Eigenes Journal `jtl-lokal-faq-vollstaendig-40047-1000.json` im bisherigen
Sicherungsordner; Absatzjournal bleibt erhalten. Bei erneuter Prüfung denselben
Aufruf mit `-Pruefen` statt `-Anwenden` verwenden. Ohne beide Flags Vorschau mit
Zeichenanzahl. Der Titel `Fragen / Antworten` bleibt wie alle übrigen Werte erhalten.
Vollständiges HTML anschließend live erfolgreich abgenommen. Tests decken langen Unicode-Text,
separate Journale und UTF-8-Rücklesen unter Windows PowerShell 5.1 ab.

## Bestätigter Einrichtungsstand

- `krautl-intern` Version `0.1.0` im Partnerportal registriert und im Hub für
  `dreikraut e.K.` erfolgreich installiert; Artikelverwaltung Lesen/Schreiben.
- App-ID: `db191954-ccfa-4ec6-a066-4099db495e35` (keine Tenant-ID).
- Eigener Service-Account erstellt. Client-ID und Secret sind laut Nutzer in der
  Server-`.env` hinterlegt; keine Zugangsdaten hier dokumentieren.
- Hub-Verbindungsstatus: JTL-Wawi verbunden, Version `2.1.1+Sha.6aebf42`.
- Tenant `5bb11f28-30fd-4966-84c5-f59d3841c64b`: lesender API-Zugriff am
  09.10.2026 mit eigenen Krautl-Zugangsdaten für `40047-000` und `30014` bestätigt.
- REST-Kurztext-Schreibabnahme am Kind `40047-1000` erfolgreich (siehe unten).
  Vollständiger HTML-Auftrag inzwischen lokal abgenommen. Noch offen: produktiver
  HTTPS-Dauerbetrieb, erstmalige Zuordnung auf weiteren Artikeln und Wawi-Shopabgleich.
- Erster Spirulina-PATCH am 09.10.2026: HTTP 403. Rücklesen bestätigt exakt den
  gesicherten Ausgangsstand. Hub, registriertes Manifest und der vom Server
  ausgestellte Token enthalten `items.read` und `items.write`; Client-ID stimmt
  mit `app-db191954-ccfa-4ec6-a066-4099db495e35` überein. Ursache noch ungeklärt.
  Der erste Test speicherte keine Antwortdetails; aus 403 allein keine Ursache ableiten.
- Zweiter REST-Versuch ebenfalls HTTP 403 mit `text/html`, danach Ausgangsstand
  erneut bestätigt. Lesende GraphQL-Abfragen mit und ohne vollständigen gesicherten
  Attributinhalt liefern HTTP 200. Keine Proxy-Umgebungsvariable auf dem Server.
  Live-Introspektion bestätigt `ChangeItem(request: ChangeItemCommandRequestInput!)`
  mit `itemId: ID!`, `attributes: UpdateItemAttributesInput` und Objektantwort
  `ChangeItemCommandResponse!`. Die Ursache des REST-403 ist damit noch nicht bewiesen.
- GraphQL-Schreibversuch: HTTP 400, `An unexpected error occurred.` Anschließend
  Ausgangsstand unverändert rückgelesen. Noch kein erfolgreicher Schreibnachweis.
  Konkreter Prüfpunkt: Bestand enthält `languageIso: null`, während das REST-
  Schreibschema eine Zeichenkette verlangt. Nicht ungeprüft in `de` umwandeln.
  `scripts.pruefe_jtl_schreibschema` prüft den gesicherten Auftrag anhand der Live-
  GraphQL-Inputtypen ausschließlich lesend. Es überträgt keine Attributwerte und
  meldet Feldpfade statt Inhalte. Ein gültiges Inputschema beweist noch keine
  gültigen Geschäftsregeln und keine sichere partielle Aktualisierungssemantik.
- Live-Schemaprüfung bestätigt zwölf fehlende Pflichtfelder `languageIso` in
  mitgesendeten fremden Bestandsattributen des Vaterartikels. Nicht als `de` ergänzen.

## Explizit freigegebener Kind-Test 40047-1000

Der Nutzer hat den Kindartikel `40047-1000` für die Teilupdate-Abnahme ausgewählt.
`scripts.teste_jtl_spirulina_kind` sendet ausschließlich die zwei FAQ-Werte auf
Deutsch für Kanal `2-2-1`, nachdem der Auftrag gegen das Live-GraphQL-Schema geprüft
wurde. Die Artikel-ID wird ausschließlich über diese exakte SKU aufgelöst.
Quelle sind die aktuell ausgewählten Krautl-FAQ des Vaterprodukts `40047-000`.
Der Vater wird nicht verändert, keine automatische Vererbung wird eingeschaltet.

Vorher werden alle Attributwerte des Kindes in einer eigenen dauerhaften Datei
`var/jtl-test/spirulina-kind-40047-1000.json` gesichert. Der Vater ist kein Ersatz
für diese Sicherung. API-Antwort und Ergebnis erhalten separate Dateien. Bei Fehler
oder Verlust anderer Werte keine automatische Wiederholung oder Wiederherstellung:
Der vollständige Lesestand ist wegen sprachneutraler Attribute nicht ohne Weiteres
schreibbar. Dann anhand der Sicherung gezielt wiederherstellen. Der Nutzer hat den
Test trotz noch ungeklärter Teilupdate-Semantik ausdrücklich beauftragt.

```bash
cd /opt/app/krautl &&
git remote set-url origin https://github.com/erikdreikraut/krautl.git &&
git switch main &&
git pull --ff-only origin main &&
docker compose build app &&
docker compose run --rm --no-deps -v /opt/app/krautl/var/jtl-test:/jtl-test app \
  python -m scripts.teste_jtl_spirulina_kind --anwenden
```

Ohne `--anwenden`: nur Vorschau. Mit `--pruefen`: nur Vergleich mit dem vorhandenen
Kind-Journal. Während des Tests Kind und FAQ-Auswahl nicht bearbeiten. Der Test liest
auch bei einer API-Fehlermeldung zurück; bei Netzwerkabbruch separat `--pruefen`
aufrufen. Erfolg erfordert erfolgreichen API-Aufruf und den exakten vollständigen
Zielstand, einschließlich aller unveränderten anderen Attributwerte. Kein Neustart
der laufenden App erforderlich. Ergebnis gilt zunächst nur für diesen Artikeltest.

Erster Kind-Aufruf lieferte HTTP 200 ohne GraphQL-Fehler, aber sofortiges und späteres
Rücklesen bestätigen den unveränderten Ausgangsstand. Bisher wurde nur `__typename`
angefordert; das beweist keine ausgeführte Änderung. Die offizielle Antwortstruktur
enthält `item` (geänderter Artikel). Der Kind-Test fordert jetzt `item { id }` an und
verlangt die passende ID sowie den vollständigen Rücklesenachweis. Ob die frühere
Typabfrage die Ausführung verhindert hat, ist noch unbestätigt.

Einmalig kann `--ergebnis-test` statt `--anwenden` verwendet werden. Dafür müssen
der ursprüngliche Auftrag, die aktuelle FAQ-Auswahl und der Wawi-Ausgangsstand
übereinstimmen. Originaljournal und Idempotenzschlüssel bleiben erhalten; eine
separate `.item-ergebnis`-Datei sperrt Wiederholungen. Bei Fehler nur `--pruefen`.

## Implementiert und noch offen

### Diagnose nach manueller Zuordnung am Kind

Auch `item { id }` und ein weiterer Auftrag nach manueller Zuordnung beider
Attribute lieferten HTTP 200 mit passender ID, aber unveränderten Attributstand.
Der separat gelesene Stand und das Journal `spirulina-kind-40047-1000-angelegt.json`
bestätigen beide Zielattribute auf `2-2-1` / `de`: Inhalt 11 Zeichen, Titel 18 Zeichen
und korrekt `Fragen / Antworten`. Die fehlende Zuordnung erklärt den letzten
Fehlschlag somit nicht. Noch keine erfolgreiche Schreibabnahme. Nutzer möchte
keinen Supportkontakt; weitere technische Tests fortsetzen.

Der Kurztext-Test isoliert HTML/Inhaltsgröße vom Schreibweg. Er verwendet temporär
`Krautl FAQ Schreibtest 40047-1000` als Inhalt und den regulären FAQ-Titel. Er
verlangt beide schon vorhandenen deutschen Shopwerte. Keine Datenbank-FAQ werden
verändert. Ein Erfolg bestätigt nur diesen Texttest, noch keinen HTML-Export.
Danach muss der reguläre FAQ-Inhalt in einem gesondert gesicherten Auftrag folgen.

```bash
docker compose run --rm --no-deps -v /opt/app/krautl/var/jtl-test:/jtl-test app \
  python -m scripts.teste_jtl_spirulina_kind --kurztext-test --anwenden
```

Standard ist GraphQL. `--transport rest` ist als separater Vergleich vorgesehen, keine
automatische Ausweichroute. Beide Varianten haben eigene dauerhafte Journale
`spirulina-kind-40047-1000-kurztext-graphql.json` bzw. `...-rest.json`. Mit denselben
Auswahlflags und `--pruefen` statt `--anwenden` wird ausschließlich zurückgelesen.
Ohne `--anwenden` nur Vorschau. Keine Wiederholung durch Löschen der Journale.

09.10.2026, 11:28:28 GMT: REST-Kurztext am Kind erfolgreich. Nutzer-Ausgabe bestätigt
`ziel_erreicht`, `andere_bestandswerte_erhalten`, `exakter_zielstand` und
`test_erfolgreich` jeweils true. Unmittelbar zuvor gleicher Kurztext per GraphQL
ohne Wirkung. Keine zusätzlichen deutschen Standardwerte zwischen den Versuchen
angelegt. Das belegt REST-Schreiben für diese Shopwerte, nicht die genaue Ursache
der GraphQL-Wirkungslosigkeit oder der früheren REST-403 mit großem HTML-Auftrag.

Nächster Schritt: vollständiges ausgewähltes FAQ-HTML per REST an denselben Kindartikel:

```bash
docker compose run --rm --no-deps -v /opt/app/krautl/var/jtl-test:/jtl-test app \
  python -m scripts.teste_jtl_spirulina_kind --transport rest --anwenden
```

Eigene Sicherung `spirulina-kind-40047-1000-html-rest.json`, eigener Idempotenzschlüssel,
beide Zielwerte müssen bereits vorhanden sein. Bei Erfolg ersetzt der FAQ-Export den
temporären Kurztext. Bei Fehler nur mit `--transport rest --pruefen` rücklesen.
Keine automatische Wiederholung oder Vererbung. Anlage fehlender Attribute weiterhin
nicht abgenommen. Der Vaterartikel bleibt unverändert.

Der separate Sprachenabruf scheiterte mit HTTP 403. Laut öffentlichem 2.1-Schema
braucht `/v2/languages/activated` `system.config.read`; das ist kein Gegenbeweis
zu den bestätigten Artikelrechten. Keine zusätzlichen Rechte dafür angefordert.

Implementiert: Manifest, serverseitiger OAuth-Client, exakte Artikelnummern-Auflösung
via GraphQL, lesende V2-Artikeldiagnose, vereinheitlichte FAQ-Freigabe und einmalige
Migration der bisherigen Exportauswahl. Keine produktive Migration ausgeführt.

Implementiert ist außerdem ein isolierter, expliziter PATCH-Test ausschließlich für
Spirulina (siehe unten). Der direkte Dauerabgleich ist inzwischen implementiert
(siehe oben); noch keine Statusanzeige in der Oberfläche. Die Diagnoseroutine bleibt
rein lesend. Der alte Vater-Test überträgt den vollständigen gesicherten Attributstand, mit nur
zwei geänderten Zielwerten: damit werden übrige Werte sowohl bei Ersetzen als auch
bei Zusammenführen der Listen mitgeliefert. Keine ungeprüften partiellen Listen senden.

## Einmaliger Spirulina-Schreibtest

Durch API-Ausgabe zu `30014` und die zugehörigen Wawi-Screenshots bestätigt:

| Feld | Attribut-ID |
| --- | --- |
| `tab1 inhalt` | `29708817-225b-4208-9a57-5ff511000000` |
| `tab1 name` | `29708817-225b-4208-9a57-5ff512000000` |

Ziel: Kanal `2-2-1`, Sprache `de`. Der alte Referenztitel `Fragen / Anworten`
(17 Zeichen) passt exakt zum Diagnose-Hash
`0c61608025b20e5c5fc02685443ac18725aa52cd90238996ca0a7b62e65bfbe3`.
Geschrieben wird ausdrücklich **Fragen / Antworten**. Referenzartikel `30014` bleibt unverändert.
Zielartikel: `40047-000`, UUID `770f139d-18dd-405c-9f84-322131010000`.

Während des Tests Spirulina weder in Wawi noch in Krautl bearbeiten. Der Test liest
vor dem Schreiben erneut und bricht bei geänderten Attributwerten ab; die API bietet
hier keinen nachgewiesenen atomaren Vergleichsschutz. Der Ersttest bricht auch bei
fehlenden ausgewählten FAQ ab. Er ergänzt fehlende Zielattribute und erhält bestehende
andere Sprachen, Kanäle, Standardwerte und Attribute. Es wird nur `attributes` gesendet.
Die tatsächlich installierte API muss den vollständigen Stand akzeptieren; vorhandene
sprachneutrale Werte werden unverändert mit `languageIso: null` weitergegeben.
Ein Validierungsfehler ist kein erfolgreicher Test und wird nicht automatisch wiederholt.

Serverbefehle für den explizit angeforderten Test:

```bash
cd /opt/app/krautl &&
git remote set-url origin https://github.com/erikdreikraut/krautl.git &&
git switch main &&
git pull --ff-only origin main &&
docker compose build app &&
mkdir -p var/jtl-test &&
docker compose run --rm --no-deps -v /opt/app/krautl/var/jtl-test:/jtl-test app \
  python -m scripts.teste_jtl_spirulina --anwenden
```

Ohne `--anwenden` wird nur die Vorschau ausgegeben. Das Skript erzeugt das HTML mit
dem bestehenden Exporter aus den aktuell ausgewählten FAQ. Vor dem einzigen PATCH
legt es exklusiv `var/jtl-test/spirulina.json` mit Vorher-/Zielstand und Idempotenzschlüssel
an, ohne Zugangsdaten. Das Verzeichnis ist nicht öffentlich und wird nicht committet.
Die Rückleseprüfung vergleicht sämtliche Attributwerte; HTTP 200 allein genügt nicht.
Bei Timeout oder Abbruch das Journal **nicht löschen**, keinen neuen Schreibversuch
erzwingen. Stattdessen ausschließlich rücklesen:

```bash
cd /opt/app/krautl &&
docker compose run --rm --no-deps -v /opt/app/krautl/var/jtl-test:/jtl-test app \
  python -m scripts.teste_jtl_spirulina --pruefen
```

Der einmalige Container erfordert keinen Neustart der laufenden Anwendung. Für die
reguläre Übernahme des gebauten App-Images anschließend `docker compose up -d --wait app worker`.
Auch eine erfolgreiche Rückleseprüfung belegt noch keinen erfolgten Wawi-Shopabgleich.

### Kontrollierte Diagnose des bestätigten 403

`--diagnose-403` ist ein ausdrücklich gestarteter weiterer Schreibversuch, keine
rein lesende Diagnose. Er verwendet ausschließlich den ursprünglichen gesicherten
Auftrag und denselben Idempotenzschlüssel, prüft vorher den unveränderten Wawi-Stand
und die weiterhin identische aktuelle FAQ-Auswahl. Ist das Ziel bereits vorhanden,
wird nicht geschrieben. Eine separate dauerhafte `.diagnose403`-Datei begrenzt den
Versuch auf einmal; Originaljournal und Sperre niemals zur Wiederholung löschen.
Alle PATCH-Antworten werden jetzt in separaten `.antwort-<UUID>.json`-Dateien neben
dem Journal mit ausgewählten Fehlerfeldern und Diagnose-Headern gespeichert.
Token und Client-Secret werden herausgefiltert; vollständige Antwortkörper und
vollständige Request-/Response-Header werden nicht gespeichert.

Nach Aktualisierung der Arbeitskopie und `docker compose build app`:

```bash
cd /opt/app/krautl &&
docker compose run --rm --no-deps -v /opt/app/krautl/var/jtl-test:/jtl-test app \
  python -m scripts.teste_jtl_spirulina --diagnose-403
```

Bei weiterem Fehler die Diagnose auswerten und ausschließlich mit `--pruefen`
rücklesen. Keine Rechteänderung oder Neuinstallation allein aufgrund des Statuscodes.

### Bestätigter GraphQL-Schreibweg

Nach gesichert unverändertem Ausgangsstand ist mit `--graphql` ein einzelner Versuch
über die reguläre, in dieser Installation bestätigte `ChangeItem`-Mutation möglich.
Der Originalauftrag, Tenant-/Artikelbindung, FAQ-Vergleich und Rücklesevergleich
bleiben erhalten. Ein vorhandener Zielstand löst keinen Schreibzugriff aus.
Die separate dauerhafte `.graphql`-Sperre verhindert Wiederholungen auch bei Timeout.
Es wird der ursprüngliche Idempotenzschlüssel mitgesendet; seine Unterstützung für
GraphQL wird nicht vorausgesetzt. Keine automatische Wiederholung über irgendeinen Transport.
HTTP 200 mit GraphQL-Fehlern oder ohne `data.ChangeItem` gilt nicht als Erfolg.
Die Antwortdiagnose erfasst nun auch Azure-Referenz, Datum und GraphQL-Fehlermeldungen.

```bash
cd /opt/app/krautl &&
git remote set-url origin https://github.com/erikdreikraut/krautl.git &&
git switch main &&
git pull --ff-only origin main &&
docker compose build app &&
docker compose run --rm --no-deps -v /opt/app/krautl/var/jtl-test:/jtl-test app \
  python -m scripts.teste_jtl_spirulina --graphql
```

## Bestätigter fachlicher Umfang

- Artikelzuordnung ausschließlich über eindeutige, exakt passende Artikelnummer;
  führende Nullen erhalten. Krautl-Produkt-ID ist keine JTL-Artikel-UUID.
- Deutsch, dreikraut JTL-Shop: `tab1 name` = `Fragen / Antworten`, `tab1 inhalt` =
  der vorhandene HTML-Export (`faq_als_jtl_html`). Andere Kanäle/Sprachen und
  Attribute bleiben erhalten. „tab2 name“ war ein inzwischen geklärter Versprecher.
- Nur über „In FAQ aufnehmen“ ausgewählte FAQ übertragen (intern freigegeben und
  aktiv). Die Auswahl ist in Übersicht und Editor verfügbar; kein Status-Dropdown. Die bisherigen aktiven Entwürfe werden beim Deployment
  einmalig freigegeben; neue Entwürfe bleiben ausgeschlossen.
- Beim Entfernen/Deaktivieren des letzten übertragbaren FAQ sowohl Titel als auch
  Inhalt leeren. Google-FAQ-Auswahl beeinflusst den JTL-Abgleich nicht.

## Eigene App registrieren

1. Im JTL-Partnerportal eine eigene interne App in der richtigen Organisation
   registrieren. [manifest.json](manifest.json) in den JSON-Editor übernehmen.
   Der Manifestentwurf enthält `items.read` und `items.write` sowie die bestehende
   Krautl-HTTPS-Adresse als Hub-Launcher. Kein zusätzliches Hosting erforderlich.
2. Eigene Client-ID und eigenes Secret ausschließlich in der Server-`.env` speichern:
   `JTL_CLIENT_ID`, `JTL_CLIENT_SECRET`. Keine Geheimnisse in Chat, Git oder Screenshots.
3. App für die Zielorganisation im JTL Hub installieren und Rechte bestätigen.
4. `JTL_TENANT_ID` mit dem bestätigten ERP-Tenant setzen. Werkels historischer Tenant
   war `5bb11f28-30fd-4966-84c5-f59d3841c64b`; vor Übernahme prüfen.
5. App-ID/Version und Tenant-Zuordnung bei der Einrichtung festhalten. Zugangsdaten
   nicht aus Werkels `.env` übernehmen. Die Hub-Kachel ersetzt Krautls Login nicht.

## Deployment der Vorbereitung und FAQ-Umstellung

Die Migration nur nach Backup nach dem regulären Serververfahren ausführen. Sie
speichert ihre betroffenen FAQ-IDs in `krautl_datenmigration` und läuft in einer
Transaktion; erneuter Aufruf gibt spätere Entwürfe nicht frei. Während des kurzen
Deployments keine FAQ bearbeiten, damit alte und neue Bedienlogik nicht überlappen.

```bash
cd /opt/app/krautl &&
git remote set-url origin https://github.com/erikdreikraut/krautl.git &&
git switch main &&
git pull --ff-only origin main &&
docker compose build app frontend &&
docker compose stop app worker &&
docker compose run --rm --no-deps app python -m scripts.migrate_faq_freigabe &&
docker compose up -d --wait app worker frontend &&
docker compose ps
```

Bei einem Migrationsfehler bleibt die Befehlsfolge stehen; Fehler klären und App/Worker
anschließend gezielt wieder starten. Keine direkte JTL-Änderung durch diese Version.

## Lesende Diagnose

Nach Hinterlegen der drei JTL-Variablen kann ein einmaliger Container mit der aktuellen
`.env` ausgeführt werden, ohne das Passwort auszugeben. Den Platzhalter ersetzen:

```bash
docker compose run --rm --no-deps app python -m scripts.pruefe_jtl_faq_anbindung --artikelnummer 'EXAKTE-ARTIKELNUMMER'
```

Das Ergebnis nennt Artikel-UUID, Attribut-UUIDs, Kanal und Sprache, Länge/Hash und
Marker für den FAQ-Titel bzw. FAQ-HTML. Es gibt weder Token noch volle Attributinhalte
aus. Kandidaten anhand des bekannten Artikels in Wawi den Attributnamen zuordnen;
Marker allein sind kein Beweis. Historisch in Werkel bestätigter Shopkanal: `2-2-1`.
Die API kann pro Installation andere Rechte oder Daten liefern; 403 ist ein Fehler,
kein leeres Ergebnis. Ein 401 erneuert den Token höchstens einmal.

## Nächster Implementierungsschritt

Nach der lesenden Abnahme: Sprache/Kanal/Attribut-IDs fest binden, Schreibsemantik an
einem geeigneten Testartikel belegen und erst dann einen dauerhaften Auftragsstatus
mit Vorher-/Nachher-Prüfung implementieren. Nur geänderte HTML-Stände übertragen;
FAQ-Bearbeitung, Freigabe, Rubrikänderung und Löschen berücksichtigen. Fehler sichtbar
machen; bei Timeout oder Neustart während eines PATCH erst den Iststand lesen,
keinen unklaren Schreibauftrag blind wiederholen. Fremde Änderungen zwischen Lesen
und Schreiben berücksichtigen. Ein Initialabgleich muss als solcher sichtbar sein.
Danach Automatik für die bestätigten Produkte aktivieren und den Wawi-Shopabgleich
prüfen: erfolgreiche API-Änderung belegt noch keine Aktualisierung im Onlineshop.

## Technische Quellen

- [JTL App Manifest](https://developer.jtl-software.com/cloud/guides/cloud-apps/app-manifest)
- [Service Account](https://developer.jtl-software.com/cloud/guides/cloud-apps/service-account-authentication)
- [OpenAPI 2.1](https://developer.jtl-software.com/openapi/erp/2.1.json), am 07.10.2026 frisch geprüft:
  `GET/PATCH /v2/items/{itemId}`, `attributes.values[].attributeId`,
  `salesChannelValues[].salesChannelId`, `values[].languageIso/value`.
- Lokale Werkel-Übergabe: `C:/Users/info/Documents/ChatGPT/Werkel/docs/krautl-jtl-anbindung.md`.
