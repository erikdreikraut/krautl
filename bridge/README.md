# Automatischer Bilddienst fuer Krautl

Der Grafiker arbeitet ausschliesslich in Krautl. Hinzufuegen und Sortieren bleiben
bei den vorhandenen API-Ablaufen. Bei aktiviertem Bilddienst wird ein bestaetigter
Austauschauftrag vom Windows-Dienst abgeholt. Es gibt keine Bedienoberflaeche und
keinen Wawi-Zugang fuer den Grafiker.

**Stand: implementiert und lokal mit simulierten Abhaengigkeiten getestet;
noch nicht auf dem Wawi-SQL-Server ausgefuehrt oder produktiv abgenommen.**
Zuerst nur SKU 1036 freigeben. Die Aktivierung ist eine eigene Betriebsaktion.

## Ablauf und Grenzen

1. Krautl prueft Ausgangsbild, Artikel und Revision, sichert das Original und
   speichert den Auftrag samt Datei. Ein offline gebliebener Dienst verhindert
   neue Austauschauftraege. Bereits laufende Auftraege bleiben dauerhaft erhalten.
2. Der Dienst prueft die bekannte Tabellen-/Trigger-/Fremdschluesselstruktur,
   SQL-Artikelnummer, API-Zuordnung und Originalvorschau. Er sichert lokal die
   kompletten Zuordnungen mit Rowversions, SEO-Daten und Originaldatei.
3. Ein einziger API-POST importiert die neuen Bilddaten ueber Wawi. Nur ein
   eindeutig neues Bild mit Auftragsdateiname, passenden Vorschaupixeln und
   ausschliesslich zusaetzlichen Shop-/Standardzuordnungen wird akzeptiert.
4. Eine SQL-Transaktion entfernt ausschliesslich die neuen temporaeren
   Importzuordnungen und ersetzt die Bildreferenz in den bisherigen Zuordnungen.
   Deren IDs, Kanal-/Kontokennungen, Positionen und Bildnamen bleiben erhalten.
   POS (Plattform 7 / Shop 8) bleibt gemaess Projektvorgabe ausgenommen.
   Originale Bilddatensaetze und gemeinsam genutzte Bilder werden nie geloescht.
5. Die installierten Trigger laufen normal. Fuer eBay wird bei betroffenen
   Positionen bis 12 zusaetzlich die native Prozedur aufgerufen, die der Trigger
   sonst nur bei Plattform-/Positionsaenderungen aufruft. Deren reale Wirkung
   gehoert ausdruecklich zur Abnahme; ein SQL-Aufruf beweist keine Veroeffentlichung.
6. Eine eigene SQL-Quittung wird in derselben Transaktion gespeichert. Erst
   Quittung, Zuordnungen, SEO und Bildinhalt ergeben ein lokales Erfolgsergebnis.
   Krautl liest zusaetzlich unabhaengig ueber die API zurueck. Erst dann erscheint
   Wawi-bestaetigt, die Vorschau wechselt und das offene Uploadfenster schliesst.
   Der vorhandene Shop-Pruefplan bleibt davon unabhaengig.

Die API-Anlage und SQL-Transaktion sind nicht gemeinsam atomar. Zwischen ihnen
kann das neue Bild kurz als zusaetzliches Bild existieren. Bei Abbruch wird kein
Upload oder SQL-Schreibversuch wiederholt: nur ruecklesen; ungeklaerte Auftraege
brauchen Administratorpruefung. Kein automatisches Entfernen unbekannter Bilder.
Ein Wawi-/Shop-Abgleich kann diesen Zwischenstand sehen; die erste Abnahme daher
mit pausiertem Abgleich und danach kontrollierter Veroeffentlichung durchfuehren.

Die Bruecke vereinigt nicht eigenmaechtig bereits auseinandergefallene Bilder.
Bei Anchan sind 2488, 2729 und 2731 verschiedene Bilddatensaetze. Ersetzt wird das
in Krautl ausgewaehlte Shopbild mit seinen tatsaechlichen Zuordnungen. Alte
ungeklaerte Krautl-Auftraege vor einem neuen Test anhand des realen Bestands
abschliessen/zuruecksetzen, nicht die Journaltabellen pauschal leeren.

## Einmalige Einrichtung auf dem Windows-/Wawi-Server

