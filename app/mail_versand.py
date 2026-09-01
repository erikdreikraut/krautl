"""SMTP-Versand für manuell geprüfte und freigegebene Kundenantworten."""
import asyncio
import mimetypes
import os
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import make_msgid, parseaddr

from .models import Mail


BCC_EMPFAENGER = "info@erikschweitzer.de"
GEMEINSAME_SIGNATUR = "-- \n" + """\
dreikraut e.K.
Gräfrather Str. 74a
42329 Wuppertal

www.dreikraut.de
Fon +49 202 2727 7835
Fax +49 202 2531 2301"""


def _smtp_einstellungen() -> dict:
    werte = {
        "host": os.environ.get("SMTP_SERVICE_HOST"),
        "port": int(os.environ.get("SMTP_SERVICE_PORT", "587")),
        "user": os.environ.get("SMTP_SERVICE_USER") or os.environ.get("IMAP_SERVICE_USER"),
        "password": (
            os.environ.get("SMTP_SERVICE_PASSWORD")
            or os.environ.get("IMAP_SERVICE_PASSWORD")
        ),
    }
    fehlend = [name for name in ("host", "user", "password") if not werte[name]]
    if fehlend:
        raise RuntimeError(
            "SMTP-Service ist nicht vollständig konfiguriert: "
            + ", ".join(fehlend)
        )
    return werte


def antwort_mit_signatur(antworttext: str, benutzer: dict) -> str:
    kopf = [benutzer["name"]]
    if benutzer.get("titel"):
        kopf.append(benutzer["titel"])
    signatur = "\n".join([*kopf, GEMEINSAME_SIGNATUR])
    text = antworttext.rstrip()
    # Bereits von Hand eingefügte dreikraut-Signaturen werden ersetzt, damit
    # nie zwei unterschiedliche Absender unter derselben Antwort stehen.
    marker = "\n-- \ndreikraut e.K."
    if marker in text:
        text = text.split(marker, 1)[0].rstrip()
        zeilen = text.splitlines()
        if zeilen and zeilen[-1].strip() in {
            "Erik Schweitzer", "Gursewak Singh", "Ludwig Schnorrenberg", "Aneta",
            "Auszubildender",
        }:
            zeilen.pop()
            if zeilen and zeilen[-1].strip() in {
                "Erik Schweitzer", "Gursewak Singh", "Ludwig Schnorrenberg", "Aneta",
            }:
                zeilen.pop()
            text = "\n".join(zeilen).rstrip()
    return f"{text}\n\n{signatur}\n"


def _gueltige_adresse(roh: str) -> str | None:
    roh = str(roh or "").strip()
    if not roh:
        return None
    _name, adresse = parseaddr(roh)
    lokalteil, trennzeichen, domain = adresse.rpartition("@")
    if (
        not trennzeichen
        or not lokalteil
        or not domain
        or any(zeichen.isspace() for zeichen in adresse)
        or "\r" in roh
        or "\n" in roh
    ):
        return None
    return adresse


def antwortadresse(mail: Mail) -> str:
    """Antwortadresse für eine Kundenmail.

    Bevorzugt Reply-To gegenüber der Absenderadresse — manche Shops/Formulare
    verschicken über eine technische Absenderadresse, während Antworten laut
    Reply-To an die eigentliche Kundenadresse gehen sollen (siehe
    mail_parser.parse_eml, das Reply-To nur übernimmt, wenn es abweicht).
    """
    for kandidat in (mail.antwort_an_adresse, mail.absender_adresse):
        adresse = _gueltige_adresse(kandidat)
        if adresse:
            return adresse
    raise RuntimeError(
        "Reply-To und Absenderadresse der Kundenmail sind ungültig"
    )


def _antwort_betreff(betreff: str) -> str:
    betreff = str(betreff or "").strip() or "Ihre Nachricht"
    if betreff.casefold().startswith(("re:", "aw:")):
        return betreff
    return f"Re: {betreff}"


def _synchron_senden(
    mail: Mail,
    antworttext: str,
    benutzer: dict,
    anhaenge: list[dict] | None = None,
) -> dict:
    smtp = _smtp_einstellungen()
    empfaenger = antwortadresse(mail)
    nachricht = EmailMessage()
    nachricht["From"] = smtp["user"]
    nachricht["To"] = empfaenger
    nachricht["Bcc"] = BCC_EMPFAENGER
    nachricht["Subject"] = _antwort_betreff(mail.betreff)
    absender_domain = smtp["user"].partition("@")[2] or None
    nachricht["Message-ID"] = make_msgid(domain=absender_domain)
    if mail.message_id:
        nachricht["In-Reply-To"] = mail.message_id
        nachricht["References"] = mail.message_id
    nachricht.set_content(antwort_mit_signatur(antworttext, benutzer))
    for anhang in anhaenge or []:
        dateiname = str(anhang["dateiname"])
        mime_type = (
            str(anhang.get("mime_type") or "")
            or mimetypes.guess_type(dateiname)[0]
            or "application/octet-stream"
        )
        haupttyp, trennzeichen, untertyp = mime_type.partition("/")
        if not trennzeichen or not haupttyp or not untertyp:
            haupttyp, untertyp = "application", "octet-stream"
        nachricht.add_attachment(
            anhang["inhalt"],
            maintype=haupttyp,
            subtype=untertyp,
            filename=dateiname,
        )

    kontext = ssl.create_default_context()
    if smtp["port"] == 465:
        with smtplib.SMTP_SSL(
            smtp["host"], smtp["port"], context=kontext, timeout=30
        ) as client:
            client.login(smtp["user"], smtp["password"])
            abgelehnt = client.send_message(nachricht)
    else:
        with smtplib.SMTP(smtp["host"], smtp["port"], timeout=30) as client:
            client.ehlo()
            client.starttls(context=kontext)
            client.ehlo()
            client.login(smtp["user"], smtp["password"])
            abgelehnt = client.send_message(nachricht)
    if abgelehnt:
        raise RuntimeError(f"SMTP hat Empfänger abgelehnt: {abgelehnt}")
    return {
        "message_id": nachricht["Message-ID"],
        "empfaenger": empfaenger,
        "bcc": BCC_EMPFAENGER,
    }


async def antwort_senden(
    mail: Mail,
    antworttext: str,
    benutzer: dict,
    anhaenge: list[dict] | None = None,
) -> dict:
    return await asyncio.to_thread(
        _synchron_senden, mail, antworttext, benutzer, anhaenge
    )
