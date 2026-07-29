from datetime import datetime, timezone
from fastapi import FastAPI, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_session, engine
from .aufgaben import aufgaben_fuer_mail_anlegen, bestaetigung_erfassen, wartende_aufgaben_ausfuehren
from .antworten import antwort_vor_versand_pruefen, antwortentwurf_speichern
from .mail_versand import (
    TEST_EMPFAENGER, antwort_mit_signatur, testantwort_senden,
)
from .auth import (
    COOKIE_NAME, SESSION_DAUER_SEKUNDEN, anmelden, oeffentliche_daten,
    sitzung_erstellen, sitzung_lesen,
)
from .models import (
    Aktionslog, Base, Mail, MailAufgabe, Rechnung, FaqEintrag, FaqVorschlag,
    Entwurf, Korrektur, Klassifikation, KlassifikationAufgabe, SystemStatus,
)

app = FastAPI(title="Krautl API")

ERLAUBTE_AKTIONEN = {
    "BESTAETIGUNG_EINHOLEN",
    "MAIL_VERSCHIEBEN",
    "RECHNUNG_VERWALTEN",
    "ANTWORTVORSCHLAG_ERSTELLEN",
    "LIEFERANTENMAIL_BEARBEITEN",
    "MARKETINGMAIL_BEARBEITEN",
    "AUDIO_TRANSKRIBIEREN",
    "SYSTEMMELDUNG_BEARBEITEN",
    "RECHTSSACHE_BEARBEITEN",
}


class KlassifikationAenderung(BaseModel):
    zielpostfach: str | None = None
    zielordner: str | None = None
    aufgaben: list[str]


class EntwurfFreigabe(BaseModel):
    finaler_text: str


class Anmeldung(BaseModel):
    benutzername: str
    passwort: str


@app.middleware("http")
async def anmeldung_erfordern(request: Request, call_next):
    if request.url.path in {"/health", "/auth/login"}:
        return await call_next(request)
    try:
        benutzer = sitzung_lesen(request.cookies.get(COOKIE_NAME))
    except RuntimeError as exc:
        return JSONResponse(status_code=503, content={"detail": str(exc)})
    if benutzer is None:
        return JSONResponse(status_code=401, content={"detail": "Anmeldung erforderlich"})
    request.state.benutzer = benutzer
    return await call_next(request)


@app.post("/auth/login")
async def login(anmeldung: Anmeldung, response: Response):
    try:
        benutzer = anmelden(anmeldung.benutzername, anmeldung.passwort)
        token = sitzung_erstellen(benutzer["benutzername"]) if benutzer else None
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if benutzer is None:
        raise HTTPException(status_code=401, detail="Benutzername oder Passwort falsch")
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=SESSION_DAUER_SEKUNDEN,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
    )
    return oeffentliche_daten(benutzer)


@app.get("/auth/me")
async def aktueller_benutzer(request: Request):
    return oeffentliche_daten(request.state.benutzer)


@app.post("/auth/logout")
async def logout(response: Response):
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"status": "abgemeldet"}


@app.on_event("startup")
async def on_startup():
    # Für den Start reicht create_all. Sobald das Schema sich weiterentwickelt,
    # auf Alembic-Migrationen umsteigen (siehe README).
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

@app.get("/health")
async def health(session: AsyncSession = Depends(get_session)):
    worker = await session.get(SystemStatus, "mail_worker")
    jetzt = datetime.now(timezone.utc)
    letzter_lauf = worker.letzter_lauf if worker else None
    if letzter_lauf and letzter_lauf.tzinfo is None:
        letzter_lauf = letzter_lauf.replace(tzinfo=timezone.utc)
    alter = (jetzt - letzter_lauf).total_seconds() if letzter_lauf else None
    return {
        "status": "ok",
        "datenbank": "ok",
        "mail_worker": {
            "aktiv": alter is not None and alter < 300,
            "status": worker.status if worker else "noch_nicht_gestartet",
            "letzter_lauf": letzter_lauf,
            "letzter_erfolg": worker.letzter_erfolg if worker else None,
            "letzter_fehler": worker.letzter_fehler if worker else None,
            "detail": worker.detail if worker else None,
        },
    }


