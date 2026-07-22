"""
Hintergrund-Job: ruft neue Mails aus allen konfigurierten Postfächern ab,
klassifiziert sie über den Agent und schreibt sie in die Datenbank.

Läuft im selben Prozess wie die API (siehe main.py) — es gibt aktuell keinen
separaten Worker-Container in docker-compose.yml.
"""
import logging

from sqlalchemy import select

from .agent import klassifiziere
from .aufgaben import aufgaben_fuer_mail_anlegen, wartende_aufgaben_ausfuehren
from .db import SessionLocal
from .imap_client import PostfachConfig, lade_postfaecher, neue_mails_abrufen
from .mail_parser import parse_eml
from .models import Aktionslog, Klassifikation, Korrektur, Mail, Postfach

logger = logging.getLogger("krautl.worker")

MAX_BEISPIELE = 20


async def _postfach_holen_oder_anlegen(session, config: PostfachConfig) -> Postfach:
    result = await session.execute(select(Postfach).where(Postfach.adresse == config.user))
    postfach = result.scalar_one_or_none()
    if postfach is None:
        postfach = Postfach(adresse=config.user, funktion=config.funktion, imap_host=config.host)
        session.add(postfach)
        await session.flush()
    return postfach


async def _katalog_laden(session) -> list[dict]:
    result = await session.execute(select(Klassifikation))
    return [
        {
            "klassifikation_id": k.klassifikation_id,
            "hauptkategorie": k.hauptkategorie,
            "unterkategorie": k.unterkategorie,
            "beschreibung": k.beschreibung,
            "standard_prio": k.standard_prio,
        }
        for k in result.scalars().all()
    ]


async def _beispiele_laden(session) -> list[dict]:
    result = await session.execute(
        select(Korrektur, Mail)
        .join(Mail, Korrektur.mail_id == Mail.id)
        .order_by(Korrektur.erstellt_am.desc())
        .limit(MAX_BEISPIELE)
    )
    return [
        {
            "betreff": mail.betreff,
            "absender_adresse": mail.absender_adresse,
            "text_auszug": mail.text_auszug,
            "korrekte_klassifikation_id": korrektur.neue_klassifikation_id,
        }
        for korrektur, mail in result.all()
    ]


async def _mail_existiert(session, message_id: str) -> bool:
    result = await session.execute(select(Mail.id).where(Mail.message_id == message_id))
    return result.scalar_one_or_none() is not None


async def postfach_abrufen_und_klassifizieren(config: PostfachConfig) -> int:
    """Ruft neue Mails eines Postfachs ab, klassifiziert und speichert sie.
    Legt den geordneten Aufgabenplan der Klassifikation an. Blockierende
    Bestätigungen werden später über die Oberfläche erledigt."""
    rohmails = neue_mails_abrufen(config)
    if not rohmails:
        return 0

    gespeichert = 0
    neue_mail_ids = []
    async with SessionLocal() as session:
        postfach = await _postfach_holen_oder_anlegen(session, config)
        katalog = await _katalog_laden(session)
        if not katalog:
            logger.warning(
                "Klassifikationskatalog ist leer — neue Mails aus %s werden "
                "ohne Klassifikation gespeichert (siehe README: Import-Skript).",
                config.funktion,
            )
        gueltige_ids = {k["klassifikation_id"] for k in katalog}
        beispiele = await _beispiele_laden(session)

        for roh in rohmails:
            geparst = parse_eml(roh["eml"])
            if await _mail_existiert(session, geparst["message_id"]):
                continue

            klass: dict = {}
            if katalog:
                try:
                    klass = klassifiziere(geparst, katalog, beispiele)
                except Exception:
                    logger.exception(
                        "Klassifizierung fehlgeschlagen für %s", geparst["message_id"]
                    )

            klassifikation_id = klass.get("klassifikation_id")
            if klassifikation_id not in gueltige_ids:
                if klassifikation_id is not None:
                    logger.warning(
                        "Agent lieferte unbekannte Klassifikation_ID %r — speichere als unklassifiziert.",
                        klassifikation_id,
                    )
                klassifikation_id = None

            mail = Mail(
                message_id=geparst["message_id"],
                imap_uid=roh["uid"],
                postfach_id=postfach.id,
                absender_name=geparst["absender_name"],
                absender_adresse=geparst["absender_adresse"],
                betreff=geparst["betreff"],
                text_auszug=geparst["text_auszug"],
                empfangen_am=geparst["empfangen_am"],
                spam_score=geparst["spam_score"],
                klassifikation_id=klassifikation_id,
                konfidenz=klass.get("sicherheit", 0.0),
                aktion_erforderlich=klass.get("aktion_erforderlich", False),
                kundennummer=klass.get("kundennummer"),
                bestellnummer=klass.get("bestellnummer"),
                rechnungsnummer=klass.get("rechnungsnummer"),
            )
            session.add(mail)
            await session.flush()  # weist mail.id zu, fürs Aktionslog gebraucht
            gespeichert += 1
            neue_mail_ids.append(mail.id)

            session.add(Aktionslog(
                mail_id=mail.id,
                ereignis="klassifiziert",
                detail=f"{klassifikation_id or 'UNKLASSIFIZIERT'} (Konfidenz {mail.konfidenz:.2f})",
            ))

            await aufgaben_fuer_mail_anlegen(session, mail)

        await session.commit()

    # Nicht blockierende Aufgaben (derzeit Rechnungsverarbeitung) beginnen
    # direkt nach dem sicheren Speichern der Mail. Bestätigungen bleiben stehen.
    for mail_id in neue_mail_ids:
        try:
            await wartende_aufgaben_ausfuehren(mail_id)
        except Exception:
            logger.exception("Automatische Aufgabe für Mail %s fehlgeschlagen", mail_id)

    return gespeichert


async def alle_postfaecher_abrufen() -> None:
    for config in lade_postfaecher():
        try:
            anzahl = await postfach_abrufen_und_klassifizieren(config)
            if anzahl:
                logger.info("%s: %d neue Mail(s) klassifiziert", config.funktion, anzahl)
        except Exception:
            logger.exception("Abruf für Postfach %s fehlgeschlagen", config.funktion)
