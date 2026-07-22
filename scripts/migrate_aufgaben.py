"""Einmalige Migration von Einzel-Aktionen auf geordnete Aufgabenlisten.

Aufruf nach dem Container-Neubau:
    docker compose exec app python -m scripts.migrate_aufgaben

Sicher mehrfach ausführbar.
"""
import asyncio

from sqlalchemy import inspect, select, text

from app.aufgaben import aufgaben_fuer_mail_anlegen
from app.db import SessionLocal, engine
from app.models import Aktionslog, Base, Klassifikation, KlassifikationAufgabe, Mail, MailAufgabe


async def migriere() -> None:
    # create_all ergänzt neue Tabellen, aber keine Spalten an bestehenden
    # Tabellen. Deshalb wird die Inbox-Spalte explizit ergänzt.
    async with engine.begin() as conn:
        def hat_spalte(sync_conn):
            tabellen = inspect(sync_conn).get_table_names()
            if "mail" not in tabellen:
                return True  # create_all legt die vollständige Tabelle an
            return "im_krautl_posteingang" in {
                spalte["name"] for spalte in inspect(sync_conn).get_columns("mail")
            }

        if not await conn.run_sync(hat_spalte):
            default = "1" if conn.dialect.name == "sqlite" else "true"
            await conn.execute(text(
                'ALTER TABLE "mail" ADD COLUMN "im_krautl_posteingang" '
                f"boolean NOT NULL DEFAULT {default}"
            ))
        await conn.run_sync(Base.metadata.create_all)

    async with SessionLocal() as session:
        klassifikationen = (await session.execute(select(Klassifikation))).scalars().all()
        for klassifikation in klassifikationen:
            vorhandene = (await session.execute(
                select(KlassifikationAufgabe.id).where(
                    KlassifikationAufgabe.klassifikation_id == klassifikation.klassifikation_id
                ).limit(1)
            )).scalar_one_or_none()
            if vorhandene is not None:
                continue

            position = 1
            if klassifikation.aktion_id == "MAIL_VERSCHIEBEN":
                session.add(KlassifikationAufgabe(
                    klassifikation_id=klassifikation.klassifikation_id,
                    position=position,
                    aufgabe_typ="BESTAETIGUNG_EINHOLEN",
                    bestaetiger_typ="alle",
                ))
                position += 1
            session.add(KlassifikationAufgabe(
                klassifikation_id=klassifikation.klassifikation_id,
                position=position,
                aufgabe_typ=klassifikation.aktion_id,
                parameter={
                    "zielpostfach": klassifikation.zielpostfach,
                    "zielordner": klassifikation.zielordner,
                },
            ))
        await session.flush()

        # Bestätigte Bestandsmails sind für Krautl abgeschlossen: sowohl bei
        # erfolgreichem Verschieben als auch bei einem protokollierten Fehler.
        verschobene_ids = set((await session.execute(
            select(Aktionslog.mail_id).where(
                Aktionslog.ereignis == "verschoben", Aktionslog.mail_id.is_not(None)
            )
        )).scalars().all())
        fehlgeschlagene_move_ids = set((await session.execute(
            select(MailAufgabe.mail_id).where(
                MailAufgabe.aufgabe_typ == "MAIL_VERSCHIEBEN",
                MailAufgabe.status == "fehlgeschlagen",
            )
        )).scalars().all())
        abgeschlossene_ids = verschobene_ids | fehlgeschlagene_move_ids
        if abgeschlossene_ids:
            mails = (await session.execute(
                select(Mail).where(Mail.id.in_(abgeschlossene_ids))
            )).scalars().all()
            for mail in mails:
                mail.im_krautl_posteingang = False

        # Noch sichtbare Bestandsmails erhalten einen Aufgabenplan. Dadurch
        # können auch sie künftig bestätigt werden.
        offene_mails = (await session.execute(
            select(Mail).where(Mail.im_krautl_posteingang.is_(True))
        )).scalars().all()
        angelegt = 0
        for mail in offene_mails:
            vorhanden = (await session.execute(
                select(MailAufgabe.id).where(MailAufgabe.mail_id == mail.id).limit(1)
            )).scalar_one_or_none()
            if vorhanden is None:
                await aufgaben_fuer_mail_anlegen(session, mail)
                angelegt += 1

        await session.commit()
    print(
        f"Aufgaben-Migration abgeschlossen: {len(klassifikationen)} Klassifikationen, "
        f"{angelegt} offene Bestandsmails mit Aufgabenplan."
    )


if __name__ == "__main__":
    asyncio.run(migriere())
