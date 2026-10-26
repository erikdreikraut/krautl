# Krautl: Projektregeln

## Arbeitskopie und Betrieb

- Lokale Arbeitskopie auf diesem Windows-Host: `C:/Users/info/Documents/Codex/Krautl`. Der im Codex-Projekt gespeicherte Dropbox-Pfad ist veraltet; vor Arbeiten die tatsächliche Arbeitskopie prüfen.
- Maßgebliche Betriebs- und Fachbeschreibung: [README.md](README.md). Vor Änderungen an WhatsApp-Einrichtung, Versand oder Verarbeitung den zugehörigen Abschnitt lesen.
- Die Produktivinstanz läuft unter `https://krautl.erikschweitzer.de`, Server-Arbeitskopie `/opt/app/krautl`. Ein lokaler Build oder Push belegt kein Deployment.
- Nach jedem erfolgreichen Push die zum Änderungsstand passenden, direkt ausführbaren Deployment-Befehle für die Serverkonsole mitliefern. Projektpfad `/opt/app/krautl`, Branch `main` und erforderliche Build-/Migrationsschritte anhand der Projektdokumentation prüfen. Für Git-Remotes und Abrufe HTTPS statt SSH verwenden: `git remote set-url origin https://github.com/erikdreikraut/krautl.git`. Bei reinen Dokumentationsänderungen ausdrücklich darauf hinweisen, dass kein Deployment erforderlich ist; dafür genügt die HTTPS-Aktualisierung der Server-Arbeitskopie. Das Bereitstellen der Befehle ist keine Freigabe, das Deployment selbst auszuführen.

## WhatsApp

- Gewählter Betrieb: direkte Meta Cloud API, API-only; keine parallele Business-App-Nutzung für die Geschäftsnummer voraussetzen.
- WhatsApp-Nachrichten werden weder initial noch bei weiteren Chatnachrichten KI-klassifiziert. Keine Kategorieauswahl im Chat. KI-Antwortvorschläge bleiben ausdrücklich ausgelöst.
- Keine automatischen Nachrichten oder automatischen Wiederholungen bei unklarem Versand. Revisionen, Reservierungen, Berechtigungen, dauerhafte Versandaufträge und Metas Antwortfenster bei Änderungen erhalten.
- In der Navigation bündelt „Archiv“ die Reiter „WhatsApp-Chats“ und „Gesendete E-Mails“; deren bestehende Such- und Detailfunktionen erhalten.
- Im WhatsApp-Antwortfeld senden Enter und „Antwort senden“; Shift+Enter fügt einen Zeilenumbruch ein. Beim Öffnen einmalig fokussieren; Polling darf den Fokus nicht aus anderen Feldern stehlen.

## FAQ-Freigabe und geplante JTL-Synchronisierung