@app.get("/mails")
async def liste_mails(session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(Mail)
        .options(selectinload(Mail.aufgaben), selectinload(Mail.postfach))
        .where(Mail.im_krautl_posteingang.is_(True))
        .order_by(Mail.empfangen_am.desc())
        .limit(100)
    )
    mails = result.scalars().all()
    return [
        {
            **{spalte.name: getattr(mail, spalte.name) for spalte in Mail.__table__.columns},
            "quellpostfach": mail.postfach.adresse if mail.postfach else None,
            "aufgaben": [
                {spalte.name: getattr(aufgabe, spalte.name) for spalte in MailAufgabe.__table__.columns}
                for aufgabe in mail.aufgaben
            ],
            "bestaetigung_erforderlich": any(
                a.aufgabe_typ == "BESTAETIGUNG_EINHOLEN" and a.status == "wartet"
                for a in mail.aufgaben
            ),
        }
        for mail in mails
    ]


@app.get("/klassifikationen")
async def liste_klassifikationen(session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(Klassifikation)
        .options(selectinload(Klassifikation.aufgaben))
        .order_by(Klassifikation.hauptkategorie)
    )
    return [
        {
            **{spalte.name: getattr(k, spalte.name) for spalte in Klassifikation.__table__.columns},
            "aufgaben": [
                {spalte.name: getattr(a, spalte.name) for spalte in a.__table__.columns}
                for a in k.aufgaben
            ],
        }
        for k in result.scalars().all()
    ]


@app.put("/klassifikationen/{klassifikation_id}")
async def klassifikation_aktualisieren(
    klassifikation_id: str,
    aenderung: KlassifikationAenderung,
    session: AsyncSession = Depends(get_session),
):
    klassifikation = await session.get(Klassifikation, klassifikation_id)
    if klassifikation is None:
        raise HTTPException(status_code=404, detail="Klassifikation nicht gefunden")

    ungueltig = [a for a in aenderung.aufgaben if a not in ERLAUBTE_AKTIONEN]
    if ungueltig:
        raise HTTPException(
            status_code=422,
            detail=f"Unbekannte Aktion: {ungueltig[0]}",
        )

    zielpostfach = (aenderung.zielpostfach or "").strip() or None
    zielordner = (aenderung.zielordner or "").strip() or None
    klassifikation.zielpostfach = zielpostfach
    klassifikation.zielordner = zielordner
    # Das alte Einzelaktionsfeld bleibt für CSV-Kompatibilität erhalten.
    klassifikation.aktion_id = (
        aenderung.aufgaben[0] if aenderung.aufgaben else "KEINE_AKTION"
    )

    await session.execute(
        delete(KlassifikationAufgabe).where(
            KlassifikationAufgabe.klassifikation_id == klassifikation_id
        )
    )
    await session.flush()

    for position, aufgabe_typ in enumerate(aenderung.aufgaben, start=1):
        session.add(KlassifikationAufgabe(
            klassifikation_id=klassifikation_id,
            position=position,
            aufgabe_typ=aufgabe_typ,
            parameter={
                "zielpostfach": zielpostfach,
                "zielordner": zielordner,
            },
            bestaetiger_typ="alle",
        ))

    await session.commit()
    return {"status": "gespeichert"}


@app.post("/mails/{mail_id}/bestaetigen")
async def mail_bestaetigen(mail_id: int, bestaetigt_von: str | None = None):
    ergebnis = await bestaetigung_erfassen(mail_id, bestaetigt_von)
    if ergebnis["status"] == "mail_nicht_gefunden":
        raise HTTPException(status_code=404, detail="Mail nicht gefunden")
    if ergebnis["status"] == "keine_bestaetigung_offen":
        raise HTTPException(status_code=409, detail="Für diese Mail wartet keine Bestätigung")
    return ergebnis


@app.get("/aktionslog")
async def liste_aktionslog(session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(Aktionslog).order_by(Aktionslog.erstellt_am.desc()).limit(200)
    )
    return result.scalars().all()


