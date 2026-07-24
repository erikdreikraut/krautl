"""Zieht die Regel „alles außer Spam bestätigen“ auf Bestandsmails nach.

Nach Klassifikationsimport einmalig ausführen:
    docker compose exec app python -m scripts.synchronisiere_bestaetigungen

Sicher mehrfach ausführbar.
"""
import asyncio

from sqlalchemy import select

from app.db import SessionLocal
from app.models import Klassifikation, Mail, MailAufgabe


async def synchronisiere() -> None:
    async with SessionLocal() as session:
        kategorien = {
            k.klassifikation_id: k.hauptkategorie
            for k in (await session.execute(select(Klassifikation))).scalars().all()
        }
        mails = (await session.execute(
            select(Mail).where(Mail.im_krautl_posteingang.is_(True))
        )).scalars().all()

        hinzugefuegt = 0
        bereits_bestaetigt = 0
        for mail in mails:
            if kategorien.get(mail.klassifikation_id, "").strip().casefold() == "spam":
                continue

            aufgaben = (await session.execute(
                select(MailAufgabe)
                .where(MailAufgabe.mail_id == mail.id)
                .order_by(MailAufgabe.position)
            )).scalars().all()
            bestaetigungen = [
                a for a in aufgaben if a.aufgabe_typ == "BESTAETIGUNG_EINHOLEN"
            ]
            if any(a.status in {"wartet", "blockiert"} for a in bestaetigungen):
                continue
            if any(a.status == "erledigt" for a in bestaetigungen):
                mail.im_krautl_posteingang = False
                bereits_bestaetigt += 1
                continue

            for aufgabe in aufgaben:
                if aufgabe.status == "wartet":
                    aufgabe.status = "blockiert"
            position = min((a.position for a in aufgaben), default=1) - 1
            session.add(MailAufgabe(
                mail_id=mail.id,
                position=position,
                aufgabe_typ="BESTAETIGUNG_EINHOLEN",
                status="wartet",
                bestaetiger_typ="alle",
            ))
            hinzugefuegt += 1

        await session.commit()

    print(
        f"Bestätigungen synchronisiert: {hinzugefuegt} hinzugefügt, "
        f"{bereits_bestaetigt} bereits bestätigte Mail(s) ausgeblendet."
    )


if __name__ == "__main__":
    asyncio.run(synchronisiere())
