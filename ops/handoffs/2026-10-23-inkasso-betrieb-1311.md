# Übergabe: Inkasso und wiederkehrende Deployment-Ausfälle

## 1. Start in 30 Sekunden

- Stand: 23.10.2026, 13:11 Europe/Berlin; abgeschlossene Übergabe.
- Ziel: Krautl im vorhandenen Stand fortsetzen; zuerst wiederkehrende Container-Neuerstellungen/502 und den auffälligen FAQ-Abgleich untersuchen.
- Status: Featurearbeit abgeschlossen; Betriebsdiagnose wartet auf Server-Ausgaben. Aktueller Nutzerauftrag ist Übergabe, kein neuer fachlicher Ausbau.
- Nächster Schritt: Arbeitsstand prüfen, dann fehlende Docker-Ereignisse/Containerübersicht vom Server erbitten, falls Problem noch besteht. Keine blinden Builds/Neustarts.
- Ursprungsaufgabe: dieser Chat; zuverlässige Chat-ID nicht verfügbar.

## 2. Auftrag und Grenzen

- Nutzer hat alle Inkasso-Funktionen für alle Sachbearbeiter ausdrücklich autorisiert (auch nach einer anfänglichen automatischen Freigabeblockade). Kein erneutes Nachfragen zu dieser Freigabe nötig.
- Alle Rechnungen bleiben für alle Admins/Sachbearbeiter sichtbar, auch bei persönlicher Zuweisung. Zuweisung ist keine Zugriffssperre.
- Nutzerentscheidungen stehen in Projekt-AGENTS.md: einzelne Personen statt Rollen, blassrote eigene Zuweisungen, kompakte Spalte, „Alle“ statt leer; nur Vornamen in Inkasso. Volle Namen für Signaturen.
- Notizen ausschließlich hinzufügen, nie alte Einträge editieren/löschen. Datum/Zeit/Urheber serverseitig. Automatische Zuweisungsnotiz gehört atomar zur Zuweisung.
- Kein Mahnversand, keine Gutschriften oder Zahlungsänderungen in Wawi beauftragt. Keine Deployment-Ausführung durch den Agenten freigegeben; Nutzer führt Serverbefehle aus.
- Keine Unteragenten ohne ausdrücklichen Auftrag. Keine neue Aufgabe eigenmächtig anlegen.
- Geltende Anweisungsdateien: `C:/Users/info/.codex/AGENTS.md` global; `C:/Users/info/Documents/Codex/Krautl/AGENTS.md` projektweit. Beide geprüft. In geprüften Vorfahren und Projekt keine zusätzlichen AGENTS.override.md/Unterbereichsregeln gefunden; alternative konfigurierte Namen nicht geprüft.
- Fachliche Dokumente: `C:/Users/info/Documents/Codex/Krautl/README.md` (Inkasso-Betrieb, Registrierung, Notizen/Zuweisung und Deployment); `C:/Users/info/Documents/Codex/Krautl/ops/jtl/README.md` (FAQ-Abgleich und Schreibschutz vor Arbeiten daran).
- Globale Präferenzen noch nicht gespeichert: keine aus diesem Verlauf offen. Globale Regeln wurden nicht geändert.

## 3. Gesicherter Arbeitsstand

| Gegenstand | Ergebnis/Status | Nachweis |
| --- | --- | --- |
| Code | main, f0586a7b51e07e4374c6b2b43f19ba722318dd01, gepusht | HEAD und origin/main per ls-remote am 23.10.2026 identisch |
| Erweiterter API-Zugang | krautl-inkasso-lesen aktiviert, alter Zugang gesichert | Nutzer-Screenshot: Channels, Invoices, SalesOrders, Kundenliste/-einzelabruf alle HTTP 200 und Aktivierungsbestätigung |
| UI und Berechtigungen | Implementiert und getestet | siehe historische Prüfungen unten |
| Produktion | Nutzer hat Builds/Deployments durchgeführt; UI-Screenshots bestätigen viele Funktionen | Letzte exakte laufende Image-/Commit-Zuordnung unbekannt |
| HTTPS | Am 22.10.2026 um 12:17 Berlin öffentlich HTTP 200 mit normaler Zertifikatsprüfung | curl.exe -I https://krautl.erikschweitzer.de/; spätere SSL-Frage ausdrücklich falsches Projekt |
| Wiederkehrende 502 | Ursache offen | Mehrfach Docker-Fehler bei Neuerstellung; Frontend Created statt Running, Start half |
| FAQ-Sync | zuletzt unhealthy | Nutzerprotokoll, kein Ursachenbefund |

