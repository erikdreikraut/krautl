# Begrenzter Cloud-Schreibtest fuer Artikel 1036

Stand 02.11.2026: vorbereitet, lokal mit simuliertem HTTP getestet. Noch kein
produktiver Cloud-Bildschreibnachweis. Die SQL-Bruecke bleibt pausiert.

Die eigene Hub-App und der Cloud-Service-Account wurden bereits fuer FAQ genutzt
(siehe README.md). Dieser Test verwendet ausschliesslich deren vorhandene
JTL_CLIENT_ID, JTL_CLIENT_SECRET und den fest gebundenen dreikraut-Tenant.
Keine neue Registrierung oder Berechtigungsfreigabe, kein SQL-Zugriff.

## Was der Test beweist

Ein PATCH an die Cloud-ERP-API vertauscht die vorhandenen Shop-Bildpositionen 1/2
von SKU 1036 und setzt das neue erste Bild als einziges Hauptbild. Alle anderen
im Bildblock enthaltenen Zuordnungen werden unveraendert mitgesendet und beim
Ruecklesen mitgeprueft. Der ausdruecklich ausgeschlossene Kassenkanal 9-7-8-0
wird weder geschrieben noch in den Erfolgsvergleich einbezogen.

Dies testet das Schreiben von Bildzuordnungen, NICHT den Upload/Austausch von
Dateiinhalten, den Erhalt nicht von der API gelieferter interner IDs/SEO-Daten
oder die Veroeffentlichung im Shop. Es gibt keinen Upload und keine Bildloeschung.
Die Wirkung der PATCH-Listen ist Teil der Abnahme, kein vorab garantierter Schutz.
Ein abweichender Bestand wird gemeldet und nicht automatisch repariert.

Dokumentierte API:
https://developer.jtl-software.com/cloud/api-reference/erp/v2.1/item/change-item

## Ausfuehrung auf dem Linux-Krautl-Server

Wawi-Shop-/Marktplatzabgleiche fuer den Test pausieren. Artikel 1036 waehrenddessen
weder in Wawi noch in Krautl parallel bearbeiten; keine offenen Bildschreibvorgaenge
laufen lassen. Ein Vergleich unmittelbar vor PATCH ist keine atomare Schreibsperre
gegen andere Anwendungen. Die temporaer geaenderte Reihenfolge kann sonst bereits
veroeffentlicht werden.

Nur neue Skriptdateien werden per stdin im vorhandenen App-Container ausgefuehrt.
Kein Build, Containerneustart, Datenbankmigration oder manuelles Deployment noetig.
Der bestehende Cloud-Client muss im Container vorhanden sein.

```bash
cd /opt/app/krautl &&
git remote set-url origin https://github.com/erikdreikraut/krautl.git &&
git pull --ff-only origin main &&
docker compose exec -T app python - --vorbereiten < scripts/teste_bilder_cloud.py
```

Vorbereitung sichert den kompletten gelesenen Artikelstand und das konkrete Ziel,
schreibt aber nicht an JTL. Erwartet: `zustand: ORIGINAL` und kein Testversuch.
Ein vorhandener Plan wird nie automatisch erneuert. Er darf beim Teststart maximal
zwei Stunden alt sein.

```bash
cd /opt/app/krautl &&
docker compose exec -T app python - --ausfuehren < scripts/teste_bilder_cloud.py
```

Erwartet nach Ruecklesen: `zustand: ZIEL`, `zuordnungen_bestaetigt: true`.
HTTP 200/201 ohne den passenden Bestand ist kein Erfolg. Bei 401/403/500/Timeout
kein automatischer zweiter Schreibversuch und kein Wechsel zu GraphQL/lokaler API.

Nur ruecklesen, auch nach einem Prozessabbruch:

```bash
cd /opt/app/krautl &&
docker compose exec -T app python - --pruefen < scripts/teste_bilder_cloud.py
```

Separat und ausdruecklich den Originalstand wiederherstellen:

```bash
cd /opt/app/krautl &&
docker compose exec -T app python - --zuruecksetzen < scripts/teste_bilder_cloud.py
```

