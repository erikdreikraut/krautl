"""Aktualisiert gezielt die Kategorien für Lieferantenkommunikation.

Einmal nach dem Deployment ausführen:
    docker compose exec app python -m scripts.aktualisiere_lieferantenkategorien

Das Skript ist wiederholbar. Es verändert keine anderen Klassifikationen und
damit auch keine dort inzwischen über die Oberfläche gepflegten Aktionen.
"""
import asyncio

from sqlalchemy import delete, select, update

from app.db import SessionLocal
from app.models import (
    Klassifikation,
    KlassifikationAufgabe,
    Korrektur,
    Mail,
    MailAufgabe,
    RollenMailzugriff,
)


ALTE_ID = "LIEFERANT_PREISAENDERUNG"
NEUE_ID = "LIEFERANT_DIVERSES"
ZIELPOSTFACH = "einkauf@dreikraut.de"
ZIELORDNER = "INBOX"

ANGEBOT_BESCHREIBUNG = (
    "Konkretes Preis-, Produkt- oder Konditionsangebot eines bestehenden oder "
    "potenziellen Lieferanten. Nicht verwenden für laufende Abstimmungen, "
    "Rückfragen oder sonstige allgemeine Korrespondenz mit Lieferanten."
)
DIVERSES_BESCHREIBUNG = (
    "Laufende individuelle Kommunikation mit bestehenden oder potenziellen "
    "Lieferanten, insbesondere Abstimmungen, Rückfragen und allgemeine "
    "Korrespondenz. Nur verwenden, wenn keine speziellere Lieferanten-Kategorie "
    "wie Angebot, Auftragsbestätigung, Lieferavis, Lieferproblem, Qualität "
    "oder Dokumente passt."
)


async def aktualisiere(session) -> dict:
    angebot = await session.get(Klassifikation, "LIEFERANT_ANGEBOT")
    if angebot:
        angebot.beschreibung = ANGEBOT_BESCHREIBUNG

    diverse = await session.get(Klassifikation, NEUE_ID)
    if diverse is None:
        diverse = Klassifikation(klassifikation_id=NEUE_ID)
        session.add(diverse)
    diverse.hauptkategorie = "Einkauf"
    diverse.unterkategorie = "Laufende Lieferantenkommunikation"
    diverse.beschreibung = DIVERSES_BESCHREIBUNG
    diverse.standard_prio = "normal"
    diverse.zielpostfach = ZIELPOSTFACH
    diverse.zielordner = ZIELORDNER
    diverse.aktion_id = "BESTAETIGUNG_EINHOLEN"
    await session.flush()

    # Die Vorlage dieser Kategorie besteht bewusst nur aus der Bestätigung.
    diverse_vorlagen = (await session.execute(
        select(KlassifikationAufgabe.id).where(
            KlassifikationAufgabe.klassifikation_id == NEUE_ID
        )
    )).scalars().all()
    if diverse_vorlagen:
        await session.execute(
            update(MailAufgabe)
            .where(MailAufgabe.klassifikation_aufgabe_id.in_(diverse_vorlagen))
            .values(klassifikation_aufgabe_id=None)
        )
    await session.execute(delete(KlassifikationAufgabe).where(
        KlassifikationAufgabe.klassifikation_id == NEUE_ID
    ))
    session.add(KlassifikationAufgabe(
        klassifikation_id=NEUE_ID,
        position=1,
        aufgabe_typ="BESTAETIGUNG_EINHOLEN",
        parameter={"zielpostfach": ZIELPOSTFACH, "zielordner": ZIELORDNER},
        bestaetiger_typ="alle",
    ))

    # Noch sichtbare Bestandsmails der entfallenden Kategorie erhalten den
    # neuen, einfachen Aufgabenplan. Historisch erledigte Mails behalten ihr
    # Aktionsprotokoll.
    offene_mail_ids = (await session.execute(
        select(Mail.id).where(
            Mail.klassifikation_id == ALTE_ID,
            Mail.im_krautl_posteingang.is_(True),
        )
    )).scalars().all()
    if offene_mail_ids:
        await session.execute(delete(MailAufgabe).where(
            MailAufgabe.mail_id.in_(offene_mail_ids)
        ))
        for mail_id in offene_mail_ids:
            session.add(MailAufgabe(
                mail_id=mail_id,
                position=1,
                aufgabe_typ="BESTAETIGUNG_EINHOLEN",
                parameter={"zielpostfach": ZIELPOSTFACH, "zielordner": ZIELORDNER},
                status="wartet",
                bestaetiger_typ="alle",
            ))

    await session.execute(
        update(Mail)
        .where(Mail.klassifikation_id == ALTE_ID)
        .values(klassifikation_id=NEUE_ID)
    )
    await session.execute(
        update(Korrektur)
        .where(Korrektur.neue_klassifikation_id == ALTE_ID)
        .values(neue_klassifikation_id=NEUE_ID)
    )

    alte_vorlagen = (await session.execute(
        select(KlassifikationAufgabe.id).where(
            KlassifikationAufgabe.klassifikation_id == ALTE_ID
        )
    )).scalars().all()
    if alte_vorlagen:
        await session.execute(
            update(MailAufgabe)
            .where(MailAufgabe.klassifikation_aufgabe_id.in_(alte_vorlagen))
            .values(klassifikation_aufgabe_id=None)
        )
    # Eine eventuell bereits gesetzte Rollenbeschränkung der ersetzten
    # Kategorie bleibt für die neue Kategorie erhalten.
    alte_rechte = (await session.execute(select(RollenMailzugriff).where(
        RollenMailzugriff.klassifikation_id == ALTE_ID
    ))).scalars().all()
    neue_rechte_rollen = set((await session.execute(
        select(RollenMailzugriff.rolle).where(
            RollenMailzugriff.klassifikation_id == NEUE_ID
        )
    )).scalars().all())
    for recht in alte_rechte:
        if recht.rolle not in neue_rechte_rollen:
            session.add(RollenMailzugriff(
                rolle=recht.rolle,
                klassifikation_id=NEUE_ID,
                darf_sehen=recht.darf_sehen,
            ))
    await session.flush()
    await session.execute(delete(RollenMailzugriff).where(
        RollenMailzugriff.klassifikation_id == ALTE_ID
    ))
    await session.execute(delete(KlassifikationAufgabe).where(
        KlassifikationAufgabe.klassifikation_id == ALTE_ID
    ))
    alt = await session.get(Klassifikation, ALTE_ID)
    if alt:
        await session.delete(alt)

    await session.commit()
    return {"umgestellte_offene_mails": len(offene_mail_ids)}


async def main() -> None:
    async with SessionLocal() as session:
        ergebnis = await aktualisiere(session)
    print(
        "Lieferanten-Kategorien aktualisiert; "
        f"{ergebnis['umgestellte_offene_mails']} offene Bestandsmail(s) umgestellt."
    )


if __name__ == "__main__":
    asyncio.run(main())
