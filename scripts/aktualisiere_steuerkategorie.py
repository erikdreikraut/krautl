"""Legt die Steuerkategorie und ihren Aufgabenplan idempotent an.

Einmal nach dem Deployment ausführen:
    docker compose exec app python -m scripts.aktualisiere_steuerkategorie
"""
import asyncio

from sqlalchemy import delete, func, or_, select, update

from app.db import SessionLocal
from app.models import (
    Klassifikation, KlassifikationAufgabe, Mail, MailAufgabe,
)


KLASSIFIKATION_ID = "RECHT_STEUERN"
ZIELPOSTFACH = "erik@dreikraut.de"
ZIELORDNER = "Steuern"
BESCHREIBUNG = (
    "Steuerberatung, Finanzbuchhaltung, Umsatzsteuer, Voranmeldungen, "
    "Steuererklärungen, Steuerbescheide, steuerliche Fristen und "
    "Korrespondenz mit Finanzämtern. Alle Mails von CountX und vom "
    "Steuerberater Kineke gehören hierher."
)


def _bekannter_steuerabsender():
    name = func.lower(Mail.absender_name)
    adresse = func.lower(Mail.absender_adresse)
    return or_(
        name.like("%countx%"),
        adresse.like("%countx%"),
        name.like("%kineke%"),
        adresse.like("%kineke%"),
    )


async def _vorlagen_ersetzen(session) -> None:
    alte_ids = (await session.execute(
        select(KlassifikationAufgabe.id).where(
            KlassifikationAufgabe.klassifikation_id == KLASSIFIKATION_ID
        )
    )).scalars().all()
    if alte_ids:
        await session.execute(
            update(MailAufgabe)
            .where(MailAufgabe.klassifikation_aufgabe_id.in_(alte_ids))
            .values(klassifikation_aufgabe_id=None)
        )
    await session.execute(delete(KlassifikationAufgabe).where(
        KlassifikationAufgabe.klassifikation_id == KLASSIFIKATION_ID
    ))
    for position, aufgabe_typ in enumerate((
        "BESTAETIGUNG_EINHOLEN", "MAIL_VERSCHIEBEN"
    ), start=1):
        session.add(KlassifikationAufgabe(
            klassifikation_id=KLASSIFIKATION_ID,
            position=position,
            aufgabe_typ=aufgabe_typ,
            parameter={
                "zielpostfach": ZIELPOSTFACH,
                "zielordner": ZIELORDNER,
            },
            bestaetiger_typ="alle",
        ))


async def aktualisiere(session) -> dict:
    klassifikation = await session.get(Klassifikation, KLASSIFIKATION_ID)
    if klassifikation is None:
        klassifikation = Klassifikation(klassifikation_id=KLASSIFIKATION_ID)
        session.add(klassifikation)
    klassifikation.hauptkategorie = "Recht und Behörden"
    klassifikation.unterkategorie = "Steuern"
    klassifikation.beschreibung = BESCHREIBUNG
    klassifikation.standard_prio = "hoch"
    klassifikation.zielpostfach = ZIELPOSTFACH
    klassifikation.zielordner = ZIELORDNER
    klassifikation.aktion_id = "BESTAETIGUNG_EINHOLEN"
    await session.flush()
    await _vorlagen_ersetzen(session)

    offene_mails = (await session.execute(select(Mail).where(
        Mail.im_krautl_posteingang.is_(True),
        or_(
            Mail.klassifikation_id.is_(None),
            Mail.klassifikation_id != KLASSIFIKATION_ID,
        ),
        _bekannter_steuerabsender(),
    ))).scalars().all()
    for mail in offene_mails:
        await session.execute(delete(MailAufgabe).where(
            MailAufgabe.mail_id == mail.id
        ))
        mail.klassifikation_id = KLASSIFIKATION_ID
        session.add_all([
            MailAufgabe(
                mail_id=mail.id,
                position=1,
                aufgabe_typ="BESTAETIGUNG_EINHOLEN",
                parameter={
                    "zielpostfach": ZIELPOSTFACH,
                    "zielordner": ZIELORDNER,
                },
                status="wartet",
                bestaetiger_typ="alle",
            ),
            MailAufgabe(
                mail_id=mail.id,
                position=2,
                aufgabe_typ="MAIL_VERSCHIEBEN",
                parameter={
                    "zielpostfach": ZIELPOSTFACH,
                    "zielordner": ZIELORDNER,
                },
                status="blockiert",
                bestaetiger_typ="alle",
            ),
        ])

    await session.commit()
    return {"umgestellte_offene_mails": len(offene_mails)}


async def main() -> None:
    async with SessionLocal() as session:
        ergebnis = await aktualisiere(session)
    print(
        f"{KLASSIFIKATION_ID} angelegt oder aktualisiert. "
        f"{ergebnis['umgestellte_offene_mails']} offene Bestandsmail(s) umgestellt."
    )


if __name__ == "__main__":
    asyncio.run(main())
