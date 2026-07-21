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
   `POSTGRES_PASSWORD`, optional `KRAUTL_DOMAIN` —
   **niemals in den Chat einfügen, niemals committen.**
3. `docker compose up -d --build` — startet Datenbank, API und Frontend/Caddy.
4. Einmalig die Klassifikationstabelle importieren (im laufenden `app`-Container):
   `docker compose exec app python -m scripts.import_klassifikationen data/mail-klassifikationen.csv`
5. Ist `KRAUTL_DOMAIN` gesetzt und zeigt die DNS-A-Record auf den Server,
   holt sich Caddy automatisch ein Let's-Encrypt-Zertifikat. Ohne Domain ist
   die Oberfläche vorerst nur per `http://<server-ip>` erreichbar.

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
