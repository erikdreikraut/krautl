"""Liest Termine aus eingebetteten Kalenderteilen und .ics-Anhängen."""
from datetime import date, datetime, timedelta, timezone
from email.message import EmailMessage

from icalendar import Calendar, Event


def _termin_aus_eintrag(eintrag: Event, abgesagt: bool) -> dict | None:
    startfeld = eintrag.get("DTSTART")
    beginn = getattr(startfeld, "dt", None)
    if not isinstance(beginn, date):
        return None

    ende = getattr(eintrag.get("DTEND"), "dt", None)
    dauer = getattr(eintrag.get("DURATION"), "dt", None)
    if ende is None and isinstance(dauer, timedelta):
        ende = beginn + dauer
    if type(ende) is not type(beginn):
        ende = None

    ganztag = not isinstance(beginn, datetime)
    zeitzone = None
    if ganztag:
        # Ein ganztägiges ICS-Enddatum ist exklusiv. Die Ansicht zeigt den letzten Tag.
        ende = ende - timedelta(days=1) if ende and ende > beginn else None
    elif beginn.utcoffset() is None:
        zeitzone = str(startfeld.params.get("TZID") or "Ortszeit")
        if ende and ende.utcoffset() is not None:
            ende = None
    else:
        beginn = beginn.astimezone(timezone.utc)
        ende = ende.astimezone(timezone.utc) if ende and ende.utcoffset() is not None else None
    return {
        "beginn": beginn.isoformat(),
        "ende": ende.isoformat() if ende else None,
        "ganztag": ganztag,
        "zeitzone": zeitzone,
        "abgesagt": abgesagt or str(eintrag.get("STATUS", "")).upper() == "CANCELLED",
    }


def kalendertermine_aus_mail(nachricht: EmailMessage) -> list[dict]:
    termine = []
    for teil in nachricht.walk():
        if teil.is_multipart() or (
            teil.get_content_type() != "text/calendar"
            and not (teil.get_filename() or "").lower().endswith(".ics")
        ):
            continue
        inhalt = teil.get_payload(decode=True)
        if not inhalt or len(inhalt) > 1_000_000:
            continue
        try:
            kalender = Calendar.from_ical(inhalt)
        except (ValueError, TypeError, LookupError, OverflowError):
            continue
        abgesagt = str(kalender.get("METHOD") or teil.get_param("method") or "").upper() == "CANCEL"
        for eintrag in kalender.walk("VEVENT"):
            try:
                termin = _termin_aus_eintrag(eintrag, abgesagt)
            except (ValueError, TypeError, LookupError, OverflowError):
                continue
            if termin and termin not in termine:
                termine.append(termin)
    return termine