Ruecksetzen erfordert einen eigenen protokollierten Testversuch und exakt das
gesicherte Testziel in allen geprueften Bildgruppen. Bei zwischenzeitlichen
Aenderungen wird nicht geschrieben. Auch der Ruecksetzversuch ist einmalig und
wird separat rueckgelesen. Erwartet: `ORIGINAL`, `zuordnungen_bestaetigt: true`.
Erst nach geklaertem Originalstand die pausierten Abgleiche wieder aufnehmen.

## Auftragsprotokoll

Fester Containerpfad `/app/var/bilder/cloud-test-1036`, durch den bestehenden
Compose-Mount auf dem Host unter `/opt/app/krautl/var/bilder/cloud-test-1036`.
`plan.json` sichert Ausgangsstand/Ziel. `*.intent.json` wird exklusiv angelegt
und vor jedem PATCH auf Datentraeger synchronisiert. Eine lokale SQLite-Sperre
verhindert parallele Skriptlaeufe im selben Verzeichnis. `*.result.json` haelt
HTTP-Status und den Ruecklesebefund fest, keine Tokens oder rohen Fehlerantworten.

Ordner nicht loeschen, um einen unklaren Versuch zu wiederholen. Auch eine
fehlgeschlagene Antwort verbraucht den Schreibversuch. Ein Prozessabbruch nach
der Absichtssicherung, aber vor dem HTTP-Aufruf, bleibt bewusst gesperrt.
Keine bestehenden Krautl-Auftraege oder Artikel-Snapshots werden zurueckgesetzt.


## Live-Vorprüfung 03.11.2026

`--vorbereiten` wurde per SSH auf dem Produktivserver ausgeführt. Abbruch vor
Plananlage/PATCH: `Unbekannte Bildfelder; keine Metadaten verwerfen.`
Keine Schreibabsichtsdateien vorhanden, kein Upload und keine Bildänderung.
Lesender Diagnosebefund unter
`/opt/app/krautl/var/bilder/cloud-test-1036/diagnose-20261103.json` gesichert
(ohne signierte Bild-URLs oder Zugangsdaten).

Konkrete Antwortprobleme für Artikel-UUID
`770f139d-18dd-405c-9f84-322128000000`:

- V2 liefert zusätzliche Felder `url`/`previewUrl`, die der vorbereitete Test
  nicht akzeptiert. Ein bloßes Weglassen dieser Felder löst die folgenden
  Identitätsprobleme nicht.
- Dem Shop-Hauptbild Position 1 fehlt `blobIdentifier` vollständig. Position 2
  hat `c930660a-27c0-4fa4-b2f8-3b3f6bc7e54d`.
- Mehrere unterschiedliche saleschannelImages-Gruppen tragen dieselbe
  saleschannelId `1-1-0`; sie lassen sich nicht eindeutig zurückschreiben.
- Direkte Wawi-v2-Antwort zeigt dieselben Probleme. Somit kein ausschließlich
  vom Cloud-Transport verursachter Befund.

Alternativer Cloud-Endpunkt GET /v1/items/{UUID}/images liefert HTTP 200 und
31 Einträge mit konkreten ImageId/SalesChannelId/SortNumber. Direkte v1-Antwort
ordnet im Shop Hauptbild 2729 auf Position 1 und Bild 2365 auf Position 2 zu.
Cloud-v1-Schreiben wurde NICHT getestet. Die bestehende lokale v1-Sortierlogik
ist ein Ansatz für einen separat protokollierten, eng begrenzten Cloud-v1-Test;
Lesbarkeit allein beweist keine Schreibfähigkeit.

Weiterer Vorbehalt: alter Auftrag `8b42f33a-d8aa-4933-9b61-15f58e2d9014`
ist weiterhin `unklar` (`ersetzen_alle`, 28.10.). Nicht löschen oder als erfolgreich
markieren, um einen Test zu ermöglichen. Vor neuem Schreibtest Bestandsabgleich
und Umgang mit diesem Altauftrag ausdrücklich klären. Die Bestätigung, dass
Shop-/Marktplatzabgleiche pausiert sind, steht ebenfalls noch aus.
