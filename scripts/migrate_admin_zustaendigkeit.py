"""
Einmalige Daten-Migration: setzt zustaendig_admin=False für alle Mails, die
noch NIE manuell zugewiesen wurden (zustaendigkeit_manuell=False).

Hintergrund: standard_zustaendigkeit() setzte Admin bisher fest auf True für
jede Mail — dadurch war praktisch der gesamte Posteingang immer schon
"MEINE" für den Admin, und der MEINE/ALLE-Schalter sowie manuelles Zuweisen
konnten nie etwas sichtbar verändern (siehe app/berechtigungen.py). Der
Code-Fix wirkt nur auf künftige Mails — ohne diese Migration würde der
riesige Bestand an Alt-Mails weiterhin so aussehen, als gehöre er dem Admin.

Manuelle Zuweisungen (zustaendigkeit_manuell=True) bleiben unangetastet.

Aufruf (vom Projekt-Root):
    python -m scripts.migrate_admin_zustaendigkeit
"""
import asyncio

from sqlalchemy import update

from app.db import SessionLocal
from app.models import Mail


async def migriere() -> None:
    async with SessionLocal() as session:
        ergebnis = await session.execute(
            update(Mail)
            .where(Mail.zustaendigkeit_manuell.is_(False))
            .values(zustaendig_admin=False)
        )
        await session.commit()
        print(f"{ergebnis.rowcount} Mail(s) aktualisiert: zustaendig_admin -> False.")


if __name__ == "__main__":
    asyncio.run(migriere())
