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
  Gursewak und Ludwig sowie deren Rollen **Admin** beziehungsweise
  **Sachbearbeiter**
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
8. Einmalig die Wissensbasis anlegen. Die Migration ergänzt Produkte,
   Produktfamilien, Wissenseinträge, produktbezogene FAQ und übernimmt das
   bisherige `data/fallwissen.md` sowie die Regeln zur Erkennung von
   Vertriebskanälen aus Auftragsnummern als sichtbare, freigegebene Einträge.
   Die Migration ist wiederholbar und ergänzt dabei fehlende Einträge:
   `docker compose exec app python -m scripts.migrate_wissensbasis`
9. Einmalig die rollenbasierte Mail-Zuständigkeit ergänzen. Bestehende Mails
   werden aus der aktuellen Rollen-Matrix initialisiert:
   `docker compose run --rm app python -m scripts.migrate_mail_zustaendigkeit`
10. Der `frontend`-Dienst bindet TLS/Domain **nicht** selbst — er lauscht nur
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

Jede sichtbare Mail kann unabhängig von ihrer Klassifikation manuell als
**Erledigt** markiert werden. Sie verschwindet dann aus der Krautl-Arbeitsliste,
bleibt im IMAP-Postfach aber unverändert erhalten; offene Krautl-Aufgaben werden
abgebrochen und der Vorgang protokolliert. **Mail löschen** ist davon klar
getrennt und versucht zusätzlich, die Nachricht dauerhaft aus IMAP zu löschen.

## Bekannt fehlend / bewusst noch nicht eingebunden

- Für das Verschieben von Rechnungen müssen `IMAP_ERIK_HOST`,
  `IMAP_ERIK_USER` und `IMAP_ERIK_PASSWORD` auf dem Server gesetzt sein.
- Antwortentwürfe können manuell aus der Mailansicht oder automatisch über die
  Klassifikationsaufgabe **Antwortvorschlag erstellen** erzeugt werden. Grundlage
  sind `data/stilprofil.md`, die passend ausgewählten freigegebenen Wissens-
  und FAQ-Einträge sowie die jeweilige Mail.
  Fehlende betriebliche Fakten werden nicht erfunden, sondern zur menschlichen
  Bearbeitung markiert.
- Wenn ein Mensch einen KI-Antwortentwurf fachlich verändert und versendet,
  prüft Krautl auf wiederverwendbaren Wissenszuwachs. Höchstens ein kompakter
  Wissens- oder FAQ-Vorschlag entsteht; er bleibt stets ein Entwurf und wird
  nie automatisch veröffentlicht.
- Vor jedem SMTP-Versand
  prüft Claude den finalen Text auf Vollständigkeit und offene Prüfhinweise.
  Die Prüfung darf denselben Entwurf höchstens zweimal blockieren; der dritte
  ausdrückliche Freigabeversuch versendet ohne eine weitere KI-Prüfung.
  Die Antwort wird an die Absenderadresse der Kundenmail gesendet.
  `info@erikschweitzer.de` erhält ausschließlich eine BCC-Kontrollkopie. Dafür müssen
  `SMTP_SERVICE_HOST`, `SMTP_SERVICE_PORT`, `SMTP_SERVICE_USER` und
  `SMTP_SERVICE_PASSWORD` gesetzt sein.
- Alle fachlichen API-Funktionen erfordern eine persönliche Krautl-Anmeldung.
  `erik` ist Admin; `gursewak` und `ludwig` sind Sachbearbeiter.
  Passwörter stehen ausschließlich in den Elestio-Umgebungsvariablen
  `KRAUTL_PASSWORD_ERIK`, `KRAUTL_PASSWORD_GURSEWAK` und
  `KRAUTL_PASSWORD_LUDWIG`. `KRAUTL_SESSION_SECRET` signiert die
  Anmeldesitzungen und muss ein langes zufälliges Geheimnis sein.
- Beim Versand ergänzt Krautl abhängig vom angemeldeten Nutzer automatisch
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
  mit `OPENAI_TRANSCRIPTION_MODEL` geändert werden. Die reine Gliederung und
  Formatierung übernimmt standardmäßig das kleine, schnelle Claude Haiku 4.5;
  `AUDIO_FORMATTING_MODEL` kann dieses zweite Modell bei Bedarf überschreiben.
