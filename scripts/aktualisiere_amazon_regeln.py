"""Präzisiert AMAZON_STATUS und korrigiert offene Amazon-Hinweismails.

Einmal nach dem Deployment ausführen:
    docker compose exec app python -m scripts.aktualisiere_amazon_regeln

Manuell bearbeitete oder bereits ausgeblendete Mails bleiben unberührt.
"""
import asyncio

from sqlalchemy import delete, func, or_, select

from app.aufgaben import aufgaben_fuer_mail_anlegen
from app.db import SessionLocal
from app.models import Aktionslog, Klassifikation, Mail, MailAufgabe


KLASSIFIKATION_ID = "AMAZON_STATUS"
BESCHREIBUNG = (
    "Normale geschäftliche Mails direkt von Amazon oder Amazon Seller Central, "
    "insbesondere zu einzelnen Bestellungen, Versand, Auszahlungen, Zahlungen "
    "oder bereitstehenden Dokumenten. Hinweise auf eine im Seller Central "
    "abrufbare Rechnung gehören ebenfalls hierher, wenn die Rechnung nicht "
    "tatsächlich als Anhang mitgesendet wurde."
)
RECHNUNGSHINWEISE = (
    "factura vendedor",
    "seller fee invoice",
    "invoice is available",
    "invoice available",
    "rechnung ist verfügbar",
    "rechnung steht bereit",
    "descargar tu factura",
    "download your invoice",
)


def _ist_rechnungshinweis(mail: Mail) -> bool:
    text = f"{mail.betreff} {mail.text_auszug}".casefold()
    return any(marker in text for marker in RECHNUNGSHINWEISE)


async def aktualisiere(session) -> dict:
    klassifikation = await session.get(Klassifikation, KLASSIFIKATION_ID)
    if klassifikation is None:
        raise RuntimeError("AMAZON_STATUS ist im Klassifikationskatalog nicht vorhanden")
    klassifikation.unterkategorie = "Laufende Amazon-Statusmeldungen"
    klassifikation.beschreibung = BESCHREIBUNG

    name = func.lower(Mail.absender_name)
    adresse = func.lower(Mail.absender_adresse)
    kandidaten = (await session.execute(select(Mail).where(
        Mail.im_krautl_posteingang.is_(True),
        Mail.pruefstatus == "offen",
        Mail.klassifikation_id != KLASSIFIKATION_ID,
        or_(
            name.like("amazon%"),
            adresse.like("%@amazon.%"),
            adresse.like("%@%.amazon.%"),
        ),
    ))).scalars().all()
    offene_hinweise = [mail for mail in kandidaten if _ist_rechnungshinweis(mail)]

    for mail in offene_hinweise:
        alte_id = mail.klassifikation_id or "UNKLASSIFIZIERT"
        await session.execute(delete(MailAufgabe).where(MailAufgabe.mail_id == mail.id))
        await session.flush()
        mail.klassifikation_id = KLASSIFIKATION_ID
        mail.aktion_erforderlich = True
        mail.konfidenz = max(mail.konfidenz, 0.95)
        await aufgaben_fuer_mail_anlegen(session, mail)
        session.add(Aktionslog(
            mail_id=mail.id,
            ereignis="umklassifiziert",
            ausgeloest_von="Krautl",
            detail=f"{alte_id} → {KLASSIFIKATION_ID} (Amazon-Regel aktualisiert)",
        ))

    await session.commit()
    return {"umgestellte_offene_mails": len(offene_hinweise)}


async def main() -> None:
    async with SessionLocal() as session:
        ergebnis = await aktualisiere(session)
    print(
        "Amazon-Regeln aktualisiert. "
        f"{ergebnis['umgestellte_offene_mails']} offene Hinweismail(s) umgestellt."
    )


if __name__ == "__main__":
    asyncio.run(main())
