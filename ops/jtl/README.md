# JTL-FAQ-Anbindung: Einrichtung und Abnahme

Stand: 09.10.2026. Eigene interne Krautl-App; Werkel bleibt unverändert.

## Bestätigter Einrichtungsstand

- `krautl-intern` Version `0.1.0` im Partnerportal registriert und im Hub für
  `dreikraut e.K.` erfolgreich installiert; Artikelverwaltung Lesen/Schreiben.
- App-ID: `db191954-ccfa-4ec6-a066-4099db495e35` (keine Tenant-ID).
- Eigener Service-Account erstellt. Client-ID und Secret sind laut Nutzer in der
  Server-`.env` hinterlegt; keine Zugangsdaten hier dokumentieren.
- Hub-Verbindungsstatus: JTL-Wawi verbunden, Version `2.1.1+Sha.6aebf42`.
- Noch offen: ERP-Tenant-ID bestätigen, lesende Artikeldiagnose und Schreibabnahme.
  Die erfolgreiche Installation belegt noch keinen geprüften Krautl-API-Aufruf.

## Implementiert und noch offen

Implementiert: Manifest, serverseitiger OAuth-Client, exakte Artikelnummern-Auflösung
via GraphQL, lesende V2-Artikeldiagnose, vereinheitlichte FAQ-Freigabe und einmalige
Migration der bisherigen Exportauswahl. Keine produktive Migration ausgeführt.

Noch NICHT implementiert: dauerhafte Synchronisierungsaufträge, Artikel-PATCH,
Automatik und Synchronisierungsstatus in der Oberfläche. Dafür zuerst eigene
Credentials, Tenant und Attribut-UUIDs am bekannten Artikel lesen und die tatsächliche
PATCH-Semantik der installierten Wawi-Version nachweisen. Die aktuellen offiziellen
Schemas beschreiben Listenstrukturen, aber nicht hinreichend, ob die enthaltenen
Listen ersetzt oder zusammengeführt werden. Keine Live-Schreibexperimente auf
Verdacht. Die Diagnoseroutine führt ausschließlich lesende ERP-Operationen aus.

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
