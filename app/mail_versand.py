"""Bewusst begrenzter SMTP-Testversand für freigegebene Antworten."""
import asyncio
import os
import smtplib
import ssl
from email.message import EmailMessage

from .models import Mail


TEST_EMPFAENGER = "info@erikschweitzer.de"
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
            "Erik Schweitzer", "Gursewak Singh", "Ludwig Schnorrenberg",
            "Auszubildender",
        }:
            zeilen.pop()
            if zeilen and zeilen[-1].strip() in {
                "Erik Schweitzer", "Gursewak Singh", "Ludwig Schnorrenberg",
            }:
                zeilen.pop()
            text = "\n".join(zeilen).rstrip()
    return f"{text}\n\n{signatur}\n"


def _synchron_senden(mail: Mail, antworttext: str, benutzer: dict) -> None:
    smtp = _smtp_einstellungen()
    nachricht = EmailMessage()
    nachricht["From"] = smtp["user"]
    nachricht["To"] = TEST_EMPFAENGER
    nachricht["Subject"] = f"TEST – Re: {mail.betreff}"
    nachricht["X-Krautl-Original-Recipient"] = mail.absender_adresse
    if mail.message_id:
        nachricht["In-Reply-To"] = mail.message_id
        nachricht["References"] = mail.message_id
    nachricht.set_content(antwort_mit_signatur(antworttext, benutzer))

    kontext = ssl.create_default_context()
    if smtp["port"] == 465:
        with smtplib.SMTP_SSL(
            smtp["host"], smtp["port"], context=kontext, timeout=30
        ) as client:
            client.login(smtp["user"], smtp["password"])
            client.send_message(nachricht)
    else:
        with smtplib.SMTP(smtp["host"], smtp["port"], timeout=30) as client:
            client.ehlo()
            client.starttls(context=kontext)
            client.ehlo()
            client.login(smtp["user"], smtp["password"])
            client.send_message(nachricht)


async def testantwort_senden(mail: Mail, antworttext: str, benutzer: dict) -> None:
    await asyncio.to_thread(_synchron_senden, mail, antworttext, benutzer)
