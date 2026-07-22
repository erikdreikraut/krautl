from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_session, engine
from .aufgaben import aufgaben_fuer_mail_anlegen, bestaetigung_erfassen
from .models import (
    Aktionslog, Base, Mail, MailAufgabe, Rechnung, FaqEintrag, FaqVorschlag,
    Entwurf, Korrektur, Klassifikation,
)
from .worker import alle_postfaecher_abrufen

app = FastAPI(title="Krautl API")
scheduler = AsyncIOScheduler()


@app.on_event("startup")
async def on_startup():
    # Für den Start reicht create_all. Sobald das Schema sich weiterentwickelt,
    # auf Alembic-Migrationen umsteigen (siehe README).
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Minütlicher Mail-Abruf über alle konfigurierten Postfächer hinweg.
    scheduler.add_job(
        alle_postfaecher_abrufen,
        trigger=IntervalTrigger(minutes=1),
        id="mail_poll",
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()


@app.on_event("shutdown")
async def on_shutdown():
    scheduler.shutdown(wait=False)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/mails")
async def liste_mails(session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(Mail)
        .options(selectinload(Mail.aufgaben))
        .where(Mail.im_krautl_posteingang.is_(True))
        .order_by(Mail.empfangen_am.desc())
        .limit(100)
    )
    mails = result.scalars().all()
    return [
        {
            **{spalte.name: getattr(mail, spalte.name) for spalte in Mail.__table__.columns},
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
    return {"status": "ok"}


@app.get("/rechnungen")
async def liste_rechnungen(session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Rechnung).order_by(Rechnung.faellig_am))
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


@app.post("/entwuerfe/{entwurf_id}/freigeben")
async def entwurf_freigeben(entwurf_id: int, finaler_text: str, session: AsyncSession = Depends(get_session)):
    """
    Setzt den Entwurf auf 'freigegeben'. Der tatsächliche Versand (SMTP)
    erfolgt danach als separater, expliziter Schritt — absichtlich nicht
    in derselben Funktion, damit hier niemals versehentlich automatisch
    gesendet werden kann.
    """
    entwurf = await session.get(Entwurf, entwurf_id)
    entwurf.text_final = finaler_text
    entwurf.status = "freigegeben"
    await session.commit()
    return {"status": "freigegeben", "hinweis": "Versand erfolgt separat per SMTP-Job."}


@app.post("/entwuerfe/{entwurf_id}/verwerfen")
async def entwurf_verwerfen(entwurf_id: int, session: AsyncSession = Depends(get_session)):
    entwurf = await session.get(Entwurf, entwurf_id)
    entwurf.status = "verworfen"
    await session.commit()
    return {"status": "verworfen"}
