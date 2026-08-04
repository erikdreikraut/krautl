"""Ergänzt die beiden Shop-Apotheke-Kategorien gezielt und idempotent.

Einmal nach dem Deployment ausführen:
    docker compose exec app python -m scripts.aktualisiere_shopapotheke_kategorien

Andere, inzwischen im Frontend bearbeitete Klassifikationen bleiben unberührt.
"""
import asyncio

from sqlalchemy import delete, select, update

from app.db import SessionLocal
from app.models import Klassifikation, KlassifikationAufgabe, MailAufgabe


SERVICE = "service@dreikraut.de"

KATEGORIEN = (
    {
        "id": "SHOPAPOTHEKE_BESTELLUNG",
        "unterkategorie": "Neue Bestellung",
        "beschreibung": (
            "Automatische Bestellbenachrichtigung von Shop Apotheke, Redcare "
            "Pharmacy oder deren Mirakl-Portal zu einer neu zu versendenden "
            "Kundenbestellung. Typisch sind eine Bestellnummer im Muster COM-..., "
            "Kunden- und Lieferdaten, Artikel, Menge sowie eine Versandfrist. "
            "Nicht für allgemeine Plattform- oder Richtlinienhinweise verwenden."
        ),
        "prio": "normal",
        "zielordner": "Bestellungen Shopapotheke",
        "aufgaben": ("BESTAETIGUNG_EINHOLEN", "MAIL_VERSCHIEBEN"),
    },
    {
        "id": "SHOPAPOTHEKE_WICHTIG",
        "unterkategorie": "Wichtige Plattformmeldung",
        "beschreibung": (
            "Geschäftlich relevante Richtlinien-, Compliance-, Konto-, Listing- "
            "oder sonstige Plattformmeldung von Shop Apotheke, Redcare Pharmacy "
            "oder deren Mirakl-Portal, insbesondere bei Handlungsbedarf, Fristen "
            "oder drohenden Einschränkungen. Nicht für konkrete neue "
            "Kundenbestellungen verwenden."
        ),
        "prio": "hoch",
        "zielordner": "INBOX",
        "aufgaben": ("BESTAETIGUNG_EINHOLEN",),
    },
)


async def _vorlagen_ersetzen(
    session, klassifikation_id: str, zielordner: str, aufgaben: tuple[str, ...]
):
    alte_ids = (await session.execute(
        select(KlassifikationAufgabe.id).where(
            KlassifikationAufgabe.klassifikation_id == klassifikation_id
        )
    )).scalars().all()
    if alte_ids:
        await session.execute(
            update(MailAufgabe)
            .where(MailAufgabe.klassifikation_aufgabe_id.in_(alte_ids))
            .values(klassifikation_aufgabe_id=None)
        )
    await session.execute(delete(KlassifikationAufgabe).where(
        KlassifikationAufgabe.klassifikation_id == klassifikation_id
    ))
    for position, aufgabe_typ in enumerate(aufgaben, start=1):
        session.add(KlassifikationAufgabe(
            klassifikation_id=klassifikation_id,
            position=position,
            aufgabe_typ=aufgabe_typ,
            parameter={"zielpostfach": SERVICE, "zielordner": zielordner},
            bestaetiger_typ="alle",
        ))


async def aktualisiere(session) -> dict:
    for daten in KATEGORIEN:
        klassifikation = await session.get(Klassifikation, daten["id"])
        if klassifikation is None:
            klassifikation = Klassifikation(klassifikation_id=daten["id"])
            session.add(klassifikation)
        klassifikation.hauptkategorie = "Shop Apotheke"
        klassifikation.unterkategorie = daten["unterkategorie"]
        klassifikation.beschreibung = daten["beschreibung"]
        klassifikation.standard_prio = daten["prio"]
        klassifikation.zielpostfach = SERVICE
        klassifikation.zielordner = daten["zielordner"]
        klassifikation.aktion_id = daten["aufgaben"][0]
        await session.flush()
        await _vorlagen_ersetzen(
            session, daten["id"], daten["zielordner"], daten["aufgaben"]
        )

    # Die vorhandenen Amazon-Kategorien werden ebenfalls eindeutig abgegrenzt.
    for amazon_id in ("AMAZON_STATUS", "AMAZON_WICHTIG"):
        amazon = await session.get(Klassifikation, amazon_id)
        if amazon and "Shop Apotheke, Redcare Pharmacy oder Mirakl" not in amazon.beschreibung:
            amazon.beschreibung += (
                " Ausschließlich tatsächliche Amazon-Nachrichten; Nachrichten "
                "von Shop Apotheke, Redcare Pharmacy oder Mirakl gehören niemals "
                "in diese Kategorie."
            )

    await session.commit()
    return {"kategorien": [daten["id"] for daten in KATEGORIEN]}


async def main() -> None:
    async with SessionLocal() as session:
        ergebnis = await aktualisiere(session)
    print("Shop-Apotheke-Kategorien aktualisiert: " + ", ".join(ergebnis["kategorien"]))


if __name__ == "__main__":
    asyncio.run(main())
