from fastapi import FastAPI, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_session, engine
from .models import Base, Mail, Rechnung, FaqVorschlag, Entwurf, Korrektur

app = FastAPI(title="Krautl API")


@app.on_event("startup")
async def on_startup():
    # Für den Start reicht create_all. Sobald das Schema sich weiterentwickelt,
    # auf Alembic-Migrationen umsteigen (siehe README).
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/mails")
async def liste_mails(session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Mail).order_by(Mail.empfangen_am.desc()).limit(100))
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


@app.get("/faq/vorschlaege")
async def liste_faq_vorschlaege(session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(FaqVorschlag).where(FaqVorschlag.status == "offen"))
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
