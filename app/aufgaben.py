"""Geordnete Aufgaben-Pipeline für klassifizierte Mails."""
import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from .db import SessionLocal
from .imap_client import lade_postfaecher, mail_verschieben
from .models import Aktionslog, KlassifikationAufgabe, Mail, MailAufgabe, Postfach
from .rechnungen import rechnung_verarbeiten

logger = logging.getLogger("krautl.aufgaben")

BESTAETIGUNG_EINHOLEN = "BESTAETIGUNG_EINHOLEN"
MAIL_VERSCHIEBEN = "MAIL_VERSCHIEBEN"
RECHNUNG_VERWALTEN = "RECHNUNG_VERWALTEN"


async def aufgaben_fuer_mail_anlegen(session, mail: Mail) -> None:
    """Kopiert die aktuellen Vorlagen auf die Mail.

    Die Kopie ist absichtlich: spätere Änderungen an einer Klassifikation
    verändern nicht rückwirkend einen bereits begonnenen Arbeitsablauf.
    """
    if not mail.klassifikation_id:
        return
    result = await session.execute(
        select(KlassifikationAufgabe)
        .where(KlassifikationAufgabe.klassifikation_id == mail.klassifikation_id)
        .order_by(KlassifikationAufgabe.position)
    )
    vorlagen = result.scalars().all()
    for index, vorlage in enumerate(vorlagen):
        session.add(MailAufgabe(
            mail_id=mail.id,
            klassifikation_aufgabe_id=vorlage.id,
            position=vorlage.position,
            aufgabe_typ=vorlage.aufgabe_typ,
            parameter=vorlage.parameter,
            status="wartet" if index == 0 else "blockiert",
            bestaetiger_typ=vorlage.bestaetiger_typ,
            bestaetiger_referenz=vorlage.bestaetiger_referenz,
        ))


async def _naechste_freischalten(session, mail_id: int, position: int) -> None:
    result = await session.execute(
        select(MailAufgabe)
        .where(MailAufgabe.mail_id == mail_id, MailAufgabe.position > position)
        .order_by(MailAufgabe.position)
        .limit(1)
    )
    naechste = result.scalar_one_or_none()
    if naechste and naechste.status == "blockiert":
        naechste.status = "wartet"


async def bestaetigung_erfassen(mail_id: int, bestaetigt_von: str | None = None) -> dict:
    """Bestätigt die wartende Freigabe und führt Folgeaufgaben aus."""
    async with SessionLocal() as session:
        result = await session.execute(
            select(MailAufgabe)
            .where(
                MailAufgabe.mail_id == mail_id,
                MailAufgabe.aufgabe_typ == BESTAETIGUNG_EINHOLEN,
                MailAufgabe.status == "wartet",
            )
            .with_for_update()
        )
        aufgabe = result.scalar_one_or_none()
        if aufgabe is None:
            return {"status": "keine_bestaetigung_offen"}

        jetzt = datetime.now(timezone.utc)
        aufgabe.status = "erledigt"
        aufgabe.bestaetigt_von = bestaetigt_von
        aufgabe.bestaetigt_am = jetzt
        aufgabe.erledigt_am = jetzt
        session.add(Aktionslog(
            mail_id=mail_id,
            ereignis="bestaetigt",
            detail=f"Bestätigung erteilt{f' durch {bestaetigt_von}' if bestaetigt_von else ''}",
        ))
        await _naechste_freischalten(session, mail_id, aufgabe.position)
        await session.commit()

    return await wartende_aufgaben_ausfuehren(mail_id)


