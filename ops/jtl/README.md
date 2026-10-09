# JTL-FAQ-Anbindung: Einrichtung und Abnahme

Stand: 09.10.2026. Eigene interne Krautl-App; Werkel bleibt unverändert.

## Bestätigter Einrichtungsstand

- `krautl-intern` Version `0.1.0` im Partnerportal registriert und im Hub für
  `dreikraut e.K.` erfolgreich installiert; Artikelverwaltung Lesen/Schreiben.
- App-ID: `db191954-ccfa-4ec6-a066-4099db495e35` (keine Tenant-ID).
- Eigener Service-Account erstellt. Client-ID und Secret sind laut Nutzer in der
  Server-`.env` hinterlegt; keine Zugangsdaten hier dokumentieren.
- Hub-Verbindungsstatus: JTL-Wawi verbunden, Version `2.1.1+Sha.6aebf42`.
- Tenant `5bb11f28-30fd-4966-84c5-f59d3841c64b`: lesender API-Zugriff am
  09.10.2026 mit eigenen Krautl-Zugangsdaten für `40047-000` und `30014` bestätigt.
- Noch offen: tatsächliche Schreibabnahme auf dem Server und Wawi-Shopabgleich.

## Implementiert und noch offen

Implementiert: Manifest, serverseitiger OAuth-Client, exakte Artikelnummern-Auflösung
via GraphQL, lesende V2-Artikeldiagnose, vereinheitlichte FAQ-Freigabe und einmalige
Migration der bisherigen Exportauswahl. Keine produktive Migration ausgeführt.

Implementiert ist außerdem ein isolierter, expliziter PATCH-Test ausschließlich für
Spirulina (siehe unten). Noch NICHT implementiert: dauerhafte Synchronisierungsaufträge,
Automatik und Synchronisierungsstatus in der Oberfläche. Die Diagnoseroutine bleibt
rein lesend. Der Test überträgt den vollständigen gesicherten Attributstand, mit nur
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
