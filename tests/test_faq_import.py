import io
import unittest
import zipfile
from types import SimpleNamespace
from unittest.mock import patch

from tests.test_google_product_qa import FeedApiTest
from app.faq_import import Paar, dokument_inhalt, zuordnen


class DokumentTest(unittest.TestCase):
    def test_artikelnummer_hat_vorrang_und_nullen_bleiben(self):
        produkte = [SimpleNamespace(id=1, name="Eins", artikelnummer="001"), SimpleNamespace(id=2, name="Zwei", artikelnummer="2")]
        p = Paar(artikelnummer="001", produkt_id=2, produktname="Zwei", frage="F?", antwort="A")
        self.assertEqual(zuordnen(p, produkte)[0], 1)
        self.assertTrue(zuordnen(p, produkte)[1])
        p.artikelnummer = "unbekannt"
        self.assertIsNone(zuordnen(p, produkte)[0])
        p.artikelnummer = ""
        self.assertEqual(zuordnen(p, produkte)[0], 2)
        p.produkt_id = None
        self.assertEqual(zuordnen(p, produkte)[0], 2)
        self.assertIsNone(zuordnen(p, produkte + [produkte[1]])[0])

    def test_dateiformate_und_fehler(self):
        self.assertEqual(dokument_inhalt("a.txt", b"Frage? Antwort.")["text"], "Frage? Antwort.")
        with self.assertRaises(ValueError): dokument_inhalt("a.exe", b"abc")
        with self.assertRaises(ValueError): dokument_inhalt("a.pdf", b"abc")
        with self.assertRaises(ValueError): dokument_inhalt("a.docx", b"abc")
        with self.assertRaises(ValueError): dokument_inhalt("a.txt", b" ")
        doc = io.BytesIO()
        with zipfile.ZipFile(doc, "w") as z:
            z.writestr("word/document.xml", '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:p><w:r><w:t>Frage?</w:t></w:r></w:p><w:p><w:r><w:t>Antwort.</w:t></w:r></w:p></w:document>')
        self.assertEqual(dokument_inhalt("a.docx", doc.getvalue())["text"], "Frage?\nAntwort.")
        self.assertEqual(dokument_inhalt("a.pdf", b"%PDF-1.7\n")["source"]["media_type"], "application/pdf")


class ImportApiTest(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = FeedApiTest.asyncSetUp
    asyncTearDown = FeedApiTest.asyncTearDown

    def paar(self, **werte):
        return {"produkt_id": self.produkt_id, "frage": "Wie anwenden?", "antwort": "Vorsichtig.", **werte}

    async def test_analyse_nur_vorschau_und_auth(self):
        with patch("app.faq_import.auswerten", return_value=[Paar(artikelnummer="00123", frage="Wie?", antwort="So.")]) as ki:
            r = await self.client.post("/faq/import/analyse", files={"datei": ("faq.txt", b"test")})
            self.assertEqual(r.status_code, 401)
            ki.assert_not_called()
            r = await self.client.post("/faq/import/analyse", headers=self.headers, files={"datei": ("faq.txt", b"test")})
            self.assertEqual(r.status_code, 200, r.text)
            self.assertEqual(r.json()["eintraege"][0]["produkt_id"], self.produkt_id)
            self.assertEqual((await self.client.get("/faq", headers=self.headers)).json(), [])

    async def test_import_entwurf_inaktiv_und_wiederholung(self):
        daten = {"dateiname": "faq.txt", "eintraege": [self.paar(), self.paar()]}
        r = await self.client.post("/faq/import/uebernehmen", headers=self.headers, json=daten)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json(), {"angelegt": 1, "uebersprungen": 1})
        r = await self.client.post("/faq/import/uebernehmen", headers=self.headers, json=daten)
        self.assertEqual(r.json()["angelegt"], 0)
        faq = (await self.client.get("/faq", headers=self.headers)).json()[0]
        self.assertEqual(faq["status"], "entwurf")
        self.assertFalse(faq["aktiv"])
        self.assertFalse(faq["include_in_google_product_qa"])
        daten["eintraege"][0]["antwort"] = "Andere Antwort"
        await self.client.post("/faq/import/uebernehmen", headers=self.headers, json=daten)
        self.assertEqual((await self.client.get("/faq", headers=self.headers)).json()[0]["antwort"], "Vorsichtig.")

    async def test_ungueltiges_batch_speichert_nichts(self):
        for fehler in ({"produkt_id": None}, {"produkt_id": 99999}, {"frage": " "}):
            r = await self.client.post("/faq/import/uebernehmen", headers=self.headers, json={"eintraege": [self.paar(), self.paar(**fehler)]})
            self.assertEqual(r.status_code, 422, r.text)
            self.assertEqual((await self.client.get("/faq", headers=self.headers)).json(), [])

    async def test_dateigrenzen_und_ki_fehler(self):
        with patch("app.faq_import.auswerten", side_effect=RuntimeError("secret")) as ki:
            for name, data, status in [("a.exe", b"x", 422), ("a.txt", b"", 422), ("a.txt", b"x" * (10 * 1024 * 1024 + 1), 413)]:
                r = await self.client.post("/faq/import/analyse", headers=self.headers, files={"datei": (name, data)})
                self.assertEqual(r.status_code, status)
            ki.assert_not_called()
            r = await self.client.post("/faq/import/analyse", headers=self.headers, files={"datei": ("a.txt", b"text")})
            self.assertEqual(r.status_code, 502)
            self.assertNotIn("secret", r.text)
