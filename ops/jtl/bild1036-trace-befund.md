# Nativer Bildaustausch: Aufzeichnung vom 29.10.2026

Quelle: `Krautl_Bild1036_D34F7AFCEB444023B71890854E3816E2_0_134378276443510000.xel`,
601088 Bytes. Lokale Untersuchung am 30.10.2026: lesbare UTF-16-SQL-Fragmente
beider Byte-Ausrichtungen extrahiert, 436 Treffer, 190 verschiedene Texte.
Dies ist keine vollstaendige XE-Ereignisdekodierung. Parameterwerte,
Bulk-Tabelleninhalte, betroffene Zeilenzahlen und Commit-Erfolg sind damit nicht
nachgewiesen. Der Nutzer bestaetigt den erfolgreichen Austausch in Wawi.

## Beobachtete Anweisungen

- Hashsuche in `dbo.tBild`, anschliessend `INSERT INTO dbo.tBild` mit Original,
  Vorschau, Abmessungen, Dateigroessen, Hash, Quelle und Zeitstempeln.
  `OUTPUT Inserted.kBild` liefert den neuen Schluessel.
- Bulk-Befuellen einer temporaeren Zuordnungstabelle mit
  `kArtikelbildPlattform`, `kBild`, `kArtikel`, `kPlattform`, `kShop`, `nNr`,
  `nInet`, `kEbayUser`, `cBildname`.
- `MERGE` dieser Daten in `dbo.tArtikelbildPlattform`: Zuordnung entweder ueber
  die eigene Zuordnungs-ID oder ueber Bild/Artikel/Plattform/Shop/Position/Konto.
  Der UPDATE-Zweig setzt `kBild`, `nNr`, `nInet`, `cBildname`. Es gibt auch
  INSERT- und DELETE-Zweige; deren konkrete Wirkung ist ohne Parameter nicht
  feststellbar. Zielmenge: Artikel und aktive Shops sowie Zuordnungen ohne Shop.
- Separates `MERGE` fuer `dbo.tArtikelbildPlattformSeo` mit Sprache und Alttext.
- Triggerartige Fragmente mit `Inserted`/`Deleted`: Vergleich alter/neuer
  Bildreferenzen und Positionen; Aktualisierung von `Sync.tEntityTracking`,
  Uploadmarkierungen `nInet`, Queue- und SCX-Verarbeitung. Das Auftreten einer
  Anweisung belegt nicht, dass ihre WHERE-Bedingung Zeilen getroffen hat.

## Konsequenz

Die Annahme, natives Ersetzen muesse die interne Bild-ID erhalten, ist nicht
belegt. Die Aufzeichnung zeigt einen Weg mit neuem Bilddatensatz und Abgleich
separater Zuordnungen. Ein direktes Ueberschreiben von `bBild` waere keine
Reproduktion dieses beobachteten Weges.

Struktureller Ansatz: lokale, versionsgepruefte Wawi-Bruecke; vollstaendige
Zuordnungs- und SEO-Sicherung, neue Bilddaten vorbereiten, gezielt Bildreferenzen
in den zum Austausch gehoerenden Zuordnungen ersetzen, Positionen/Kanaele/Konten
erhalten, Synchronisierung ueber die gepruefte native Datenbanklogik beachten.
Andere Artikel mit gemeinsamem Original nicht unbeabsichtigt veraendern.
Kein pauschales Nachbauen des MERGE mit seinem DELETE-Zweig; keine Freigabe
fuer produktive SQL-Schreibzugriffe aus dieser Fragmentanalyse.

Naechster notwendiger Nachweis: `bild1036_struktur_lesen.sql` in SSMS ausfuehren.
Es liest den bekannten internen Artikel 40 (SKU 1036), Zuordnungen, SEO,
Metadaten, Trigger, Fremdschluessel und Indizes. Keine Bildbinaerdaten.
Triggerdefinitionen vollstaendig exportieren; gekuerzte SSMS-Zellen reichen
nicht zur Implementierung. Anschliessend Transaktionsgrenzen, Hash-/Vorschau-
Erzeugung und Wiederaufnahme nach Antwortverlust festlegen und isoliert testen.
Der Krautl-Austausch ist durch diese Analyse noch nicht repariert.