Voraussetzungen: Python 3.11 oder neuer, Microsoft ODBC Driver 18 for SQL Server,
Zugriff auf die lokale Datenbank eazybusiness sowie HTTPS zu Krautl und zur
bestehenden Wawi-API. Keine eingehende Internetfreigabe fuer SQL oder den Dienst.
Das Verzeichnis `bridge` aus diesem Repository nach
`C:\Krautl-Bilddienst\bridge` uebertragen. Befehle in PowerShell:

```powershell
Set-Location C:\Krautl-Bilddienst
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r bridge\requirements.txt
Copy-Item bridge\config.example.json bridge\config.json
.\.venv\Scripts\python.exe -c "import uuid,secrets; print('worker_id:',uuid.uuid4()); print('bridge_token:',secrets.token_urlsafe(48))"
```

Config nur einmal anlegen, bestehende Config nicht ueberschreiben. Die erzeugte
Worker-ID bleibt dauerhaft gleich. Token und Wawi-Schluessel nicht in Chats,
Tickets oder Git speichern. `config.json` lokal ausfuellen:

- `worker_id` und zufaelliges `bridge_token` einsetzen.
- `wawi_url` entspricht exakt dem Krautl-Wert `JTL_LOCAL_URL`, ebenso den
  vorhandenen FAQ-/Bildzugang verwenden. Keine neue App registrieren.
- `wawi_ca` bei eigener CA auf die lokale Zertifikatsdatei setzen; TLS-Pruefung
  nicht abschalten. Die URL muss auch vom Windows-Server erreichbar sein.
- `sql_connection` an Instanz und vertrauenswuerdiges Zertifikat anpassen.
  Fuer integrierte Anmeldung gilt das Windows-Konto des geplanten Dienstes,
  nicht automatisch das des geoeffneten SSMS.
- `allowed_skus` zunaechst `["1036"]`, `enable_writes` zunaechst `false`.

In SSMS einmal `bridge/install_receipts.sql` ausfuehren. Es legt ausschliesslich
das eigene Schema `KrautlBilddienst` und die Auftragstabelle an, keine Bilder.
Eigene Quittungen gemeinsam mit der Wawi-Datenbank sichern.

Das Dienstkonto braucht Leserechte auf die verwendeten Wawi-Tabellen und
Metadaten/Triggerdefinitionen, gezielte UPDATE/DELETE-Rechte auf
`dbo.tArtikelbildPlattform`, EXECUTE/Typrechte fuer die native eBay-Prozedur und
INSERT/SELECT auf die eigene Quittungstabelle. Rechte fuer durch Trigger
angesprochene Objekte muessen im konkreten SQL-Sicherheitsmodell funktionieren.
Keine automatische Rechtevergabe und kein pauschales db_owner fuer den Betrieb.

Config und Journalordner per NTFS ausschliesslich dem Dienstkonto, SYSTEM und
Administratoren zugaenglich machen. Das Journal enthaelt Originalbilder.

```powershell
.\.venv\Scripts\python.exe -m bridge.worker --config bridge\config.json --check
```

Dieser Lauf prueft SQL-Struktur und Quittungstabelle, schreibt aber keine Bilder.
Wawi-API-/Krautl-Erreichbarkeit wird damit noch nicht bestaetigt.

## Krautl aktivieren und Test

Auf dem Krautl-Server in `.env` setzen:

```dotenv
BILDER_BRUECKE_AKTIV=1
BILDER_BRUECKE_SKUS=1036
BILDER_BRUECKE_TOKEN=<derselbe zufaellige Token wie in config.json>
```

App und Frontend mit dem aktuellen Commit bauen/ausrollen. Erst laufende
Elestio-Pipeline abwarten, keine parallelen Deployments. Der Bilddienst bleibt
ohne diese Aktivierung unbenutzt; der alte API-Austauschpfad wird nicht still
als repariert ausgegeben.

Nach erfolgreicher Strukturpruefung in Windows-Config `enable_writes=true`
setzen und Dienst starten:

```powershell
.\.venv\Scripts\python.exe -m bridge.worker --config bridge\config.json
```

Er pollt alle zehn Sekunden und nimmt nur bereits vom Nutzer bestaetigte
Krautl-Auftraege an. Kein Auftrag bedeutet keine Bildaenderung. Im Fehlerfall
zeigt die Konsole Auftrag und Fehlerklasse bzw. kontrollierte Pruefmeldung.

