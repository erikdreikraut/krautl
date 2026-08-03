import os
import unittest
from datetime import datetime, timezone

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_lieferantenkategorien.db")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")

from sqlalchemy import select

from app.db import SessionLocal, engine
from app.models import (
    Base,
    Klassifikation,
    KlassifikationAufgabe,
    Mail,
    MailAufgabe,
    Postfach,
    RollenMailzugriff,
)
from scripts.aktualisiere_lieferantenkategorien import aktualisiere


class LieferantenkategorienTest(unittest.IsolatedAsyncioTestCase):
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
            angebot = Klassifikation(
                klassifikation_id="LIEFERANT_ANGEBOT",
                hauptkategorie="Einkauf",
                unterkategorie="Angebot",
                beschreibung="zu weit gefasst",
                standard_prio="normal",
                zielpostfach=None,
                zielordner="Einkauf/Angebote",
                aktion_id="LIEFERANTENMAIL_BEARBEITEN",
            )
            alt = Klassifikation(
                klassifikation_id="LIEFERANT_PREISAENDERUNG",
                hauptkategorie="Einkauf",
                unterkategorie="Preisänderung",
                beschreibung="entfällt",
                standard_prio="normal",
                zielpostfach=None,
                zielordner="Einkauf/Preisaenderungen",
                aktion_id="LIEFERANTENMAIL_BEARBEITEN",
            )
            session.add_all([postfach, angebot, alt])
            await session.flush()
            vorlage = KlassifikationAufgabe(
                klassifikation_id=alt.klassifikation_id,
                position=1,
                aufgabe_typ="LIEFERANTENMAIL_BEARBEITEN",
            )
            session.add(vorlage)
            await session.flush()
            mail = Mail(
                message_id="<lieferant@test>",
                imap_uid=1,
                postfach_id=postfach.id,
                absender_name="Lieferant",
                absender_adresse="lieferant@example.test",
                betreff="Laufende Abstimmung",
                text_auszug="Rückfrage zu unserem Gespräch",
                empfangen_am=datetime.now(timezone.utc),
                klassifikation_id=alt.klassifikation_id,
                konfidenz=0.9,
                aktion_erforderlich=True,
                im_krautl_posteingang=True,
            )
            session.add(mail)
            await session.flush()
            session.add_all([
                MailAufgabe(
                    mail_id=mail.id,
                    klassifikation_aufgabe_id=vorlage.id,
                    position=1,
                    aufgabe_typ="LIEFERANTENMAIL_BEARBEITEN",
                    status="wartet",
                ),
                RollenMailzugriff(
                    rolle="sachbearbeiter",
                    klassifikation_id=alt.klassifikation_id,
                    darf_sehen=False,
                ),
            ])
            await session.commit()
            self.mail_id = mail.id

    async def test_kategorie_wird_ersetzt_und_ist_wiederholbar(self):
        async with SessionLocal() as session:
            ergebnis = await aktualisiere(session)
        self.assertEqual(1, ergebnis["umgestellte_offene_mails"])

        # Ein zweiter Lauf darf weder Kategorie noch Aufgaben duplizieren.
        async with SessionLocal() as session:
            await aktualisiere(session)

        async with SessionLocal() as session:
            self.assertIsNone(
                await session.get(Klassifikation, "LIEFERANT_PREISAENDERUNG")
            )
            diverse = await session.get(Klassifikation, "LIEFERANT_DIVERSES")
            self.assertEqual("einkauf@dreikraut.de", diverse.zielpostfach)
            self.assertEqual("INBOX", diverse.zielordner)
            self.assertEqual("BESTAETIGUNG_EINHOLEN", diverse.aktion_id)
            self.assertIn("laufende Abstimmungen", (
                await session.get(Klassifikation, "LIEFERANT_ANGEBOT")
            ).beschreibung)

            vorlagen = (await session.execute(
                select(KlassifikationAufgabe).where(
                    KlassifikationAufgabe.klassifikation_id == "LIEFERANT_DIVERSES"
                )
            )).scalars().all()
            self.assertEqual(
                ["BESTAETIGUNG_EINHOLEN"], [a.aufgabe_typ for a in vorlagen]
            )

            mail = await session.get(Mail, self.mail_id)
            self.assertEqual("LIEFERANT_DIVERSES", mail.klassifikation_id)
            aufgaben = (await session.execute(
                select(MailAufgabe).where(MailAufgabe.mail_id == self.mail_id)
            )).scalars().all()
            self.assertEqual(
                [("BESTAETIGUNG_EINHOLEN", "wartet")],
                [(a.aufgabe_typ, a.status) for a in aufgaben],
            )
            alte_rechte = (await session.execute(
                select(RollenMailzugriff).where(
                    RollenMailzugriff.klassifikation_id
                    == "LIEFERANT_PREISAENDERUNG"
                )
            )).scalars().all()
            self.assertEqual([], alte_rechte)
            neues_recht = (await session.execute(
                select(RollenMailzugriff).where(
                    RollenMailzugriff.klassifikation_id == "LIEFERANT_DIVERSES",
                    RollenMailzugriff.rolle == "sachbearbeiter",
                )
            )).scalar_one()
            self.assertFalse(neues_recht.darf_sehen)


if __name__ == "__main__":
    unittest.main()
