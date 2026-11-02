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