Abgeschlossen: Rechnungsv1-Import, Shop/Wawi-Zuordnung, Telefon-/Bestellübersicht, Zahlungsfilter, Auswahlaktualisierung, append-only Notizen, Acht-Wochen-Abschnitte, Sachbearbeiterzugang, Personenzuweisung mit Protokoll, vollständige Namen, kompakte Zuweisung mit „Alle“.

Offen: Betriebsdiagnose. Außerdem historischer Wunsch nach schlankerem täglichen Abruf: noch NICHT umgesetzt. v1 lädt weiterhin offene/teilbezahlte Rechnungen seitenweise und prüft gespeicherte Fälle; nicht behaupten, täglich würden nur sieben Tage geladen. Es wurden nicht jedes Mal alle 370.000 Rechnungen geladen. Manuelle Auswahlaktualisierung bleibt gezielt.

Tatsächliche externe Datenänderungen: Nutzer registrierte/freigab neuen Wawi-Lesezugang und aktivierte ihn; Kandidat liegt unter `/app/var/inkasso-zugang/lesezugang/`, aktive Datei `zugang.json`, Sicherung `zugang-vor-lesezugang.json`. Nicht erneut registrieren, löschen oder Schlüssel anzeigen. Notizen/Zuweisungen wurden produktiv von Nutzern gespeichert; Screenshots zeigen dies. Agent hat keine Nachrichten versendet und keine Produktivdaten direkt geändert. Keine Änderungen am FAQ-Zugang oder Werkel.

## 4. Arbeitsumgebung und Änderungen

- Derselbe Windows-Host, Arbeitskopie `C:/Users/info/Documents/Codex/Krautl`. PowerShell. Nicht den veralteten Dropbox-Projektpfad verwenden.
- Remote `https://github.com/erikdreikraut/krautl.git`, Branch main. Codebaseline f0586a7; diese Übergabe und gezielte AGENTS-Pflege kommen als separater Dokumentationscommit danach.
- Vor Übergabe keine getrackten lokalen Änderungen. Fünf bereits unversionierte Übergaben unter `ops/handoffs/` bleiben unberührt und werden NICHT mitcommittet. Fortsetzung auf gleichem Host, keine Übertragung auf andere Hosts geprüft.
- Neue Übergabedatei: `C:/Users/info/Documents/Codex/Krautl/ops/handoffs/2026-10-23-inkasso-betrieb-1311.md`.
- Skill am Ziel geprüft vorhanden: `C:/Users/info/.codex/skills/weiter/SKILL.md`. Vorlage: `C:/Users/info/.codex/handoff-template.md`.
- Relevanter Code: app/inkasso.py (Snapshot/API/Telefonfallback), app/inkasso_notizen.py (SQLite-Historie und Zuweisungen), app/inkasso_auftrag.py (dauerhafte Auswahlqueue), app/inkasso_service.py (Worker), app/inkasso_zugang.py (Registrierung), app/auth.py und app/mail_versand.py (volle Namen/Signaturen), frontend/src/InkassoView.jsx, frontend/src/App.jsx, frontend/src/api.js. Alle relativ zur obigen absoluten Arbeitskopie.
- Daten auf Server: `/opt/app/krautl/var/inkasso/stand.json`, `var/inkasso-notizen/notizen.sqlite3`, `var/inkasso-auftraege/`, `var/inkasso-zugang/`. Nicht durch lokale Dateien ersetzen. SQLite konsistent über Backup-API oder bei gestoppter App sichern.
- Keine agentseitigen laufenden Prozesse/Operationen. Serverkontrolle durch Nutzer; kein bestätigter SSH-Zugang. Normale Sandbox-Prozesse hingen gelegentlich, require_escalated funktionierte; keine Blockaden umgehen.

