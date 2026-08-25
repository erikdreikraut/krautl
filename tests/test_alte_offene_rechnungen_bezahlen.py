import os
import unittest
from datetime import datetime, timezone

os.environ.setdefault(
    "DATABASE_URL",
    "sqlite+aiosqlite:///./test_alte_offene_rechnungen_bezahlen.db",
)

from sqlalchemy import select

from app.db import SessionLocal, engine
from app.models import Aktionslog, Base, Mail, Postfach, Rechnung
from scripts.alte_offene_rechnungen_bezahlen import (
    alte_offene_rechnungen_als_bezahlt_markieren,
)


class AlteOffeneRechnungenBezahlenTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)

        async with SessionLocal() as session:
            postfach = Postfach(
                adresse="einkauf@dreikraut.de",
                funktion="einkauf",
                imap_host="imap.test",
            )
            session.add(postfach)
            await session.flush()

            for uid, (nummer, eingang, status) in enumerate((
                ("ALT-OFFEN", datetime(2026, 4, 30, 16, 5, tzinfo=timezone.utc), "offen"),
                ("ALT-UNKLAR", datetime(2026, 7, 31, 21, 59, tzinfo=timezone.utc), "unklar"),
                ("ALT-ERLEDIGT", datetime(2026, 4, 1, tzinfo=timezone.utc), "automatisch"),
                # 22:00 UTC ist am 1. August 00:00 Uhr in Berlin.
                ("AUGUST-OFFEN", datetime(2026, 7, 31, 22, tzinfo=timezone.utc), "offen"),
            ), start=1):
                mail = Mail(
                    message_id=f"<{nummer}@example.test>",
                    imap_uid=uid,
                    postfach_id=postfach.id,
                    absender_name="Lieferant",
                    absender_adresse="rechnung@example.test",
                    betreff=nummer,
                    text_auszug="Rechnung",
                    empfangen_am=eingang,
                )
                session.add(mail)
                await session.flush()
                session.add(Rechnung(
                    mail_id=mail.id,
                    aussteller="Lieferant",
                    rechnungsnummer=nummer,
                    zahlungsstatus=status,
                ))
            await session.commit()

    async def test_nur_offene_und_unklare_vor_august_werden_bezahlt(self):
        async with SessionLocal() as session:
            getroffen = await alte_offene_rechnungen_als_bezahlt_markieren(session)
            self.assertEqual(2, len(getroffen))

        async with SessionLocal() as session:
            result = await session.execute(select(Rechnung))
            stati = {r.rechnungsnummer: r.zahlungsstatus for r in result.scalars()}
            self.assertEqual("bezahlt", stati["ALT-OFFEN"])
            self.assertEqual("bezahlt", stati["ALT-UNKLAR"])
            self.assertEqual("automatisch", stati["ALT-ERLEDIGT"])
            self.assertEqual("offen", stati["AUGUST-OFFEN"])

            logs = (await session.execute(select(Aktionslog))).scalars().all()
            self.assertEqual(1, len(logs))
            self.assertIn("2 vor August 2026", logs[0].detail)

    async def test_vorschau_veraendert_nichts(self):
        async with SessionLocal() as session:
            getroffen = await alte_offene_rechnungen_als_bezahlt_markieren(
                session,
                nur_anzeigen=True,
            )
            self.assertEqual(2, len(getroffen))

        async with SessionLocal() as session:
            result = await session.execute(select(Rechnung.zahlungsstatus))
            self.assertEqual(2, list(result.scalars()).count("offen"))
            self.assertEqual(1, list((await session.execute(
                select(Rechnung.zahlungsstatus).where(Rechnung.zahlungsstatus == "unklar")
            )).scalars()).count("unklar"))
            self.assertEqual([], list((await session.execute(select(Aktionslog))).scalars()))


if __name__ == "__main__":
    unittest.main()
