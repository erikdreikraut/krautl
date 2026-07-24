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
- `app/worker.py` — läuft minütlich (siehe `app/main.py`, `apscheduler`):
  ruft neue Mails aus allen konfigurierten Postfächern ab, klassifiziert sie
  und führt die `MAIL_VERSCHIEBEN`-Aktion der Klassifikation aus, sofern das
  Zielpostfach konfiguriert ist
- `app/main.py` — FastAPI mit den Endpunkten, die die Oberfläche braucht
- `scripts/import_klassifikationen.py` — importiert/aktualisiert die
  `klassifikation`-Tabelle aus `data/mail-klassifikationen.csv` (idempotent)
- `frontend/` — Vite+React-Oberfläche, spricht die Backend-Endpunkte über
  `/api/*` an (im Dev-Modus per Vite-Proxy, in Produktion per Caddy)
- `docker-compose.yml` — Postgres + API + Frontend/Caddy als Reverse Proxy

## Schritte auf dem Server (mit Claude Code)

1. Dieses Verzeichnis auf den Server bringen (`git clone`).
2. `cp .env.example .env` und dort die echten Werte eintragen:
   IMAP-Zugangsdaten je Postfach, `ANTHROPIC_API_KEY`, `DROPBOX_ACCESS_TOKEN`,
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

Der minütliche Mail-Abruf läuft danach automatisch im `app`-Container mit —
kein separater Scheduler-Job nötig.

## Bekannt fehlend / bewusst noch nicht eingebunden

- Für das Verschieben von Rechnungen müssen `IMAP_ERIK_HOST`,
  `IMAP_ERIK_USER` und `IMAP_ERIK_PASSWORD` auf dem Server gesetzt sein.
- Antwortentwürfe (`Entwurf`-Tabelle) werden noch nirgends automatisch
  generiert — die Oberfläche kann sie anzeigen/freigeben, sobald es passiert.
- FAQ-Vorschläge (`FaqVorschlag`) werden ebenfalls noch nicht automatisch
  erkannt.
- SMTP-Versandmodul (separat vom Freigabe-Endpunkt, siehe Sicherheitsprinzip)
- Klassifikationstabelle ist nur per Skript/DB editierbar, noch nicht über
  die Oberfläche
- Bestätigungen gelten aktuell für alle Nutzer mit Zugriff auf Krautl. Das
  Datenmodell enthält bereits Zieltyp/-referenz für spätere Rollen oder
  einzelne Nutzer; Nutzerverwaltung und Rollenprüfung fehlen noch.
- Authentifizierung für die API (aktuell komplett offen — nicht für den
  Produktivbetrieb geeignet, bevor das ergänzt ist)

## Geparkt: produktbezogene Wissensbasis und FAQ

Die Wissensbasis wird erst weitergebaut, wenn Mail-Abruf, Aufgaben,
Verschieben und Rechnungsverarbeitung zuverlässig laufen. Das fachliche
Regelwerk für spätere FAQ-Entwürfe liegt bereits unter
`data/faq-stilprofil.md`.

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
5. Erst danach Antwortvorschläge und die produktbezogene Wissensbasis
   weiterbauen.

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