- Unter **Einstellungen → Rollen & Mailzugriff** legt ein Admin je
  Klassifikation fest, welche Mailarten Sachbearbeiter sehen und bearbeiten
  dürfen. Die Prüfung erfolgt auch im Backend für Posteingang, Bestätigungen,
  Kategoriekorrekturen, Antwortentwürfe, zugehörige Rechnungen und aus Mails
  abgeleitete Wissensvorschläge. Admins haben stets Zugriff auf alle Mailarten.
- Die Rollen-Matrix bestimmt zugleich die anfängliche Zuständigkeit neuer
  Mails. Über **Zuweisen** kann eine Mail anschließend exklusiv Erik als Admin
  oder der gemeinsamen Sachbearbeiter-Gruppe Guri und Ludwig zugeordnet
  werden. Admins sehen standardmäßig nur ihre eigene Arbeitsliste und können
  zur Kontrolle auf **Alle Mails** wechseln. Zuweisungen werden im Aktionslog
  mit dem auslösenden Nutzer festgehalten.
- Bestätiger-Ziele pro Aufgabe sind weiterhin nicht nach einzelnen Personen
  oder Rollen differenziert; innerhalb einer freigegebenen Mailart darf jeder
  Sachbearbeiter bestätigen.

Nach dem Deployment der Lieferanten-Kategorie `LIEFERANT_DIVERSES` wird die
gezielte Katalogänderung einmalig mit folgendem Befehl eingespielt. Dabei wird
`LIEFERANT_PREISAENDERUNG` entfernt, ohne die inzwischen im Frontend
bearbeiteten Aktionen anderer Kategorien anzutasten:

```bash
docker compose exec app python -m scripts.aktualisiere_lieferantenkategorien
```

Die beiden getrennten Shop-Apotheke-Kategorien für Bestellungen und wichtige
Plattformmeldungen werden nach dem entsprechenden Deployment einmalig so
eingespielt, ohne andere Klassifikationen zu überschreiben:

```bash
docker compose exec app python -m scripts.aktualisiere_shopapotheke_kategorien
```

Die feste Absenderregel für Anthropic-Systemmails und ihr Zielordner werden
gezielt und wiederholbar aktualisiert mit:

```bash
docker compose exec app python -m scripts.aktualisiere_anthropic_mailregel
```

Amazon-Mails bleiben grundsätzlich in den Amazon-Kategorien. Hinweise auf
eine nur im Seller Central bereitstehende Rechnung sind `AMAZON_STATUS`, eine
tatsächlich angehängte Rechnung bleibt in der Rechnungsverarbeitung. Nach dem
Deployment wird die Regel und die noch offene Beispielmail einmalig mit diesem
Befehl aktualisiert:

```bash
docker compose exec app python -m scripts.aktualisiere_amazon_regeln
```

Das verbindliche Ablaufwissen für normale Rücksendungen ohne Qualitätsmangel
wird gezielt und wiederholbar eingespielt mit:

```bash
docker compose exec app python -m scripts.aktualisiere_ruecksende_wissen
```

## Produktbezogene Wissensbasis und FAQ

Unter **Wissensdatenbank** werden vier Geltungsbereiche getrennt gepflegt:

1. **Allgemeines dreikraut-Wissen** — zum Beispiel Versand, Zahlung,
   Rückgabe, Bio-Zertifizierung und Unternehmensangaben.
2. **Abläufe & Fallwissen** — wiederkehrende betriebliche Fälle und die
   gewünschte Behandlung, unabhängig vom Schreibstil.
3. **Produktfamilie** — gemeinsames Rohstoffwissen, etwa zu Hagebutte,
   Weihrauch oder Kurkuma.
4. **Konkretes Produkt** — Zusammensetzung, Varianten, Herkunft,
   Verarbeitung, Anwendung, Pflichtangaben und typische Kundenfragen.

