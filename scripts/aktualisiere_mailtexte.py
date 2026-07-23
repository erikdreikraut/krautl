"""Liest sichtbare Bestandsmails erneut und erzeugt lesbaren Klartext.

Aufruf:
    docker compose exec app python -m scripts.aktualisiere_mailtexte
"""
import asyncio

from sqlalchemy import select

from app.db import SessionLocal
from app.imap_client import lade_postfaecher, mail_rohdaten_laden
from app.mail_parser import parse_eml
from app.models import Mail, Postfach


async def aktualisiere() -> tuple[int, int]:
    configs = {config.user: config for config in lade_postfaecher()}
    aktualisiert = 0
    uebersprungen = 0

    async with SessionLocal() as session:
        result = await session.execute(
            select(Mail, Postfach)
            .join(Postfach, Mail.postfach_id == Postfach.id)
            .where(
                Mail.im_krautl_posteingang.is_(True),
                Mail.imap_uid.is_not(None),
            )
        )
        for mail, postfach in result.all():
            config = configs.get(postfach.adresse)
            if not config:
                uebersprungen += 1
                continue
            try:
                raw = await asyncio.to_thread(
                    mail_rohdaten_laden, config, mail.imap_uid
                )
                mail.text_auszug = parse_eml(raw)["text_auszug"]
                aktualisiert += 1
            except Exception as exc:
                uebersprungen += 1
                print(f"Mail #{mail.id} übersprungen: {exc}")
        await session.commit()

    return aktualisiert, uebersprungen


if __name__ == "__main__":
    bearbeitet, uebersprungen = asyncio.run(aktualisiere())
    print(
        f"Mailtexte aktualisiert: {bearbeitet}; "
        f"übersprungen/nicht mehr im Posteingang: {uebersprungen}"
    )
