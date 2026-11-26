import os
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from fastapi import HTTPException
from sqlalchemy import select

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_berechtigungen.db")

from app.berechtigungen import darf_mail_sehen
from app.db import SessionLocal, engine
from app.main import (
    KlassifikationAenderung, MailZuweisung, RollenMailzugriffAenderung, WiedervorlageAenderung,
    _wiedervorlage_bis,
    aktionslog_mail_ansehen, klassifikation_aktualisieren, korrigiere_klassifikation, liste_aktionslog, liste_entwuerfe,
    liste_klassifikationen, liste_mails, mail_antwortentwurf_erzeugen, mail_reservieren,
    mail_wiedervorlegen, mail_zaehler,
    mail_zustaendigkeit_aendern, rollen_mailzugriff_speichern,
)
from app.models import (
    Aktionslog, Base, Entwurf, Klassifikation, Mail, MailNotiz, MailWiedervorlage, Postfach,
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

    async def test_wiedervorlage_blendet_mail_und_entwurf_bis_zum_ablauf_aus(self):
        admin = request_fuer({**ADMIN, "benutzername": "erik"})
        sachbearbeiter = request_fuer({**SACHBEARBEITER, "benutzername": "gursewak"})
        async with SessionLocal() as session:
            mail = await session.scalar(select(Mail).where(Mail.betreff == "Erlaubt"))
            entwurf = Entwurf(mail_id=mail.id, text_ki="Alter Text", status="wartet")
            session.add(entwurf)
            await session.commit()
            mail_id, entwurf_id = mail.id, entwurf.id
            await mail_reservieren(mail_id, sachbearbeiter, session)

        async with SessionLocal() as session:
            with self.assertRaises(HTTPException) as konflikt:
                await mail_wiedervorlegen(mail_id, WiedervorlageAenderung(dauer="12h"), admin, session)
            self.assertEqual(409, konflikt.exception.status_code)

        async with SessionLocal() as session:
            aenderung = WiedervorlageAenderung(
                dauer="12h", entwurf={"id": entwurf_id, "text": "Überarbeiteter Text"},
            )
            erste = await mail_wiedervorlegen(mail_id, aenderung, sachbearbeiter, session)
            self.assertEqual(erste, await mail_wiedervorlegen(mail_id, aenderung, sachbearbeiter, session))
            with self.assertRaises(HTTPException) as verborgen:
                await mail_reservieren(mail_id, sachbearbeiter, session)
            self.assertEqual(409, verborgen.exception.status_code)

        async with SessionLocal() as session:
            self.assertEqual(["Gesperrt"], [m["betreff"] for m in await liste_mails(admin, session)])
            self.assertEqual({"meine": 1, "alle": 0}, await mail_zaehler(admin, session))
            self.assertEqual([], await liste_mails(sachbearbeiter, session))
            self.assertEqual([], await liste_entwuerfe(admin, session))
            mail = await session.get(Mail, mail_id)
            self.assertTrue(mail.im_krautl_posteingang)
            vormerkung = await session.get(MailWiedervorlage, mail_id)
            vormerkung.bis = datetime.now(timezone.utc) - timedelta(seconds=1)
            await session.commit()

        async with SessionLocal() as session:
            self.assertEqual(["Gesperrt", "Erlaubt"], [m["betreff"] for m in await liste_mails(admin, session)])
            self.assertEqual({"meine": 2, "alle": 0}, await mail_zaehler(admin, session))
            self.assertEqual("Überarbeiteter Text", (await liste_entwuerfe(admin, session))[0]["arbeitsfassung"])
            self.assertTrue((await mail_reservieren(mail_id, sachbearbeiter, session))["eigene"])

    def test_wiedervorlage_monat_und_sommerzeit(self):
        januar = datetime(2027, 1, 31, 9, tzinfo=timezone.utc)
        self.assertEqual(datetime(2027, 2, 28, 9, tzinfo=timezone.utc), _wiedervorlage_bis(januar, "1m"))
        vor_sommerzeit = datetime(2027, 3, 27, 9, tzinfo=timezone.utc)
        self.assertEqual(datetime(2027, 3, 28, 8, tzinfo=timezone.utc), _wiedervorlage_bis(vor_sommerzeit, "1d"))

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
            with self.assertRaises(HTTPException) as ansichtsfehler:
                await aktionslog_mail_ansehen(
                    gesperrte_mail.id, request_fuer(SACHBEARBEITER), session
                )
        self.assertEqual(["Erlaubt"], [mail["betreff"] for mail in sichtbar])
        self.assertEqual(403, fehler.exception.status_code)
        self.assertEqual(403, ansichtsfehler.exception.status_code)

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
        self.assertEqual("Erlaubt", erlaubt.beschreibung)
        self.assertEqual("Bearbeitet", erlaubt.zielordner)
        self.assertEqual(403, fehler.exception.status_code)

    async def test_beschreibung_der_klassifikation_ist_editierbar(self):
        aenderung = KlassifikationAenderung(
            beschreibung="  Präzise neue Beschreibung für die KI.  ",
            zielpostfach="service@dreikraut.de",
            zielordner="INBOX",
            aufgaben=[],
        )
        async with SessionLocal() as session:
            await klassifikation_aktualisieren(
                "KUNDE_TEST",
                aenderung,
                request_fuer(SACHBEARBEITER),
                session,
            )
            klassifikation = await session.get(Klassifikation, "KUNDE_TEST")
            log = (await session.execute(
                select(Aktionslog).where(
                    Aktionslog.ereignis == "klassifikation_geaendert"
                )
            )).scalar_one()

        self.assertEqual(
            "Präzise neue Beschreibung für die KI.",
            klassifikation.beschreibung,
        )
        self.assertIn("Beschreibung", log.detail)

    async def test_leere_klassifikationsbeschreibung_wird_abgelehnt(self):
        aenderung = KlassifikationAenderung(
            beschreibung="   ",
            aufgaben=[],
        )
        async with SessionLocal() as session:
            with self.assertRaises(HTTPException) as fehler:
                await klassifikation_aktualisieren(
                    "KUNDE_TEST",
                    aenderung,
                    request_fuer(SACHBEARBEITER),
                    session,
                )

        self.assertEqual(422, fehler.exception.status_code)

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

    async def test_eriks_postfach_bleibt_bei_erik_bis_zur_manuellen_weitergabe(self):
        admin = request_fuer(ADMIN)
        team = request_fuer(SACHBEARBEITER)
        async with SessionLocal() as session:
            postfach = Postfach(adresse="Erik@dreikraut.de", funktion="admin", imap_host="imap.test")
            session.add(postfach)
            await session.flush()
            mail = await session.scalar(select(Mail).where(Mail.betreff == "Erlaubt"))
            mail.postfach_id = postfach.id
            await session.commit()
            await korrigiere_klassifikation(mail.id, admin, "KUNDE_TEST", session=session)
            await rollen_mailzugriff_speichern(
                "sachbearbeiter", RollenMailzugriffAenderung(klassifikation_ids=["KUNDE_TEST"]), admin, session,
            )
            self.assertTrue(mail.zustaendig_admin)
            self.assertFalse(mail.zustaendig_sachbearbeiter)
            self.assertIn(mail.id, [eintrag["id"] for eintrag in await liste_mails(admin, session)])
            self.assertEqual([], await liste_mails(team, session))
            self.assertEqual([], await liste_mails(team, session, alle=True))
            self.assertEqual({"meine": 0, "alle": 0}, await mail_zaehler(team, session))

            await mail_zustaendigkeit_aendern(mail.id, MailZuweisung(rolle="sachbearbeiter"), admin, session)
            self.assertEqual(["Erlaubt"], [m["betreff"] for m in await liste_mails(team, session)])

    async def test_zuweisung_an_sachbearbeiter_entfernt_mail_aus_allen_sammellisten(self):
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
        self.assertEqual([], alle_mails)
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
            session.add(MailNotiz(
                mail_id=mail.id,
                text="Interner Prüfhinweis",
                bearbeitet_von="Erik Schweitzer",
                geaendert_am=datetime.now(timezone.utc),
            ))
            await session.commit()
            antwort = await liste_aktionslog(request_fuer(ADMIN), session)
            mailansicht = await aktionslog_mail_ansehen(
                mail.id, request_fuer(ADMIN), session
            )

        self.assertEqual("Test", antwort["eintraege"][0]["mail_absender"])
        self.assertEqual("Test", antwort["eintraege"][0]["mail_absender_name"])
        self.assertEqual(
            "test@example.test",
            antwort["eintraege"][0]["mail_absender_adresse"],
        )
        self.assertEqual(
            "KUNDE_TEST", antwort["eintraege"][0]["mail_klassifikation"]
        )
        self.assertEqual(["KUNDE_TEST"], antwort["klassifikationen"])
        self.assertTrue(antwort["eintraege"][0]["mail_verfuegbar"])
        self.assertTrue(antwort["eintraege"][0]["hat_notiz"])
        self.assertEqual("Interner Prüfhinweis", mailansicht["notiz"]["text"])

    async def test_aktionslog_sucht_in_absender_und_betreff(self):
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

            nach_name = await liste_aktionslog(
                request_fuer(ADMIN), session, suche="tEsT"
            )
            nach_adresse = await liste_aktionslog(
                request_fuer(ADMIN), session, suche="@example.test"
            )
            nach_betreff = await liste_aktionslog(
                request_fuer(ADMIN), session, suche="laub"
            )
            ohne_treffer = await liste_aktionslog(
                request_fuer(ADMIN), session, suche="nicht vorhanden"
            )

        self.assertEqual(1, nach_name["gesamt"])
        self.assertEqual(1, nach_adresse["gesamt"])
        self.assertEqual(1, nach_betreff["gesamt"])
        self.assertEqual(0, ohne_treffer["gesamt"])

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
            nach_klassifikation = await liste_aktionslog(
                request_fuer(SACHBEARBEITER), session,
                klassifikation="KUNDE_TEST",
            )
            verborgene_klassifikation = await liste_aktionslog(
                request_fuer(SACHBEARBEITER), session,
                klassifikation="RECHT_TEST",
            )

        self.assertEqual(2, antwort["gesamt"])
        self.assertEqual(
            {"Sichtbar", "Global sichtbar"},
            {eintrag["detail"] for eintrag in antwort["eintraege"]},
        )
        self.assertEqual(["KUNDE_TEST"], antwort["klassifikationen"])
        self.assertEqual(1, nach_klassifikation["gesamt"])
        self.assertEqual(0, verborgene_klassifikation["gesamt"])

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
            bestaetigungen = await liste_aktionslog(
                request_fuer(ADMIN), session,
                ereignis="bestaetigt", pro_seite=25,
            )

        self.assertEqual(27, februar["gesamt"])
        self.assertEqual(2, februar["seiten"])
        self.assertEqual(2, len(februar["eintraege"]))
        self.assertEqual(1, zweiter_februar["gesamt"])
        self.assertEqual("Zweiter Februar", zweiter_februar["eintraege"][0]["detail"])
        self.assertEqual(2, bestaetigungen["gesamt"])
        self.assertEqual(
            {"bestaetigt"},
            {eintrag["ereignis"] for eintrag in bestaetigungen["eintraege"]},
        )
        self.assertIn("2026-02", bestaetigungen["monate"])
        self.assertIn("2026-03", bestaetigungen["monate"])
        self.assertEqual(
            {"bestaetigt", "klassifiziert"},
            set(bestaetigungen["ereignisse"]),
        )


if __name__ == "__main__":
    unittest.main()
