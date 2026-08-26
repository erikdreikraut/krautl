"""Übersetzt bereits wartende Entwürfe fremdsprachiger Mails ins Deutsche.

Einmal nach dem Deployment ausführen:
    docker compose exec app python -m scripts.bereinige_fremdsprachige_entwuerfe

Neue KI-Entwürfe werden bereits bei ihrer Erzeugung technisch auf Deutsch
normalisiert. Dieses Skript ist für die zuvor angelegten Bestandsentwürfe.
"""

import asyncio

from sqlalchemy import select

from app.db import SessionLocal
from app.models import Aktionslog, Entwurf, Mail
from app.uebersetzungen import (
    antwort_ins_deutsche_uebersetzen, ist_deutsche_sprache,
)


async def bereinige(session) -> dict:
    zeilen = (await session.execute(
        select(Entwurf, Mail)
        .join(Mail, Entwurf.mail_id == Mail.id)
        .where(Entwurf.status == "wartet")
        .order_by(Entwurf.id)
    )).all()
    kandidaten = [
        (entwurf, mail)
        for entwurf, mail in zeilen
        if (
            entwurf.text_ki.strip()
            and mail.originalsprache
            and not ist_deutsche_sprache(mail.originalsprache)
        )
    ]
    aktualisiert = 0
    fehler = []
    for entwurf, mail in kandidaten:
        try:
            entwurf.text_ki = await antwort_ins_deutsche_uebersetzen(
                entwurf.text_ki, mail.originalsprache
            )
            session.add(Aktionslog(
                mail_id=mail.id,
                ereignis="antwortentwurf_ins_deutsche_uebersetzt",
                detail=(
                    f"Wartenden Entwurf #{entwurf.id} aus "
                    f"{mail.originalsprache} in eine deutsche Arbeitsfassung überführt"
                ),
            ))
            await session.commit()
            aktualisiert += 1
        except Exception as exc:
            await session.rollback()
            fehler.append(f"Entwurf #{entwurf.id}: {exc}")
    return {
        "kandidaten": len(kandidaten),
        "aktualisiert": aktualisiert,
        "fehler": fehler,
    }


async def main() -> None:
    async with SessionLocal() as session:
        ergebnis = await bereinige(session)
    print(
        f"{ergebnis['aktualisiert']} von {ergebnis['kandidaten']} wartenden "
        "fremdsprachigen Entwürfen ins Deutsche übersetzt."
    )
    if ergebnis["fehler"]:
        raise RuntimeError("; ".join(ergebnis["fehler"]))


if __name__ == "__main__":
    asyncio.run(main())
