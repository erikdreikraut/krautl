"""Convert a user-confirmed JTL-Shop Ameise export to a local preview bundle."""
import argparse
import base64
import csv
import json
from pathlib import Path
from app.bilder_abgleich import vorschaubild


def erstellen(csv_path, ziel):
    csv_path = Path(csv_path)
    raw = csv_path.read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp1252")
    rows = list(csv.DictReader(text.splitlines(), delimiter=";"))
    if len(rows) != 1:
        raise ValueError("Für diese Vorschau genau einen Artikel exportieren.")
    row = rows[0]
    bilder = []
    positionen = set()
    for key, name in row.items():
        if not key or not key.startswith("Bild ") or not name:
            continue
        nr = key[5:]
        pos = int(row["Nummer " + nr])
        if pos in positionen:
            raise ValueError("Doppelte Bildposition.")
        positionen.add(pos)
        file = (csv_path.parent / name).resolve()
        if file.parent != csv_path.parent.resolve() or file.suffix.lower() not in (".jpg", ".jpeg", ".png"):
            raise ValueError("Bilddatei muss im Exportordner liegen.")
        if file.stat().st_size != int(row["Bildgröße " + nr]):
            raise ValueError("Dateigröße passt nicht zur CSV.")
        bilder.append({"position": pos, "jpeg": base64.b64encode(vorschaubild(file.read_bytes())).decode("ascii")})
    if not bilder:
        raise ValueError("Keine Bilder im Export.")
    data = {"format": "krautl-shopvorschau-1", "kanal": "2-2-1", "sku": row["Artikelnummer"], "bilder": bilder}
    Path(ziel).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    print("Vorschaudatei erstellt:", ziel, "| Artikel:", data["sku"], "| Bilder:", len(bilder))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("csv")
    parser.add_argument("ziel")
    parser.add_argument("--jtl-shop-bestaetigt", action="store_true", required=True,
                        help="Bestätigt, dass in Ameise ausschließlich JTL-Shop ausgewählt war.")
    args = parser.parse_args()
    erstellen(args.csv, args.ziel)