async def wartende_aufgaben_ausfuehren(mail_id: int) -> dict:
    """Führt ausführbare Folgeaufgaben bis zum nächsten Blocker aus."""
    async with SessionLocal() as session:
        result = await session.execute(
            select(Mail)
            .options(selectinload(Mail.aufgaben))
            .where(Mail.id == mail_id)
        )
        mail = result.scalar_one_or_none()
        if mail is None:
            return {"status": "mail_nicht_gefunden"}

        wartend = next((a for a in mail.aufgaben if a.status == "wartet"), None)
        if wartend is None:
            return {"status": "keine_aufgabe_offen"}
        if wartend.aufgabe_typ == RECHNUNG_VERWALTEN:
            try:
                ergebnis = await rechnung_verarbeiten(session, mail)
            except Exception as exc:
                logger.exception("Rechnungsverarbeitung fehlgeschlagen für %s", mail.message_id)
                wartend.status = "fehlgeschlagen"
                wartend.fehler = str(exc)
                session.add(Aktionslog(
                    mail_id=mail.id, ereignis="rechnung_fehlgeschlagen", detail=str(exc),
                ))
                await session.commit()
                return {"status": "fehlgeschlagen", "detail": str(exc)}
            wartend.status = "erledigt"
            wartend.erledigt_am = datetime.now(timezone.utc)
            wartend.fehler = None
            session.add(Aktionslog(
                mail_id=mail.id, ereignis="rechnung_verarbeitet",
                detail=f"{len(ergebnis['rechnungen'])} Rechnung(en) ausgewertet und in Dropbox abgelegt",
            ))
            await _naechste_freischalten(session, mail.id, wartend.position)
            await session.commit()
            return await wartende_aufgaben_ausfuehren(mail_id)

        if wartend.aufgabe_typ != MAIL_VERSCHIEBEN:
            return {"status": "wartet", "aufgabe_typ": wartend.aufgabe_typ}

        postfach = await session.get(Postfach, mail.postfach_id)
        parameter = wartend.parameter or {}
        zieladresse = parameter.get("zielpostfach")
        zielordner = parameter.get("zielordner") or "INBOX"
        configs = {config.user: config for config in lade_postfaecher()}
        quelle = configs.get(postfach.adresse) if postfach else None
        ziel = configs.get(zieladresse)

        if not quelle or not ziel or mail.imap_uid is None:
            fehler = "Quell-/Zielpostfach oder IMAP-UID nicht konfiguriert"
            wartend.status = "fehlgeschlagen"
            wartend.fehler = fehler
            mail.im_krautl_posteingang = False
            session.add(Aktionslog(
                mail_id=mail.id, ereignis="verschieben_fehlgeschlagen",
                detail=f"{fehler}; aus Krautl-Posteingang entfernt",
            ))
            await session.commit()
            return {"status": "fehlgeschlagen", "detail": fehler}

        aufgabe_id = wartend.id
        position = wartend.position
        message_id = mail.message_id

    try:
        await asyncio.to_thread(
            mail_verschieben, quelle, mail.imap_uid, ziel, zielordner
        )
    except Exception as exc:
        logger.exception("Verschieben nach %s/%s fehlgeschlagen für %s", ziel.user, zielordner, message_id)
        async with SessionLocal() as session:
            aufgabe = await session.get(MailAufgabe, aufgabe_id)
            mail = await session.get(Mail, mail_id)
            aufgabe.status = "fehlgeschlagen"
            aufgabe.fehler = str(exc)
            mail.im_krautl_posteingang = False
            session.add(Aktionslog(
                mail_id=mail_id, ereignis="verschieben_fehlgeschlagen",
                detail=(
                    f"nach {ziel.user}/{zielordner}: {exc}; "
                    "aus Krautl-Posteingang entfernt"
                ),
            ))
            await session.commit()
        return {"status": "fehlgeschlagen", "detail": str(exc)}

    async with SessionLocal() as session:
        aufgabe = await session.get(MailAufgabe, aufgabe_id)
        mail = await session.get(Mail, mail_id)
        aufgabe.status = "erledigt"
        aufgabe.erledigt_am = datetime.now(timezone.utc)
        aufgabe.fehler = None
        mail.im_krautl_posteingang = False
        session.add(Aktionslog(
            mail_id=mail_id, ereignis="verschoben",
            detail=f"nach {ziel.user}/{zielordner}; aus Krautl-Posteingang entfernt",
        ))
        await _naechste_freischalten(session, mail_id, position)
        await session.commit()
    return {"status": "erledigt"}