@app.post("/mails/{mail_id}/korrektur")
async def korrigiere_klassifikation(
    mail_id: int, neue_klassifikation_id: str, notiz: str | None = None,
    session: AsyncSession = Depends(get_session),
):
    mail = await session.get(Mail, mail_id)
    korrektur = Korrektur(
        mail_id=mail_id,
        alte_klassifikation_id=mail.klassifikation_id,
        neue_klassifikation_id=neue_klassifikation_id,
        notiz=notiz,
    )
    mail.klassifikation_id = neue_klassifikation_id
    mail.pruefstatus = "geprueft"
    session.add(korrektur)
    await session.execute(delete(MailAufgabe).where(MailAufgabe.mail_id == mail_id))
    await session.flush()
    await aufgaben_fuer_mail_anlegen(session, mail)
    await session.commit()
    await wartende_aufgaben_ausfuehren(mail_id)
    return {"status": "ok"}


@app.get("/rechnungen")
async def liste_rechnungen(session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(Rechnung)
        .where(Rechnung.zahlungsstatus.in_(["offen", "unklar", "bezahlt"]))
        .order_by(Rechnung.faellig_am.nulls_last(), Rechnung.rechnungsdatum.desc())
    )
    return result.scalars().all()


@app.post("/rechnungen/{rechnung_id}/als-bezahlt")
async def rechnung_als_bezahlt(rechnung_id: int, session: AsyncSession = Depends(get_session)):
    rechnung = await session.get(Rechnung, rechnung_id)
    rechnung.zahlungsstatus = "bezahlt"
    await session.commit()
    return {"status": "ok"}


@app.get("/faq")
async def liste_faq(session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(FaqEintrag).where(FaqEintrag.aktiv.is_(True)))
    return result.scalars().all()


@app.get("/faq/vorschlaege")
async def liste_faq_vorschlaege(session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(FaqVorschlag).where(FaqVorschlag.status == "offen"))
    return result.scalars().all()


@app.post("/faq/vorschlaege/{vorschlag_id}/uebernehmen")
async def faq_vorschlag_uebernehmen(vorschlag_id: int, session: AsyncSession = Depends(get_session)):
    vorschlag = await session.get(FaqVorschlag, vorschlag_id)
    eintrag = FaqEintrag(
        kategorie=vorschlag.kategorie,
        frage=vorschlag.frage,
        antwort=vorschlag.entwurf_antwort,
    )
    vorschlag.status = "uebernommen"
    session.add(eintrag)
    await session.commit()
    return {"status": "uebernommen"}


@app.post("/faq/vorschlaege/{vorschlag_id}/verwerfen")
async def faq_vorschlag_verwerfen(vorschlag_id: int, session: AsyncSession = Depends(get_session)):
    vorschlag = await session.get(FaqVorschlag, vorschlag_id)
    vorschlag.status = "verworfen"
    await session.commit()
    return {"status": "verworfen"}


@app.get("/entwuerfe")
async def liste_entwuerfe(session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Entwurf).where(Entwurf.status == "wartet"))
    return result.scalars().all()


@app.post("/mails/{mail_id}/antwortentwurf")
async def mail_antwortentwurf_erzeugen(
    mail_id: int,
    session: AsyncSession = Depends(get_session),
):
    mail = await session.get(Mail, mail_id)
    if mail is None:
        raise HTTPException(status_code=404, detail="Mail nicht gefunden")

    try:
        entwurf, erzeugt = await antwortentwurf_speichern(session, mail)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Antwortvorschlag konnte nicht erzeugt werden: {exc}",
        ) from exc

    await session.commit()
    return {
        "status": "erzeugt" if erzeugt else "vorhanden",
        "entwurf_id": entwurf.id,
    }


