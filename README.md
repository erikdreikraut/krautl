# Krautl — Mail-Klassifikation & Backend für dreikraut

## Was hier bereits steht

- `app/models.py` — Datenbankschema (Mails, Klassifikation, Korrekturen,
  Entwürfe, Rechnungen, FAQ)
- `app/imap_client.py` — IMAP-Abruf + der aus n8n portierte Cross-Postfach-Move
  (inkl. "Schon am Ziel?"-Kurzschluss)
- `app/mail_parser.py` — parst rohe EML-Bytes in die Felder für Klassifizierung/DB
- `app/agent.py` — Klassifizierungs-Prompt + Tool-Schema für die Claude API
  (kein Versand-Tool — Sicherheitsprinzip aus CLAUDE.md)
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
5. Der `frontend`-Dienst bindet TLS/Domain **nicht** selbst — er lauscht nur
   intern auf Host-Port `8081`. Läuft davor bereits ein eigener Reverse Proxy
   (z. B. bei Elestio), muss dessen Domain-Routing auf Port `8081` dieses
   Servers zeigen. Ohne eigenen vorgeschalteten Proxy reicht ein simpler
   Reverse Proxy (Caddy/nginx) mit eigener Domain + TLS vor Port `8081`.

Der minütliche Mail-Abruf läuft danach automatisch im `app`-Container mit —
kein separater Scheduler-Job nötig.

## Bekannt fehlend / bewusst noch nicht eingebunden

- `erik@dreikraut.de` ist in der Klassifikationstabelle als Zielpostfach für
  Rechnungen/Bewerbungen vorgesehen, aber aktuell **nicht** konfiguriert
  (siehe `.env.example`) — so klassifizierte Mails bleiben bis auf Weiteres
  im Ursprungspostfach liegen, es passiert nichts Kaputtes.
- Antwortentwürfe (`Entwurf`-Tabelle) werden noch nirgends automatisch
  generiert — die Oberfläche kann sie anzeigen/freigeben, sobald es passiert.
- FAQ-Vorschläge (`FaqVorschlag`) werden ebenfalls noch nicht automatisch
  erkannt.
- SMTP-Versandmodul (separat vom Freigabe-Endpunkt, siehe Sicherheitsprinzip)
- Dropbox-Upload-Modul für Anhänge
- Klassifikationstabelle ist nur per Skript/DB editierbar, noch nicht über
  die Oberfläche
- Authentifizierung für die API (aktuell komplett offen — nicht für den
  Produktivbetrieb geeignet, bevor das ergänzt ist)
