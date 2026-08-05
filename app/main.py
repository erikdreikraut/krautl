import asyncio
import logging
import mimetypes
from datetime import datetime, timezone
from urllib.parse import quote
from fastapi import FastAPI, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_session, engine
from .aufgaben import aufgaben_fuer_mail_anlegen, bestaetigung_erfassen, wartende_aufgaben_ausfuehren
from .antworten import antwort_vor_versand_pruefen, antwortentwurf_speichern
from .mail_versand import (
    TEST_EMPFAENGER, antwort_mit_signatur, testantwort_senden,
)
from .imap_client import lade_postfaecher, mail_loeschen as mail_imap_loeschen
from .auth import (
    BENUTZER, COOKIE_NAME, SESSION_DAUER_SEKUNDEN, anmelden, oeffentliche_daten,
    sitzung_erstellen, sitzung_lesen,
)
from .berechtigungen import (
    ROLLE_SACHBEARBEITER, darf_klassifikation_sehen, darf_mail_sehen,
    ist_admin, verweigerte_klassifikationen,
)
from .models import (
    Aktionslog, Base, Mail, MailAufgabe, Postfach, Rechnung, FaqEintrag, FaqVorschlag,
    Entwurf, Korrektur, Klassifikation, KlassifikationAufgabe, SystemStatus,
    Produkt, Produktfamilie, RollenMailzugriff, Wissenseintrag, WissensVorschlag,
)
from .wissensbasis import (
    FAQ_STATUS, WISSENSARTEN, WISSENSSTATUS, faq_als_jtl_html,
    relevante_wissensbasis, wissenszuwachs_nach_antwort_pruefen,
)
from .shop_import import shop_katalog_laden, shop_katalog_speichern
from .rechnungen import (
    rechnungsdatei_aus_mail_laden,
)

app = FastAPI(title="Krautl API")
logger = logging.getLogger(__name__)

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


class RechnungsstatusAenderung(BaseModel):
    zahlungsstatus: str


class RollenMailzugriffAenderung(BaseModel):
    klassifikation_ids: list[str]


class Anmeldung(BaseModel):
    benutzername: str
    passwort: str


class ProduktAenderung(BaseModel):
    name: str
    artikelnummer: str | None = None
    familie: str | None = None
    aliases: list[str] = Field(default_factory=list)
    website_url: str | None = None
    aktiv: bool = True


class WissenAenderung(BaseModel):
    wissensart: str
    titel: str
    inhalt: str
    produkt_id: int | None = None
    produktfamilie_id: int | None = None
    quelle: str | None = None
    stand: str | None = None
    status: str = "entwurf"
    sensibel: bool = False
    schlagwoerter: list[str] = Field(default_factory=list)


class FaqAenderung(BaseModel):
    produkt_id: int | None = None
    kategorie: str
    frage: str
    antwort: str
    quelle: str | None = None
    status: str = "entwurf"
    sortierung: int = 0
    aktiv: bool = True


class FaqRubrikAenderung(BaseModel):
    produkt_id: int | None = None
    alte_kategorie: str
    neue_kategorie: str


class VorschlagUebernahme(BaseModel):
    ziel: str
    wissensart: str = "allgemein"
    produkt_id: int | None = None
    titel: str
    inhalt: str
    kategorie: str = "Kundenfragen"


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


def _admin_erfordern(request: Request):
    if not ist_admin(request.state.benutzer):
        raise HTTPException(status_code=403, detail="Nur für Administratoren")


async def _mailzugriff_erfordern(session, request: Request, mail: Mail | None):
    if mail is None:
        raise HTTPException(status_code=404, detail="Mail nicht gefunden")
    if not await darf_mail_sehen(session, request.state.benutzer, mail):
        raise HTTPException(status_code=403, detail="Kein Zugriff auf diese Mailart")


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
async def liste_mails(request: Request, session: AsyncSession = Depends(get_session)):
    verweigert = await verweigerte_klassifikationen(session, request.state.benutzer)
    if "*" in verweigert:
        return []
    abfrage = (
        select(Mail)
        .options(selectinload(Mail.aufgaben), selectinload(Mail.postfach))
        .where(Mail.im_krautl_posteingang.is_(True))
        .order_by(Mail.empfangen_am.desc())
        .limit(100)
    )
    if verweigert:
        abfrage = abfrage.where(or_(
            Mail.klassifikation_id.is_(None),
            ~Mail.klassifikation_id.in_(verweigert),
        ))
    result = await session.execute(abfrage)
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
async def liste_klassifikationen(request: Request, session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(Klassifikation)
        .options(selectinload(Klassifikation.aufgaben))
        .order_by(Klassifikation.hauptkategorie)
    )
    klassifikationen = result.scalars().all()
    verweigert = await verweigerte_klassifikationen(session, request.state.benutzer)
    if "*" in verweigert:
        return []
    return [
        {
            **{spalte.name: getattr(k, spalte.name) for spalte in Klassifikation.__table__.columns},
            "aufgaben": [
                {spalte.name: getattr(a, spalte.name) for spalte in a.__table__.columns}
                for a in k.aufgaben
            ],
        }
        for k in klassifikationen
        if k.klassifikation_id not in verweigert
    ]


