"""Persistierte Arbeitsübersetzungen; kein Versand und keine Klassifikation."""
import hashlib
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from .models import WhatsAppNachricht as Nachricht, WhatsAppUebersetzung as Uebersetzung
from .uebersetzungen import mail_ins_deutsche_uebersetzen


def quelltext(msg):
    return (msg.transkript or msg.text or "").strip()


def auswertbar(msg):
    text = quelltext(msg)
    return bool(text) and (bool(msg.transkript) or (
        msg.typ in {"text", "image", "document", "video"} and text != f"[{msg.typ}]"))


def fingerprint(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


async def sprachdaten(session, msg):
    daten = await session.get(Uebersetzung, msg.id)
    return daten if daten and daten.original_hash == fingerprint(quelltext(msg)) else None


async def sicherstellen(session, msg):
    daten = await sprachdaten(session, msg)
    if daten:
        return daten
    text, ident = quelltext(msg), msg.id
    if not auswertbar(msg):
        raise HTTPException(409, "Keine auswertbare Kundennachricht. Bitte zunächst eine Sprachnachricht transkribieren.")
    await session.commit()  # Keine Chat-Sperre während des KI-Aufrufs.
    try:
        result = await mail_ins_deutsche_uebersetzen("WhatsApp-Nachricht", text)
        sprache = result["originalsprache"]
        if not sprache or sprache.casefold() in {"unbekannt", "unknown", "und"}:
            raise ValueError("Sprache nicht erkannt")
    except Exception as exc:
        raise HTTPException(502, "Sprache/Übersetzung konnte nicht ermittelt werden. Es wurde nichts gesendet. Bitte erneut versuchen.") from exc
    session.expire_all()
    aktuell = await session.get(Nachricht, ident)
    if not aktuell or quelltext(aktuell) != text:
        raise HTTPException(409, "Nachricht wurde inzwischen geändert. Bitte erneut laden.")
    daten = await session.get(Uebersetzung, ident)
    if daten is None:
        daten = Uebersetzung(nachricht_id=ident)
        session.add(daten)
    daten.original_hash = fingerprint(text)
    daten.sprache = sprache
    daten.text_deutsch = result["text_deutsch"]
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        daten = await session.get(Uebersetzung, ident)
        if not daten or daten.original_hash != fingerprint(text):
            raise HTTPException(409, "Übersetzung wurde parallel geändert. Bitte erneut laden.")
    return daten


async def letzte_kundennachricht(session, ident):
    kandidaten = (await session.execute(select(Nachricht).where(
        Nachricht.chat_id == ident, Nachricht.richtung == "eingehend",
    ).order_by(Nachricht.zeit.desc(), Nachricht.id.desc()).limit(300))).scalars().all()
    kurze_bestaetigungen = {"ja", "yes", "si", "sí", "ok", "okay", "danke", "thanks", "gracias", "👍"}
    passende = [m for m in kandidaten if auswertbar(m)]
    return next((m for m in passende if quelltext(m).casefold().strip(".! ") not in kurze_bestaetigungen), passende[0] if passende else None)