Abnahme: Austausch in Krautl bestaetigen; Original-/Kanalpositionen vorher/nachher
vergleichen, insbesondere mehrere eBay-Konten mit verschiedenen Positionen,
SEO und unbeteiligte Bilder. Wiederholung/Neustart darf keinen zweiten Upload
erzeugen. Anschliessend Wawi-Abgleich starten und Shopbild getrennt pruefen.
Erst danach `allowed_skus` und serverseitig `BILDER_BRUECKE_SKUS` erweitern.
`["*"]` in der Config und `BILDER_BRUECKE_SKUS=*` geben alle Artikel frei.

## Automatischer Start nach erfolgreicher Abnahme

Windows-Aufgabenplanung: Aufgabe `Krautl-Bilddienst`, Trigger Systemstart,
Programm `C:\Krautl-Bilddienst\.venv\Scripts\python.exe`, Argumente
`-m bridge.worker --config C:\Krautl-Bilddienst\bridge\config.json`,
Arbeitsverzeichnis `C:\Krautl-Bilddienst`. Unter dem eingerichteten Dienstkonto
unabhaengig von dessen Anmeldung ausfuehren, keine zweite Instanz starten,
keine maximale Laufzeit; Neustart nach Fehler aktivieren. Kein interaktives
Wawi-Fenster erforderlich. Zugriff und Protokollierung unter diesem Konto testen.

Die Worker-ID und das Journal bei Updates erhalten. Bei verlorenem Journal
werden schon ausgelieferte Auftraege abgewiesen; niemals eine neue Worker-ID
verwenden, um einen unklaren Schreibauftrag erneut auszufuehren.

Ruecknahme: Windows-Aufgabe stoppen und Brueckenaktivierung deaktivieren.
Auftraege/Originalsicherungen und SQL-Quittungen behalten. Angefangene Auftraege
werden nicht automatisch durch den alten API-Pfad wiederholt.


## Vereinfachte Einrichtung ueber Administrator-Download (03.11.2026)

Vom Nutzer ausdruecklich freigegeben: GET `/api/admin/bilddienst-paket` liefert
nach normaler Krautl-Sitzungspruefung ausschliesslich Administratoren ein ZIP mit
vorhandenem Wawi-API-Key, eigenem Brueckentoken, stabiler Worker-ID und optional
CA-Zertifikat. Kein oeffentlicher Link mit Zugangstoken, kein Cache, keine
Ausgabe der Zugangsdaten in Logs. Das ZIP darf nicht geteilt werden.

Serverseitig muessen `BILDER_BRUECKE_TOKEN` (mindestens 32 Zeichen) und
`BILDER_BRUECKE_WORKER_ID` (dauerhafte UUID) vorbereitet sein. Bestehende Werte
nicht rotieren. Der Download aktiviert weder `BILDER_BRUECKE_AKTIV` noch Windows-
Schreibzugriffe. Config: `enable_writes=false`, `allowed_skus=["1036"]`.

Die SQL-Strukturpruefung und Anlage der eigenen Quittungstabelle wurden auf dem
Wawi-Server am 03.11. durch die Nutzer-Ausgabe erfolgreich bestaetigt. Dort ist
ODBC Driver 17 vorhanden; die lokale Verbindung verwendet Shared Memory
`lpc:.\JTLWAWI` und integrierte Anmeldung. Sie oeffnet keinen SQL-Netzwerkzugang.

Das Paket enthaelt `einrichten.py` aus `bridge/install_package.py`. Es installiert
nur nach C:/Krautl-Bilddienst, setzt zuerst restriktive NTFS-Rechte fuer aktuellen
Benutzer, SYSTEM und Administratoren, ueberschreibt keine vorhandene config.json
und laesst Journale unberuehrt. Nach erfolgreicher Installation wird die eigene
ZIP-Kopie in Downloads entfernt. Anschliessend liest `bridge.check_connection`
SQL-Struktur, Wawi-Artikel 1036 und Krautl-Health; kein Poll, kein Dienststart,
keine Bildaenderung. Ein erfolgreicher Test belegt noch keine Bruecken-Schreibabnahme.

Bereitstellung nach Ende einer laufenden Elestio-Pipeline, nur wenn der Container
nicht bereits den neuen Stand und die vorbereiteten Umgebungswerte enthaelt:

```bash
cd /opt/app/krautl &&
git remote set-url origin https://github.com/erikdreikraut/krautl.git &&
git pull --ff-only origin main &&
docker compose build app &&
docker compose up -d --no-deps --force-recreate app
```