Der erste angelegte Testfall ist das Bio-Hagebuttenpulver, Artikelnummer
20810. Krautl erkennt das Produkt über Name, Artikelnummer und pflegbare
Suchbegriffe. Antwortentwurf und Versandkontrolle erhalten nur allgemeines
Wissen, Abläufe sowie das zur Mail passende Familien-/Produktwissen und FAQ.

Wissen und fertige FAQ-Formulierungen bleiben getrennt. Jeder Wissenseintrag
hat Quelle, Stand und Freigabestatus. Nur **freigegebene** Einträge gelangen in
KI-Antworten. Gesundheitsbezogene Aussagen können als sensibel markiert
werden und dürfen weder erfunden noch durch Umformulierung verstärkt werden.

FAQ werden in der Oberfläche als einfache Frage und Antwort bearbeitet. Für
Absätze, Aufzählungen, `**Fettdruck**` und Weblinks ist kein HTML nötig. Für
jedes Produkt erzeugt **Aktuelles JTL-HTML kopieren** alle als **Im aktuellen
FAQ enthalten** markierten Entwürfe und freigegebenen FAQ in einem vollständigen
Schema.org-`FAQPage`-Accordion mit den bei dreikraut verwendeten
Bootstrap-/JTL-Attributen. Veraltete oder inaktive Einträge werden nicht
exportiert. Sind Entwürfe enthalten, verlangt Krautl vor dem Kopieren eine
ausdrückliche Bestätigung. Der Block kann als Ganzes in JTL eingefügt werden.
HTML muss nicht von Hand gepflegt werden.

**Shop-Produkte aktualisieren** liest den derzeit sichtbaren Produktbestand
aus der öffentlichen JTL-Produktübersicht ein. Vorhandene Produkte werden über
Artikelnummer, Produktadresse oder Namen wiedererkannt; manuell gepflegte
Produktfamilien und Suchbegriffe bleiben erhalten. Der Abgleich verändert
keine Wissens- oder FAQ-Einträge.

Als Test für die einmalige FAQ-Erstbefüllung können acht redaktionell zu prüfende
Entwürfe für die Chlorella-Presslinge eingespielt werden. Der Import arbeitet
nur, wenn dieses Produkt noch gar keine FAQ besitzt, lässt alle anderen
Produkte unberührt und veröffentlicht nichts automatisch:

```bash
docker compose exec app python -m scripts.importiere_chlorella_faq_entwuerfe
```

Die Fragen orientieren sich an typischen Kundenfragen und vergleichbaren
Angeboten. Die Antworten verwenden ausschließlich die dreikraut-Produktseite
und bei den allgemeinen Fragen zusätzlich ausgewiesene Verbraucherquellen.
Alle Einträge erhalten den Status **Entwurf** und müssen in Krautl einzeln
redaktionell geprüft und freigegeben werden.

Ein erneuter Lauf verändert keine vorhandenen Chlorella-FAQ. Sobald auch nur
ein FAQ-Eintrag für das Produkt vorhanden ist, wird der Import vollständig
übersprungen. Die Quellen bleiben intern im Feld **Quelle** erhalten.

Ein zweiter, davon vollständig getrennter Testimport legt acht FAQ-Entwürfe für
die **Thailändischen Riechkräuter dreikraut im Glas** an. Auch dieser Import
arbeitet nur bei einem vollständig leeren FAQ-Bestand des Produkts:

```bash
docker compose exec app python -m scripts.importiere_thailaendische_riechkraeuter_faq_entwuerfe
```

Die Konkurrenzrecherche dient hierbei ausschließlich zum Erkennen typischer
Fragen. Die sichtbaren Antworten beruhen auf den dreikraut-Produktangaben und
allgemeinen, unmittelbar produktbezogenen Anwendungshinweisen. Alle Einträge
werden als Entwurf angelegt und nicht automatisch veröffentlicht.

Nach dem Versand einer manuell veränderten Kundenantwort vergleicht Krautl
Kundenfrage, ursprünglichen KI-Entwurf, endgültige Antwort und vorhandenes
Wissen. Nur eine wirklich wiederverwendbare Ergänzung wird vorgeschlagen.
Unter **Vorschläge** kann sie verworfen oder als weiterhin unfertiger
Wissens-/FAQ-Entwurf übernommen und anschließend redaktionell freigegeben
werden.

