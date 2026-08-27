import os
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_antwortentwuerfe.db")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")

from sqlalchemy import select

from app.db import SessionLocal, engine
from app.antworten import PRUEFUNGS_SYSTEMPROMPT, pruefergebnis_absichern
from app.main import (
    EntwurfFreigabe, entwurf_freigeben, liste_entwuerfe,
    mail_antwort_beginnen, mail_antwortentwurf_erzeugen,
)
from app.aufgaben import wartende_aufgaben_ausfuehren
from app.models import (
    Aktionslog, Base, Entwurf, Klassifikation, Mail, MailAufgabe, Postfach,
)


TEST_BENUTZER = {
    "benutzername": "erik",
    "name": "Erik Schweitzer",
    "titel": None,
    "rolle": "admin",
}


def test_request():
    return SimpleNamespace(state=SimpleNamespace(benutzer=TEST_BENUTZER))


class AntwortentwurfTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        async with SessionLocal() as session:
            session.add(Klassifikation(
                klassifikation_id="KUNDE_FRAGE",
                hauptkategorie="KUNDENSERVICE",
                unterkategorie="Allgemeine Frage",
                beschreibung="Kundenanfrage",
                standard_prio="normal",
                zielpostfach="service@dreikraut.de",
                zielordner="INBOX",
                aktion_id="ANTWORTVORSCHLAG_ERSTELLEN",
            ))
            postfach = Postfach(
                adresse="service@dreikraut.de",
                funktion="service",
                imap_host="imap.example.test",
            )
            session.add(postfach)
            await session.flush()
            mail = Mail(
                message_id="<antwort-test@example.test>",
                postfach_id=postfach.id,
                absender_name="Ada Beispiel",
                absender_adresse="ada@example.test",
                betreff="Eine Frage",
                text_auszug="Hallo, könnt Ihr mir helfen?",
                originalsprache="Deutsch",
                empfangen_am=datetime.now(timezone.utc),
                im_krautl_posteingang=True,
                klassifikation_id="KUNDE_FRAGE",
                zustaendig_admin=True,
            )
            session.add(mail)
            await session.commit()
            self.mail_id = mail.id

    async def test_entwurf_wird_erzeugt_und_nicht_doppelt_angelegt(self):
        generator = AsyncMock(return_value="Hallo Ada,\n\nsehr gern.")
        with patch("app.antworten.antwortentwurf_erzeugen", generator):
            async with SessionLocal() as session:
                erstes = await mail_antwortentwurf_erzeugen(self.mail_id, test_request(), session)
            async with SessionLocal() as session:
                zweites = await mail_antwortentwurf_erzeugen(self.mail_id, test_request(), session)

        self.assertEqual("erzeugt", erstes["status"])
        self.assertEqual("vorhanden", zweites["status"])
        self.assertEqual(1, generator.await_count)
        async with SessionLocal() as session:
            entwuerfe = (await session.execute(select(Entwurf))).scalars().all()
            self.assertEqual(1, len(entwuerfe))
            self.assertEqual("Hallo Ada,\n\nsehr gern.", entwuerfe[0].text_ki)
            self.assertEqual("wartet", entwuerfe[0].status)

    async def test_fremdsprachiger_ki_entwurf_wird_vor_dem_speichern_deutsch(self):
        async with SessionLocal() as session:
            mail = await session.get(Mail, self.mail_id)
            mail.originalsprache = "Französisch"
            mail.betreff_deutsch = "Eine Frage"
            mail.text_deutsch = "Hallo, könnt Ihr mir helfen?"
            await session.commit()

        generator = AsyncMock(return_value="Bonjour,\n\nmerci pour votre message.")
        uebersetzung = AsyncMock(
            return_value="Guten Tag,\n\nvielen Dank für Ihre Nachricht."
        )
        with patch("app.antworten.antwortentwurf_erzeugen", generator), \
             patch(
                 "app.antworten.antwort_ins_deutsche_uebersetzen", uebersetzung
             ):
            async with SessionLocal() as session:
                ergebnis = await mail_antwortentwurf_erzeugen(
                    self.mail_id, test_request(), session
                )

        self.assertEqual("erzeugt", ergebnis["status"])
        uebersetzung.assert_awaited_once_with(
            "Bonjour,\n\nmerci pour votre message.", "Französisch"
        )
        async with SessionLocal() as session:
            entwurf = (await session.execute(select(Entwurf))).scalar_one()
            self.assertEqual(
                "Guten Tag,\n\nvielen Dank für Ihre Nachricht.", entwurf.text_ki
            )

    async def test_manuelle_antwort_legt_ohne_ki_einen_leeren_entwurf_an(self):
        generator = AsyncMock(return_value="Dieser Text darf nicht entstehen")
        with patch("app.antworten.antwortentwurf_erzeugen", generator):
            async with SessionLocal() as session:
                ergebnis = await mail_antwort_beginnen(
                    self.mail_id, test_request(), session
                )

        self.assertEqual("erzeugt", ergebnis["status"])
        generator.assert_not_awaited()
        async with SessionLocal() as session:
            entwurf = (await session.execute(select(Entwurf))).scalar_one()
            self.assertEqual("", entwurf.text_ki)

    async def test_nicht_kundendienst_wird_ohne_ki_pruefung_versendet(self):
        async with SessionLocal() as session:
            session.add(Klassifikation(
                klassifikation_id="LIEFERANT_DIVERSES",
                hauptkategorie="EINKAUF",
                unterkategorie="Lieferant Diverses",
                beschreibung="Laufende Lieferantenkommunikation",
                standard_prio="normal",
                zielpostfach="einkauf@dreikraut.de",
                zielordner="INBOX",
                aktion_id="BESTAETIGUNG_EINHOLEN",
            ))
            mail = await session.get(Mail, self.mail_id)
            mail.klassifikation_id = "LIEFERANT_DIVERSES"
            entwurf = Entwurf(
                mail_id=self.mail_id,
                text_ki="Guten Tag,\n\nvielen Dank.",
                status="wartet",
            )
            session.add(entwurf)
            await session.commit()
            entwurf_id = entwurf.id

        pruefung = AsyncMock(return_value={"freigabefaehig": False, "probleme": ["Nein"]})
        wissenspruefung = AsyncMock()
        versand = AsyncMock(return_value={
            "message_id": "<manuell-1@dreikraut.de>",
            "empfaenger": "ada@example.test",
            "bcc": "info@erikschweitzer.de",
        })
        with patch("app.main.antwort_vor_versand_pruefen", pruefung), \
             patch("app.main.wissenszuwachs_nach_antwort_pruefen", wissenspruefung), \
             patch("app.main.antwort_senden", versand):
            async with SessionLocal() as session:
                ergebnis = await entwurf_freigeben(
                    entwurf_id,
                    EntwurfFreigabe(finaler_text="Guten Tag,\n\nvielen Dank."),
                    test_request(),
                    session,
                )

        self.assertEqual("versendet", ergebnis["status"])
        self.assertFalse(ergebnis["ki_pruefung"])
        pruefung.assert_not_awaited()
        wissenspruefung.assert_not_awaited()
        versand.assert_awaited_once()

    async def test_entwurf_einer_ausgeblendeten_mail_wird_nicht_mehr_gezaehlt(self):
        async with SessionLocal() as session:
            session.add(Entwurf(
                mail_id=self.mail_id,
                text_ki="Guten Tag,\n\nvielen Dank.",
                status="wartet",
            ))
            await session.commit()

        async with SessionLocal() as session:
            sichtbar = await liste_entwuerfe(test_request(), session)
            mail = await session.get(Mail, self.mail_id)
            mail.im_krautl_posteingang = False
            await session.commit()

        async with SessionLocal() as session:
            ausgeblendet = await liste_entwuerfe(test_request(), session)

        self.assertEqual(1, len(sichtbar))
        self.assertEqual([], ausgeblendet)

    async def test_klassifikationsaufgabe_erzeugt_entwurf_automatisch(self):
        async with SessionLocal() as session:
            session.add(MailAufgabe(
                mail_id=self.mail_id,
                position=1,
                aufgabe_typ="ANTWORTVORSCHLAG_ERSTELLEN",
                status="wartet",
            ))
            await session.commit()

        generator = AsyncMock(return_value="Guten Tag,\n\nvielen Dank für Ihre Nachricht.")
        with patch("app.antworten.antwortentwurf_erzeugen", generator):
            ergebnis = await wartende_aufgaben_ausfuehren(self.mail_id)

        self.assertEqual("keine_aufgabe_offen", ergebnis["status"])
        async with SessionLocal() as session:
            aufgabe = (await session.execute(select(MailAufgabe))).scalar_one()
            entwurf = (await session.execute(select(Entwurf))).scalar_one()
            log = (await session.execute(
                select(Aktionslog).where(
                    Aktionslog.ereignis == "antwortvorschlag_erstellt"
                )
            )).scalar_one()
            self.assertEqual("erledigt", aufgabe.status)
            self.assertEqual("wartet", entwurf.status)
            self.assertIn("Entwurf", log.detail)

    async def test_freigabe_prueft_und_sendet_an_kunden_mit_bcc(self):
        async with SessionLocal() as session:
            entwurf = Entwurf(
                mail_id=self.mail_id,
                text_ki="Guten Tag,\n\nvielen Dank.",
                status="wartet",
            )
            session.add(entwurf)
            await session.commit()
            entwurf_id = entwurf.id

        pruefung = AsyncMock(return_value={"freigabefaehig": True, "probleme": []})
        versand = AsyncMock(return_value={
            "message_id": "<test-1@dreikraut.de>",
            "empfaenger": "ada@example.test",
            "bcc": "info@erikschweitzer.de",
        })
        abschluss = AsyncMock(return_value={"status": "bestaetigt"})
        with patch("app.main.antwort_vor_versand_pruefen", pruefung), \
             patch("app.main.wissenszuwachs_nach_antwort_pruefen", AsyncMock(return_value=None)), \
             patch("app.main.antwort_senden", versand), \
             patch("app.main.bestaetigung_erfassen", abschluss):
            async with SessionLocal() as session:
                ergebnis = await entwurf_freigeben(
                    entwurf_id,
                    EntwurfFreigabe(finaler_text="Guten Tag,\n\nvielen Dank."),
                    test_request(),
                    session,
                )

        self.assertEqual("versendet", ergebnis["status"])
        self.assertEqual("ada@example.test", ergebnis["empfaenger"])
        self.assertEqual("info@erikschweitzer.de", ergebnis["bcc"])
        self.assertEqual("bestaetigt", ergebnis["abschlussstatus"])
        versand.assert_awaited_once()
        abschluss.assert_awaited_once_with(self.mail_id, "Erik Schweitzer")
        async with SessionLocal() as session:
            entwurf = await session.get(Entwurf, entwurf_id)
            mail = await session.get(Mail, self.mail_id)
            self.assertEqual("versendet", entwurf.status)
            self.assertIsNotNone(entwurf.versendet_am)
            self.assertIn("\nErik Schweitzer\n-- \ndreikraut e.K.\n", entwurf.text_final)
            self.assertIn(
                "\nErik Schweitzer\n-- \ndreikraut e.K.\n",
                entwurf.text_final_deutsch,
            )
            self.assertFalse(mail.im_krautl_posteingang)

    async def test_fremdsprachige_antwort_wird_erst_nach_freigabe_uebersetzt(self):
        async with SessionLocal() as session:
            mail = await session.get(Mail, self.mail_id)
            mail.originalsprache = "Englisch"
            mail.betreff_deutsch = "Eine Frage"
            mail.text_deutsch = "Hallo, könnt Ihr mir helfen?"
            entwurf = Entwurf(
                mail_id=self.mail_id,
                text_ki="Guten Tag,\n\nja, sehr gern.",
                status="wartet",
            )
            session.add(entwurf)
            await session.commit()
            entwurf_id = entwurf.id

        pruefung = AsyncMock(return_value={"freigabefaehig": True, "probleme": []})
        uebersetzung = AsyncMock(return_value="Hello,\n\nyes, gladly.")
        versand = AsyncMock(return_value={
            "message_id": "<test-en@dreikraut.de>",
            "empfaenger": "ada@example.test",
            "bcc": "info@erikschweitzer.de",
        })
        with patch("app.main.antwort_vor_versand_pruefen", pruefung), \
             patch("app.main.antwort_in_originalsprache_uebersetzen", uebersetzung), \
             patch("app.main.antwort_senden", versand), \
             patch("app.main.wissenszuwachs_nach_antwort_pruefen", AsyncMock(return_value=None)), \
             patch("app.main.bestaetigung_erfassen", AsyncMock(return_value={"status": "bestaetigt"})):
            async with SessionLocal() as session:
                ergebnis = await entwurf_freigeben(
                    entwurf_id,
                    EntwurfFreigabe(finaler_text="Guten Tag,\n\nja, sehr gern."),
                    test_request(),
                    session,
                )

        pruefung.assert_awaited_once()
        uebersetzung.assert_awaited_once_with(
            "Guten Tag,\n\nja, sehr gern.", "Englisch"
        )
        self.assertEqual("Hello,\n\nyes, gladly.", versand.await_args.args[1])
        self.assertEqual("Englisch", ergebnis["versandsprache"])
        async with SessionLocal() as session:
            entwurf = await session.get(Entwurf, entwurf_id)
            self.assertIn("Guten Tag", entwurf.text_final_deutsch)
            self.assertIn("Hello", entwurf.text_final)

    async def test_offene_punkte_blockieren_den_versand(self):
        async with SessionLocal() as session:
            entwurf = Entwurf(
                mail_id=self.mail_id,
                text_ki="[Vor Versand prüfen/ergänzen: Bestellnummer]",
                status="wartet",
            )
            session.add(entwurf)
            await session.commit()
            entwurf_id = entwurf.id

        pruefung = AsyncMock(return_value={
            "freigabefaehig": False,
            "probleme": ["Bestellnummer fehlt"],
        })
        versand = AsyncMock(return_value={
            "message_id": "<test-2@dreikraut.de>",
            "empfaenger": "ada@example.test",
            "bcc": "info@erikschweitzer.de",
        })
        with patch("app.main.antwort_vor_versand_pruefen", pruefung), \
             patch("app.main.wissenszuwachs_nach_antwort_pruefen", AsyncMock(return_value=None)), \
             patch("app.main.antwort_senden", versand):
            async with SessionLocal() as session:
                ergebnis = await entwurf_freigeben(
                    entwurf_id,
                    EntwurfFreigabe(
                        finaler_text="[Vor Versand prüfen/ergänzen: Bestellnummer]"
                    ),
                    test_request(),
                    session,
                )

        self.assertEqual("pruefung_noetig", ergebnis["status"])
        versand.assert_not_awaited()
        async with SessionLocal() as session:
            entwurf = await session.get(Entwurf, entwurf_id)
            self.assertEqual("wartet", entwurf.status)

    async def test_dritter_versuch_sendet_ohne_weitere_ki_pruefung(self):
        async with SessionLocal() as session:
            entwurf = Entwurf(
                mail_id=self.mail_id,
                text_ki="Guten Tag,\n\nTestantwort.",
                status="wartet",
            )
            session.add(entwurf)
            await session.commit()
            entwurf_id = entwurf.id

        pruefung = AsyncMock(return_value={
            "freigabefaehig": False,
            "probleme": ["Kontroll-KI erhebt einen Einwand"],
        })
        versand = AsyncMock(return_value={
            "message_id": "<test-3@dreikraut.de>",
            "empfaenger": "ada@example.test",
            "bcc": "info@erikschweitzer.de",
        })
        ergebnisse = []
        with patch("app.main.antwort_vor_versand_pruefen", pruefung), \
             patch("app.main.wissenszuwachs_nach_antwort_pruefen", AsyncMock(return_value=None)), \
             patch("app.main.antwort_senden", versand):
            for _ in range(3):
                async with SessionLocal() as session:
                    ergebnisse.append(await entwurf_freigeben(
                        entwurf_id,
                        EntwurfFreigabe(finaler_text="Guten Tag,\n\nTestantwort."),
                        test_request(),
                        session,
                    ))

        self.assertEqual(
            ["pruefung_noetig", "pruefung_noetig", "versendet"],
            [ergebnis["status"] for ergebnis in ergebnisse],
        )
        self.assertFalse(ergebnisse[0]["naechster_versuch_ohne_pruefung"])
        self.assertTrue(ergebnisse[1]["naechster_versuch_ohne_pruefung"])
        self.assertTrue(ergebnisse[2]["pruefung_uebersprungen"])
        self.assertEqual(2, pruefung.await_count)
        versand.assert_awaited_once()
        async with SessionLocal() as session:
            entwurf = await session.get(Entwurf, entwurf_id)
            self.assertEqual("versendet", entwurf.status)