Keine Datenbankmigration und kein Frontend-Neubau fuer diesen Endpunkt erforderlich.

## Isolierte Schreibabnahme fuer Artikel 1036

Einrichtung einschliesslich Wawi-Lesen und Krautl-Erreichbarkeit wurde vom Nutzer
am 03.11.2026 erfolgreich bestaetigt. Dauerbetrieb und Schreibfreigabe bleiben aus.
Der alte offene Krautl-Auftrag fuer Bild 2488 wird nicht erneut ausgefuehrt;
die lokale Vorschau ist ebenfalls noch veraltet. Beides vor der spaeteren
Freigabe der Bedienoberflaeche separat abgleichen und nachvollziehbar klaeren.

GET `/api/admin/bilddienst-test` liefert nur angemeldeten Administratoren
`Krautl-Bildtest.py` (Quelle `bridge/acceptance.py`), ohne Zugangsdaten. Auf dem
Wawi-Server nach Downloads speichern und in PowerShell ausfuehren:

```powershell
Set-Location C:\Krautl-Bilddienst
& .\.venv\Scripts\python.exe "$env:USERPROFILE\Downloads\Krautl-Bildtest.py" --ausfuehren
```

Nur bei weiterhin pausierten Abgleichen und unberuehrtem Artikel 1036 ausfuehren.
Das Skript verwendet die vorhandene Konfiguration, verlangt `enable_writes=false`
und `allowed_skus=["1036"]`, startet keinen Dienst und pollt keine Auftraege.
Es sperrt parallel laufende Worker ueber deren regulaere Dateisperre. Artikel,
Shoppositionen und alle vier Originaldateien werden gegen den zuvor unabhaengig
gelesenen Stand geprueft. Originaldateien, SQL-Zuordnungen, SEO und API-Zuordnungen
werden im geschuetzten Installationsordner in `bildtest-1036.sqlite3` gesichert.

Ein verkleinertes vorhandenes Produktfoto mit einmaliger kleiner Farbmarkierung
ist nur die technische Testdatei. Der Austausch verwendet `run_job` aus dem
installierten Bilddienst. Nach bestaetigtem Austausch setzt eine gesondert
protokollierte SQL-Transaktion dieselben Zuordnungs-IDs auf die Original-Bild-ID
zurueck; sie laedt das Original nicht nochmals hoch. Originaldateien werden
nicht geloescht. Der neue Test-Bilddatensatz bleibt danach ohne Artikelzuordnung
erhalten. API-Aliase werden im unabhaengigen Vergleich mit ihrer Anzahl geprueft.

Bei unklarem Ausgang oder Abweichung stoppen; keine blinde Wiederholung,
Abgleiche pausiert lassen. Ein vorhandenes Journal verhindert einen neuen Lauf.
Bei erneutem Aufruf wird hoechstens der Originalbestand lesend geprueft;
angefangene Schreibschritte werden nicht automatisch wiederholt oder fortgesetzt.
Eine Fehlermeldung nach dem Import kann daher eine zusaetzliche Testzuordnung
zur manuellen Diagnose hinterlassen. Journal und SQL-Quittungen aufbewahren.

Die Live-Schreibabnahme steht noch aus. Ein Erfolg prueft die lokale Import-/
Austausch-/Ruecknahmelogik; weder Krautl-Auftragszustellung noch Shop-Veroeffentlichung
sind damit abgenommen. Bereitstellung des Download-Endpunkts: dieselben oben
angegebenen App-Build-/Recreate-Befehle, keine Migration und kein Frontend-Build.

Erster Windows-Test stoppte vor Schreibbeginn mit `Unerwartete Bildnummern`.
Die anschliessende Nutzerabfrage bestaetigte zusaetzlich Bild 2488 auf Plattform 8,
Shops 11/13/14, jeweils Position 1. Diese drei SQL-Zuordnungen fehlen in der API.
Der Test verlangt nun genau diese bestaetigten Zusatzzuordnungen und sichert
auch deren Originaldatei. Nach Austausch und Ruecknahme werden alle gesicherten
Originaldateien bytegenau verglichen, einschliesslich des API-unsichtbaren Bilds.
Andere unerwartete SQL-Bilder oder Zusatzzuordnungen bleiben Abbruchgruende.
Die alte Vorpruefung erreichte weder Auftragsjournal-Eintrag noch Upload; fuer
den korrigierten Lauf ist keine Journal-Loeschung erforderlich oder erlaubt.
