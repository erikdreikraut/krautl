"""Nur IMAP-Ablage bereits gesendeter Nachrichten; niemals erneuter SMTP-Versand."""
import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from email import message_from_bytes, policy

from imapclient import IMAPClient
from sqlalchemy import or_, select
from sqlalchemy.orm import undefer

from .imap_client import lade_postfaecher
from .models import Aktionslog, Entwurf, Versandkopie

logger = logging.getLogger(__name__)
_ABLAGE_LOCK = asyncio.Lock()


def _ordner(client, vorgabe):
    ordner = client.list_folders()
    namen = [(flags, delimiter, name.decode() if isinstance(name, bytes) else name)
             for flags, delimiter, name in ordner]
    if vorgabe:
        if vorgabe not in {name for _, _, name in namen}:
            raise RuntimeError("IMAP_SERVICE_SENT_FOLDER wurde auf dem Server nicht gefunden")
        return vorgabe
    sent = [name for flags, _, name in namen if any(
        (f.decode() if isinstance(f, bytes) else f).casefold() == "\\sent" for f in flags)]
    if len(sent) == 1:
        return sent[0]
    if not sent:
        bekannt = {"sent", "sent items", "sent messages", "gesendet", "gesendete elemente", "gesendete objekte"}
        for _, delimiter, name in namen:
            delimiter = delimiter.decode() if isinstance(delimiter, bytes) else delimiter
            letzter_teil = name.rsplit(delimiter, 1)[-1] if delimiter else name
            if letzter_teil.casefold() in bekannt:
                sent.append(name)
        if len(sent) == 1:
            return sent[0]
    raise RuntimeError("Gesendet-Ordner nicht eindeutig; IMAP_SERVICE_SENT_FOLDER konfigurieren")


def kopie_in_gesendet(eml: bytes, absender: str, message_id: str) -> str:
    postfaecher = lade_postfaecher()
    config = next((p for p in postfaecher if p.user.casefold() == absender.casefold()), None)
    if config is None:
        config = next((p for p in postfaecher if p.funktion == "service"), None)
    if config is None:
        raise RuntimeError("IMAP-Servicepostfach ist nicht konfiguriert")
    with IMAPClient(config.host, ssl=True, timeout=30) as client:
        client.login(config.user, config.password)
        ordner = _ordner(client, os.environ.get("IMAP_SERVICE_SENT_FOLDER", "").strip())
        client.select_folder(ordner)
        # IMAP HEADER-Suche kann Teiltreffer liefern: Message-ID exakt abgleichen.
        uids = client.search(["HEADER", "Message-ID", message_id])
        if uids:
            for daten in client.fetch(uids, ["BODY.PEEK[HEADER.FIELDS (MESSAGE-ID)]"]).values():
                for wert in daten.values():
                    if isinstance(wert, bytes):
                        kopf = message_from_bytes(wert, policy=policy.default)
                        if str(kopf.get("Message-ID", "")).strip() == message_id:
                            return ordner
        client.append(ordner, eml, flags=[b"\\Seen"])
        return ordner


async def versandkopie_ablegen(session, entwurf_id):
    # Serialisiert auch SQLite-Tests; PostgreSQL-Sperre schützt mehrere Prozesse.
    async with _ABLAGE_LOCK:
        kopie = (await session.execute(select(Versandkopie)
            .options(undefer(Versandkopie.eml))
            .where(Versandkopie.entwurf_id == entwurf_id).with_for_update()
            .execution_options(populate_existing=True))).scalar_one_or_none()
        if kopie is None:
            raise LookupError("Für diese ältere Antwort liegt keine vollständige Versandkopie vor")
        if kopie.imap_status == "gespeichert":
            return kopie
        kopie.imap_versuche += 1
        kopie.imap_letzter_versuch = datetime.now(timezone.utc)
        entwurf = await session.get(Entwurf, entwurf_id)
        try:
            kopie.imap_ordner = await asyncio.to_thread(
                kopie_in_gesendet, kopie.eml, kopie.absender, kopie.message_id)
            kopie.imap_status, kopie.imap_fehler = "gespeichert", None
            ereignis = "antwort_gesendet_abgelegt"
            detail = f"Antwort #{entwurf_id} in {kopie.absender}/{kopie.imap_ordner} abgelegt."
        except Exception:
            logger.exception("Gesendet-Ablage fehlgeschlagen für Antwort %s", entwurf_id)
            kopie.imap_status = "fehler"
            kopie.imap_fehler = "Kopie konnte nicht abgelegt werden. IMAP-Zugang und Gesendet-Ordner prüfen."
            ereignis = "antwort_ablage_fehlgeschlagen"
            detail = f"Antwort #{entwurf_id}: {kopie.imap_fehler} Die Mail wurde bereits an den Mailserver übergeben."
        session.add(Aktionslog(mail_id=entwurf.mail_id, ereignis=ereignis,
            ausgeloest_von="Krautl", detail=detail))
        await session.commit()
        return kopie


async def ausstehende_kopien_ablegen(session_factory):
    grenze = datetime.now(timezone.utc) - timedelta(minutes=5)
    async with session_factory() as session:
        ids = (await session.execute(select(Versandkopie.entwurf_id).where(
            Versandkopie.imap_status.in_(["ausstehend", "fehler"]),
            Versandkopie.imap_versuche < 10,
            or_(Versandkopie.imap_letzter_versuch.is_(None),
                Versandkopie.imap_letzter_versuch < grenze),
        ).order_by(Versandkopie.entwurf_id).limit(10))).scalars().all()
    for entwurf_id in ids:
        async with session_factory() as session:
            await versandkopie_ablegen(session, entwurf_id)


async def versandkopien_ueberwachen(session_factory):
    while True:
        await asyncio.sleep(30)
        try:
            await ausstehende_kopien_ablegen(session_factory)
        except Exception:
            logger.exception("Nachholen der Gesendet-Kopien fehlgeschlagen")
