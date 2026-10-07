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
  Gursewak, Ludwig, Aneta und Micha sowie deren Rollen **Admin** beziehungsweise
  **Sachbearbeiter**
- `scripts/import_klassifikationen.py` — importiert/aktualisiert die
  `klassifikation`-Tabelle aus `data/mail-klassifikationen.csv` (idempotent)
- `frontend/` — Vite+React-Oberfläche, spricht die Backend-Endpunkte über
  `/api/*` an (im Dev-Modus per Vite-Proxy, in Produktion per Caddy)
- `docker-compose.yml` — Postgres + API + Frontend/Caddy als Reverse Proxy

## WhatsApp und gemeinsamer Eingang

Der bisherige Posteingang heißt **Eingang**. E-Mails und offene WhatsApp-Chats
werden gemeinsam angezeigt: WhatsApp-Chats zuerst, danach Mails mit hoher
Priorität, anschließend übrige Mails. Innerhalb jeder Gruppe stehen neue
Nachrichten zuerst. WhatsApp erhält einen eigenen blassblauen Hintergrund,
Mails behalten Klassifikations-Tags und ihre bisherige Farbgebung; Kanalfilter, Rollenlisten,
Zuständigkeiten bleiben verfügbar. Ein Kontakt belegt genau einen
Chat je Geschäftsnummer. Nach manuell freigegebener Antwort wartet der Chat auf
den Kunden und verschwindet aus dem aktiven Eingang. Eine neue Kundennachricht
öffnet ihn wieder. **Erledigt** schließt ohne Versand. **Archiv → WhatsApp-Chats** zeigt den
suchbaren Verlauf auch nach Abschluss. **Archiv → Gesendete E-Mails** enthält
die bisherige Ansicht gesendeter Antworten.

Implementiert sind Textnachrichten, manuell freigegebene Wissensbasis-Vorschläge,
Entwürfe, interne Notizen, Zuweisung, 90-Sekunden-Reservierung,
API-Versandstatus, eingehende Medien, Sprachnachrichten-Transkription sowie
PDF-/JPG-/PNG-Versand. WhatsApp-Chats werden weder beim ersten Eingang noch bei weiteren Nachrichten KI-klassifiziert.
Es gibt keine Kategorieauswahl für Chats; die KI wird für Antwortvorschläge weiterhin auf Knopfdruck genutzt. Es werden keine
Mail-Verschiebeaktionen auf Chats ausgeführt. Vorschläge benutzen den Verlauf
und freigegebene Wissenseinträge/FAQ; Transkription benötigt den vorhandenen
OpenAI-Zugang. Versand und KI-Vorschläge erfolgen ausschließlich auf Knopfdruck.

Neue Nachrichten/Transkripte machen ältere Entwürfe prüfpflichtig. Neue Eingänge
während des Sendens bleiben sichtbar. Ein dauerhafter Versandauftrag mit UUID
verhindert Wiederholung desselben Auftrags. Bei Timeout oder Serverfehler gibt
es keinen automatischen Neuversand: Unterbrochene Übergaben werden nach zwei Minuten wieder sichtbar. Den Meta-Status abwarten oder das Ergebnis anhand eines verlässlichen Nachweises
(z. B. Empfängerbestätigung oder technische Versandprüfung) explizit im Chat bestätigen.
Ein ausbleibender Zustellstatus beweist keinen Nichtversand. Nach definitiver Ablehnung kann eine neue Antwort
vorbereitet werden. Annahme, Versand, Zustellung und Lesen werden getrennt
angezeigt. Reihenfolgefehler dürfen den Zustellstatus nicht zurücksetzen.

Webhook-Ereignisse werden vor der HTTP-Bestätigung in PostgreSQL gespeichert.
Der App-Hintergrundprozess verarbeitet sie alle zwei Sekunden; wiederholte
Nachrichten werden anhand der WhatsApp-ID erkannt. Fehler bleiben im Admin-
Bereich **Archiv → WhatsApp-Chats** sichtbar und können ohne Versand erneut verarbeitet werden.
Berechtigungen gelten für Chatliste, Verlauf, Medien und sämtliche Aktionen.

### Einrichtung: direkte Meta Cloud API (API-only)