class AntwortpruefungTest(unittest.TestCase):
    def test_json_text_wird_als_problemliste_statt_als_einzelzeichen_gelesen(self):
        ergebnis = pruefergebnis_absichern(
            {
                "freigabefaehig": False,
                "probleme": '["Die Anrede enthält einen Platzhalter.", "Eine Angabe fehlt."]',
            },
            "Guten Tag,\n\nvielen Dank.",
        )
        self.assertEqual(
            ["Die Anrede enthält einen Platzhalter.", "Eine Angabe fehlt."],
            ergebnis["probleme"],
        )

    def test_einfacher_problemtext_bleibt_ein_einzelner_punkt(self):
        ergebnis = pruefergebnis_absichern(
            {"freigabefaehig": "false", "probleme": "Eine wesentliche Angabe fehlt."},
            "Guten Tag,\n\nvielen Dank.",
        )
        self.assertFalse(ergebnis["freigabefaehig"])
        self.assertEqual(["Eine wesentliche Angabe fehlt."], ergebnis["probleme"])

    def test_auswahlplatzhalter_in_anrede_wird_blockiert(self):
        ergebnis = pruefergebnis_absichern(
            {"freigabefaehig": True, "probleme": []},
            "Liebe/r Frau/Herr Topuzidis,\n\nvielen Dank.",
        )
        self.assertFalse(ergebnis["freigabefaehig"])
        self.assertIn("Auswahl-Platzhalter", ergebnis["probleme"][0])

    def test_pruefauftrag_trennt_zusage_von_erledigter_handlung(self):
        self.assertIn("angekündigte nächste Handlung", PRUEFUNGS_SYSTEMPROMPT)
        self.assertIn("internen Prüfhinweis", PRUEFUNGS_SYSTEMPROMPT)
        self.assertIn("als vom Menschen bestätigte Tatsache", PRUEFUNGS_SYSTEMPROMPT)
        self.assertIn("Erfinde niemals nachträglich", PRUEFUNGS_SYSTEMPROMPT)
        self.assertIn("IN DER ANTWORT", PRUEFUNGS_SYSTEMPROMPT)
        self.assertIn("früheren Bearbeitungsstands", PRUEFUNGS_SYSTEMPROMPT)
        self.assertIn("Wochenendwunsch am Freitag", PRUEFUNGS_SYSTEMPROMPT)
        self.assertIn("zusätzlichen Punkte", PRUEFUNGS_SYSTEMPROMPT)

    def test_unbelegte_betriebliche_behauptung_ohne_klammer_blockiert_nicht(self):
        ergebnis = pruefergebnis_absichern(
            {
                "freigabefaehig": False,
                "probleme": [{
                    "typ": "betriebliche_aussage_unbelegt",
                    "beschreibung": (
                        "Die Antwort behauptet die Stornierung, obwohl sie in "
                        "der Kundenmail nicht belegt ist und ein Prüfhinweis fehlt."
                    ),
                }],
            },
            (
                "Sehr geehrter Herr Maciejewski,\n\n"
                "Ihre Bestellungen hatten wir richtig gehandhabt, nur die "
                "überflüssige noch nicht storniert. Es ist alles in bester Ordnung."
            ),
        )
        self.assertTrue(ergebnis["freigabefaehig"])
        self.assertEqual([], ergebnis["probleme"])

    def test_innerer_widerspruch_bleibt_ein_versandhindernis(self):
        ergebnis = pruefergebnis_absichern(
            {
                "freigabefaehig": False,
                "probleme": [{
                    "typ": "innerer_widerspruch",
                    "beschreibung": (
                        "Kostenlos und eine Berechnung von 10 Euro widersprechen sich."
                    ),
                }],
            },
            (
                "Sie erhalten das Produkt kostenlos. "
                "Dafür berechnen wir Ihnen 10 Euro."
            ),
        )
        self.assertFalse(ergebnis["freigabefaehig"])
        self.assertEqual(1, len(ergebnis["probleme"]))

    def test_klammer_blockiert_trotz_nicht_blockierendem_ki_einwand(self):
        ergebnis = pruefergebnis_absichern(
            {
                "freigabefaehig": False,
                "probleme": [{
                    "typ": "betriebliche_aussage_unbelegt",
                    "beschreibung": "Die Ausführung ist nicht extern belegt.",
                }],
            },
            "Wir haben storniert. [Stornierung noch ausführen]",
        )
        self.assertFalse(ergebnis["freigabefaehig"])
        self.assertIn("eckigen Klammern", ergebnis["probleme"][0])

    def test_eckige_klammern_blockieren_auch_bei_ki_fehlurteil(self):
        ergebnis = pruefergebnis_absichern(
            {"freigabefaehig": True, "probleme": []},
            "Hallo [Vor Versand prüfen/ergänzen: Versand anstoßen]",
        )
        self.assertFalse(ergebnis["freigabefaehig"])
        self.assertTrue(ergebnis["probleme"])

    def test_tageszeitabhaengige_anrede_wird_blockiert(self):
        ergebnis = pruefergebnis_absichern(
            {"freigabefaehig": True, "probleme": []},
            "Guten Morgen, liebe Frau Holz,\n\nvielen Dank.",
            datetime(2026, 8, 7, 9, 0, tzinfo=timezone.utc),
        )
        self.assertFalse(ergebnis["freigabefaehig"])
        self.assertIn("tageszeitabhängige Anrede", ergebnis["probleme"][0])

    def test_wochenstart_wird_am_freitag_blockiert(self):
        ergebnis = pruefergebnis_absichern(
            {"freigabefaehig": True, "probleme": []},
            "Ich wünsche Ihnen einen guten Start in die Woche.",
            datetime(2026, 8, 7, 12, 0, tzinfo=timezone.utc),
        )
        self.assertFalse(ergebnis["freigabefaehig"])
        self.assertIn("Freitag", ergebnis["probleme"][0])

    def test_wochenende_ist_am_freitag_zulaessig(self):
        ergebnis = pruefergebnis_absichern(
            {"freigabefaehig": True, "probleme": []},
            "Ich wünsche Ihnen ein schönes Wochenende.",
            datetime(2026, 8, 7, 12, 0, tzinfo=timezone.utc),
        )
        self.assertTrue(ergebnis["freigabefaehig"])
        self.assertEqual([], ergebnis["probleme"])


if __name__ == "__main__":
    unittest.main()
