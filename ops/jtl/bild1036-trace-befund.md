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
