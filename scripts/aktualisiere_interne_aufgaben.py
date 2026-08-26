"""Legt die Kategorie INTERN_AUFGABEN gezielt und idempotent an.

Einmal nach dem Deployment ausführen:
    docker compose exec app python -m scripts.aktualisiere_interne_aufgaben

Noch sichtbare, eindeutig passende Mails werden ebenfalls umklassifiziert.
"""

import asyncio

from sqlalchemy import delete, or_, select, update

from app.db import SessionLocal
from app.interne_aufgaben import ist_interne_aufgabenmail
from app.models import Klassifikation, KlassifikationAufgabe, Mail, MailAufgabe


KLASSIFIKATION_ID = "INTERN_AUFGABEN"
ZIELPOSTFACH = "service@dreikraut.de"
ZIELORDNER = "Erledigt"
BESCHREIBUNG = (
    "Automatisch von einem dreikraut-System erzeugter interner Aufgabenhinweis "
    "zu Lagerbeständen, Bestandswarnungen, Fehlbeständen oder möglichen Fehlern "
    "in Kunden- beziehungsweise Lieferadressen. Nur verwenden, wenn die "
    "tatsächliche Absenderadresse zur Domain dreikraut.de gehört. Andere interne "
    "Korrespondenz und externe Hinweise mit bloßer dreikraut-Erwähnung gehören "
    "nicht in diese Kategorie."
)


async def _aufgabenvorlagen_ersetzen(session) -> None:
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
    session.add_all([
        KlassifikationAufgabe(
            klassifikation_id=KLASSIFIKATION_ID,
            position=1,
            aufgabe_typ="BESTAETIGUNG_EINHOLEN",
            parameter={"zielpostfach": ZIELPOSTFACH, "zielordner": ZIELORDNER},
            bestaetiger_typ="alle",
        ),
        KlassifikationAufgabe(
            klassifikation_id=KLASSIFIKATION_ID,
            position=2,
            aufgabe_typ="MAIL_VERSCHIEBEN",
            parameter={"zielpostfach": ZIELPOSTFACH, "zielordner": ZIELORDNER},
            bestaetiger_typ="alle",
        ),
    ])


async def aktualisiere(session) -> dict:
    klassifikation = await session.get(Klassifikation, KLASSIFIKATION_ID)
    if klassifikation is None:
        klassifikation = Klassifikation(klassifikation_id=KLASSIFIKATION_ID)
        session.add(klassifikation)
    klassifikation.hauptkategorie = "Intern"
    klassifikation.unterkategorie = "Aufgabenhinweis"
    klassifikation.beschreibung = BESCHREIBUNG
    klassifikation.standard_prio = "normal"
    klassifikation.zielpostfach = ZIELPOSTFACH
    klassifikation.zielordner = ZIELORDNER
    klassifikation.aktion_id = "BESTAETIGUNG_EINHOLEN"
    await session.flush()
    await _aufgabenvorlagen_ersetzen(session)

    kandidaten = (await session.execute(select(Mail).where(
        Mail.im_krautl_posteingang.is_(True),
        or_(
            Mail.klassifikation_id.is_(None),
            Mail.klassifikation_id != KLASSIFIKATION_ID,
        ),
    ))).scalars().all()
    passende_mails = [
        mail for mail in kandidaten
        if ist_interne_aufgabenmail(
            mail.absender_adresse, mail.betreff, mail.text_auszug
        )
    ]

    for mail in passende_mails:
        await session.execute(delete(MailAufgabe).where(
            MailAufgabe.mail_id == mail.id
        ))
        mail.klassifikation_id = KLASSIFIKATION_ID
        mail.aktion_erforderlich = True
        session.add_all([
            MailAufgabe(
                mail_id=mail.id,
                position=1,
                aufgabe_typ="BESTAETIGUNG_EINHOLEN",
                parameter={"zielpostfach": ZIELPOSTFACH, "zielordner": ZIELORDNER},
                status="wartet",
                bestaetiger_typ="alle",
            ),
            MailAufgabe(
                mail_id=mail.id,
                position=2,
                aufgabe_typ="MAIL_VERSCHIEBEN",
                parameter={"zielpostfach": ZIELPOSTFACH, "zielordner": ZIELORDNER},
                status="blockiert",
                bestaetiger_typ="alle",
            ),
        ])

    await session.commit()
    return {"umgestellte_offene_mails": len(passende_mails)}


async def main() -> None:
    async with SessionLocal() as session:
        ergebnis = await aktualisiere(session)
    print(
        f"{KLASSIFIKATION_ID} angelegt oder aktualisiert; "
        f"Ziel {ZIELPOSTFACH}/{ZIELORDNER}; "
        f"{ergebnis['umgestellte_offene_mails']} offene Mail(s) umgestellt."
    )


if __name__ == "__main__":
    asyncio.run(main())