@app.post("/entwuerfe/{entwurf_id}/freigeben")
async def entwurf_freigeben(
    entwurf_id: int,
    freigabe: EntwurfFreigabe,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    entwurf = (await session.execute(
        select(Entwurf)
        .where(Entwurf.id == entwurf_id)
        .with_for_update()
    )).scalar_one_or_none()
    if entwurf is None:
        raise HTTPException(status_code=404, detail="Entwurf nicht gefunden")
    if entwurf.status == "versendet":
        return {
            "status": "bereits_versendet",
            "empfaenger": TEST_EMPFAENGER,
        }

    finaler_text = freigabe.finaler_text.strip()
    if not finaler_text:
        raise HTTPException(status_code=422, detail="Die Antwort ist leer")
    mail = await session.get(Mail, entwurf.mail_id)
    if mail is None:
        raise HTTPException(status_code=404, detail="Zugehörige Mail nicht gefunden")
    faq = (await session.execute(
        select(FaqEintrag).where(FaqEintrag.aktiv.is_(True))
    )).scalars().all()

    bisherige_blockierungen = (await session.execute(
        select(func.count(Aktionslog.id)).where(
            Aktionslog.mail_id == mail.id,
            Aktionslog.ereignis == "antwort_pruefung_noetig",
            Aktionslog.detail.like(f"Entwurf #{entwurf.id}:%"),
        )
    )).scalar_one()
    pruefung_uebersprungen = bisherige_blockierungen >= 2

    if not pruefung_uebersprungen:
        try:
            pruefung = await antwort_vor_versand_pruefen(mail, finaler_text, faq)
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail=f"KI-Prüfung konnte nicht durchgeführt werden: {exc}",
            ) from exc

        if not pruefung["freigabefaehig"]:
            neue_anzahl = bisherige_blockierungen + 1
            session.add(Aktionslog(
                mail_id=mail.id,
                ereignis="antwort_pruefung_noetig",
                detail=(
                    f"Entwurf #{entwurf.id}: geprüft durch "
                    f"{request.state.benutzer['name']}; "
                    + (
                        "; ".join(pruefung["probleme"])
                        or "Antwort noch nicht freigabefähig"
                    )
                ),
            ))
            await session.commit()
            return {
                "status": "pruefung_noetig",
                "probleme": pruefung["probleme"],
                "blockierungen": neue_anzahl,
                "naechster_versuch_ohne_pruefung": neue_anzahl >= 2,
            }
    else:
        session.add(Aktionslog(
            mail_id=mail.id,
            ereignis="antwort_pruefung_uebersprungen",
            detail=(
                "Nach zwei KI-Blockierungen auf ausdrücklichen dritten "
                f"Freigabeversuch durch {request.state.benutzer['name']} verzichtet"
            ),
        ))

    try:
        await testantwort_senden(mail, finaler_text, request.state.benutzer)
    except Exception as exc:
        session.add(Aktionslog(
            mail_id=mail.id,
            ereignis="antwort_versand_fehlgeschlagen",
            detail=(
                f"Freigabe durch {request.state.benutzer['name']}; "
                f"Testversand an {TEST_EMPFAENGER}: {exc}"
            ),
        ))
        await session.commit()
        raise HTTPException(
            status_code=502,
            detail=f"Testversand fehlgeschlagen: {exc}",
        ) from exc

    entwurf.text_final = antwort_mit_signatur(
        finaler_text, request.state.benutzer
    )
    entwurf.status = "versendet"
    entwurf.versendet_am = datetime.now(timezone.utc)
    session.add(Aktionslog(
        mail_id=mail.id,
        ereignis="antwort_versendet_test",
        detail=(
            f"Durch {request.state.benutzer['name']} "
            f"{'ohne weitere KI-Prüfung ' if pruefung_uebersprungen else 'nach KI-Prüfung '}"
            f"ausschließlich an {TEST_EMPFAENGER} versendet"
        ),
    ))
    await session.commit()
    return {
        "status": "versendet",
        "empfaenger": TEST_EMPFAENGER,
        "pruefung_uebersprungen": pruefung_uebersprungen,
    }


@app.post("/entwuerfe/{entwurf_id}/verwerfen")
async def entwurf_verwerfen(entwurf_id: int, session: AsyncSession = Depends(get_session)):
    entwurf = await session.get(Entwurf, entwurf_id)
    entwurf.status = "verworfen"
    await session.commit()
    return {"status": "verworfen"}
