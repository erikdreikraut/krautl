# Krautl — Mail-Klassifikation & Backend für dreikraut

## Was hier bereits steht

- `app/models.py` — Datenbankschema (Mails, Klassifikation, Korrekturen,
  Entwürfe, Rechnungen, FAQ)
- `app/imap_client.py` — IMAP-Abruf + der aus n8n portierte Cross-Postfach-Move
  (inkl. "Schon am Ziel?"-Kurzschluss)
- `app/mail_parser.py` — parst rohe EML-Bytes in die Felder für Klassifizierung/DB
- `app/agent.py` — Klassifizierungs-Prompt + Tool-Schema für die Claude API
  (kein Versand-Tool — Sicherheitsprinzip aus CLAUDE.md)
- `app/rechnungen.py` — wertet PDF-, XML- und Bildrechnungen aus, erkennt
  Dubletten und legt Originale nach Jahr sortiert in Dropbox ab
- `app/audio_transkription.py` — transkribiert Audioanhänge, strukturiert
  den vollständigen Text und stellt ihn samt Originalaudio als interne Mail in
  `service@dreikraut.de/INBOX` bereit
- `app/worker.py` — führt einen vollständigen Abruf aller Postfächer aus:
  ruft neue Mails aus allen konfigurierten Postfächern ab, klassifiziert sie
  und führt die `MAIL_VERSCHIEBEN`-Aktion der Klassifikation aus, sofern das
  Zielpostfach konfiguriert ist
- `app/worker_service.py` — eigenständiger dauerhaft laufender Hintergrunddienst:
  startet sofort mit Docker, ruft `app/worker.py` minütlich auf und speichert
  sein letztes Lebenszeichen in der Datenbank
- `app/main.py` — FastAPI mit den Endpunkten, die die Oberfläche braucht
- `app/auth.py` — persönliche Anmeldung mit signierten Sitzungen für Erik,
  Gursewak und Ludwig; das Rollenfeld ist für spätere Rechteunterschiede
  bereits vorhanden
- `scripts/import_klassifikationen.py` — importiert/aktualisiert die
  `klassifikation`-Tabelle aus `data/mail-klassifikationen.csv` (idempotent)
- `frontend/` — Vite+React-Oberfläche, spricht die Backend-Endpunkte über
  `/api/*` an (im Dev-Modus per Vite-Proxy, in Produktion per Caddy)
- `docker-compose.yml` — Postgres + API + Frontend/Caddy als Reverse Proxy

## Schritte auf dem Server (mit Claude Code)

1. Dieses Verzeichnis auf den Server bringen (`git clone`).
2. `cp .env.example .env` und dort die echten Werte eintragen:
   IMAP-Zugangsdaten je Postfach, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`,
   `DROPBOX_ACCESS_TOKEN`,
   `POSTGRES_PASSWORD` — **niemals in den Chat einfügen, niemals committen.**
3. `docker compose up -d --build` — startet Datenbank, API und Frontend/Caddy.
4. Einmalig die Klassifikationstabelle importieren (im laufenden `app`-Container):
   `docker compose exec app python -m scripts.import_klassifikationen data/mail-klassifikationen.csv`
5. Einmalig die Zeitzonen-Migration ausführen (bestehende Zeitstempel-Spalten
   auf `timestamptz` umstellen, sonst zeigt die Oberfläche falsche Uhrzeiten):
   `docker compose exec app python -m scripts.migrate_zeitzone`
6. Einmalig die Aufgaben-Migration ausführen. Sie ergänzt geordnete
   Aufgabenlisten, setzt vor alle bisherigen `MAIL_VERSCHIEBEN`-Aufgaben eine
   Bestätigung und übernimmt offene Bestandsmails:
   `docker compose exec app python -m scripts.migrate_aufgaben`
7. Für die Rechnungsverarbeitung einmalig das Schema ergänzen und den
   Klassifikationskatalog neu importieren:
   `docker compose exec app python -m scripts.migrate_rechnungen`
   `docker compose exec app python -m scripts.import_klassifikationen data/mail-klassifikationen.csv`
   Spam-Kategorien benötigen keine Bestätigung. Nach Einführung dieser Regel
   werden bereits vorhandene Spam-Aufgaben einmalig bereinigt:
   `docker compose exec app python -m scripts.entferne_spam_bestaetigungen`
   Alle übrigen Mails benötigen eine Bestätigung; vorhandene Bestandsmails
   werden einmalig nachgezogen:
   `docker compose exec app python -m scripts.synchronisiere_bestaetigungen`
8. Der `frontend`-Dienst bindet TLS/Domain **nicht** selbst — er lauscht nur
   intern auf Host-Port `8081`. Läuft davor bereits ein eigener Reverse Proxy
   (z. B. bei Elestio), muss dessen Domain-Routing auf Port `8081` dieses
   Servers zeigen. Ohne eigenen vorgeschalteten Proxy reicht ein simpler
   Reverse Proxy (Caddy/nginx) mit eigener Domain + TLS vor Port `8081`.

Der minütliche Mail-Abruf läuft danach automatisch im separaten
`worker`-Container. Er ist weder von einem geöffneten Browser noch von
Webseitenaufrufen abhängig. Alle Container verwenden `restart: unless-stopped`
und starten daher nach einem Server-/Docker-Neustart oder Prozessabsturz
automatisch wieder.

Nach dem ersten Abruf eines Postfachs verwendet der Worker die fortlaufenden
IMAP-UIDs statt des Gelesen-Status. Eine neue Mail wird dadurch auch dann
erfasst, wenn Betterbird oder eine serverseitige Regel sie vor dem nächsten
Minutenabruf bereits als gelesen markiert.

Der aktuelle Zustand ist über `/api/health` beziehungsweise intern über
`http://127.0.0.1:8000/health` sichtbar. `mail_worker.aktiv` ist nur dann
`true`, wenn innerhalb der letzten fünf Minuten ein Abruf-Lebenszeichen
gespeichert wurde.

