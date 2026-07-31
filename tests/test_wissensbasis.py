import os
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from sqlalchemy import select

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_wissensbasis.db")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")

from app.db import SessionLocal, engine
from app.models import (
    Base, Entwurf, FaqEintrag, Mail, Postfach, Produkt, Produktfamilie,
    Wissenseintrag, WissensVorschlag,
)
from app.wissensbasis import (
    faq_als_jtl_html, relevante_wissensbasis,
    wissenszuwachs_nach_antwort_pruefen,
)


class WissensbasisTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        async with SessionLocal() as session:
            familie = Produktfamilie(name="Hagebutte")
            postfach = Postfach(
                adresse="service@dreikraut.de", funktion="service", imap_host="imap.test"
            )
            session.add_all([familie, postfach])
            await session.flush()
            produkt = Produkt(
                produktfamilie_id=familie.id,
                name="Bio-Hagebuttenpulver aus EU-Wildsammlung",
                artikelnummer="20810",
                aliases=["Hagebuttenpulver"],
            )
            session.add(produkt)
            await session.flush()
            session.add_all([
                Wissenseintrag(
                    wissensart="allgemein", titel="Versand", inhalt="Versandwissen",
                    status="freigegeben",
                ),
                Wissenseintrag(
                    wissensart="produkt", produkt_id=produkt.id,
                    titel="Anwendung", inhalt="Produktwissen", status="freigegeben",
                ),
                FaqEintrag(
                    produkt_id=produkt.id, kategorie="Anwendung & Praktisches",
                    frage="Wie einnehmen?", antwort="Kalt oder lauwarm einrühren.",
                    status="freigegeben", aktiv=True,
                ),
            ])
            mail = Mail(
                message_id="<wissen@example.test>", postfach_id=postfach.id,
                absender_name="Ada", absender_adresse="ada@example.test",
                betreff="Frage zum Hagebuttenpulver", text_auszug="Wie nehme ich es ein?",
                empfangen_am=datetime.now(timezone.utc),
            )
            session.add(mail)
            await session.commit()
            self.mail_id = mail.id
            self.produkt_id = produkt.id

    async def test_passendes_produktwissen_und_faq_werden_geladen(self):
        async with SessionLocal() as session:
            mail = await session.get(Mail, self.mail_id)
            produkt, wissen, faq = await relevante_wissensbasis(session, mail)
        self.assertEqual(self.produkt_id, produkt.id)
        self.assertEqual({"Versand", "Anwendung"}, {e.titel for e in wissen})
        self.assertEqual(["Wie einnehmen?"], [e.frage for e in faq])

    async def test_export_hat_jtl_accordion_und_schema_org(self):
        async with SessionLocal() as session:
            produkt = await session.get(Produkt, self.produkt_id)
            faq = [e for e in (await session.execute(
                select(FaqEintrag)
            )).scalars().all()]
        export = faq_als_jtl_html(produkt, faq)
        self.assertIn('itemtype="https://schema.org/FAQPage"', export)
        self.assertIn('data-target="#faq-1"', export)
        self.assertIn("Anwendung &amp; Praktisches", export)
        self.assertIn("Kalt oder lauwarm einrühren.", export)

    async def test_export_unterstuetzt_einfache_formatierung_ohne_rohes_html(self):
        async with SessionLocal() as session:
            produkt = await session.get(Produkt, self.produkt_id)
            faq = [FaqEintrag(
                id=99, produkt_id=produkt.id, kategorie="Test",
                frage="Was ist wichtig?",
                antwort="**Wichtig**\n\n- Punkt eins\n- Punkt zwei\n\n<script>nein</script>",
                status="freigegeben", aktiv=True,
            )]
        export = faq_als_jtl_html(produkt, faq)
        self.assertIn("<strong>Wichtig</strong>", export)
        self.assertIn("<ul>", export)
        self.assertIn("&lt;script&gt;nein&lt;/script&gt;", export)
        self.assertNotIn("<script>", export)

    async def test_unveraenderter_entwurf_erzeugt_keinen_vorschlag(self):
        async with SessionLocal() as session:
            mail = await session.get(Mail, self.mail_id)
            entwurf = Entwurf(mail_id=mail.id, text_ki="Gleicher Text", status="versendet")
            session.add(entwurf)
            await session.flush()
            with patch("app.wissensbasis._vorschlag_synchron") as pruefung:
                ergebnis = await wissenszuwachs_nach_antwort_pruefen(
                    session, mail, entwurf, "Gleicher Text"
                )
            self.assertIsNone(ergebnis)
            pruefung.assert_not_called()

    async def test_manuelle_ergaenzung_wird_nur_als_entwurf_vorgeschlagen(self):
        async with SessionLocal() as session:
            mail = await session.get(Mail, self.mail_id)
            entwurf = Entwurf(mail_id=mail.id, text_ki="Kurze Antwort", status="versendet")
            session.add(entwurf)
            await session.flush()
            ki_ergebnis = {
                "vorschlag_noetig": True,
                "ziel": "faq",
                "wissensart": "produkt",
                "produkt_id": self.produkt_id,
                "titel": "Wie wird das Pulver eingerührt?",
                "inhalt": "Das Pulver kann kalt oder lauwarm eingerührt werden.",
                "begruendung": "Die Ergänzung ist wiederverwendbar.",
            }
            with patch(
                "app.wissensbasis._vorschlag_synchron", return_value=ki_ergebnis
            ):
                ergebnis = await wissenszuwachs_nach_antwort_pruefen(
                    session, mail, entwurf, "Kurze Antwort mit neuer Fachinformation"
                )
            await session.commit()

        self.assertEqual("offen", ergebnis.status)
        self.assertEqual("faq", ergebnis.ziel)
        async with SessionLocal() as session:
            self.assertEqual(1, len((await session.execute(
                select(WissensVorschlag)
            )).scalars().all()))
            # Ein Vorschlag darf niemals unmittelbar als FAQ veröffentlicht werden.
            self.assertEqual(1, len((await session.execute(
                select(FaqEintrag)
            )).scalars().all()))


if __name__ == "__main__":
    unittest.main()