- FAQ haben in Übersicht und Editor nur die unabhängigen Auswahlhaken „In FAQ aufnehmen“ und „Für Google ausgewählt“. Kein FAQ-Status-Dropdown und keine separate Freigabeanzeige. Der FAQ-Haken steuert HTML-Export und geplanten JTL-Abgleich; ohne Haken ist der Eintrag ein Entwurf. Intern bleiben `status=freigegeben` und `aktiv=true` als gemeinsame Speicherung der Auswahl erhalten; Abwählen setzt `entwurf` und `aktiv=false`. Wissenseinträge behalten ihre eigene Statuslogik.
- Bestehende aktive Entwürfe gehörten zur alten Exportauswahl und sollen einmalig durch `scripts.migrate_faq_freigabe` freigegeben werden. Die Migration nicht ohne ihren dauerhaften Ausführungsnachweis nachbauen oder erneut per pauschalem UPDATE ausführen.
- Bestätigte JTL-Ziele: `tab1 name` = `Fragen / Antworten`, `tab1 inhalt` = bestehender HTML-Export; ausschließlich Deutsch im dreikraut JTL-Shop. Entfällt der letzte übertragbare FAQ, beide Zielwerte leeren. Andere Attribute, Sprachen und Kanäle erhalten.
- Google-Zusatzfeed bleibt unabhängig. Eigene Krautl-JTL-App und eigene Zugangsdaten verwenden; Werkel bleibt unverändert. Stand der lokalen Schreibabnahme und noch ausstehende HTTPS-Inbetriebnahme in `ops/jtl/README.md` beachten.
- Dauerabgleich: HTTPS-Direktzugriff auf die Wawi-API, Firewall nur für die öffentliche Krautl-Server-IP. Alle fünf Minuten nur geänderten FAQ-HTML-Export übertragen; erfolgreich bestätigte Stände dauerhaft merken. Artikel mit gleicher SKU und echte JTL-Varianten über `parentItemId` bedienen, keine Zuordnung anhand von SKU-Präfixen. Eigene ausgewählte Varianten-FAQ haben Vorrang. Bei unklarem Schreibausgang zuerst rücklesen, niemals blind erneut schreiben.
- JTL-Überwachung: Nutzer wünscht Warnungen sichtbar auf der Krautl-Startseite, keinen externen Überwachungsdienst und keine E-Mail-Benachrichtigung. Letzten erfolgreichen Prüflauf, Fehler, Sperren und ausbleibende Läufe anzeigen; unbekannten/veralteten Status nicht als gesund darstellen.

## Inkasso

- Für Admins und alle Sachbearbeiter zugänglich, einschließlich Auswahlaktualisierung und Hinzufügen von Notizen; eigener Hauptmenüpunkt rechts neben Rechnungen. Nur bestätigte Kanäle JTL-Shop `2-2-1` und JTL-Wawi `1-1-0` (v1-Auftragsalias `1-1-1`, anhand RE315603 bestätigt); Herkunft in der Bestellübersicht erhalten; keine Kanalspalte in der Inkasso-Liste. Telefonnummern aus Rechnungs-/Auftragsrechnungsadressen und eine lokale Auftragsübersicht als modales Pop-up anbieten.
- Neuaufnahme offener Rechnungen maximal aus den letzten zwölf Kalendermonaten. Einmal erfasste Fälle unabhängig vom Alter weiter prüfen; bezahlte/stornierte Fälle als abgeschlossen erhalten. Abruffehler sind niemals ein Zahlungsnachweis.
- Aktiver eigener Inkasso-Lesezugang: `krautl-inkasso-lesen`; der alte Zugang `krautl-inkasso` bleibt als gesicherter Rückfallzugang erhalten. FAQ-Zugang unverändert lassen. API-v1-Rechnungen über Positionen und Aufträge zuordnen. Registrierungs- und Betriebsablauf siehe README, Abschnitt Inkasso.

- Inkasso-Zahlungsartfilter ohne eigene Spalte: Standard Rechnungskauf Apotheken (12); weitere Optionen Alliance Healthcare (14), Bar (1), Überweisung (2), PayPal (6) und alle diese relevanten Zahlungsarten. Andere Zahlungsarten nicht im Dropdown anbieten.

- Inkasso „Auswahl aktualisieren“ liest Rechnungsdetails der aktuell gefilterten IDs (alle Seiten) und bei fehlenden Telefonnummern mit erweitertem Lesezugang gezielt deren Kundenstamm. Kein dadurch ausgelöster Gesamtabruf und keine Wawi-Schreibzugriffe/Gutschriftanlage. Teilaktualisierungen dürfen den globalen Datenstand nicht als frisch markieren.

- Erweiterter Lesezugang (bereits aktiviert und durch erfolgreiche API-Prüfungen bestätigt): Parallelregistrierung `krautl-inkasso-lesen` mit `all.read` plus expliziten Rechnungs-, Auftrags-, Verkaufskanal- und Kundenleserechten. Alten Zugang erst nach erfolgreichen API-Pruefungen atomar ersetzen und sichern; FAQ/Werkel unveraendert. Fehlende Telefonnummern gezielt per CustomerId aus BillingAddress ergaenzen, Kundenantwort-ID validieren und pro Lauf cachen. Ablauf in README.