## Struktur-XML vom 30.10.2026

Der bereitgestellte XML-Export ist syntaktisch vollstaendig: 40 Zuordnungen,
5 Bildmetadatensaetze, 34 Spalten, 4 aktivierte Trigger, 5 Fremdschluessel,
29 Indexspalten. SEO fehlt als Abschnitt; die XML-Abfrage laesst leere
Unterergebnisse weg. Das ist mit null SEO-Zeilen vereinbar, kein Hinweis auf
abgeschnittene Trigger. Alle vier Definitionen enden mit END CATCH.

Artikel 40: Bild 2488 bleibt in drei Zuordnungen (Plattform 8, Shops 11/13/14).
Bild 2729 bleibt im Standard auf Position 4 und im Shop 1/Plattform 2 auf
Position 1. Bild 2731 hat elf Zuordnungen, darunter die zwei eBay-Konten
mit unterschiedlichen Positionen 1 und 2. Ein globales Ersetzen nur anhand
der Position 1 wuerde daher fachlich falsche Ergebnisse produzieren.
Warum die drei alten Zuordnungen erhalten blieben, ist nicht nachgewiesen;
der native MERGE filterte unter anderem auf aktive Shops.

### Trigger und Konsequenzen fuer die Implementierung

- tgr_tBild_INSUP reagiert auf cHash/cQuelle. Allein bBild zu aendern reicht
  nicht. Bei geaendertem Hash setzt er Uploadmarkierungen an referenzierenden
  Tabellen und schreibt Queue-Eintraege. Ein solcher globaler Eingriff koennte
  auch andere Artikel, Kategorien oder Merkmale treffen.
- tgr_tArtikelbildPlattform_INSUP erkennt kBild/nNr-Aenderungen und setzt nInet
  fuer vorhandene Artikel-Shop-Zuordnungen. SCX- und POS-Tracking sind enthalten.
- Kritische Ausnahme: spUpdateEbayBilderLaufendGeplant wird nur im UPDATE(nNr)-
  Zweig aufgerufen, wenn Plattform/Position tatsaechlich geaendert wurden und
  die eBay-Positionsbedingung gilt. Ein kBild-Wechsel bei gleicher Position
  erfuellt diese Bedingung nicht; auch SET nNr=nNr hilft nicht. Daher keine
  Zusage, ein simples Zuordnungs-UPDATE aktualisiere automatisch eBay-Angebote.
- Fremdschluessel von SEO und FulfillmentNetwork.tProductPictureRef verweisen
  auf die Zuordnungs-ID, mit DELETE CASCADE. Bestehende Zuordnungszeilen erhalten;
  DELETE/INSERT wuerde weitere Daten verlieren koennen. Auch das Loeschen eines
  Bilddatensatzes kann Zuordnungen kaskadierend entfernen.
- tBild besitzt neben Binaerdaten und Hash auch iBlobIdentifier, nState, cUrl,
  cMetadata und Rowversion; dbo.tBildBlobIdentifier referenziert kBild. Eine
  handgebaute Bildanlage ohne Kenntnis dieser Semantik ist nicht freigegeben.

Belastbarer Entwurf: nativen Bildimport fuer neue Bilddaten nutzen; vor jedem
Schreiben exakte Zuordnungs-IDs, Plattform/Shop/Konto/Position und Rowversion
sichern. Austausch auf den beauftragten Artikel und die bestaetigten alten
Bildzuordnungen begrenzen, Zuordnungs-IDs und abhaengige Texte erhalten.
Bildinhalt, Zuordnungen und Veroeffentlichung getrennt bestaetigen. Die bereits
auseinandergelaufenen Anchan-Bilder nicht automatisch als eine gemeinsame alte
Bildidentitaet interpretieren. Fuer eBay ist die separate native Aktualisierung
noch zu klaeren; SQL-Trigger allein belegen keine vollstaendige Auslieferung.
Noch keine produktive Schreibimplementierung und kein Live-Erfolgsnachweis.
