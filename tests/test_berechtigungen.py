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
    KlassifikationAenderung, MailZuweisung, RollenMailzugriffAenderung,
    klassifikation_aktualisieren, liste_aktionslog, liste_entwuerfe,
    liste_klassifikationen, liste_mails, mail_antwortentwurf_erzeugen, mail_zaehler,
    mail_zustaendigkeit_aendern, rollen_mailzugriff_speichern,
)
from app.models import (
    Aktionslog, Base, Entwurf, Klassifikation, Mail, Postfach,
    RollenMailzugriff,
)


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
                    zustaendig_admin=True,
                ),
                Mail(
                    message_id="<gesperrt@test>", postfach_id=postfach.id,
                    absender_name="Test", absender_adresse="test@example.test",
                    betreff="Gesperrt", text_auszug="Test", empfangen_am=datetime.now(timezone.utc),
                    klassifikation_id="RECHT_TEST",
                    zustaendig_admin=True,
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

    async def test_sachbearbeiter_kann_alle_erlaubten_statt_nur_meine_laden(self):
        async with SessionLocal() as session:
            erlaubte_mail = (await session.execute(
                select(Mail).where(Mail.klassifikation_id == "KUNDE_TEST")
            )).scalar_one()
            erlaubte_mail.zustaendig_sachbearbeiter = False
            session.add(Entwurf(
                mail_id=erlaubte_mail.id,
                text_ki="Guten Tag,",
                status="wartet",
            ))
            await session.commit()

        async with SessionLocal() as session:
            meine_mails = await liste_mails(
                request_fuer(SACHBEARBEITER), session, alle=False
            )
            alle_mails = await liste_mails(
                request_fuer(SACHBEARBEITER), session, alle=True
            )
            meine_entwuerfe = await liste_entwuerfe(
                request_fuer(SACHBEARBEITER), session, alle=False
            )
            alle_entwuerfe = await liste_entwuerfe(
                request_fuer(SACHBEARBEITER), session, alle=True
            )

        self.assertEqual([], meine_mails)
        self.assertEqual(["Erlaubt"], [mail["betreff"] for mail in alle_mails])
        self.assertEqual([], meine_entwuerfe)
        self.assertEqual(1, len(alle_entwuerfe))

    async def test_mailzaehler_liefert_meine_und_alle_unabhaengig_vom_schalter(self):
        async with SessionLocal() as session:
            admin = await mail_zaehler(request_fuer(ADMIN), session)
            sachbearbeiter = await mail_zaehler(
                request_fuer(SACHBEARBEITER), session
            )

        self.assertEqual({"meine": 2, "alle": 0}, admin)
        self.assertEqual({"meine": 1, "alle": 0}, sachbearbeiter)

    async def test_hoch_priorisierte_mails_stehen_vor_neueren_normalen_mails(self):
        async with SessionLocal() as session:
            mails = await liste_mails(request_fuer(ADMIN), session, alle=False)

        self.assertEqual(
            ["Gesperrt", "Erlaubt"],
            [mail["betreff"] for mail in mails],
        )

    async def test_sachbearbeiter_kann_freigegebene_klassifikationen_bearbeiten(self):
        aenderung = KlassifikationAenderung(
            zielpostfach="service@dreikraut.de",
            zielordner="Bearbeitet",
            aufgaben=["MAIL_VERSCHIEBEN"],
        )
        async with SessionLocal() as session:
            sichtbare = await liste_klassifikationen(
                request_fuer(SACHBEARBEITER), session
            )
            await klassifikation_aktualisieren(
                "KUNDE_TEST", aenderung, request_fuer(SACHBEARBEITER), session
            )
            with self.assertRaises(HTTPException) as fehler:
                await klassifikation_aktualisieren(
                    "RECHT_TEST", aenderung,
                    request_fuer(SACHBEARBEITER), session,
                )
            erlaubt = await session.get(Klassifikation, "KUNDE_TEST")

        self.assertEqual(
            ["KUNDE_TEST"], [k["klassifikation_id"] for k in sichtbare]
        )
        self.assertEqual("Bearbeitet", erlaubt.zielordner)
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
            mails = {
                mail.klassifikation_id: mail.zustaendig_sachbearbeiter
                for mail in (await session.execute(select(Mail))).scalars().all()
            }
        self.assertEqual(1, ergebnis["freigegeben"])
        self.assertEqual({"KUNDE_TEST": True, "RECHT_TEST": False}, rechte)
        self.assertEqual({"KUNDE_TEST": True, "RECHT_TEST": False}, mails)

    async def test_manuelle_zuweisung_ist_exklusiv_und_filtert_die_arbeitsliste(self):
        async with SessionLocal() as session:
            erlaubte_mail = (await session.execute(
                select(Mail).where(Mail.klassifikation_id == "KUNDE_TEST")
            )).scalar_one()
            ergebnis = await mail_zustaendigkeit_aendern(
                erlaubte_mail.id,
                MailZuweisung(rolle="sachbearbeiter"),
                request_fuer(ADMIN),
                session,
            )

        self.assertEqual("sachbearbeiter", ergebnis["rolle"])
        async with SessionLocal() as session:
            admin_mails = await liste_mails(request_fuer(ADMIN), session)
            alle_mails = await liste_mails(request_fuer(ADMIN), session, alle=True)
            sachbearbeiter_mails = await liste_mails(
                request_fuer(SACHBEARBEITER), session
            )
            sachbearbeiter_alle = await liste_mails(
                request_fuer(SACHBEARBEITER), session, alle=True
            )
            mail = (await session.execute(
                select(Mail).where(Mail.klassifikation_id == "KUNDE_TEST")
            )).scalar_one()
            log = (await session.execute(
                select(Aktionslog).where(Aktionslog.ereignis == "mail_zugewiesen")
            )).scalar_one()

        self.assertEqual(["Gesperrt"], [mail["betreff"] for mail in admin_mails])
        self.assertEqual(["Erlaubt"], [mail["betreff"] for mail in alle_mails])
        self.assertEqual(["Erlaubt"], [mail["betreff"] for mail in sachbearbeiter_mails])
        self.assertEqual([], sachbearbeiter_alle)
        self.assertFalse(mail.zustaendig_admin)
        self.assertTrue(mail.zustaendig_sachbearbeiter)
        self.assertTrue(mail.zustaendigkeit_manuell)
        self.assertEqual("Erik Schweitzer", log.ausgeloest_von)

    async def test_an_admin_zugewiesene_mail_verschwindet_auch_aus_alle_der_sachbearbeiter(self):
        async with SessionLocal() as session:
            erlaubte_mail = (await session.execute(
                select(Mail).where(Mail.klassifikation_id == "KUNDE_TEST")
            )).scalar_one()
            session.add(Entwurf(
                mail_id=erlaubte_mail.id,
                text_ki="Guten Tag,",
                status="wartet",
            ))
            await session.commit()
            await mail_zustaendigkeit_aendern(
                erlaubte_mail.id,
                MailZuweisung(rolle="admin"),
                request_fuer(ADMIN),
                session,
            )

        async with SessionLocal() as session:
            admin_meine = await liste_mails(
                request_fuer(ADMIN), session, alle=False
            )
            admin_alle = await liste_mails(
                request_fuer(ADMIN), session, alle=True
            )
            sachbearbeiter_meine = await liste_mails(
                request_fuer(SACHBEARBEITER), session, alle=False
            )
            sachbearbeiter_alle = await liste_mails(
                request_fuer(SACHBEARBEITER), session, alle=True
            )
            sachbearbeiter_entwuerfe = await liste_entwuerfe(
                request_fuer(SACHBEARBEITER), session, alle=True
            )
            zaehler = await mail_zaehler(
                request_fuer(SACHBEARBEITER), session
            )
            mail = (await session.execute(
                select(Mail).where(Mail.klassifikation_id == "KUNDE_TEST")
            )).scalar_one()
            direkter_zugriff = await darf_mail_sehen(
                session, SACHBEARBEITER, mail
            )

        self.assertIn("Erlaubt", [mail["betreff"] for mail in admin_meine])
        self.assertNotIn("Erlaubt", [mail["betreff"] for mail in admin_alle])
        self.assertNotIn(
            "Erlaubt", [mail["betreff"] for mail in sachbearbeiter_meine]
        )
        self.assertNotIn(
            "Erlaubt", [mail["betreff"] for mail in sachbearbeiter_alle]
        )
        self.assertEqual([], sachbearbeiter_entwuerfe)
        self.assertEqual({"meine": 0, "alle": 0}, zaehler)
        self.assertFalse(direkter_zugriff)

    async def test_zuweisung_respektiert_die_rollen_matrix(self):
        async with SessionLocal() as session:
            gesperrte_mail = (await session.execute(
                select(Mail).where(Mail.klassifikation_id == "RECHT_TEST")
            )).scalar_one()
            with self.assertRaises(HTTPException) as fehler:
                await mail_zustaendigkeit_aendern(
                    gesperrte_mail.id,
                    MailZuweisung(rolle="sachbearbeiter"),
                    request_fuer(ADMIN),
                    session,
                )
        self.assertEqual(422, fehler.exception.status_code)

    async def test_aktionslog_liefert_den_mail_absender(self):
        async with SessionLocal() as session:
            mail = (await session.execute(
                select(Mail).where(Mail.klassifikation_id == "KUNDE_TEST")
            )).scalar_one()
            session.add(Aktionslog(
                mail_id=mail.id,
                ereignis="klassifiziert",
                detail="KUNDE_TEST",
            ))
            await session.commit()
            antwort = await liste_aktionslog(request_fuer(ADMIN), session)

        self.assertEqual("Test", antwort["eintraege"][0]["mail_absender"])

    async def test_sachbearbeiter_sieht_nur_zulaessige_mailbezogene_logs(self):
        async with SessionLocal() as session:
            mails = {
                mail.klassifikation_id: mail
                for mail in (await session.execute(select(Mail))).scalars().all()
            }
            session.add_all([
                Aktionslog(
                    mail_id=mails["KUNDE_TEST"].id,
                    ereignis="klassifiziert",
                    detail="Sichtbar",
                ),
                Aktionslog(
                    mail_id=mails["RECHT_TEST"].id,
                    ereignis="klassifiziert",
                    detail="Verborgen",
                ),
                Aktionslog(
                    mail_id=None,
                    ereignis="system",
                    detail="Global sichtbar",
                ),
            ])
            await session.commit()
            antwort = await liste_aktionslog(
                request_fuer(SACHBEARBEITER), session
            )

        self.assertEqual(2, antwort["gesamt"])
        self.assertEqual(
            {"Sichtbar", "Global sichtbar"},
            {eintrag["detail"] for eintrag in antwort["eintraege"]},
        )

    async def test_aktionslog_filtert_nach_monat_und_tag_und_paginiert(self):
        async with SessionLocal() as session:
            mail = (await session.execute(
                select(Mail).where(Mail.klassifikation_id == "KUNDE_TEST")
            )).scalar_one()
            session.add_all([
                Aktionslog(
                    mail_id=mail.id,
                    ereignis="klassifiziert",
                    detail=f"Februar {nummer}",
                    erstellt_am=datetime(2026, 2, 1, 10, nummer, tzinfo=timezone.utc),
                )
                for nummer in range(26)
            ])
            session.add_all([
                Aktionslog(
                    mail_id=mail.id,
                    ereignis="bestaetigt",
                    detail="Zweiter Februar",
                    erstellt_am=datetime(2026, 2, 2, 10, 0, tzinfo=timezone.utc),
                ),
                Aktionslog(
                    mail_id=mail.id,
                    ereignis="bestaetigt",
                    detail="März",
                    erstellt_am=datetime(2026, 3, 1, 10, 0, tzinfo=timezone.utc),
                ),
            ])
            await session.commit()

            februar = await liste_aktionslog(
                request_fuer(ADMIN), session, monat="2026-02", seite=2, pro_seite=25
            )
            zweiter_februar = await liste_aktionslog(
                request_fuer(ADMIN), session,
                monat="2026-02", tag="2026-02-02", pro_seite=25,
            )

        self.assertEqual(27, februar["gesamt"])
        self.assertEqual(2, februar["seiten"])
        self.assertEqual(2, len(februar["eintraege"]))
        self.assertEqual(1, zweiter_februar["gesamt"])
        self.assertEqual("Zweiter Februar", zweiter_februar["eintraege"][0]["detail"])


if __name__ == "__main__":
    unittest.main()
