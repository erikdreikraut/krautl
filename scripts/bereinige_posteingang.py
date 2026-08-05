"""Blendet Mails nur aus Krautls Posteingang aus.

Die Mails und Protokolle bleiben in der Datenbank erhalten. IMAP wird nicht
verändert. Beispiele:

    python -m scripts.bereinige_posteingang --vor 2026-07-22T16:22:00+02:00
    python -m scripts.bereinige_posteingang --alle
"""
import argparse
import asyncio
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import exists, select, update

from app.db import SessionLocal
from app.models import Aktionslog, Mail, MailAufgabe


def _zeitpunkt(wert: str) -> datetime:
    zeitpunkt = datetime.fromisoformat(wert)
    if zeitpunkt.tzinfo is None:
        zeitpunkt = zeitpunkt.replace(tzinfo=ZoneInfo("Europe/Berlin"))
    return zeitpunkt.astimezone(timezone.utc)


async def bereinige(vor: datetime) -> int:
    offene_bestaetigung = exists(
        select(MailAufgabe.id).where(
            MailAufgabe.mail_id == Mail.id,
            MailAufgabe.aufgabe_typ == "BESTAETIGUNG_EINHOLEN",
            MailAufgabe.status == "wartet",
        )
    )
    async with SessionLocal() as session:
        mails = (await session.execute(
            select(Mail).where(
                Mail.im_krautl_posteingang.is_(True),
                Mail.empfangen_am < vor,
                ~offene_bestaetigung,
            )
        )).scalars().all()

        for mail in mails:
            mail.im_krautl_posteingang = False
            session.add(Aktionslog(
                mail_id=mail.id,
                ereignis="posteingang_bereinigt",
                detail=(
                    "Historischer Eintrag ohne offene Bestätigung aus dem "
                    f"Krautl-Posteingang entfernt (Stichtag {vor.isoformat()})"
                ),
            ))
        await session.commit()
        return len(mails)


async def leere_posteingang() -> int:
    """Leert die Arbeitsliste, ohne eine Mail oder ein Postfach zu verändern."""
    async with SessionLocal() as session:
        mails = (await session.execute(
            select(Mail).where(Mail.im_krautl_posteingang.is_(True))
        )).scalars().all()
        if not mails:
            return 0

        mail_ids = [mail.id for mail in mails]
        jetzt = datetime.now(timezone.utc)
        for mail in mails:
            mail.im_krautl_posteingang = False
            session.add(Aktionslog(
                mail_id=mail.id,
                ereignis="posteingang_bereinigt",
                detail=(
                    "Einmalige Bereinigung: aus der Krautl-Arbeitsliste "
                    "entfernt. Mail im IMAP-Postfach unverändert."
                ),
            ))

        await session.execute(
            update(MailAufgabe)
            .where(
                MailAufgabe.mail_id.in_(mail_ids),
                MailAufgabe.status.in_(["wartet", "blockiert"]),
            )
            .values(
                status="abgebrochen",
                fehler="Einmalige Bereinigung der Krautl-Arbeitsliste",
                erledigt_am=jetzt,
            )
        )
        await session.commit()
        return len(mails)


async def main() -> None:
    parser = argparse.ArgumentParser()
    auswahl = parser.add_mutually_exclusive_group(required=True)
    auswahl.add_argument(
        "--vor",
        help="ISO-Zeitpunkt; ohne Offset wird Europe/Berlin angenommen",
    )
    auswahl.add_argument(
        "--alle", action="store_true",
        help="Alle derzeit sichtbaren Mails nur aus Krautls Arbeitsliste entfernen",
    )
    args = parser.parse_args()
    if args.alle:
        anzahl = await leere_posteingang()
        print(
            f"{anzahl} Mail(s) aus der Krautl-Arbeitsliste ausgeblendet. "
            "IMAP blieb unverändert."
        )
    else:
        vor = _zeitpunkt(args.vor)
        anzahl = await bereinige(vor)
        print(
            f"{anzahl} historische Mail(s) aus dem Krautl-Posteingang "
            "ausgeblendet."
        )


if __name__ == "__main__":
    asyncio.run(main())
