"""Aktualisiert gezielt die feste Mailregel für Anthropic-Systemmails.

Einmal nach dem Deployment ausführen:
    docker compose exec app python -m scripts.aktualisiere_anthropic_mailregel

Das Skript ist wiederholbar und verändert keine andere Klassifikation.
"""
import asyncio

from sqlalchemy import delete, select, update

from app.db import SessionLocal
from app.models import Klassifikation, KlassifikationAufgabe, MailAufgabe


KLASSIFIKATION_ID = "SYSTEM_TECHNIK"
ZIELPOSTFACH = "info@dreikraut.de"
ZIELORDNER = "service-Technik"
REGELTEXT = (
    " Nachrichten von Absenderadressen der Domain mail.anthropic.com "
    "gehören immer hierher und sind kein Spam."
)


async def aktualisiere(session) -> dict:
    klassifikation = await session.get(Klassifikation, KLASSIFIKATION_ID)
    if klassifikation is None:
        raise RuntimeError(
            "SYSTEM_TECHNIK fehlt. Bitte zuerst die Mail-Klassifikationen "
            "importieren."
        )

    if "mail.anthropic.com" not in klassifikation.beschreibung.casefold():
        klassifikation.beschreibung = (
            klassifikation.beschreibung.rstrip() + REGELTEXT
        )
    klassifikation.zielpostfach = ZIELPOSTFACH
    klassifikation.zielordner = ZIELORDNER
    klassifikation.aktion_id = "MAIL_VERSCHIEBEN"

    alte_vorlagen = (await session.execute(
        select(KlassifikationAufgabe.id).where(
            KlassifikationAufgabe.klassifikation_id == KLASSIFIKATION_ID
        )
    )).scalars().all()
    if alte_vorlagen:
        await session.execute(
            update(MailAufgabe)
            .where(MailAufgabe.klassifikation_aufgabe_id.in_(alte_vorlagen))
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
            parameter={
                "zielpostfach": ZIELPOSTFACH,
                "zielordner": ZIELORDNER,
            },
            bestaetiger_typ="alle",
        ),
        KlassifikationAufgabe(
            klassifikation_id=KLASSIFIKATION_ID,
            position=2,
            aufgabe_typ="MAIL_VERSCHIEBEN",
            parameter={
                "zielpostfach": ZIELPOSTFACH,
                "zielordner": ZIELORDNER,
            },
            bestaetiger_typ="alle",
        ),
    ])
    await session.commit()
    return {
        "klassifikation": KLASSIFIKATION_ID,
        "zielpostfach": ZIELPOSTFACH,
        "zielordner": ZIELORDNER,
    }


async def main() -> None:
    async with SessionLocal() as session:
        ergebnis = await aktualisiere(session)
    print(
        f"{ergebnis['klassifikation']} aktualisiert: "
        f"{ergebnis['zielpostfach']} / {ergebnis['zielordner']}"
    )


if __name__ == "__main__":
    asyncio.run(main())