@app.get("/rollen-mailzugriff")
async def rollen_mailzugriff_laden(
    request: Request, session: AsyncSession = Depends(get_session)
):
    _admin_erfordern(request)
    klassifikationen = (await session.execute(
        select(Klassifikation).order_by(
            Klassifikation.hauptkategorie, Klassifikation.klassifikation_id
        )
    )).scalars().all()
    rechte = {
        zeile.klassifikation_id: zeile.darf_sehen
        for zeile in (await session.execute(select(RollenMailzugriff).where(
            RollenMailzugriff.rolle == ROLLE_SACHBEARBEITER
        ))).scalars().all()
    }
    return {
        "rollen": [
            {
                "id": "admin",
                "name": "Admin",
                "benutzer": [
                    oeffentliche_daten(b) for b in BENUTZER.values()
                    if b["rolle"] == "admin"
                ],
                "alle_mailarten": True,
            },
            {
                "id": ROLLE_SACHBEARBEITER,
                "name": "Sachbearbeiter",
                "benutzer": [
                    oeffentliche_daten(b) for b in BENUTZER.values()
                    if b["rolle"] == ROLLE_SACHBEARBEITER
                ],
                "klassifikation_ids": [
                    k.klassifikation_id for k in klassifikationen
                    if rechte.get(k.klassifikation_id, True)
                ],
            },
        ],
        "klassifikationen": [
            {
                "klassifikation_id": k.klassifikation_id,
                "hauptkategorie": k.hauptkategorie,
                "beschreibung": k.beschreibung,
            }
            for k in klassifikationen
        ],
    }


