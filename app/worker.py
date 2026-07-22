"""
Hintergrund-Job: ruft neue Mails aus allen konfigurierten Postfächern ab,
klassifiziert sie über den Agent und schreibt sie in die Datenbank.

Läuft im selben Prozess wie die API (siehe main.py) — es gibt aktuell keinen
separaten Worker-Container in docker-compose.yml.
"""
import logging

from sqlalchemy import select

from .agent import klassifiziere
from .db import SessionLocal
from .imap_client import PostfachConfig, lade_postfaecher, mail_verschieben, neue_mails_abrufen
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


async def _klassifikation_zeilen_laden(session) -> dict[str, Klassifikation]:
    result = await session.execute(select(Klassifikation))
    return {k.klassifikation_id: k for k in result.scalars().all()}


async def postfach_abrufen_und_klassifizieren(
    config: PostfachConfig, alle_postfaecher: dict[str, PostfachConfig],
) -> int:
    """Ruft neue Mails eines Postfachs ab, klassifiziert und speichert sie.
    Führt anschließend die MAIL_VERSCHIEBEN-Aktion der Klassifikation aus,
    sofern das Zielpostfach konfiguriert ist. Gibt die Anzahl neu gespeicherter
    Mails zurück."""
    rohmails = neue_mails_abrufen(config)
    if not rohmails:
        return 0

    gespeichert = 0
    zu_verschieben: list[tuple[int, int, PostfachConfig, str, str]] = []

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
        klassifikation_zeilen = await _klassifikation_zeilen_laden(session)
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

            session.add(Aktionslog(
                mail_id=mail.id,
                ereignis="klassifiziert",
                detail=f"{klassifikation_id or 'UNKLASSIFIZIERT'} (Konfidenz {mail.konfidenz:.2f})",
            ))

            klass_zeile = klassifikation_zeilen.get(klassifikation_id)
            if klass_zeile and klass_zeile.aktion_id == "MAIL_VERSCHIEBEN" and klass_zeile.zielpostfach:
                ziel_config = alle_postfaecher.get(klass_zeile.zielpostfach)
                if ziel_config:
                    zu_verschieben.append(
                        (mail.id, roh["uid"], ziel_config, klass_zeile.zielordner or "INBOX", geparst["message_id"])
                    )
                else:
                    logger.warning(
                        "Zielpostfach %s (Klassifikation %s) ist nicht konfiguriert — Mail bleibt in %s liegen.",
                        klass_zeile.zielpostfach, klassifikation_id, config.funktion,
                    )

        await session.commit()

    # Verschieben erst nach dem Commit: die Mail ist damit in jedem Fall schon
    # dauerhaft erfasst, auch wenn das IMAP-Verschieben selbst fehlschlägt.
    for mail_id, uid, ziel_config, ziel_ordner, message_id in zu_verschieben:
        async with SessionLocal() as log_session:
            try:
                mail_verschieben(config, uid, ziel_config, ziel_ordner)
                log_session.add(Aktionslog(
                    mail_id=mail_id, ereignis="verschoben",
                    detail=f"nach {ziel_config.user}/{ziel_ordner}",
                ))
            except Exception as exc:
                logger.exception("Verschieben nach %s/%s fehlgeschlagen für %s", ziel_config.user, ziel_ordner, message_id)
                log_session.add(Aktionslog(
                    mail_id=mail_id, ereignis="verschieben_fehlgeschlagen",
                    detail=f"nach {ziel_config.user}/{ziel_ordner}: {exc}",
                ))
            await log_session.commit()

    return gespeichert


async def alle_postfaecher_abrufen() -> None:
    alle_postfaecher = {config.user: config for config in lade_postfaecher()}
    for config in alle_postfaecher.values():
        try:
            anzahl = await postfach_abrufen_und_klassifizieren(config, alle_postfaecher)
            if anzahl:
                logger.info("%s: %d neue Mail(s) klassifiziert", config.funktion, anzahl)
        except Exception:
            logger.exception("Abruf für Postfach %s fehlgeschlagen", config.funktion)
