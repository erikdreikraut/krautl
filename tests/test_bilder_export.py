import csv
import json
import os
import tempfile
import unittest
from pathlib import Path
from PIL import Image
os.environ.setdefault("ANTHROPIC_API_KEY", "test")
from scripts.erstelle_bilder_vorschau import erstellen


class ExportTest(unittest.TestCase):
    def test_batch_validates_files_and_skips_whole_incomplete_articles(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            Image.new("RGB", (20, 20), "green").save(root / "A.webp")
            Image.new("RGB", (20, 20), "red").save(root / "unrelated.jpg")
            size = (root / "A.webp").stat().st_size
            source = root / "export.csv"
            with source.open("w", encoding="cp1252", newline="") as f:
                writer = csv.writer(f, delimiter=";")
                writer.writerow(["Artikelnummer", "Bild 1", "Nummer 1", "Bildgröße 1"])
                writer.writerows([["A", "A.webp", 1, size], ["B", "missing.jpg", 1, 50],
                                 ["C", "A.webp", 1, size+1]])
            erstellen(source, root / "out.json")
            data = json.loads((root / "out.json").read_text(encoding="utf-8"))
            self.assertEqual(data["format"], "krautl-shopvorschau-2")
            self.assertEqual([a["sku"] for a in data["artikel"]], ["A"])
            self.assertEqual([a["sku"] for a in data["ausgelassen"]], ["B", "C"])
            self.assertTrue((root / "unrelated.jpg").exists())

    def test_duplicate_skus_rejected_before_output(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "export.csv"
            source.write_text("Artikelnummer;Bild 1\nA;x.jpg\nA;y.jpg\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "doppelte"):
                erstellen(source, root / "out.json")
            self.assertFalse((root / "out.json").exists())