@app.put("/rollen-mailzugriff/{rolle}")
async def rollen_mailzugriff_speichern(
    rolle: str,
    aenderung: RollenMailzugriffAenderung,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    _admin_erfordern(request)
    if rolle != ROLLE_SACHBEARBEITER:
        raise HTTPException(status_code=422, detail="Diese Rolle ist nicht editierbar")
    klassifikation_ids = set((await session.execute(
        select(Klassifikation.klassifikation_id)
    )).scalars().all())
    ausgewaehlt = set(aenderung.klassifikation_ids)
    unbekannt = ausgewaehlt - klassifikation_ids
    if unbekannt:
        raise HTTPException(
            status_code=422,
            detail=f"Unbekannte Klassifikation: {sorted(unbekannt)[0]}",
        )
    vorhanden = {
        zeile.klassifikation_id: zeile
        for zeile in (await session.execute(select(RollenMailzugriff).where(
            RollenMailzugriff.rolle == rolle
        ))).scalars().all()
    }
    for klassifikation_id in klassifikation_ids:
        zeile = vorhanden.get(klassifikation_id)
        if zeile is None:
            zeile = RollenMailzugriff(
                rolle=rolle, klassifikation_id=klassifikation_id
            )
            session.add(zeile)
        zeile.darf_sehen = klassifikation_id in ausgewaehlt
    session.add(Aktionslog(
        mail_id=None,
        ereignis="rollenzugriff_geaendert",
        ausgeloest_von=request.state.benutzer["name"],
        detail=(
            f"Sachbearbeiter: {len(ausgewaehlt)} von {len(klassifikation_ids)} "
            f"Mailarten freigegeben; durch {request.state.benutzer['name']}"
        ),
    ))
    await session.commit()
    return {"status": "gespeichert", "freigegeben": len(ausgewaehlt)}


@app.put("/klassifikationen/{klassifikation_id}")
async def klassifikation_aktualisieren(
    klassifikation_id: str,
    aenderung: KlassifikationAenderung,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    _admin_erfordern(request)
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

    session.add(Aktionslog(
        mail_id=None,
        ereignis="klassifikation_geaendert",
        ausgeloest_von=request.state.benutzer["name"],
        detail=f"{klassifikation_id}: Ziel und Aufgabenplan aktualisiert",
    ))
    await session.commit()
    return {"status": "gespeichert"}


@app.post("/mails/{mail_id}/bestaetigen")
async def mail_bestaetigen(
    mail_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    mail = await session.get(Mail, mail_id)
    await _mailzugriff_erfordern(session, request, mail)
    ergebnis = await bestaetigung_erfassen(
        mail_id, request.state.benutzer["name"]
    )
    if ergebnis["status"] == "mail_nicht_gefunden":
        raise HTTPException(status_code=404, detail="Mail nicht gefunden")
    if ergebnis["status"] == "keine_bestaetigung_offen":
        raise HTTPException(status_code=409, detail="Für diese Mail wartet keine Bestätigung")
    return ergebnis


@app.post("/mails/{mail_id}/erledigen")
async def mail_erledigen(
    mail_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """Entfernt eine Mail nur aus der Krautl-Arbeitsliste, nicht aus IMAP."""
    mail = (await session.execute(
        select(Mail).where(Mail.id == mail_id).with_for_update()
    )).scalar_one_or_none()
    await _mailzugriff_erfordern(session, request, mail)
    if not mail.im_krautl_posteingang:
        raise HTTPException(status_code=409, detail="Mail ist bereits erledigt")

    jetzt = datetime.now(timezone.utc)
    mail.im_krautl_posteingang = False
    await session.execute(
        update(MailAufgabe)
        .where(
            MailAufgabe.mail_id == mail.id,
            MailAufgabe.status.in_(["wartet", "blockiert"]),
        )
        .values(
            status="abgebrochen",
            fehler="Mail manuell in Krautl erledigt",
            erledigt_am=jetzt,
        )
    )
    session.add(Aktionslog(
        mail_id=mail.id,
        ereignis="mail_manuell_erledigt",
        ausgeloest_von=request.state.benutzer["name"],
        detail=(
            "Aus Krautl-Posteingang entfernt; Mail im IMAP-Postfach "
            f"unverändert; durch {request.state.benutzer['name']}"
        ),
    ))
    await session.commit()
    return {"status": "erledigt", "imap_unveraendert": True}


@app.delete("/mails/{mail_id}")
async def mail_loeschen(
    mail_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    mail = (await session.execute(
        select(Mail).where(Mail.id == mail_id).with_for_update()
    )).scalar_one_or_none()
    await _mailzugriff_erfordern(session, request, mail)
    if not mail.im_krautl_posteingang:
        raise HTTPException(status_code=409, detail="Mail ist nicht mehr im Krautl-Posteingang")

    postfach = await session.get(Postfach, mail.postfach_id)
    configs = {config.user.casefold(): config for config in lade_postfaecher()}
    config = configs.get(postfach.adresse.casefold()) if postfach else None
    imap_fehler = None
    if config is None or mail.imap_uid is None:
        imap_fehler = "Quellpostfach oder IMAP-UID ist nicht konfiguriert"
    else:
        try:
            await asyncio.to_thread(
                mail_imap_loeschen, config, mail.imap_uid, mail.message_id
            )
        except Exception as exc:
            imap_fehler = str(exc)

    jetzt = datetime.now(timezone.utc)
    mail.im_krautl_posteingang = False
    await session.execute(
        update(MailAufgabe)
        .where(
            MailAufgabe.mail_id == mail.id,
            MailAufgabe.status.in_(["wartet", "blockiert"]),
        )
        .values(
            status="abgebrochen",
            fehler=(
                "Mail manuell gelöscht"
                if imap_fehler is None
                else "IMAP-Löschversuch fehlgeschlagen; manuell aus Krautl entfernt"
            ),
            erledigt_am=jetzt,
        )
    )
    postfachname = postfach.adresse if postfach else "unbekanntes Postfach"
    session.add(Aktionslog(
        mail_id=mail.id,
        ereignis=(
            "mail_geloescht" if imap_fehler is None
            else "mail_loeschen_fehlgeschlagen"
        ),
        ausgeloest_von=request.state.benutzer["name"],
        detail=(
            f"Dauerhaft aus {postfachname}/INBOX gelöscht; "
            f"durch {request.state.benutzer['name']}"
            if imap_fehler is None
            else (
                f"Löschversuch in {postfachname}/INBOX fehlgeschlagen: "
                f"{imap_fehler}; trotzdem aus Krautl-Posteingang entfernt; "
                f"durch {request.state.benutzer['name']}"
            )
        ),
    ))
    await session.commit()
    if imap_fehler is not None:
        return {
            "status": "ausgeblendet",
            "imap_geloescht": False,
            "detail": imap_fehler,
        }
    return {"status": "geloescht", "imap_geloescht": True}


@app.get("/aktionslog")
async def liste_aktionslog(request: Request, session: AsyncSession = Depends(get_session)):
    _admin_erfordern(request)
    result = await session.execute(
        select(Aktionslog).order_by(Aktionslog.erstellt_am.desc()).limit(200)
    )
    return result.scalars().all()


@app.post("/mails/{mail_id}/korrektur")
async def korrigiere_klassifikation(
    mail_id: int, request: Request, neue_klassifikation_id: str, notiz: str | None = None,
    session: AsyncSession = Depends(get_session),
):
    mail = await session.get(Mail, mail_id)
    await _mailzugriff_erfordern(session, request, mail)
    if not await session.get(Klassifikation, neue_klassifikation_id):
        raise HTTPException(status_code=404, detail="Klassifikation nicht gefunden")
    if not await darf_klassifikation_sehen(
        session, request.state.benutzer, neue_klassifikation_id
    ):
        raise HTTPException(status_code=403, detail="Kein Zugriff auf die neue Mailart")
    korrektur = Korrektur(
        mail_id=mail_id,
        alte_klassifikation_id=mail.klassifikation_id,
        neue_klassifikation_id=neue_klassifikation_id,
        notiz=notiz,
    )
    alte_klassifikation_id = mail.klassifikation_id
    mail.klassifikation_id = neue_klassifikation_id
    mail.pruefstatus = "geprueft"
    session.add(korrektur)
    await session.execute(delete(MailAufgabe).where(MailAufgabe.mail_id == mail_id))
    await session.flush()
    await aufgaben_fuer_mail_anlegen(session, mail)
    session.add(Aktionslog(
        mail_id=mail.id,
        ereignis="klassifikation_korrigiert",
        ausgeloest_von=request.state.benutzer["name"],
        detail=(
            f"{alte_klassifikation_id or 'UNKLASSIFIZIERT'} → "
            f"{neue_klassifikation_id}"
        ),
    ))
    await session.commit()
    await wartende_aufgaben_ausfuehren(
        mail_id, ausgeloest_von=request.state.benutzer["name"]
    )
    return {"status": "ok"}


@app.get("/rechnungen")
async def liste_rechnungen(request: Request, session: AsyncSession = Depends(get_session)):
    verweigert = await verweigerte_klassifikationen(session, request.state.benutzer)
    if "*" in verweigert:
        return []
    abfrage = select(
        Rechnung,
        Mail.empfangen_am.label("eingegangen_am"),
    ).outerjoin(Mail, Rechnung.mail_id == Mail.id).order_by(
        Mail.empfangen_am.desc().nulls_last(),
        Rechnung.id.desc(),
    )
    if not ist_admin(request.state.benutzer):
        abfrage = abfrage.where(Rechnung.mail_id.is_not(None))
    if verweigert:
        abfrage = abfrage.where(or_(
            Mail.klassifikation_id.is_(None),
            ~Mail.klassifikation_id.in_(verweigert),
        ))
    result = await session.execute(abfrage)
    return [
        {
            **{
                spalte.name: getattr(rechnung, spalte.name)
                for spalte in Rechnung.__table__.columns
            },
            "eingegangen_am": eingegangen_am,
        }
        for rechnung, eingegangen_am in result.all()
    ]


@app.put("/rechnungen/{rechnung_id}/zahlungsstatus")
async def rechnungsstatus_aendern(
    rechnung_id: int,
    aenderung: RechnungsstatusAenderung,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    erlaubte_stati = {"offen", "automatisch", "bezahlt", "gutschrift", "unklar"}
    if aenderung.zahlungsstatus not in erlaubte_stati:
        raise HTTPException(status_code=422, detail="Unbekannter Zahlungsstatus")
    rechnung = await session.get(Rechnung, rechnung_id)
    if rechnung is None:
        raise HTTPException(status_code=404, detail="Rechnung nicht gefunden")
    if rechnung.mail_id:
        await _mailzugriff_erfordern(
            session, request, await session.get(Mail, rechnung.mail_id)
        )
    elif not ist_admin(request.state.benutzer):
        raise HTTPException(status_code=403, detail="Kein Zugriff auf diese Rechnung")
    vorher = rechnung.zahlungsstatus
    rechnung.zahlungsstatus = aenderung.zahlungsstatus
    session.add(Aktionslog(
        mail_id=rechnung.mail_id,
        ereignis="rechnungsstatus_geaendert",
        ausgeloest_von=request.state.benutzer["name"],
        detail=(
            f"Rechnung {rechnung.rechnungsnummer or rechnung.id}: {vorher} → "
            f"{aenderung.zahlungsstatus}; durch {request.state.benutzer['name']}"
        ),
    ))
    await session.commit()
    return rechnung


@app.get("/rechnungen/{rechnung_id}/datei")
async def rechnungsdatei_ansehen(
    rechnung_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    rechnung = await session.get(Rechnung, rechnung_id)
    if rechnung is None:
        raise HTTPException(status_code=404, detail="Rechnung nicht gefunden")
    mail = await session.get(Mail, rechnung.mail_id) if rechnung.mail_id else None
    if mail:
        await _mailzugriff_erfordern(session, request, mail)
    elif not ist_admin(request.state.benutzer):
        raise HTTPException(status_code=403, detail="Kein Zugriff auf diese Rechnung")
    if mail is None:
        raise HTTPException(
            status_code=404,
            detail="Zu dieser Rechnung ist keine Ursprungsmail mehr hinterlegt",
        )
    quellpostfach = await session.get(Postfach, mail.postfach_id) if mail else None
    klassifikation = (
        await session.get(Klassifikation, mail.klassifikation_id)
        if mail and mail.klassifikation_id else None
    )
    verschiebe_aufgabe = (await session.execute(
        select(MailAufgabe).where(
            MailAufgabe.mail_id == mail.id,
            MailAufgabe.aufgabe_typ == "MAIL_VERSCHIEBEN",
        ).order_by(MailAufgabe.position.desc())
    )).scalars().first() if mail else None
    verschiebe_parameter = verschiebe_aufgabe.parameter if verschiebe_aufgabe else {}
    verschiebe_parameter = verschiebe_parameter or {}
    zielpostfach = (
        verschiebe_parameter.get("zielpostfach")
        or (klassifikation.zielpostfach if klassifikation else None)
    )
    zielordner = (
        verschiebe_parameter.get("zielordner")
        or (klassifikation.zielordner if klassifikation else None)
    )

    try:
        dateiname, inhalt = await rechnungsdatei_aus_mail_laden(
            rechnung,
            mail,
            quellpostfach.adresse if quellpostfach else None,
            zielpostfach,
            zielordner,
        )
    except RuntimeError as exc:
        logger.exception(
            "Rechnungsdatei %s nicht aus der zugehörigen Mail abrufbar: %s",
            rechnung_id,
            exc,
        )
        raise HTTPException(
            status_code=404,
            detail=(
                "Die Rechnungsdatei konnte nicht aus der zugehörigen Mail "
                "geladen werden. Die Mail wurde möglicherweise inzwischen "
                "verschoben oder gelöscht."
            ),
        ) from exc

    medientyp = mimetypes.guess_type(dateiname)[0] or "application/octet-stream"
    return Response(
        content=inhalt,
        media_type=medientyp,
        headers={
            "Content-Disposition": (
                "inline; filename*=UTF-8''" + quote(dateiname, safe="")
            ),
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@app.post("/rechnungen/{rechnung_id}/als-bezahlt")
async def rechnung_als_bezahlt(
    rechnung_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    rechnung = await session.get(Rechnung, rechnung_id)
    if rechnung is None:
        raise HTTPException(status_code=404, detail="Rechnung nicht gefunden")
    if rechnung.mail_id:
        await _mailzugriff_erfordern(
            session, request, await session.get(Mail, rechnung.mail_id)
        )
    elif not ist_admin(request.state.benutzer):
        raise HTTPException(status_code=403, detail="Kein Zugriff auf diese Rechnung")
    rechnung.zahlungsstatus = "bezahlt"
    session.add(Aktionslog(
        mail_id=rechnung.mail_id,
        ereignis="rechnungsstatus_geaendert",
        ausgeloest_von=request.state.benutzer["name"],
        detail=f"Rechnung {rechnung.rechnungsnummer or rechnung.id}: als bezahlt markiert",
    ))
    await session.commit()
    return {"status": "ok"}


@app.get("/faq")
async def liste_faq(session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(FaqEintrag).order_by(
        FaqEintrag.produkt_id, FaqEintrag.sortierung, FaqEintrag.id
    ))
    return result.scalars().all()


@app.get("/wissensbasis")
async def wissensbasis_laden(session: AsyncSession = Depends(get_session)):
    familien = (await session.execute(
        select(Produktfamilie).order_by(Produktfamilie.name)
    )).scalars().all()
    produkte = (await session.execute(
        select(Produkt).order_by(Produkt.name)
    )).scalars().all()
    eintraege = (await session.execute(
        select(Wissenseintrag).order_by(Wissenseintrag.wissensart, Wissenseintrag.titel)
    )).scalars().all()
    return {"familien": familien, "produkte": produkte, "eintraege": eintraege}


async def _familie_holen_oder_anlegen(session, name: str | None):
    name = (name or "").strip()
    if not name:
        return None
    familie = (await session.execute(
        select(Produktfamilie).where(func.lower(Produktfamilie.name) == name.lower())
    )).scalar_one_or_none()
    if familie is None:
        familie = Produktfamilie(name=name, aktiv=True)
        session.add(familie)
        await session.flush()
    return familie


@app.post("/produkte")
async def produkt_anlegen(aenderung: ProduktAenderung, session: AsyncSession = Depends(get_session)):
    familie = await _familie_holen_oder_anlegen(session, aenderung.familie)
    produkt = Produkt(
        produktfamilie_id=familie.id if familie else None,
        name=aenderung.name.strip(), artikelnummer=(aenderung.artikelnummer or "").strip() or None,
        aliases=[a.strip() for a in aenderung.aliases if a.strip()],
        website_url=(aenderung.website_url or "").strip() or None, aktiv=aenderung.aktiv,
    )
    if not produkt.name:
        raise HTTPException(status_code=422, detail="Produktname fehlt")
    session.add(produkt)
    await session.commit()
    await session.refresh(produkt)
    return produkt


@app.post("/produkte/shop-import")
async def produkte_aus_shop_importieren(session: AsyncSession = Depends(get_session)):
    try:
        katalog = await asyncio.to_thread(shop_katalog_laden)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Produktbestand konnte nicht aus dem Shop gelesen werden: {exc}",
        ) from exc
    return await shop_katalog_speichern(session, katalog)


@app.put("/produkte/{produkt_id}")
async def produkt_aktualisieren(
    produkt_id: int, aenderung: ProduktAenderung, session: AsyncSession = Depends(get_session)
):
    produkt = await session.get(Produkt, produkt_id)
    if produkt is None:
        raise HTTPException(status_code=404, detail="Produkt nicht gefunden")
    if not aenderung.name.strip():
        raise HTTPException(status_code=422, detail="Produktname fehlt")
    familie = await _familie_holen_oder_anlegen(session, aenderung.familie)
    produkt.produktfamilie_id = familie.id if familie else None
    produkt.name = aenderung.name.strip()
    produkt.artikelnummer = (aenderung.artikelnummer or "").strip() or None
    produkt.aliases = [a.strip() for a in aenderung.aliases if a.strip()]
    produkt.website_url = (aenderung.website_url or "").strip() or None
    produkt.aktiv = aenderung.aktiv
    await session.commit()
    return produkt


def _wissen_validieren(aenderung: WissenAenderung):
    if aenderung.wissensart not in WISSENSARTEN:
        raise HTTPException(status_code=422, detail="Unbekannte Wissensart")
    if aenderung.status not in WISSENSSTATUS:
        raise HTTPException(status_code=422, detail="Unbekannter Wissensstatus")
    if not aenderung.titel.strip() or not aenderung.inhalt.strip():
        raise HTTPException(status_code=422, detail="Titel und Inhalt sind erforderlich")


async def _wissen_daten(session, aenderung: WissenAenderung) -> dict:
    """Normalisiert den Geltungsbereich, damit widersprüchliche Zuordnungen
    nicht unbemerkt in der Wissensbasis landen."""
    _wissen_validieren(aenderung)
    daten = aenderung.model_dump()
    if aenderung.wissensart in {"allgemein", "ablauf"}:
        daten["produkt_id"] = None
        daten["produktfamilie_id"] = None
    elif aenderung.wissensart == "produktfamilie":
        if not aenderung.produktfamilie_id or not await session.get(
            Produktfamilie, aenderung.produktfamilie_id
        ):
            raise HTTPException(status_code=422, detail="Produktfamilie fehlt")
        daten["produkt_id"] = None
    elif aenderung.wissensart == "produkt":
        if not aenderung.produkt_id or not await session.get(Produkt, aenderung.produkt_id):
            raise HTTPException(status_code=422, detail="Produkt fehlt")
        daten["produktfamilie_id"] = None
    return daten


@app.post("/wissen")
async def wissen_anlegen(aenderung: WissenAenderung, session: AsyncSession = Depends(get_session)):
    eintrag = Wissenseintrag(**await _wissen_daten(session, aenderung))
    session.add(eintrag)
    await session.commit()
    await session.refresh(eintrag)
    return eintrag


@app.put("/wissen/{eintrag_id}")
async def wissen_aktualisieren(
    eintrag_id: int, aenderung: WissenAenderung, session: AsyncSession = Depends(get_session)
):
    daten = await _wissen_daten(session, aenderung)
    eintrag = await session.get(Wissenseintrag, eintrag_id)
    if eintrag is None:
        raise HTTPException(status_code=404, detail="Wissenseintrag nicht gefunden")
    for name, wert in daten.items():
        setattr(eintrag, name, wert)
    await session.commit()
    return eintrag


def _faq_validieren(aenderung: FaqAenderung):
    if aenderung.status not in FAQ_STATUS:
        raise HTTPException(status_code=422, detail="Unbekannter FAQ-Status")
    if not aenderung.kategorie.strip() or not aenderung.frage.strip() or not aenderung.antwort.strip():
        raise HTTPException(status_code=422, detail="Kategorie, Frage und Antwort sind erforderlich")


async def _faq_daten(session, aenderung: FaqAenderung) -> dict:
    _faq_validieren(aenderung)
    if aenderung.produkt_id and not await session.get(Produkt, aenderung.produkt_id):
        raise HTTPException(status_code=422, detail="Produkt nicht gefunden")
    return aenderung.model_dump()


@app.post("/faq")
async def faq_anlegen(aenderung: FaqAenderung, session: AsyncSession = Depends(get_session)):
    eintrag = FaqEintrag(**await _faq_daten(session, aenderung))
    session.add(eintrag)
    await session.commit()
    await session.refresh(eintrag)
    return eintrag


@app.put("/faq-rubriken")
async def faq_rubrik_umbenennen(
    aenderung: FaqRubrikAenderung, session: AsyncSession = Depends(get_session)
):
    alte_kategorie = aenderung.alte_kategorie.strip()
    neue_kategorie = aenderung.neue_kategorie.strip()
    if not alte_kategorie or not neue_kategorie:
        raise HTTPException(status_code=422, detail="Alter und neuer Rubrikname sind erforderlich")
    if aenderung.produkt_id is not None and not await session.get(Produkt, aenderung.produkt_id):
        raise HTTPException(status_code=422, detail="Produkt nicht gefunden")

    produkt_bedingung = (
        FaqEintrag.produkt_id == aenderung.produkt_id
        if aenderung.produkt_id is not None
        else FaqEintrag.produkt_id.is_(None)
    )
    ergebnis = await session.execute(
        update(FaqEintrag)
        .where(produkt_bedingung, FaqEintrag.kategorie == alte_kategorie)
        .values(kategorie=neue_kategorie)
    )
    if not ergebnis.rowcount:
        raise HTTPException(status_code=404, detail="FAQ-Rubrik nicht gefunden")
    await session.commit()
    return {"kategorie": neue_kategorie, "aktualisiert": ergebnis.rowcount}


@app.put("/faq/{faq_id}")
async def faq_aktualisieren(
    faq_id: int, aenderung: FaqAenderung, session: AsyncSession = Depends(get_session)
):
    daten = await _faq_daten(session, aenderung)
    eintrag = await session.get(FaqEintrag, faq_id)
    if eintrag is None:
        raise HTTPException(status_code=404, detail="FAQ-Eintrag nicht gefunden")
    for name, wert in daten.items():
        setattr(eintrag, name, wert)
    await session.commit()
    return eintrag


@app.get("/produkte/{produkt_id}/faq-export")
async def faq_export(produkt_id: int, session: AsyncSession = Depends(get_session)):
    produkt = await session.get(Produkt, produkt_id)
    if produkt is None:
        raise HTTPException(status_code=404, detail="Produkt nicht gefunden")
    faq = (await session.execute(select(FaqEintrag).where(
        FaqEintrag.produkt_id == produkt_id,
        FaqEintrag.aktiv.is_(True),
        FaqEintrag.status.in_(["entwurf", "freigegeben"]),
    ))).scalars().all()
    entwuerfe = sum(eintrag.status == "entwurf" for eintrag in faq)
    return {
        "produkt": produkt.name,
        "html": faq_als_jtl_html(produkt, faq),
        "anzahl": len(faq),
        "entwuerfe": entwuerfe,
    }


@app.get("/wissensvorschlaege")
async def wissensvorschlaege_laden(
    request: Request, session: AsyncSession = Depends(get_session)
):
    verweigert = await verweigerte_klassifikationen(session, request.state.benutzer)
    if "*" in verweigert:
        return []
    abfrage = select(WissensVorschlag).join(
        Mail, WissensVorschlag.quelle_mail_id == Mail.id
    ).where(
        WissensVorschlag.status == "offen"
    ).order_by(WissensVorschlag.erstellt_am.desc())
    if verweigert:
        abfrage = abfrage.where(or_(
            Mail.klassifikation_id.is_(None),
            ~Mail.klassifikation_id.in_(verweigert),
        ))
    return (await session.execute(abfrage)).scalars().all()


@app.post("/wissensvorschlaege/{vorschlag_id}/uebernehmen")
async def wissensvorschlag_uebernehmen(
    vorschlag_id: int, aenderung: VorschlagUebernahme,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    vorschlag = await session.get(WissensVorschlag, vorschlag_id)
    if vorschlag is None:
        raise HTTPException(status_code=404, detail="Vorschlag nicht gefunden")
    await _mailzugriff_erfordern(
        session, request, await session.get(Mail, vorschlag.quelle_mail_id)
    )
    if vorschlag.status != "offen":
        raise HTTPException(status_code=409, detail="Vorschlag wurde bereits bearbeitet")
    if aenderung.ziel not in {"wissen", "faq"}:
        raise HTTPException(status_code=422, detail="Unbekanntes Vorschlagsziel")
    if not aenderung.titel.strip() or not aenderung.inhalt.strip():
        raise HTTPException(status_code=422, detail="Titel und Inhalt sind erforderlich")
    if aenderung.ziel == "faq":
        if not aenderung.kategorie.strip():
            raise HTTPException(status_code=422, detail="FAQ-Kategorie fehlt")
        if aenderung.produkt_id and not await session.get(Produkt, aenderung.produkt_id):
            raise HTTPException(status_code=422, detail="Produkt nicht gefunden")
        session.add(FaqEintrag(
            produkt_id=aenderung.produkt_id, kategorie=aenderung.kategorie.strip(),
            frage=aenderung.titel.strip(), antwort=aenderung.inhalt.strip(),
            quelle=f"Kundenmail #{vorschlag.quelle_mail_id}", status="entwurf", aktiv=True,
        ))
    else:
        if aenderung.wissensart not in WISSENSARTEN:
            raise HTTPException(status_code=422, detail="Unbekannte Wissensart")
        produkt = await session.get(Produkt, aenderung.produkt_id) if aenderung.produkt_id else None
        produkt_id = produkt.id if produkt and aenderung.wissensart == "produkt" else None
        familie_id = (
            produkt.produktfamilie_id
            if produkt and aenderung.wissensart == "produktfamilie"
            else None
        )
        session.add(Wissenseintrag(
            wissensart=aenderung.wissensart,
            produkt_id=produkt_id,
            produktfamilie_id=familie_id,
            titel=aenderung.titel.strip(), inhalt=aenderung.inhalt.strip(),
            quelle=f"Kundenmail #{vorschlag.quelle_mail_id}", status="entwurf",
        ))
    vorschlag.status = "uebernommen"
    await session.commit()
    return {"status": "uebernommen"}


@app.post("/wissensvorschlaege/{vorschlag_id}/verwerfen")
async def wissensvorschlag_verwerfen(
    vorschlag_id: int, request: Request, session: AsyncSession = Depends(get_session)
):
    vorschlag = await session.get(WissensVorschlag, vorschlag_id)
    if vorschlag is None:
        raise HTTPException(status_code=404, detail="Vorschlag nicht gefunden")
    await _mailzugriff_erfordern(
        session, request, await session.get(Mail, vorschlag.quelle_mail_id)
    )
    vorschlag.status = "verworfen"
    await session.commit()
    return {"status": "verworfen"}


@app.get("/faq/vorschlaege")
async def liste_faq_vorschlaege(
    request: Request, session: AsyncSession = Depends(get_session)
):
    verweigert = await verweigerte_klassifikationen(session, request.state.benutzer)
    if "*" in verweigert:
        return []
    abfrage = select(FaqVorschlag).join(
        Mail, FaqVorschlag.quelle_mail_id == Mail.id
    ).where(FaqVorschlag.status == "offen")
    if verweigert:
        abfrage = abfrage.where(or_(
            Mail.klassifikation_id.is_(None),
            ~Mail.klassifikation_id.in_(verweigert),
        ))
    result = await session.execute(abfrage)
    return result.scalars().all()


@app.post("/faq/vorschlaege/{vorschlag_id}/uebernehmen")
async def faq_vorschlag_uebernehmen(
    vorschlag_id: int, request: Request, session: AsyncSession = Depends(get_session)
):
    vorschlag = await session.get(FaqVorschlag, vorschlag_id)
    if vorschlag is None:
        raise HTTPException(status_code=404, detail="Vorschlag nicht gefunden")
    await _mailzugriff_erfordern(
        session, request, await session.get(Mail, vorschlag.quelle_mail_id)
    )
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
async def faq_vorschlag_verwerfen(
    vorschlag_id: int, request: Request, session: AsyncSession = Depends(get_session)
):
    vorschlag = await session.get(FaqVorschlag, vorschlag_id)
    if vorschlag is None:
        raise HTTPException(status_code=404, detail="Vorschlag nicht gefunden")
    await _mailzugriff_erfordern(
        session, request, await session.get(Mail, vorschlag.quelle_mail_id)
    )
    vorschlag.status = "verworfen"
    await session.commit()
    return {"status": "verworfen"}


@app.get("/entwuerfe")
async def liste_entwuerfe(request: Request, session: AsyncSession = Depends(get_session)):
    verweigert = await verweigerte_klassifikationen(session, request.state.benutzer)
    if "*" in verweigert:
        return []
    abfrage = select(Entwurf).join(Mail, Entwurf.mail_id == Mail.id).where(
        Entwurf.status == "wartet",
        Mail.im_krautl_posteingang.is_(True),
    )
    if verweigert:
        abfrage = abfrage.where(or_(
            Mail.klassifikation_id.is_(None),
            ~Mail.klassifikation_id.in_(verweigert),
        ))
    result = await session.execute(abfrage)
    return result.scalars().all()


@app.post("/mails/{mail_id}/antwortentwurf")
async def mail_antwortentwurf_erzeugen(
    mail_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    mail = await session.get(Mail, mail_id)
    await _mailzugriff_erfordern(session, request, mail)

    try:
        entwurf, erzeugt = await antwortentwurf_speichern(session, mail)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Antwortvorschlag konnte nicht erzeugt werden: {exc}",
        ) from exc

    session.add(Aktionslog(
        mail_id=mail.id,
        ereignis="antwortvorschlag_erstellt",
        ausgeloest_von=request.state.benutzer["name"],
        detail=(
            f"Entwurf #{entwurf.id} manuell angefordert"
            if erzeugt else f"Vorhandenen Entwurf #{entwurf.id} aufgerufen"
        ),
    ))
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
    mail = await session.get(Mail, entwurf.mail_id)
    await _mailzugriff_erfordern(session, request, mail)
    if entwurf.status == "versendet":
        return {
            "status": "bereits_versendet",
            "empfaenger": TEST_EMPFAENGER,
        }

    finaler_text = freigabe.finaler_text.strip()
    if not finaler_text:
        raise HTTPException(status_code=422, detail="Die Antwort ist leer")
    _produkt, _wissen, faq = await relevante_wissensbasis(session, mail)

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
            pruefung = await antwort_vor_versand_pruefen(
                mail, finaler_text, faq, _wissen
            )
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
                ausgeloest_von=request.state.benutzer["name"],
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
            ausgeloest_von=request.state.benutzer["name"],
            detail=(
                "Nach zwei KI-Blockierungen auf ausdrücklichen dritten "
                f"Freigabeversuch durch {request.state.benutzer['name']} verzichtet"
            ),
        ))

    try:
        versandergebnis = await testantwort_senden(
            mail, finaler_text, request.state.benutzer
        )
    except Exception as exc:
        session.add(Aktionslog(
            mail_id=mail.id,
            ereignis="antwort_versand_fehlgeschlagen",
            ausgeloest_von=request.state.benutzer["name"],
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
        ausgeloest_von=request.state.benutzer["name"],
        detail=(
            f"Durch {request.state.benutzer['name']} "
            f"{'ohne weitere KI-Prüfung ' if pruefung_uebersprungen else 'nach KI-Prüfung '}"
            f"ausschließlich an den Mailserver für {TEST_EMPFAENGER} übergeben; "
            f"Message-ID {versandergebnis['message_id']}"
        ),
    ))
    try:
        vorschlag = await wissenszuwachs_nach_antwort_pruefen(
            session, mail, entwurf, finaler_text
        )
        if vorschlag is not None:
            session.add(Aktionslog(
                mail_id=mail.id,
                ereignis="wissensvorschlag_erstellt",
                ausgeloest_von=request.state.benutzer["name"],
                detail=(
                    f"Nach Antwortfreigabe Vorschlag #{vorschlag.id} "
                    f"für {vorschlag.ziel} erstellt"
                ),
            ))
    except Exception as exc:
        # Der Versand ist zu diesem Zeitpunkt bereits erfolgt. Eine optionale
        # Wissensprüfung darf ihn weder zurücknehmen noch als Fehler darstellen.
        session.add(Aktionslog(
            mail_id=mail.id,
            ereignis="wissenspruefung_fehlgeschlagen",
            ausgeloest_von=request.state.benutzer["name"],
            detail=f"Antwort wurde versendet; Wissensprüfung nicht möglich: {exc}",
        ))
    await session.commit()
    return {
        "status": "versendet",
        "empfaenger": TEST_EMPFAENGER,
        "message_id": versandergebnis["message_id"],
        "pruefung_uebersprungen": pruefung_uebersprungen,
    }


@app.post("/entwuerfe/{entwurf_id}/verwerfen")
async def entwurf_verwerfen(
    entwurf_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    entwurf = await session.get(Entwurf, entwurf_id)
    if entwurf is None:
        raise HTTPException(status_code=404, detail="Entwurf nicht gefunden")
    mail = await session.get(Mail, entwurf.mail_id)
    await _mailzugriff_erfordern(session, request, mail)
    entwurf.status = "verworfen"
    session.add(Aktionslog(
        mail_id=mail.id,
        ereignis="antwortvorschlag_verworfen",
        ausgeloest_von=request.state.benutzer["name"],
        detail=f"Entwurf #{entwurf.id} verworfen",
    ))
    await session.commit()
    return {"status": "verworfen"}
