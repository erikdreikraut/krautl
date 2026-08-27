"""Nimmt vom alten Schleifenschutz versteckte Telefontranskripte wieder auf.

Aufruf nach dem Container-Neubau:
    docker compose exec app python -m scripts.klassifiziere_transkripte_nach

Die Auswahl ist absichtlich eng und der Lauf wiederholbar: Bearbeitet werden
nur unsichtbare, noch unklassifizierte Krautl-Audio-Ausgabemails. Sobald eine
Mail nachklassifiziert wurde, fällt sie bei weiteren Läufen aus der Auswahl.
"""
import asyncio
import logging

from sqlalchemy import select

from app.agent import klassifiziere
from app.aufgaben import aufgaben_fuer_mail_anlegen, wartende_aufgaben_ausfuehren
from app.berechtigungen import standard_zustaendigkeit
from app.db import SessionLocal
from app.models import Aktionslog, Mail
from app.uebersetzungen import mail_ins_deutsche_uebersetzen
from app.worker import (
    _beispiele_laden,
    _katalog_laden,
    klassifizierungsdaten_fuer_transkript,
)

logger = logging.getLogger("krautl.transkripte_nachklassifizieren")


def _maildaten(mail: Mail) -> dict:
    return {
        "message_id": mail.message_id,
        "absender_name": mail.absender_name,
        "absender_adresse": mail.absender_adresse,
        "antwort_an_adresse": mail.antwort_an_adresse,
        "betreff": mail.betreff,
        "text_auszug": mail.text_auszug,
        "empfangen_am": mail.empfangen_am,
        "spam_score": mail.spam_score,
        "anhang_dateinamen": mail.anhang_dateinamen or [],
        "krautl_generiert": True,
    }


async def nachklassifizieren(session) -> dict:
    katalog = await _katalog_laden(session)
    beispiele = await _beispiele_laden(session)
    mails = (await session.execute(
        select(Mail).where(
            Mail.message_id.like("<krautl-audio-%@dreikraut.de>"),
            Mail.klassifikation_id.is_(None),
            Mail.im_krautl_posteingang.is_(False),
        ).order_by(Mail.id)
    )).scalars().all()

    sichtbar_gemacht = 0
    klassifiziert = 0
    fehler = 0
    mail_ids = []
    for mail in mails:
        maildaten, transkript_katalog = klassifizierungsdaten_fuer_transkript(
            _maildaten(mail), katalog
        )
        gueltige_ids = {
            eintrag["klassifikation_id"] for eintrag in transkript_katalog
        }
        ergebnis = {}
        if transkript_katalog:
            try:
                ergebnis = await asyncio.to_thread(
                    klassifiziere, maildaten, transkript_katalog, beispiele
                )
            except Exception:
                fehler += 1
                logger.exception(
                    "Nachklassifizierung fehlgeschlagen für %s", mail.message_id
                )

        klassifikation_id = ergebnis.get("klassifikation_id")
        if klassifikation_id not in gueltige_ids:
            klassifikation_id = None
        else:
            klassifiziert += 1

        sprachdaten = {
            "originalsprache": ergebnis.get("originalsprache"),
            "betreff_deutsch": None,
            "text_deutsch": None,
        }
        try:
            sprachdaten = await mail_ins_deutsche_uebersetzen(
                mail.betreff,
                mail.text_auszug,
                ergebnis.get("originalsprache"),
            )
        except Exception:
            logger.exception("Übersetzung fehlgeschlagen für %s", mail.message_id)

        zustaendig_admin, zustaendig_sachbearbeiter = await standard_zustaendigkeit(
            session, klassifikation_id
        )
        mail.klassifikation_id = klassifikation_id
        mail.konfidenz = ergebnis.get("sicherheit", 0.0)
        mail.aktion_erforderlich = ergebnis.get("aktion_erforderlich", False)
        mail.kundennummer = ergebnis.get("kundennummer")
        mail.bestellnummer = ergebnis.get("bestellnummer")
        mail.rechnungsnummer = ergebnis.get("rechnungsnummer")
        mail.originalsprache = sprachdaten["originalsprache"]
        mail.betreff_deutsch = sprachdaten["betreff_deutsch"]
        mail.text_deutsch = sprachdaten["text_deutsch"]
        mail.zustaendig_admin = zustaendig_admin
        mail.zustaendig_sachbearbeiter = zustaendig_sachbearbeiter
        mail.im_krautl_posteingang = True
        await aufgaben_fuer_mail_anlegen(session, mail)
        session.add(Aktionslog(
            mail_id=mail.id,
            ereignis="klassifiziert",
            detail=(
                "Telefontranskript nachklassifiziert: "
                f"{klassifikation_id or 'UNKLASSIFIZIERT'} "
                f"(Konfidenz {mail.konfidenz:.2f})"
            ),
        ))
        sichtbar_gemacht += 1
        mail_ids.append(mail.id)

    await session.commit()
    return {
        "gefunden": len(mails),
        "sichtbar_gemacht": sichtbar_gemacht,
        "klassifiziert": klassifiziert,
        "fehler": fehler,
        "mail_ids": mail_ids,
    }


async def ausfuehren() -> None:
    async with SessionLocal() as session:
        ergebnis = await nachklassifizieren(session)
    for mail_id in ergebnis.pop("mail_ids"):
        try:
            await wartende_aufgaben_ausfuehren(mail_id)
        except Exception:
            logger.exception("Automatische Aufgabe für Mail %s fehlgeschlagen", mail_id)
    print(
        "Telefontranskripte: "
        f"{ergebnis['gefunden']} gefunden, "
        f"{ergebnis['klassifiziert']} klassifiziert, "
        f"{ergebnis['sichtbar_gemacht']} in den Bearbeitungsfluss aufgenommen, "
        f"{ergebnis['fehler']} Klassifizierungsfehler."
    )


if __name__ == "__main__":
    asyncio.run(ausfuehren())
