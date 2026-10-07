"""Read one JTL article using Krautl credentials; never writes Wawi data."""
import argparse
import asyncio
import hashlib
import json
import sys

from app.jtl_client import JtlClient, JtlFehler


def diagnose(artikel):
    result = {"artikel_id": artikel["id"], "artikelnummer": artikel["identifiers"]["sku"], "attribute": []}
    for attribut in (artikel.get("attributes") or {}).get("values") or []:
        eintrag = {"attribut_id": attribut.get("attributeId"), "werte": []}
        gruppen = [("Standard/JTL-Wawi", attribut.get("defaultValues") or [])]
        gruppen.extend((kanal.get("salesChannelId"), kanal.get("values") or []) for kanal in attribut.get("salesChannelValues") or [])
        for kanal, werte in gruppen:
            for wert in werte:
                text = wert.get("value") or ""
                eintrag["werte"].append({"kanal": kanal, "sprache": wert.get("languageIso"),
                    "zeichen": len(text), "sha256": hashlib.sha256(text.encode()).hexdigest(),
                    "faq_titel": text.strip() == "Fragen / Antworten",
                    "faq_html": 'schema.org/FAQPage' in text})
        result["attribute"].append(eintrag)
    return result


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artikelnummer", required=True, help="Exakte SKU eines bekannten Artikels mit vorhandenen FAQ-Attributen")
    args = parser.parse_args()
    try:
        async with JtlClient.aus_umgebung() as client:
            artikel = await client.artikel_lesen(args.artikelnummer)
        print(json.dumps(diagnose(artikel), ensure_ascii=False, indent=2))
    except JtlFehler as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
