# Vertriebskanal aus Bestell- und Auftragsnummern erkennen

Stand: 2026-08-01

Kunden nennen häufig eine Bestell- oder Auftragsnummer, ohne den Kaufort zu
nennen. Krautl darf daraus den wahrscheinlichen Vertriebskanal ableiten. Die
Nummer muss dabei im Kontext ausdrücklich als Bestellnummer, Auftragsnummer
oder Order-ID erscheinen. Eine zufällige Zahl im Mailtext reicht nicht.

## Eigener Onlineshop (JTL)

- Derzeit sind die Auftragsnummern aus dem eigenen dreikraut-Onlineshop
  **fünfstellig und rein numerisch**, zum Beispiel `68751`.
- Arbeitsmuster: `^[0-9]{5}$`.
- Dieses Format ist vorläufig und kann mit wachsender Zahl der Bestellungen
  sechsstellig werden. Die Regel muss dann erweitert werden.
- Eine fünfstellige Postleitzahl, ein Betrag oder ein Teil einer Telefonnummer
  ist keine Auftragsnummer. Entscheidend ist die Bezeichnung bzw. der Kontext.

## Amazon

- Amazon-Bestellnummern haben offiziell das Format **3–7–7**:
  drei Ziffern, Bindestrich, sieben Ziffern, Bindestrich, sieben Ziffern.
- Arbeitsmuster: `^[0-9]{3}-[0-9]{7}-[0-9]{7}$`.
- Ein vollständiger Treffer ist ein sehr starkes Indiz für Amazon.
- Quelle: Amazon Selling Partner API, `AmazonOrderId` im 3-7-7-Format:
  https://developer-docs.amazon.com/sp-api/reference/getorderbuyerinfo

## Temu

- Temu bestätigt, dass seine Bestellnummern stets mit **`PO`** beginnen.
- In aktuellen Beispielen ist die typische Form `PO-123-12345678901234567`:
  `PO-`, ein dreistelliger Block, ein Bindestrich und ein langer Ziffernblock.
- Robustes Arbeitsmuster: `^PO-[0-9]{3}-[0-9]{15,20}$`, ohne die genaue Länge
  als dauerhaft garantiert anzusehen.
- Ein `PO-…`-Treffer ist im Kundenbestell-Kontext ein sehr starkes Temu-Indiz.
  Die bloße Abkürzung „PO“ kann in Geschäftsmails auch „Purchase Order“ heißen
  und genügt ohne passende Nummer nicht.
- Quelle für den garantierten Präfix:
  https://www.temu.com/dk/support/c3/hvor-er-mit-ordre-id-f-66-s-169.html

## Shop Apotheke

- Aktuell werden für Shop Apotheke insbesondere diese beiden Bestell-/
  Auftragsnummernformen dokumentiert:
  - `COM-12345678` — `^COM-[0-9]{8}$`
  - `A02740234720` — `^A[0-9]{11}$`
- Diese Formate stammen aus einer aktuellen Cashback-Nachbuchungsanleitung,
  nicht aus einer offiziellen technischen Formatspezifikation von Shop
  Apotheke. Ein Treffer ist deshalb ein **starkes Indiz**, aber kein Beweis.
- Quelle:
  https://www.shopmate.eu/de/cashback/shop-apotheke

## Anwendung und Konfliktfälle

- Bindestriche erhalten; führende oder nachgestellte Leerzeichen und Zeichen
  wie `#`, Komma oder Punkt dürfen zur Prüfung entfernt werden.
- Groß-/Kleinschreibung bei Buchstaben ignorieren.
- Absender, Mailverlauf, Plattformname und vorhandene Bestelldaten haben
  Vorrang vor einer reinen Mustererkennung.
- Bestellnummern nicht mit Rechnungsnummern, Kundennummern oder Paket-
  Sendungsnummern verwechseln.
- Bei einem eindeutigen JTL-, Amazon- oder Temu-Muster kann Krautl den Kanal
  intern als erkannt behandeln. Bei Shop Apotheke oder widersprüchlichen
  Angaben neutral von „Ihrer Bestellung“ sprechen und den Kanal bei Bedarf
  prüfen, statt ihn dem Kunden gegenüber als sicher zu behaupten.
- Passt keine Regel sicher, den Vertriebskanal nicht erfinden. Nur dann danach
  fragen, wenn er für die Bearbeitung tatsächlich benötigt wird.