Der gewählte Betriebsweg verbindet Krautl direkt mit Meta, ohne zusätzlichen
Anbieter und ohne parallele Nutzung der WhatsApp-Business-App für diese Nummer.
Die Anbindung bleibt bis zur Einrichtung deaktiviert. `Base.metadata.create_all`
legt nur neue WhatsApp-Tabellen an; bestehende Mailtabellen werden nicht geändert.
Die Geschäftsrufnummer ist **+4920227277835**. `WHATSAPP_PHONE_NUMBER_ID` ist eine
von Meta vergebene technische ID, nicht die Rufnummer.

1. Unter [Meta Business Suite](https://business.facebook.com/) ein eigenes
   Unternehmensportfolio verwenden oder einrichten. Unter
   [Meta for Developers](https://developers.facebook.com/) eine eigene App mit
   WhatsApp Cloud API anlegen und mit dem Portfolio verbinden. Ein vorhandener
   Business-App-Zugang oder die QR-Gerätekopplung ersetzt diese API-Einrichtung nicht.
2. Zuerst Metas bereitgestellte Testnummer verwenden. Im App-Dashboard einen
   Testempfänger hinterlegen. Damit Empfang, Antwort und Zustellstatus prüfen,
   bevor die bisherige Firmennummer verändert wird.
3. `.env` anhand `.env.example` ergänzen: `WHATSAPP_PROVIDER=meta`,
   `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_API_VERSION`,
   `WHATSAPP_APP_SECRET`, `WHATSAPP_VERIFY_TOKEN` und `WHATSAPP_WABA_ID`.
   Für den Dauerbetrieb einen System-User-Zugriffstoken mit Zugriff auf die eigene
   WABA und den benötigten Messaging-/Management-Berechtigungen verwenden;
   Ablauf und Widerruf berücksichtigen. Der temporäre Dashboard-Token reicht
   nur für den Test. Geheimnisse ausschließlich in der Server-Konfiguration speichern.
4. HTTPS-Callback-URL im Meta-Dashboard hinterlegen:
   `https://krautl.erikschweitzer.de/api/whatsapp/webhook`.
   `WHATSAPP_ENABLED=true` für die vorbereitete Testkonfiguration setzen und
   den App-Service neu starten. Webhook mit dem konfigurierten Verify-Token
   verifizieren, das Feld `messages` abonnieren und die App mit der WABA verbinden
   (`subscribed_apps`). Die vorhandene Caddy-Weiterleitung für `/api/*` reicht aus.
   Krautl prüft Metas HMAC-Signatur. App-Echoes sind bei API-only nicht erforderlich.
5. Erst nach erfolgreichem Test die bisherige Nummer umstellen: benötigte alte
   Chats vorher exportieren. Beim klassischen Wechsel aus der Business-App muss
   der dortige WhatsApp-Account freigegeben werden; bloßes Deinstallieren der App
   genügt nicht. Die Account-Löschung erst unmittelbar vor der vorbereiteten
   Registrierung durchführen, nicht während der Testeinrichtung. Die bisherigen
   App-Chats werden nicht in Krautl importiert; ein Export ist kein API-Import.
6. Die Festnetznummer im WhatsApp Manager hinzufügen und ihre Erreichbarkeit
   über den angebotenen Sprachanruf verifizieren. Anschließend die Nummer für
   Cloud API registrieren, einschließlich der dort verlangten Zwei-Schritt-PIN.
   Produktions-Phone-Number-ID und WABA-ID in der Server-Konfiguration setzen.
   Erforderliche Firmenprüfung und Zahlungsdaten im Meta-Dashboard abschließen.
   Die konkrete Freigabe der Nummer erfolgt bei Meta, nicht durch Krautl.
7. Eingang von einer externen Testperson, Zuweisung, manuelle Antwort,
   Zustellstatus und Wiederöffnung durch die nächste Kundennachricht prüfen.
   Danach läuft die Bearbeitung dieser Nummer über Krautl; die Business-App und
   ihre gekoppelten Geräte sind für diese Nummer nicht mehr der Arbeitsweg.

Referenz: [Metas Cloud-API-Sammlung](https://www.postman.com/meta/whatsapp-business-platform/collection/wlk6lh4/whatsapp-cloud-api)
und [Migration einer bestehenden WhatsApp-Nummer](https://developers.facebook.com/docs/whatsapp/cloud-api/get-started/migrate-existing-whatsapp-number-to-a-business-account).
Meta-Nachrichtengebühren können weiterhin anfallen. Ein zusätzlicher
Anbietervertrag ist für diesen Betriebsweg nicht erforderlich. Der optionale
360dialog-Adapter bleibt im Code erhalten, wird mit `WHATSAPP_PROVIDER=meta`
aber nicht verwendet. Neue Kontakte entstehen aus eingehenden Nachrichten;
alte Kontaktlisten und Chatverläufe werden nicht importiert.

Nach 24 Stunden seit letzter Kundennachricht ist freier API-Versand gesperrt.
Krautl lädt freigegebene Textvorlagen (BODY, optional FOOTER, positionale
Textplatzhalter) und prüft sie vor Versand erneut beim Anbieter. Medienvorlagen,
Buttonvorlagen und benannte Platzhalter sind im Pilot nicht auswählbar. Es gibt
keinen automatischen Vorlagenversand und keine Kampagnen. Vorlagen können
kostenpflichtig sein; passende Kundenanfrage/Einwilligung beachten.

Pilot-Grenzen: bis 500 Chats je Liste, die letzten 300 Nachrichten je Detail,
60 Nachrichten als Vorschlagskontext. Bildversand bis 5 MB, PDF bis 10 MB,
Anhangsbeschriftung bis 1.024 Zeichen; Mediendownload bis 20 MB. Medien werden
beim Anbieter abgerufen und nicht dauerhaft in Krautl archiviert; ihre dortige
Verfügbarkeit ist zeitlich begrenzt. Texte, Versandaufträge und Transkripte
bleiben gespeichert. Gruppen, Anrufe und alte Historienimporte gehören nicht
zum Pilot. Eine deaktivierte Anbindung nimmt keine Webhooks oder Versände an;
bereits gespeicherte Chats bleiben lesbar.

Lokale Prüfung: `python -m unittest tests.test_whatsapp -q`. Tests verwenden
ausschließlich In-Memory-SQLite und simulierte Anbieter; PostgreSQL-Sperren,
Onboarding und echte Zustellwege benötigen einen separaten Produktivnachweis.

## Schritte auf dem Server (mit Claude Code)

### Gesendete Antworten

Der Reiter **Gesendet** zeigt versendete Antworten auch nach Abschluss der
ursprünglichen Anfrage. Die Suche erfasst Namen, Empfänger, Betreff und
Antworttext; neueste Antworten stehen zuerst. Im Aktionslog zeigt die
Mailansicht ebenfalls die gespeicherten Antworten. Die bisherigen Rollen-
und Mailzugriffsrechte gelten auch für Suche, Ansicht, Download und Ablage.

Ältere Antworten werden aus `entwurf.text_final` angezeigt. Für sie sind
vollständige Mailkopien und damalige Anhänge nicht gespeichert; Empfänger
und Betreff werden aus der Anfrage abgeleitet und entsprechend gekennzeichnet.
Es werden keine alten Antworten erneut versendet oder als vollständige EML
rekonstruiert.

Ab dieser Erweiterung speichert KRAUTL nach erfolgreicher SMTP-Übergabe die
Nachricht einschließlich Message-ID, Datum, Empfänger und Anhängen in der
neuen Tabelle `versandkopie`. Sie wird beim App-Start automatisch angelegt.
Die vollständige Nachricht lässt sich in **Gesendet** als EML herunterladen.
„An Mailserver übergeben“ bestätigt die SMTP-Annahme, nicht die Zustellung
beim Empfänger.

Ein Hintergrundjob prüft alle 30 Sekunden ausstehende Kopien und legt sie im
Gesendet-Ordner des Absenderpostfachs (ersatzweise Servicepostfach) ab.
Der Ordner wird bevorzugt über die IMAP-Markierung `\Sent` erkannt, sonst
über gängige Ordnernamen. Bei uneindeutiger Erkennung kann in `.env` der
exakte vorhandene Ordner mit `IMAP_SERVICE_SENT_FOLDER` angegeben werden.
Es werden keine neuen Mailordner angelegt.

Versand und Ablage sind getrennt: Ein IMAP-Fehler nimmt den erfolgreichen
Versand nicht zurück. KRAUTL zeigt den Ablagefehler an und versucht die Ablage
nach mindestens fünf Minuten erneut (höchstens zehn automatische Versuche).
**Kopie in Gesendet ablegen** ermöglicht einen weiteren manuellen Versuch.
Die Message-ID-Prüfung verhindert doppelte Kopien bei Wiederholung; eine
erneute Ablage verschickt niemals erneut eine Kundenmail. Ausstehende
Kopien bleiben über App-Neustarts erhalten.

Gezielte Tests: `python -m unittest tests.test_gesendete_antworten
tests.test_mail_versand tests.test_antwortentwuerfe tests.test_berechtigungen`.

### Google-Merchant-Center-FAQ-Zusatzfeed

Unter **Wissensdatenbank → Google-FAQ-Feed** stehen Feed-URL, letzte erfolgreiche
Generierung, Produkt-/Q&A-Zahlen, Warnungen und die Produktvorschau bereit.
Im FAQ-Editor wählt **„Ergänzt die Artikelbeschreibung“** einen Eintrag für diesen
Feed aus. In der FAQ-Übersicht und der Google-Produktvorschau lässt sich dieselbe
Auswahl direkt über **„Für Google ausgewählt“** ändern. Sie wird sofort gespeichert;
der Haken ist bei Auswahl grün hinterlegt. Nur dieses Feld wird dabei geändert.
Das Feld `include_in_google_product_qa` ist bei bestehenden und neuen
FAQs standardmäßig `false`. Die eigene Schemaergänzung läuft beim App-Start
idempotent; sie ändert keine vorhandenen Freigaben oder Texte.

Der Feed ist ohne Anmeldung unter
`https://krautl.erikschweitzer.de/feeds/google-product-faq.tsv` erreichbar.
Allein der Haken bestimmt die Auswahl für Google. FAQ-Status (auch `entwurf`
oder `veraltet`) sowie die Aktiv-Merkmale von FAQ und Produkt beeinflussen sie
nicht. Ohne Haken erscheint ein FAQ in der Vorschau als „Nicht ausgewählt“;
das ist keine Warnung. Ausgewählte FAQs benötigen eine Produktzuordnung und
eine gültige Artikelnummer und müssen die folgenden Google-Limits einhalten.
`id` entspricht der Artikelnummer einschließlich führender Nullen; die ID muss
im Google-Hauptfeed identisch sein. Allgemeine FAQs werden nicht exportiert.
Der bestehende JTL-HTML-Export bleibt unabhängig vom neuen Feld unverändert.

**Format und Grenzen:** UTF-8 ohne BOM, eine TSV-Zeile je Produkt, nur die Spalten
`id` und `question_and_answer`. Q&A werden als `"Frage":"Antwort","Frage":"Antwort"`
serialisiert, innere Anführungszeichen verdoppelt, Backslashes unverändert
übernommen. Keine zusätzliche CSV-Quotierung um die gesamte Q&A-Zelle.
HTML/unterstützte Markdown-Formatierung werden in Plaintext umgewandelt;
Tabs und Zeilenumbrüche werden Leerzeichen. Pro Produkt höchstens 30 Paare,
je Frage/Antwort höchstens 1.000 Unicode-Zeichen. Das Gesamtlimit von 10.000
wird vorsichtig einschließlich Gruppentrennzeichen, Quotes und deren Escaping
geprüft. Reihenfolge: FAQ-Sortierung, danach FAQ-ID. Ungültige oder überzählige
Einträge werden vollständig ausgelassen und in Warnungen/Vorschau erklärt;
Quelltexte werden niemals gekürzt oder verändert. Ohne geeignete FAQs enthält
der Feed nur die Kopfzeile und liefert HTTP 200.

Nach erfolgreichen FAQ-/Produktänderungen über die Oberfläche wird der Feed
sofort geprüft und bei Änderungen neu erzeugt. Ein Hintergrundabgleich alle
30 Sekunden erfasst zusätzlich Importskripte und direkte Datenbankänderungen.
Jeder öffentliche Abruf prüft ebenfalls den aktuellen Stand. Die Datei wird
über eine temporäre Datei im selben Verzeichnis, `fsync` und `os.replace`
atomar ausgetauscht. Docker speichert sie dauerhaft im Volume `krautl_feeds`
unter `/app/var/feeds/google-product-faq.tsv`. Standardpfad lokal: `var/feeds`;
optional per `GOOGLE_PRODUCT_QA_DIR` umstellbar (Volume dann ebenfalls anpassen).
Die Generatoren werden im bestehenden einzelnen Uvicorn-Prozess serialisiert.
Beim Neustart wird neu generiert. Bei einem Fehler bleibt die alte Datei
erhalten; der öffentliche Endpunkt liefert 503 statt möglicherweise inzwischen
zurückgezogener Inhalte. Die Oberfläche zeigt den Fehler und den letzten
erfolgreichen Stand. Es gibt weder Merchant-Center-API noch SFTP/JTL-Anbindung.

Geschützte Verwaltungsendpunkte unter `/api`:
`GET /google-product-qa`, `POST /google-product-qa/generieren`,
`GET /produkte/{id}/google-product-qa`. Nur der exakte TSV-Pfad ist öffentlich.
Google ruft den Zusatzfeed nach dem im Merchant Center eingerichteten Zeitplan
ab; die lokale Neuerzeugung stößt keinen Google-Abruf an.

Quellen (geprüft am 04.10.2026):
[Q&A-Spezifikation](https://support.google.com/merchants/answer/17085211),
[TSV-Quotierung](https://support.google.com/merchants/answer/14998273),
[ID-Spezifikation](https://support.google.com/merchants/answer/6324405).

Deployment dieser Erweiterung (Schema vor dem neuen Worker ergänzen):

```sh
cd /opt/app/krautl
git pull --ff-only origin main
docker compose build app frontend
docker compose run --rm --no-deps app python -m scripts.migrate_google_product_qa
docker compose up -d --wait app worker frontend
curl --fail --show-error https://krautl.erikschweitzer.de/feeds/google-product-faq.tsv
```

Gezielte Tests (mit `requirements.txt` sowie `aiosqlite`, `httpx` und unter
Windows `tzdata`): `python -m unittest tests.test_google_product_qa tests.test_wissensbasis`.

### Erstinstallation

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
`http://127.0.0.1:8000/health` sichtbar. `mail_worker.laeuft` zeigt ein
höchstens fünf Minuten altes technisches Lebenszeichen. `mail_worker.aktiv`
ist nur nach einem ebenso aktuellen, vollständig erfolgreichen Abruf `true`;
Abruffehler erscheinen dadurch nicht mehr irreführend als grüner Zustand.

### Automatische Wiederherstellung auf dem Produktivserver

Die Docker-Restart-Policy startet abgestürzte vorhandene Container neu, kann
aber einen entfernten oder bei einem Deployment nicht angelegten Container
nicht zurückbringen. Ergänzend prüft deshalb ein systemd-Timer alle zwei
Minuten die Dienste `db`, `app`, `worker` und `frontend`. Fehlende oder
gestoppte Dienste werden mit Docker Compose wiederhergestellt; als `unhealthy`
markierte Dienste werden neu gestartet. Frontend und Mail-Worker besitzen
dafür eigene Healthchecks; ein festhängender Worker wird so ebenfalls erkannt.

Der Wächter wird auf dem Server einmalig installiert:

```bash
cd /opt/app/krautl
sudo install -m 0644 ops/krautl-guardian.service /etc/systemd/system/krautl-guardian.service
sudo install -m 0644 ops/krautl-guardian.timer /etc/systemd/system/krautl-guardian.timer
sudo systemctl daemon-reload
sudo systemctl enable --now krautl-guardian.timer
sudo systemctl start krautl-guardian.service
systemctl status krautl-guardian.timer --no-pager
journalctl -u krautl-guardian.service -n 30 --no-pager
```

Für eine geplante vollständige Abschaltung muss der Timer vorher mit
`sudo systemctl stop krautl-guardian.timer` angehalten werden. Nach der Wartung
wird er mit `sudo systemctl start krautl-guardian.timer` wieder aktiviert.

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
  Die Antwort wird ausschließlich an die Absenderadresse der Kundenmail
  gesendet. Dafür müssen `SMTP_SERVICE_HOST`, `SMTP_SERVICE_PORT`,
  `SMTP_SERVICE_USER` und
  `SMTP_SERVICE_PASSWORD` gesetzt sein.
- Alle fachlichen API-Funktionen erfordern eine persönliche Krautl-Anmeldung.
  `erik` ist Admin; `gursewak`, `ludwig`, `aneta` und `micha` gehören zur
  Sachbearbeitung.
  Passwörter stehen ausschließlich in den Elestio-Umgebungsvariablen
  `KRAUTL_PASSWORD_ERIK`, `KRAUTL_PASSWORD_GURSEWAK` und
  `KRAUTL_PASSWORD_LUDWIG`, `KRAUTL_PASSWORD_ANETA` sowie `KRAUTL_PASSWORD_MICHA`.
  `KRAUTL_SESSION_SECRET` signiert die
  Anmeldesitzungen und muss ein langes zufälliges Geheimnis sein.
- Beim Versand ergänzt Krautl abhängig vom angemeldeten Nutzer automatisch
  Name, gegebenenfalls `Auszubildender` und die gemeinsame
  dreikraut-Geschäftssignatur. Der freigebende Nutzer wird im Aktionslog
  protokolliert.
- Die Klassifikation erkennt die Hauptsprache eingehender Mails. Fremdsprachige
  Nachrichten werden im Original und zusätzlich als deutsche Arbeitsübersetzung
  angezeigt. Bereits vorhandene Mails werden beim ersten Öffnen nachgezogen.
  Antwortvorschläge und manuelle Entwürfe bleiben für die interne Bearbeitung
  immer deutsch. Erst nach der finalen Freigabe und unmittelbar vor SMTP wird
  die Antwort in die Originalsprache übersetzt. Krautl speichert sowohl die
  freigegebene deutsche als auch die tatsächlich versendete Fassung.
- Nach dem ersten Deployment dieser Fremdsprachenfunktion muss einmalig
  `python -m scripts.migrate_uebersetzungen` im App-Container ausgeführt werden,
  bevor App und Worker mit dem neuen Schema gestartet werden.
- Bestehende Klassifikationen lassen sich unter **Einstellungen →
  Mail-Klassifikationen** bearbeiten: Zielordner sowie eine geordnete Liste
  von Aufgaben. **Bestätigung einholen** ist dabei eine frei wählbare Aufgabe,
  keine fest eingebaute Pflicht. Neue Klassifikationen anlegen oder vorhandene
  löschen ist noch nicht über die Oberfläche möglich.
- **Audio transkribieren** ist als auswählbare Aufgabe implementiert. Sie muss
  vor **Mail verschieben** stehen, solange das Audio aus dem ursprünglichen
  IMAP-Posteingang geladen wird. Das Ergebnis wird als bereits gelesene Mail
  mit dem Präfix **[TRANSKRIPTION]** eingestellt und anschließend anhand des
  gesprochenen Kundenanliegens normal klassifiziert. Der technische Absender
  und das mitgesendete Originalaudio werden dabei als Klassifikationsmerkmale
  ausgeschlossen, damit weder INTERN_AUFGABEN noch eine erneute
  AUDIO_TRANSKRIBIEREN-Schleife entstehen. Bereits vom alten Schleifenschutz
  versteckte Transkripte nimmt einmalig
  `python -m scripts.klassifiziere_transkripte_nach` wieder auf.
  `OPENAI_API_KEY` ist erforderlich; das Modell kann optional mit
  `OPENAI_TRANSCRIPTION_MODEL` geändert werden. Die reine Gliederung und
  Formatierung übernimmt standardmäßig das kleine, schnelle Claude Haiku 4.5;
  `AUDIO_FORMATTING_MODEL` kann dieses zweite Modell bei Bedarf überschreiben.
- Unter **Einstellungen → Rollen & Mailzugriff** legt ein Admin je
  Klassifikation fest, welche Mailarten Sachbearbeiter sehen und bearbeiten
  dürfen. Die Prüfung erfolgt auch im Backend für Posteingang, Bestätigungen,
  Kategoriekorrekturen, Antwortentwürfe, zugehörige Rechnungen und aus Mails
  abgeleitete Wissensvorschläge. Admins haben stets Zugriff auf alle Mailarten.
- Die Rollen-Matrix bestimmt zugleich die anfängliche Zuständigkeit neuer
  Mails. Über **Zuweisen** kann eine Mail anschließend exklusiv Erik als Admin
  oder der gemeinsamen Sachbearbeitungsgruppe Guri, Ludwig, Aneta und Micha zugeordnet
  werden. Admins sehen standardmäßig nur ihre eigene Arbeitsliste und können
  zur Kontrolle auf **Alle Mails** wechseln. Zuweisungen werden im Aktionslog
  mit dem auslösenden Nutzer festgehalten.
- Von `dreikraut.de` selbst versendete Systemhinweise zu Lagerbeständen oder
  möglichen Adressfehlern gehören in `INTERN_AUFGABEN`. Sie warten nur auf
  Bestätigung und werden danach nach `service@dreikraut.de/Erledigt`
  verschoben. Die Kategorie wird einmalig mit
  `python -m scripts.aktualisiere_interne_aufgaben` angelegt beziehungsweise
  gezielt aktualisiert.
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

### Historische Rechnungen nachholen

Der historische Rechnungslauf durchsucht ausschließlich den jeweiligen
`INBOX`-Ordner der vier operativen Postfächer `info`, `service`, `einkauf` und
`marketing`. Unterordner werden ausdrücklich nicht durchsucht. Zusätzlich zur
IMAP-Datumssuche wird das tatsächliche Eingangsdatum jeder gefundenen Nachricht
noch einmal lokal in Berliner Zeit geprüft. Die Nachrichten werden weder
verschoben noch gelöscht oder als gelesen markiert. Erkannte Rechnungen
erscheinen in Krautl, bleiben aber aus der Mail-Arbeitsliste ausgeblendet.

Für den vorbereiteten Zeitraum vom 1. Februar bis einschließlich 30. April
2026 und den Dropbox-App-Pfad `/Rechnungen/Eingang` genügt:

```bash
docker compose exec app python -m scripts.historische_rechnungen_importieren
```

Bei der Dropbox-App `krautl Elestio` entspricht das lokal dem synchronisierten
Ordner `Apps/krautl Elestio/Rechnungen/Eingang`. Der Lauf ist wiederholbar:
Message-IDs, Rechnungsmerkmale und deterministische Dateinamen verhindern
zusätzliche Rechnungsdatensätze und Dateikopien. Erfolgreiche Importe und als
Nicht-Rechnung erkannte Anhänge werden als Fortschritt gespeichert und bei
einem Fortsetzungslauf nicht erneut per KI analysiert. Mit
`--erneut-pruefen` kann diese Sperre für einen bewussten Kontrolllauf
übergangen werden. Abweichende Zeiträume und Zielordner lassen sich mit
`--start`, `--ende-einschliesslich` und `--zielordner` angeben. Nach fünf
aufeinanderfolgenden Abruf- oder Verarbeitungsfehlern bricht das Skript
kontrolliert ab, damit eine fehlerhafte Konfiguration nicht den gesamten
Posteingang mit Fehlversuchen durchläuft. Standardmäßig laufen zwei
Rechnungsanalysen gleichzeitig. `--parallelitaet 1` schaltet auf den
langsameren seriellen Betrieb zurück; Werte bis höchstens `4` sind möglich.

### FAQ aus Dokumenten übernehmen

Unter **Wissensdatenbank → FAQ → FAQ aus Dokument** können PDF, DOCX, ODT,
TXT, Markdown, CSV, JSON und HTML bis 10 MB ausgewertet werden. Andere Formate
vorher als PDF speichern. Textdateien sind auf 150.000 Zeichen begrenzt;
pro Dokument sind höchstens 100 Frage-Antwort-Paare vorgesehen. Die Auswertung
verwendet die bestehende Anthropic-Anbindung (`ANTHROPIC_API_KEY`) und übermittelt
den Dokumentinhalt an die KI. Originaldateien werden nicht dauerhaft abgelegt.

Die Vorschau ordnet Produkte zuerst anhand der Artikelnummer zu (einschließlich
führender Nullen), nur ohne Artikelnummer anhand der ID, danach des exakten
Namens. Unbekannte oder mehrdeutige Artikelnummern erfordern manuelle Zuordnung.
Abweichende IDs/Namen werden angezeigt. Auswahl, Zuordnung, Rubrik, Frage und
Antwort sind vor dem Übernehmen bearbeitbar.

Die Übernahme legt ausschließlich Entwürfe an, zunächst mit `aktiv=false` und
`include_in_google_product_qa=false`. Nach Prüfung können sie im vorhandenen
FAQ-Editor aktiviert und freigegeben werden. Vorhandene Fragen desselben Produkts
(ohne Beachtung von Groß-/Kleinschreibung und äußerem Leerraum) werden übersprungen,
auch bei wiederholter Übernahme; vorhandene Antworten werden niemals überschrieben.
Die gesamte Auswahl wird vor dem Speichern validiert und in einer Transaktion
übernommen. Die Analyse selbst verändert keine FAQ.