Gruppenbezeichnungen sind produktbezogen und nicht auf ein starres Set
beschränkt. Vorhandene Gruppen werden beim Bearbeiten vorgeschlagen. Für das
Bio-Hagebuttenpulver übernimmt die Wissensbasis initial die 11 veröffentlichten
FAQ in den Gruppen **Herkunft & Qualität**, **Nährstoffe & Wirkung** und
**Anwendung & Praktisches** von der dreikraut-Produktseite. Ein erneuter Lauf
der Migration legt keine Dubletten an und überschreibt spätere redaktionelle
Änderungen nicht.

## Nächste Stabilisierungsschritte

1. Dropbox mit dauerhaft erneuerbarer Anmeldung konfigurieren
   (`DROPBOX_REFRESH_TOKEN`, `DROPBOX_APP_KEY`, `DROPBOX_APP_SECRET`) und
   einen echten Upload nach `/Rechnungen/{Jahr}/` prüfen.
2. Nach Behebung der Dropbox-Anmeldung fehlgeschlagene Rechnungsaufgaben mit
   `python -m scripts.wiederhole_rechnungen` kontrolliert wiederholen.
   Die Rechnungsauswertung prüft alle Dokumentseiten auch auf Lastschrift,
   Verrechnung, Guthabenabzug und Einbehalt von Auszahlungen. Sämtliche
   Zahlungsstati bleiben in der Rechnungsansicht sichtbar und können dort
   redaktionell korrigiert werden; nur **offen** und **unklar** zählen als
   Rechnungen mit Handlungsbedarf.
3. Die korrigierte postfachübergreifende Verschiebefunktion mit echten Mails
   prüfen: genau eine Kopie im Ziel, Entfernung aus dem Ursprungsordner und
   nachvollziehbarer Eintrag im Aktionslog.
4. Einen mindestens 24-stündigen Dauerlauf beobachten: minütlicher Abruf,
   keine dauerhaft hängenden Aufgaben, keine Dubletten und keine lange
   Ladezeit der Oberfläche.
5. Die ersten Antwortvorschläge mit unterschiedlichen Mailtypen prüfen und
   daraus Prompt sowie Stilprofil behutsam verfeinern; anschließend die
   Produkt- und FAQ-Inhalte in der neuen Wissensdatenbank schrittweise füllen.

### Dropbox einmalig dauerhaft anmelden

Der in der Dropbox-App-Konsole erzeugbare `DROPBOX_ACCESS_TOKEN` ist nur ein
kurzlebiger Testzugang. Für Krautls unbeaufsichtigten Hintergrundbetrieb werden
stattdessen App Key, App Secret und ein dauerhaft wiederverwendbarer Refresh
Token verwendet.

1. In der Dropbox-App-Konsole bei der für Krautl angelegten App unter
   **Permissions** mindestens `files.content.write` und `files.content.read`
   aktivieren und die Änderung speichern. Die Schreibberechtigung wird zum
   Ablegen der Rechnungen benötigt, die Leseberechtigung für die geschützte
   Rechnungsansicht in Krautl.
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
   Wird `files.content.read` erst später ergänzt, muss die Dropbox-Anmeldung
   erneut durchlaufen und der bisherige Refresh Token durch den neu
   ausgegebenen Wert ersetzt werden. Bereits gespeicherte Tokens erhalten
   nachträglich keine zusätzlichen Berechtigungen.
6. App-Container erneut starten. Danach eine fehlgeschlagene Rechnung gezielt
   wiederholen:
   `docker compose exec app python -m scripts.wiederhole_rechnungen`

Bei einer Dropbox-App mit Zugriffstyp **App folder** erscheint Krautls
`/Rechnungen/{Jahr}/` innerhalb des von Dropbox angelegten App-Ordners unter
`Apps/{Dropbox-App-Name}/Rechnungen/{Jahr}/`. Bei **Full Dropbox** liegt der
Ordner direkt im Dropbox-Hauptverzeichnis. Für Krautl genügt grundsätzlich
`App folder`; ein Vollzugriff ist nicht nötig.