- Inkasso-Anzeige nach Rechnungsalter trennen: ab 56 Kalendertagen oben, jüngere offene Rechnungen darunter unter „Noch nicht fällig“. Stichtag Europe/Berlin; reine Anzeigegruppierung unabhängig vom Wawi-Zahlungsziel. Filter/Auswahlaktualisierung gelten für beide Abschnitte.

- Inkasso-Zuweisung rechts per kompaktem Dropdown an einzelne Nutzer, nicht Rollen/Abteilungen. „Alle“ bedeutet keine persönliche Zuweisung (intern leer), nicht Zuweisung an sämtliche Nutzer. Dropdown und neue automatische Zuweisungsnotizen verwenden einheitlich nur den Vornamen; bestehende Protokolleinträge bleiben unverändert. Alle Rechnungen bleiben für alle Admins/Sachbearbeiter sichtbar. Nur der konkret zugewiesene aktive Nutzer sieht die Zeile blassrot. Zuweisung getrennt vom Wawi-Snapshot speichern und atomar mit unveränderbarem Notizeintrag „Name zugewiesen“ samt ausführendem Nutzer/Zeitstempel protokollieren; Aufheben ebenfalls protokollieren.

## Nutzernamen

- Vollständige zentrale Anzeigenamen: Erik Schweitzer, Gursewak Singh, Ludwig Schnorrenberg, Aneta Mikolajec und Micha Durst. Mail-Signaturen verwenden diese vollständigen Namen. Bewusst kurze Anzeigen (insbesondere Inkasso-Zuweisungen) bleiben bei Vornamen; historische Protokolle und bereits versendete Mails nicht umschreiben.

## Grafik

- Micha Durst gehört zur Nutzergruppe `grafik`, nicht mehr zur Sachbearbeitung. Grafik darf ausschließlich Wissensdatenbank (einschließlich Bearbeiten von Wissen, Produkten und FAQ) und Bilder nutzen. Mailbasierte Vorschläge und alle übrigen internen Bereiche auch serverseitig sperren. Erik als Admin sieht weiterhin alles.
- Bilder ist für Admin und Grafik: eine Zeile je aktivem Shop-Artikel, Vater/Kinder über echte parentItemId gruppiert, links Name/Artikelnummer und rechts ausschließlich Bilder des JTL-Shop-Kanals `2-2-1` in Shop-Reihenfolge. Auch Artikel ohne Bilder anzeigen. Seit 26.10.2026 sind manuell bestätigtes Hinzufügen und Austauschen von Shop-Bildern über Krautl beauftragt; andere Verkaufskanäle unverändert erhalten.
- Klick auf den Artikelnamen öffnet ein Popup mit „Ausblenden“. Ausblendungen gelten dauerhaft für alle Nutzer ausschließlich in der Bilderverwaltung, werden unabhängig vom Wawi-Snapshot gespeichert und bei Aktualisierungen vor Detail-/Bildabrufen sowie vor Veröffentlichung geprüft. Filter „Ausgeblendete anzeigen“ erlaubt Wieder-Einblenden. FAQ-Abgleich bleibt unberührt. Nur manuelles Aktualisieren; letzte erfolgreiche Aktualisierung, Fortschritt und Fehler sichtbar machen.
- Bestehenden FAQ-Zugang für Artikellesen verwenden. Der Inkasso-Lesezugang lieferte beim Artikelabruf am 23.10. HTTP 403; keine stillen Registrierungen oder Rechteänderungen. Bildlesezugriff und Shop-Zuordnung vor Produktivabnahme gezielt prüfen. Historische Notizen und bestehende Inkasso-Zuweisungen bei Rollenwechseln erhalten.
- Elestio hat den Push von `4cf9877` am 23.10.2026 automatisch gebaut und ausgerollt. Vor manuellen Deployment-Befehlen den Pipeline-Status prüfen; keine parallelen Deployments starten.

