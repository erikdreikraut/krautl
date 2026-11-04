"""Opt-in-Liveprüfung mit synthetischen Daten; keine DB-, Mail- oder Wawi-Schreibzugriffe."""
import argparse
import io
import logging
from types import SimpleNamespace as NS


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ausfuehren", action="store_true", help="Kostenpflichtige OpenAI-Testaufrufe ausführen")
    if not parser.parse_args().ausfuehren:
        parser.error("Für Live-Aufrufe --ausfuehren angeben")
    from dotenv import load_dotenv
    load_dotenv(".env")
    import os
    os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    from app.ki import KIClient, STANDARD_MODELL
    from app.agent import klassifiziere
    from app.uebersetzungen import _synchron_mail_uebersetzen, _synchron_antwort_uebersetzen
    from app.audio_transkription import _strukturieren
    from app.faq_import import auswerten
    from app.rechnungen import _analysiere
    from app.antworten import _synchron_erzeugen, _synchron_pruefen
    from app.wissensbasis import _vorschlag_synchron
    from PIL import Image, ImageDraw
    logging.basicConfig(level=logging.INFO, format="%(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)

    def ok(name):
        print("OK:", name, flush=True)

    mail = NS(betreff="Testfrage", betreff_deutsch=None, text_auszug="Wie bewahre ich Tee auf?",
              text_deutsch=None, klassifikation_id="KUNDE_FRAGE", absender_name="Testperson",
              absender_adresse="test@example.test", originalsprache="Deutsch")
    for _ in range(2):
        result = klassifiziere(vars(mail), [{"klassifikation_id": "KUNDE_FRAGE", "beschreibung": "Kunden fragen zu Produkten"},
                                          {"klassifikation_id": "SPAM", "beschreibung": "Unerwünschte Werbung"}])
        assert result["klassifikation_id"] == "KUNDE_FRAGE", result
    ok("Klassifikation, wiederholter statischer Präfix")
    translated = _synchron_mail_uebersetzen("Order 4711", "Please keep order number 4711 unchanged.", "Englisch")
    assert "4711" in translated["text_deutsch"]
    answer = _synchron_antwort_uebersetzen("Die Bestellnummer lautet 4711.", "Englisch")
    assert "4711" in answer
    ok("Mail- und Antwortübersetzung")
    transcript = "Guten Tag. Mein Name ist Testperson. Bitte rufen Sie mich morgen zurück. Vielen Dank."
    subject, formatted = _strukturieren(transcript)
    assert "Testperson" in (subject + formatted)
    ok("Transkriptformatierung")
    faq = auswerten({"type": "text", "text": "Produkt: Testtee, Artikelnummer 00123. Frage des Kunden: Wie lagern? Antwort des Herstellers: Trocken lagern."})
    assert len(faq) == 1 and faq[0].artikelnummer == "00123", faq
    ok("FAQ-Extraktion")
    image = Image.new("RGB", (1400, 900), "white")
    draw = ImageDraw.Draw(image)
    draw.text((70, 70), "RECHNUNG\nTestlieferant\nRechnungsnummer TEST-4711\nDatum 2026-11-04\nGesamtbetrag brutto 119,00 EUR\nZahlungsart: PayPal\nBereits bezahlt", fill="black", font_size=40, spacing=25)
    for fmt, mime in [("PNG", "image/png"), ("PDF", "application/pdf")]:
        data = io.BytesIO();image.save(data, format=fmt)
        result = _analysiere({"inhalt": data.getvalue(), "mime_type": mime, "endung": "." + fmt.lower(), "dateiname": "test." + fmt.lower()}, mail)
        assert result["rechnungsnummer"] == "TEST-4711" and result["zahlungsstatus"] == "bezahlt", result
        assert result["bruttobetrag"] == 119, result
        ok("Rechnungsanalyse " + fmt)
    draft = _synchron_erzeugen(mail, [])
    assert draft.strip()
    checked = _synchron_pruefen(mail, draft, [])
    assert isinstance(checked["freigabefaehig"], bool), checked
    ok("Antwortentwurf und Versandprüfung ohne Versand")
    growth = _vorschlag_synchron(mail, "Danke.", "Vielen Dank.", [], [], [])
    assert isinstance(growth, dict)
    ok("Wissensvorschlag")
    response = KIClient().erzeugen(model=STANDARD_MODELL,max_tokens=1000,
        system="Erstelle einen kurzen WhatsApp-Antwortvorschlag. Keine erfundenen Fakten. Du versendest nichts.",
        messages=[{"role": "user", "content": "Kunde: Vielen Dank für die Hilfe!"}])
    assert response.content[0].text.strip()
    ok("Kurzer Antwortvorschlag ohne Versand")
    print("Alle synthetischen OpenAI-Prüfungen erfolgreich.", flush=True)


if __name__ == "__main__":
    main()
