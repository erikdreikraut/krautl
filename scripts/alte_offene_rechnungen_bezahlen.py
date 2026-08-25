"""Markiert den offenen Rechnungs-Altbestand vor August 2026 als bezahlt.

Der Lauf entspricht exakt der Anzeige unter "Offene Rechnungen": Beruecksichtigt
werden nur die Zahlungsstati ``offen`` und ``unklar``. Als Stichtag gilt das
Eingangsdatum der zugehoerigen Mail, nicht Rechnungs- oder Faelligkeitsdatum.
Der Lauf ist wiederholbar; bereits bezahlte Rechnungen werden nicht angefasst.
"""

import argparse
import asyncio
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import SessionLocal
from app.models import Aktionslog, Mail, Rechnung


STICHTAG = datetime(2026, 8, 1, tzinfo=ZoneInfo("Europe/Berlin")).astimezone(
    timezone.utc
)
OFFENE_STATI = {"offen", "unklar"}


async def alte_offene_rechnungen_finden(
    session: AsyncSession,
    stichtag: datetime = STICHTAG,
) -> list[tuple[Rechnung, datetime]]:
    result = await session.execute(
        select(Rechnung, Mail.empfangen_am)
        .join(Mail, Rechnung.mail_id == Mail.id)
        .where(
            Rechnung.zahlungsstatus.in_(OFFENE_STATI),
            Mail.empfangen_am < stichtag,
        )
        .order_by(Mail.empfangen_am, Rechnung.id)
    )
    return list(result.all())


async def alte_offene_rechnungen_als_bezahlt_markieren(
    session: AsyncSession,
    stichtag: datetime = STICHTAG,
    *,
    nur_anzeigen: bool = False,
) -> list[tuple[Rechnung, datetime]]:
    rechnungen = await alte_offene_rechnungen_finden(session, stichtag)
    if nur_anzeigen or not rechnungen:
        return rechnungen

    vorher = {"offen": 0, "unklar": 0}
    for rechnung, _ in rechnungen:
        vorher[rechnung.zahlungsstatus] += 1
        rechnung.zahlungsstatus = "bezahlt"

    session.add(Aktionslog(
        ereignis="rechnungen_altbestand_bezahlt",
        ausgeloest_von="Erik Schweitzer",
        detail=(
            f"Einmalige Bereinigung: {len(rechnungen)} vor August 2026 "
            f"eingegangene offene Rechnungen als bezahlt markiert "
            f"(zuvor offen: {vorher['offen']}, unklar: {vorher['unklar']})"
        ),
    ))
    await session.commit()
    return rechnungen


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--nur-anzeigen",
        action="store_true",
        help="Treffer nur zaehlen und anzeigen, ohne sie zu veraendern",
    )
    args = parser.parse_args()

    async with SessionLocal() as session:
        rechnungen = await alte_offene_rechnungen_als_bezahlt_markieren(
            session,
            nur_anzeigen=args.nur_anzeigen,
        )

    modus = "gefunden" if args.nur_anzeigen else "als bezahlt markiert"
    print(f"{len(rechnungen)} Rechnung(en) {modus}.")
    if rechnungen:
        erstes_datum = rechnungen[0][1].astimezone(timezone.utc).date()
        letztes_datum = rechnungen[-1][1].astimezone(timezone.utc).date()
        print(f"Zeitraum des bearbeiteten Bestands: {erstes_datum} bis {letztes_datum}")


if __name__ == "__main__":
    asyncio.run(main())