- Ältere Wawi ohne Artikelblock `salesChannels`: Katalogstatus nur nach pro Lauf bestätigtem Einzelshop `2-2-1` verwenden. Verkaufskanäle lesend über bestehenden Inkasso-Zugang; Shop meldet Typ 0 mit onlineShopActivation=true, POS Typ 2 ausschließen. Mehrere Shops/unklare Daten brechen ab. Artikel und Bilder weiterhin über FAQ-Zugang.

- Einzelne fehlerhafte Bilder als sichtbare Platzhalter mit Position/Fehler erhalten; übrigen Bilderbestand übernehmen und Warnung anzeigen. Fehlende Vorschauen beim nächsten manuellen Abgleich erneut versuchen, ausgeblendete Artikel weiterhin überspringen. Globale Zugangs-/Katalog-/Verbindungsfehler nicht als erfolgreiche Teilaktualisierung behandeln.

- Bilderabgleich speichert fertig verarbeitete Artikel revisionsgeschützt als sichtbaren, ausdrücklich unvollständigen Zwischenstand. Bei globalen Fehlern keine Löschungen und keinen vollständigen Erfolgszeitpunkt setzen. Erst vollständiger Lauf bereinigt entfernte Artikel. Nur lesende Katalog-/Detailabfragen bei HTTP 500/502/503/504 oder Verbindungsfehlern maximal dreimal versuchen; keine Änderung an FAQ-Schreiblogik.

- Wiederholte HTTP 500/502/503/504 ausschließlich beim Einzelartikel-Detailabruf nach drei Versuchen überspringen und separat als ungeprüft führen. Bestehende Bilder erhalten, bei neuen Artikeln Bildbestand unbekannt lassen; übrige Artikel weiterverarbeiten. Bei offenen Artikeln keine Bestandsbereinigung und keinen neuen vollständigen Erfolgszeitpunkt. Katalog-/Berechtigungs-/Netzwerkfehler bleiben Abbruchgründe.

- Ersatzvorschauen dürfen aus vom Nutzer bestätigten JTL-Shop-Ameise-Exporten ausschließlich in Krautl importiert werden. Keine Wawi-Schreibzugriffe. Exakte Positionsmenge prüfen, an aktuelle Bild-ID/Version binden, nur fehlende Vorschauen ergänzen und als Exportvorschau kennzeichnen. Ausgeblendete/ungeprüfte Artikel und laufende Abgleiche sperren.

- Bilderübersicht nach aktiven Shop-Kategorien mit kleinen Kategoriepfad-Überschriften und Shop-Sortierreihenfolge gruppieren; Artikelfamilien zusammenhalten, Mehrfachzuordnungen ohne doppelte Artikelzeilen anzeigen. Keine umgebenden Artikelboxen; Vater-/Kind-Einrückung erhalten. Kategoriefehler dürfen den Bildabruf nicht verhindern und müssen sichtbar bleiben.

- Bildänderungen nur nach Dateiauswahl, Vorschau und ausdrücklicher Bestätigung. Neue Datei mit ASCII-Dateiname anlegen; beim Austausch ausschließlich Shop-Zuordnung ändern, gemeinsam genutzte Originaldateien nicht überschreiben/löschen. Dauerhaften Auftrag vor Schreibzugriff sichern; bei unklarem Ausgang nur rücklesen, nicht automatisch erneut schreiben. Wawi-Bestätigung und tatsächliche Shop-Veröffentlichung unterscheiden; ohne öffentlichen Nachweis keine Shop-Erfolgsbehauptung.

- Bilderreihenfolge innerhalb einer Artikelzeile per Drag-and-drop ändern; erst „Reihenfolge speichern“ schreibt an Wawi. Das erste Bild wird automatisch einziges Hauptbild, Positionen fortlaufend ab 1. Andere Kanäle unverändert erhalten. Entwürfe beim Polling erhalten, bei geändertem Bildbestand Speichern sperren. Reihenfolgeaufträge ebenfalls dauerhaft sichern und bei unklarem Ausgang ausschließlich rücklesen.