## Bekannt fehlend / bewusst noch nicht eingebunden

- Für das Verschieben von Rechnungen müssen `IMAP_ERIK_HOST`,
  `IMAP_ERIK_USER` und `IMAP_ERIK_PASSWORD` auf dem Server gesetzt sein.
- Antwortentwürfe können manuell aus der Mailansicht oder automatisch über die
  Klassifikationsaufgabe **Antwortvorschlag erstellen** erzeugt werden. Grundlage
  sind `data/stilprofil.md`, die freigegebenen FAQ und die jeweilige Mail.
  Fehlende betriebliche Fakten werden nicht erfunden, sondern zur menschlichen
  Bearbeitung markiert.
- FAQ-Vorschläge (`FaqVorschlag`) werden ebenfalls noch nicht automatisch
  erkannt.
- Der SMTP-Versand befindet sich im sicheren Testbetrieb: Vor jedem Versand
  prüft Claude den finalen Text auf Vollständigkeit und offene Prüfhinweise.
  Die Prüfung darf denselben Entwurf höchstens zweimal blockieren; der dritte
  ausdrückliche Freigabeversuch versendet ohne eine weitere KI-Prüfung.
  Unabhängig von der Kundenadresse wird ausschließlich an
  `info@erikschweitzer.de` gesendet. Für den Testversand müssen
  `SMTP_SERVICE_HOST`, `SMTP_SERVICE_PORT`, `SMTP_SERVICE_USER` und
  `SMTP_SERVICE_PASSWORD` gesetzt sein.
- Alle fachlichen API-Funktionen erfordern eine persönliche Krautl-Anmeldung.
  Aktuell haben `erik`, `gursewak` und `ludwig` identischen Vollzugriff.
  Passwörter stehen ausschließlich in den Elestio-Umgebungsvariablen
  `KRAUTL_PASSWORD_ERIK`, `KRAUTL_PASSWORD_GURSEWAK` und
  `KRAUTL_PASSWORD_LUDWIG`. `KRAUTL_SESSION_SECRET` signiert die
  Anmeldesitzungen und muss ein langes zufälliges Geheimnis sein.
- Beim Testversand ergänzt Krautl abhängig vom angemeldeten Nutzer automatisch
  Name, gegebenenfalls `Auszubildender` und die gemeinsame
  dreikraut-Geschäftssignatur. Der freigebende Nutzer wird im Aktionslog
  protokolliert.
- Bestehende Klassifikationen lassen sich unter **Einstellungen →
  Mail-Klassifikationen** bearbeiten: Zielordner sowie eine geordnete Liste
  von Aufgaben. **Bestätigung einholen** ist dabei eine frei wählbare Aufgabe,
  keine fest eingebaute Pflicht. Neue Klassifikationen anlegen oder vorhandene
  löschen ist noch nicht über die Oberfläche möglich.
- **Audio transkribieren** ist als auswählbare Aufgabe implementiert. Sie muss
  vor **Mail verschieben** stehen, solange das Audio aus dem ursprünglichen
  IMAP-Posteingang geladen wird. Das Ergebnis wird als bereits gelesene Mail
  eingestellt, damit der Worker seine eigene Transkriptionsmail nicht erneut
  verarbeitet. `OPENAI_API_KEY` ist erforderlich; das Modell kann optional
  mit `OPENAI_TRANSCRIPTION_MODEL` geändert werden.
- Bestätigungen gelten aktuell für alle Nutzer mit Zugriff auf Krautl. Das
  Datenmodell enthält bereits Zieltyp/-referenz für spätere Rollen oder
  einzelne Nutzer; Nutzerverwaltung und Rollenprüfung fehlen noch.
- Rollenbasierte Rechteprüfung fehlt noch; derzeit haben alle drei eingerichteten
  Nutzer Vollzugriff.

## Geparkt: produktbezogene Wissensbasis und FAQ

