"""Entfernt Bestätigungen aus bestehenden Spam-Aufgabenplänen.

Nach Deployment und Klassifikationsimport einmalig ausführen:
    docker compose exec app python -m scripts.entferne_spam_bestaetigungen

Sicher mehrfach ausführbar. Freigeschaltete Spam-Verschiebungen werden direkt
ausgeführt; ein eventueller IMAP-Fehler erscheint wie gewohnt im Aktionslog.
"""
import asyncio

from sqlalchemy import delete, select

from app.aufgaben import wartende_aufgaben_ausfuehren
from app.db import SessionLocal
from app.models import Klassifikation, KlassifikationAufgabe, Mail, MailAufgabe


async def bereinige() -> None:
    async with SessionLocal() as session:
        spam_ids = set((await session.execute(
            select(Klassifikation.klassifikation_id).where(
                Klassifikation.hauptkategorie == "Spam"
            )
        )).scalars().all())

        if not spam_ids:
            print("Keine Spam-Klassifikationen gefunden.")
            return

        await session.execute(
            delete(KlassifikationAufgabe).where(
                KlassifikationAufgabe.klassifikation_id.in_(spam_ids),
                KlassifikationAufgabe.aufgabe_typ == "BESTAETIGUNG_EINHOLEN",
            )
        )

        mails = (await session.execute(
            select(Mail).where(
                Mail.klassifikation_id.in_(spam_ids),
                Mail.im_krautl_posteingang.is_(True),
            )
        )).scalars().all()

        freigeschaltet: list[int] = []
        for mail in mails:
            bestaetigungen = (await session.execute(
                select(MailAufgabe).where(
                    MailAufgabe.mail_id == mail.id,
                    MailAufgabe.aufgabe_typ == "BESTAETIGUNG_EINHOLEN",
                    MailAufgabe.status.in_(["wartet", "blockiert"]),
                )
            )).scalars().all()
            for bestaetigung in bestaetigungen:
                await session.delete(bestaetigung)

            naechste = (await session.execute(
                select(MailAufgabe)
                .where(
                    MailAufgabe.mail_id == mail.id,
                    MailAufgabe.status.in_(["wartet", "blockiert"]),
                )
                .order_by(MailAufgabe.position)
                .limit(1)
            )).scalar_one_or_none()
            if naechste:
                naechste.status = "wartet"
                freigeschaltet.append(mail.id)

        await session.commit()

    for mail_id in freigeschaltet:
        await wartende_aufgaben_ausfuehren(mail_id)

    print(
        f"Spam-Bestätigungen entfernt; "
        f"{len(freigeschaltet)} bestehende Spam-Mail(s) freigeschaltet."
    )


if __name__ == "__main__":
    asyncio.run(bereinige())
