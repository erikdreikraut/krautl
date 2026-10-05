"""Berechtigte Wiederansicht versendeter Antworten, einschließlich Altbestand."""
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import func, or_, select
from sqlalchemy.orm import undefer
from sqlalchemy.ext.asyncio import AsyncSession

from .berechtigungen import darf_mail_sehen, mailzugriffsfilter, verweigerte_klassifikationen
from .db import get_session
from .gesendet_ablage import versandkopie_ablegen
from .mail_versand import _antwort_betreff
from .models import Entwurf, Mail, Versandkopie

router = APIRouter()


def _daten(entwurf, mail, kopie):
    return {
        "id": entwurf.id, "mail_id": mail.id,
        "kunde": mail.absender_name or mail.absender_adresse,
        "empfaenger": kopie.empfaenger if kopie else mail.antwort_an_adresse or mail.absender_adresse,
        "absender": kopie.absender if kopie else None,
        "betreff": kopie.betreff if kopie else _antwort_betreff(mail.betreff),
        "versendet_am": entwurf.versendet_am,
        "gesendet_von": kopie.gesendet_von if kopie else None,
        "message_id": kopie.message_id if kopie else None,
        "historisch": kopie is None,
        "imap_status": kopie.imap_status if kopie else "historisch",
        "imap_ordner": kopie.imap_ordner if kopie else None,
        "imap_fehler": kopie.imap_fehler if kopie else None,
        "anhaenge": kopie.anhaenge if kopie else None,
    }


async def _laden(session, request, ident, mit_eml=False):
    abfrage = select(Entwurf, Mail, Versandkopie).join(Mail, Mail.id == Entwurf.mail_id).outerjoin(
        Versandkopie, Versandkopie.entwurf_id == Entwurf.id).where(
        Entwurf.id == ident, Entwurf.status == "versendet")
    if mit_eml:
        abfrage = abfrage.options(undefer(Versandkopie.eml))
    zeile = (await session.execute(abfrage)).one_or_none()
    if zeile is None:
        raise HTTPException(404, "Versendete Antwort nicht gefunden")
    if not await darf_mail_sehen(session, request.state.benutzer, zeile[1]):
        raise HTTPException(403, "Kein Zugriff auf diese Mailart")
    return zeile


@router.get("/gesendet")
async def gesendete_antworten(
    request: Request, session: AsyncSession = Depends(get_session),
    suche: str = Query("", max_length=300), seite: int = Query(1, ge=1),
    pro_seite: int = Query(30, ge=1, le=100),
):
    bedingungen = [Entwurf.status == "versendet"]
    verweigert = await verweigerte_klassifikationen(session, request.state.benutzer)
    if "*" in verweigert:
        bedingungen.append(Mail.id.is_(None))
    elif verweigert:
        bedingungen.append(or_(Mail.klassifikation_id.is_(None), ~Mail.klassifikation_id.in_(verweigert)))
    zugriff = mailzugriffsfilter(request.state.benutzer)
    if zugriff is not None:
        bedingungen.append(zugriff)
    if suche.strip():
        muster = "%" + suche.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        bedingungen.append(or_(*(spalte.ilike(muster, escape="\\") for spalte in (
            Mail.absender_name, Mail.absender_adresse, Mail.antwort_an_adresse,
            Mail.betreff, Versandkopie.empfaenger, Versandkopie.betreff,
            Versandkopie.gesendet_von, Entwurf.text_final, Entwurf.text_final_deutsch,
        ))))
    abfrage = select(Entwurf, Mail, Versandkopie).join(Mail, Mail.id == Entwurf.mail_id).outerjoin(
        Versandkopie, Versandkopie.entwurf_id == Entwurf.id).where(*bedingungen)
    gesamt = (await session.execute(select(func.count()).select_from(
        abfrage.with_only_columns(Entwurf.id).subquery()))).scalar_one()
    seiten = max(1, (gesamt + pro_seite - 1) // pro_seite)
    seite = min(seite, seiten)
    zeilen = (await session.execute(abfrage.order_by(Entwurf.versendet_am.desc().nullslast(), Entwurf.id.desc())
        .offset((seite-1)*pro_seite).limit(pro_seite))).all()
    return {"eintraege": [_daten(*z) for z in zeilen], "gesamt": gesamt,
            "seite": seite, "seiten": seiten}


@router.get("/gesendet/{ident}")
async def gesendete_antwort(ident: int, request: Request, session: AsyncSession = Depends(get_session)):
    entwurf, mail, kopie = await _laden(session, request, ident)
    return {**_daten(entwurf, mail, kopie),
        "text": entwurf.text_final, "text_deutsch": entwurf.text_final_deutsch,
        "anfrage": {"betreff": mail.betreff, "text": mail.text_auszug, "empfangen_am": mail.empfangen_am}}


@router.get("/gesendet/{ident}/eml")
async def versand_eml(ident: int, request: Request, session: AsyncSession = Depends(get_session)):
    _, _, kopie = await _laden(session, request, ident, mit_eml=True)
    if kopie is None:
        raise HTTPException(404, "Für diese ältere Antwort ist keine vollständige EML gespeichert")
    return Response(kopie.eml, media_type="message/rfc822", headers={
        "Content-Disposition": f'attachment; filename="krautl-antwort-{ident}.eml"',
        "Cache-Control": "private, no-store",
    })


@router.post("/gesendet/{ident}/ablage")
async def gesendet_ablage_wiederholen(ident: int, request: Request, session: AsyncSession = Depends(get_session)):
    entwurf, mail, kopie = await _laden(session, request, ident)
    if kopie is None:
        raise HTTPException(409, "Für diese ältere Antwort ist keine vollständige Versandkopie gespeichert")
    kopie = await versandkopie_ablegen(session, ident)
    return _daten(entwurf, mail, kopie)