Die Wissensbasis wird erst weitergebaut, wenn Mail-Abruf, Aufgaben,
Verschieben und Rechnungsverarbeitung zuverlässig laufen. Das fachliche
Regelwerk für spätere FAQ-Entwürfe liegt bereits unter
`data/faq-stilprofil.md`.

Wiederkehrende betriebliche Fälle, die kein Schreibstil und keine klassische
Produkt-FAQ sind, stehen getrennt unter `data/fallwissen.md`. Dieses Fallwissen
wird bei Antwortvorschlägen und bei der Prüfung vor dem Versand berücksichtigt.

Geplante Struktur:

1. **Allgemeines dreikraut-Wissen** — zum Beispiel Versand, Zahlung,
   Rückgabe, Bio-Zertifizierung und Unternehmensangaben.
2. **Produktfamilie** — gemeinsames Rohstoffwissen, etwa zu Hagebutte,
   Weihrauch oder Kurkuma.
3. **Konkretes Produkt** — Zusammensetzung, Varianten, Herkunft,
   Verarbeitung, Anwendung, Pflichtangaben, freigegebene FAQ und typische
   Kundenfragen. Der erste Testfall wird das Bio-Hagebuttenpulver,
   Artikelnummer 20810.

Wissen und fertige Formulierungen bleiben getrennt. Jeder Wissenseintrag
erhält Quelle, Stand und Freigabestatus. Gesundheitsbezogene Aussagen sind
prüfpflichtig und dürfen weder erfunden noch durch Umformulierung verstärkt
werden. Neue FAQ werden aus wiederkehrenden Kundenfragen nur vorgeschlagen;
sie werden erst nach menschlicher Prüfung verbindliches Wissen.

## Nächste Stabilisierungsschritte

1. Dropbox mit dauerhaft erneuerbarer Anmeldung konfigurieren
   (`DROPBOX_REFRESH_TOKEN`, `DROPBOX_APP_KEY`, `DROPBOX_APP_SECRET`) und
   einen echten Upload nach `/Rechnungen/{Jahr}/` prüfen.
2. Nach Behebung der Dropbox-Anmeldung fehlgeschlagene Rechnungsaufgaben mit
   `python -m scripts.wiederhole_rechnungen` kontrolliert wiederholen.
3. Die korrigierte postfachübergreifende Verschiebefunktion mit echten Mails
   prüfen: genau eine Kopie im Ziel, Entfernung aus dem Ursprungsordner und
   nachvollziehbarer Eintrag im Aktionslog.
4. Einen mindestens 24-stündigen Dauerlauf beobachten: minütlicher Abruf,
   keine dauerhaft hängenden Aufgaben, keine Dubletten und keine lange
   Ladezeit der Oberfläche.
5. Die ersten Antwortvorschläge mit unterschiedlichen Mailtypen prüfen und
   daraus Prompt sowie Stilprofil behutsam verfeinern; anschließend die
   produktbezogene Wissensbasis weiterbauen.

### Dropbox einmalig dauerhaft anmelden

Der in der Dropbox-App-Konsole erzeugbare `DROPBOX_ACCESS_TOKEN` ist nur ein
kurzlebiger Testzugang. Für Krautls unbeaufsichtigten Hintergrundbetrieb werden
stattdessen App Key, App Secret und ein dauerhaft wiederverwendbarer Refresh
Token verwendet.

1. In der Dropbox-App-Konsole bei der für Krautl angelegten App unter
   **Permissions** mindestens `files.content.write` aktivieren und die Änderung
   speichern.
2. **App key** und **App secret** aus den App-Einstellungen als
   `DROPBOX_APP_KEY` und `DROPBOX_APP_SECRET` in Elestio hinterlegen. Diese
   Werte niemals in Chat oder Git kopieren.
3. Den App-Container neu bauen/starten und darin den Anmelde-Assistenten
   ausführen:
   `docker compose exec app python -m scripts.dropbox_anmelden`
4. Den angezeigten Link im Browser öffnen, Dropbox-Zugriff erlauben und den
   einmaligen Code zurück in das Serverfenster kopieren.
5. Den danach ausgegebenen Wert in Elestio als `DROPBOX_REFRESH_TOKEN`
   hinterlegen. `DROPBOX_ACCESS_TOKEN` kann anschließend leer bleiben.
6. App-Container erneut starten. Danach eine fehlgeschlagene Rechnung gezielt
   wiederholen:
   `docker compose exec app python -m scripts.wiederhole_rechnungen`

Bei einer Dropbox-App mit Zugriffstyp **App folder** erscheint Krautls
`/Rechnungen/{Jahr}/` innerhalb des von Dropbox angelegten App-Ordners unter
`Apps/{Dropbox-App-Name}/Rechnungen/{Jahr}/`. Bei **Full Dropbox** liegt der
Ordner direkt im Dropbox-Hauptverzeichnis. Für Krautl genügt grundsätzlich
`App folder`; ein Vollzugriff ist nicht nötig.
