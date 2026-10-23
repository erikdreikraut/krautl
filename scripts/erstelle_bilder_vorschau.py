"""Convert a user-confirmed JTL-Shop Ameise export to a local preview bundle."""
import argparse
import base64
import csv
import json
from pathlib import Path
from app.bilder_abgleich import vorschaubild
from app.jtl_client import JtlFehler


def artikel_vorbereiten(row, ordner):
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
        file = (ordner / name).resolve()
        if file.parent != ordner.resolve() or file.suffix.lower() not in (".jpg", ".jpeg", ".png", ".webp"):
            raise ValueError("Bilddatei muss im Exportordner liegen.")
        if file.stat().st_size != int(row["Bildgröße " + nr]):
            raise ValueError("Dateigröße passt nicht zur CSV.")
        bilder.append({"position": pos, "jpeg": base64.b64encode(vorschaubild(file.read_bytes())).decode("ascii")})
    if not bilder:
        raise ValueError("Keine Bilder im Export.")
    return {"format": "krautl-shopvorschau-1", "kanal": "2-2-1", "sku": row["Artikelnummer"], "bilder": bilder}


def erstellen(csv_path, ziel):
    csv_path = Path(csv_path)
    raw = csv_path.read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp1252")
    rows = list(csv.DictReader(text.splitlines(), delimiter=";"))
    skus = [r.get("Artikelnummer", "") for r in rows]
    if not rows or any(not sku.strip() for sku in skus) or len(set(skus)) != len(skus):
        raise ValueError("Fehlende oder doppelte Artikelnummern im Export.")
    artikel, ausgelassen = [], []
    for row in rows:
        try:
            data = artikel_vorbereiten(row, csv_path.parent)
            if len(json.dumps(data, ensure_ascii=False).encode("utf-8")) > 1024 * 1024:
                raise ValueError("Artikel-Vorschaudatei überschreitet 1 MB.")
            artikel.append(data)
        except (ValueError, OSError, KeyError, JtlFehler) as exc:
            ausgelassen.append({"sku": row["Artikelnummer"], "grund": str(exc)})
    if not artikel:
        raise ValueError("Kein Artikel vollständig verwendbar: " + str(ausgelassen))
    data = artikel[0] if len(rows) == 1 and not ausgelassen else {
        "format": "krautl-shopvorschau-2", "kanal": "2-2-1",
        "artikel": artikel, "ausgelassen": ausgelassen}
    output = json.dumps(data, ensure_ascii=False)
    if len(output.encode("utf-8")) > 20 * 1024 * 1024:
        raise ValueError("Gesamtexport überschreitet 20 MB; bitte Export aufteilen.")
    Path(ziel).write_text(output, encoding="utf-8")
    print("Vorschaudatei:", ziel, "| Artikel:", len(artikel), "| Bilder:",
          sum(len(a["bilder"]) for a in artikel), "| Ausgelassen:", len(ausgelassen))
    for item in ausgelassen:
        print("Ausgelassen:", item["sku"], item["grund"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("csv")
    parser.add_argument("ziel")
    parser.add_argument("--jtl-shop-bestaetigt", action="store_true", required=True,
                        help="Bestätigt, dass in Ameise ausschließlich JTL-Shop ausgewählt war.")
    args = parser.parse_args()
    erstellen(args.csv, args.ziel)
