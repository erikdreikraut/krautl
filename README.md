# Krautl — Backend-Grundgerüst

Dieses Grundgerüst wurde im Chat mit Claude vorbereitet. Die eigentliche
Inbetriebnahme (echte Zugangsdaten, Server, Domain) macht am besten
**Claude Code direkt auf Deinem Server** — nicht diese Chat-Umgebung, die
keinen Internetzugriff hat.

## Was hier bereits steht

- `app/models.py` — Datenbankschema (Mails, Klassifikation, Korrekturen,
  Entwürfe, Rechnungen, FAQ)
- `app/imap_client.py` — IMAP-Abruf + der aus n8n portierte Cross-Postfach-Move
- `app/agent.py` — Klassifizierungs-Prompt + Tool-Schema für die Claude API
  (kein Versand-Tool — Sicherheitsprinzip aus CLAUDE.md)
- `app/main.py` — FastAPI mit den Endpunkten, die die Oberfläche braucht
- `docker-compose.yml` / `Dockerfile` — Postgres + App lokal/auf dem Server

## Schritte auf dem Server (mit Claude Code)

1. Dieses Verzeichnis auf den Server bringen (z. B. per `git clone` aus
   einem eigenen Repo, das Du aus diesem Grundgerüst anlegst).
2. `cp .env.example .env` und dort die echten Werte eintragen:
   IMAP-Zugangsdaten je Postfach, `ANTHROPIC_API_KEY`, `DROPBOX_ACCESS_TOKEN`
   etc. — **niemals in den Chat einfügen, niemals committen.**
3. Die Klassifikationstabelle (aus `Mail-Klassifikationen.csv`) einmalig in
   die `klassifikation`-Tabelle importieren — ein kleines Import-Skript
   dafür lässt sich direkt mit Claude Code schreiben.
4. `docker compose up -d --build` — startet Datenbank + API lokal auf
   Port 8000.
5. Für den Zugriff von überall: einen Reverse Proxy (z. B. Caddy oder
   nginx) mit eigener Subdomain + TLS-Zertifikat (Let's Encrypt) vor die
   App schalten. Caddy ist hierfür meist der unkomplizierteste Einstieg
   (automatisches HTTPS).
6. Einen Scheduler-Job (z. B. via `apscheduler`, bereits in
   requirements.txt) einrichten, der `neue_mails_abrufen()` regelmäßig für
   jedes Postfach aufruft und die Klassifizierung anstößt.

## Offene Punkte, die Claude Code als Nächstes angehen sollte

- Import-Skript für die Klassifikationstabelle
- Endpunkt/Job, der `agent.klassifiziere()` mit echten Mails verbindet und
  die Ergebnisse in die `mail`-Tabelle schreibt
- SMTP-Versandmodul (separat vom Freigabe-Endpunkt, siehe Sicherheitsprinzip)
- Dropbox-/Mega-Upload-Modul für Anhänge
- Authentifizierung für die API (aktuell komplett offen — nicht für den
  Produktivbetrieb geeignet, bevor das ergänzt ist)
