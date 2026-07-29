"""Eigenständiger, dauerhaft laufender Mail-Worker."""
import asyncio
import logging
import os
import time
from datetime import datetime, timezone

from .db import SessionLocal, engine
from .models import Base, SystemStatus
from .worker import alle_postfaecher_abrufen

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("krautl.worker_service")

POLL_INTERVALL = max(10, int(os.getenv("MAIL_POLL_INTERVAL_SECONDS", "60")))


async def _status_speichern(
    status: str,
    *,
    erfolgreich: bool = False,
    fehler: bool = False,
    detail: str | None = None,
) -> None:
    jetzt = datetime.now(timezone.utc)
    async with SessionLocal() as session:
        eintrag = await session.get(SystemStatus, "mail_worker")
        if eintrag is None:
            eintrag = SystemStatus(dienst="mail_worker")
            session.add(eintrag)
        eintrag.status = status
        eintrag.letzter_lauf = jetzt
        if erfolgreich:
            eintrag.letzter_erfolg = jetzt
        if fehler:
            eintrag.letzter_fehler = jetzt
        eintrag.detail = detail
        await session.commit()


async def main() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    logger.info("Mail-Worker gestartet; Abrufintervall %d Sekunden", POLL_INTERVALL)
    await _status_speichern("startet", detail="Worker gestartet")

    while True:
        beginn = time.monotonic()
        try:
            ergebnis = await alle_postfaecher_abrufen()
            if ergebnis["fehler"]:
                await _status_speichern(
                    "teilweise_fehlerhaft",
                    erfolgreich=True,
                    fehler=True,
                    detail="; ".join(ergebnis["fehler"])[:2000],
                )
            else:
                await _status_speichern(
                    "ok",
                    erfolgreich=True,
                    detail=f"{ergebnis['mails']} neue Mail(s)",
                )
        except Exception as exc:
            logger.exception("Kompletter Mail-Abruf fehlgeschlagen")
            await _status_speichern("fehler", fehler=True, detail=str(exc)[:2000])

        laufzeit = time.monotonic() - beginn
        await asyncio.sleep(max(0, POLL_INTERVALL - laufzeit))


if __name__ == "__main__":
    asyncio.run(main())