## 5. Prüfung und Ergebnis

| Zeitpunkt | Prüfung | Ergebnis | Stand |
| --- | --- | --- | --- |
| Historisch 22.10. | unittest tests.test_inkasso tests.test_jtl_sync tests.test_jtl_status | 49 Tests bestanden | Personenzuweisung 08cb5ca |
| Historisch 22.10. | npm test und npm run build | 23 Tests + Build bestanden | Personenzuweisung 08cb5ca |
| Historisch 22.10. | unittest tests.test_auth tests.test_mail_versand tests.test_inkasso | 40 Tests bestanden | volle Namen 5a6ec13 |
| Historisch 22.10. | npm run build | bestanden | kompakte Auswahl 770554a und „Alle“ f0586a7 |
| 23.10. Übergabe | Git-Status, HEAD, Remote, Pfade, Anweisungsquellen | geprüft | Codebaseline f0586a7 |

Keine erneuten Tests nötig nur wegen Übergabe. Frontend-Testläufe geben gelegentlich eine harmlose Meldung über belegten Vite-WebSocket-Port aus; Ergebnis separat prüfen. Keine live durchgeführte Prüfung am 23.10.

Betriebsbeobachtung: Nach reinen Frontend-Deployments waren auch App, DB und Mail-Worker jeweils neu erstellt, während Profil-Dienste jtl-sync und inkasso-sync alt blieben. Meldungen „No such container“ und „removal ... already in progress“ traten auf. Nutzer verneinte weitere manuelle Deployments/Kollegen. Automatischer Verwaltungsdienst ist eine Hypothese, kein bewiesener Befund. Nicht erneut als Tatsache behaupten. Frontend-Start per `docker compose start frontend` stellte mehrfach Erreichbarkeit her. Caddy-Warnungen zu HTTP/2/3 ohne TLS sind bei internem HTTP hinter Elestio erwartbar, kein SSL-Nachweis.

## 6. Konkrete Fortsetzung

1. Mit $weiter diese Übergabe übernehmen; dieselbe Arbeitskopie behalten, bestehende unversionierte Übergaben nicht anfassen.
2. Aktuellen Betriebszustand erfragen. Noch ausstehende lesende Serverdiagnose:
   ```bash
   docker events --since 30m --until "$(date -Iseconds)" --filter type=container --filter label=com.docker.compose.project=krautl --format '{{.Time}} {{.Action}} {{.Actor.Attributes.name}}'
   docker ps --format 'table {{.Names}}	{{.Image}}	{{.Status}}'
   ```
   Alte Ereignisse sind möglicherweise nicht mehr verfügbar. Dann gezielt bei nächstem Vorfall erfassen, nicht künstlich durch wiederholte Builds provozieren. Ziel: tatsächlichen Verursacher/Startablauf belegen. Nicht pauschal Docker/DB neu starten.
3. FAQ-Sync separat lesend über Logs/Healthcheck untersuchen, wenn weiterhin unhealthy; davor ops/jtl/README.md beachten. Keine unkontrollierten FAQ-Schreibwiederholungen.
4. Bei weiteren Codeänderungen passende Tests, Commit und Push main; danach konkrete Serverbefehle. Push ist kein Deployment. Vollständige Container-Neuerstellung nicht als Standardreparatur verwenden.

## Startauftrag für eine neue Aufgabe

$weiter Nutze die Übergabe unter C:/Users/info/Documents/Codex/Krautl/ops/handoffs/2026-10-23-inkasso-betrieb-1311.md und setze Krautl in C:/Users/info/Documents/Codex/Krautl fort. Prüfe zuerst lesend den aktuellen Stand. Offene Arbeit: wiederkehrende Container-Neuerstellungen/502 und zuletzt unhealthy gemeldeten FAQ-Abgleich eingrenzen. Keine weiteren Produktfunktionen ohne Auftrag, keine blinden Neustarts, keine erneute API-Registrierung, keine Produktivschreibaktionen. Erhalte vorhandene lokale Dateien und alle Inkasso-/FAQ-Schutzregeln.
