"""Wiederholt fehlgeschlagene Rechnungsaufgaben nach Behebung der Ursache.

Ohne --mail-id werden alle fehlgeschlagenen RECHNUNG_VERWALTEN-Aufgaben
erneut angestoßen. Der Dropbox-Upload ist über deterministische Pfade und die
Rechnungs-Dublettenerkennung wiederholbar.
"""
import argparse
import asyncio

from sqlalchemy import select

from app.aufgaben import RECHNUNG_VERWALTEN, wartende_aufgaben_ausfuehren
from app.db import SessionLocal
from app.models import Mail, MailAufgabe


async def wiederholen(mail_id: int | None = None) -> list[dict]:
    async with SessionLocal() as session:
        anfrage = select(MailAufgabe).where(
            MailAufgabe.aufgabe_typ == RECHNUNG_VERWALTEN,
            MailAufgabe.status == "fehlgeschlagen",
        )
        if mail_id is not None:
            anfrage = anfrage.where(MailAufgabe.mail_id == mail_id)
        aufgaben = (await session.execute(anfrage)).scalars().all()
        mail_ids = [aufgabe.mail_id for aufgabe in aufgaben]
        for aufgabe in aufgaben:
            aufgabe.status = "wartet"
            aufgabe.fehler = None
            mail = await session.get(Mail, aufgabe.mail_id)
            if mail:
                mail.im_krautl_posteingang = True
        await session.commit()

    ergebnisse = []
    for aktuelle_mail_id in mail_ids:
        ergebnis = await wartende_aufgaben_ausfuehren(aktuelle_mail_id)
        ergebnisse.append({"mail_id": aktuelle_mail_id, **ergebnis})
    return ergebnisse


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mail-id", type=int)
    args = parser.parse_args()
    ergebnisse = asyncio.run(wiederholen(args.mail_id))
    if not ergebnisse:
        print("Keine passende fehlgeschlagene Rechnungsaufgabe gefunden.")
        return
    for ergebnis in ergebnisse:
        print(ergebnis)


if __name__ == "__main__":
    main()
