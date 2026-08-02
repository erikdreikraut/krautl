import os
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

from fastapi import HTTPException
from sqlalchemy import select

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_berechtigungen.db")

from app.berechtigungen import darf_mail_sehen
from app.db import SessionLocal, engine
from app.main import (
    RollenMailzugriffAenderung, liste_mails, mail_antwortentwurf_erzeugen,
    rollen_mailzugriff_speichern,
)
from app.models import Base, Klassifikation, Mail, Postfach, RollenMailzugriff


ADMIN = {"rolle": "admin", "name": "Erik Schweitzer"}
SACHBEARBEITER = {"rolle": "sachbearbeiter", "name": "Gursewak Singh"}


def request_fuer(benutzer):
    return SimpleNamespace(state=SimpleNamespace(benutzer=benutzer))


class BerechtigungenTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        async with SessionLocal() as session:
            postfach = Postfach(
                adresse="service@dreikraut.de", funktion="service", imap_host="imap.test"
            )
            erlaubt = Klassifikation(
                klassifikation_id="KUNDE_TEST", hauptkategorie="Kundenservice",
                unterkategorie="Test", beschreibung="Erlaubt", standard_prio="normal",
                aktion_id="KEINE_AKTION",
            )
            gesperrt = Klassifikation(
                klassifikation_id="RECHT_TEST", hauptkategorie="Recht",
                unterkategorie="Test", beschreibung="Gesperrt", standard_prio="hoch",
                aktion_id="KEINE_AKTION",
            )
            session.add_all([postfach, erlaubt, gesperrt])
            await session.flush()
            session.add(RollenMailzugriff(
                rolle="sachbearbeiter", klassifikation_id="RECHT_TEST", darf_sehen=False
            ))
            session.add_all([
                Mail(
                    message_id="<erlaubt@test>", postfach_id=postfach.id,
                    absender_name="Test", absender_adresse="test@example.test",
                    betreff="Erlaubt", text_auszug="Test", empfangen_am=datetime.now(timezone.utc),
                    klassifikation_id="KUNDE_TEST",
                ),
                Mail(
                    message_id="<gesperrt@test>", postfach_id=postfach.id,
                    absender_name="Test", absender_adresse="test@example.test",
                    betreff="Gesperrt", text_auszug="Test", empfangen_am=datetime.now(timezone.utc),
                    klassifikation_id="RECHT_TEST",
                ),
            ])
            await session.commit()

    async def test_admin_sieht_alle_mailarten(self):
        async with SessionLocal() as session:
            mails = (await session.execute(select(Mail))).scalars().all()
            self.assertTrue(all([await darf_mail_sehen(session, ADMIN, mail) for mail in mails]))

    async def test_sachbearbeiter_sieht_nur_freigegebene_mailarten(self):
        async with SessionLocal() as session:
            mails = (await session.execute(select(Mail))).scalars().all()
            zugriff = {mail.betreff: await darf_mail_sehen(session, SACHBEARBEITER, mail) for mail in mails}
        self.assertEqual({"Erlaubt": True, "Gesperrt": False}, zugriff)

    async def test_posteingang_und_bearbeitung_sind_serverseitig_begrenzt(self):
        async with SessionLocal() as session:
            sichtbar = await liste_mails(request_fuer(SACHBEARBEITER), session)
            gesperrte_mail = (await session.execute(
                select(Mail).where(Mail.klassifikation_id == "RECHT_TEST")
            )).scalar_one()
            with self.assertRaises(HTTPException) as fehler:
                await mail_antwortentwurf_erzeugen(
                    gesperrte_mail.id, request_fuer(SACHBEARBEITER), session
                )
        self.assertEqual(["Erlaubt"], [mail["betreff"] for mail in sichtbar])
        self.assertEqual(403, fehler.exception.status_code)

    async def test_admin_kann_rollenzugriff_speichern(self):
        async with SessionLocal() as session:
            ergebnis = await rollen_mailzugriff_speichern(
                "sachbearbeiter",
                RollenMailzugriffAenderung(klassifikation_ids=["KUNDE_TEST"]),
                request_fuer(ADMIN),
                session,
            )
            rechte = {
                zeile.klassifikation_id: zeile.darf_sehen
                for zeile in (await session.execute(select(RollenMailzugriff))).scalars().all()
            }
        self.assertEqual(1, ergebnis["freigegeben"])
        self.assertEqual({"KUNDE_TEST": True, "RECHT_TEST": False}, rechte)


if __name__ == "__main__":
    unittest.main()
