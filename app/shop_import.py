"""Liest den aktuell sichtbaren Produktbestand aus dem dreikraut-Shop ein."""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from sqlalchemy import select

from .models import Produkt


SHOP_BASIS = "https://dreikraut.de"
PRODUKTLISTE_PFAD = "/Blueten"
ERSTE_PRODUKTSEITE = f"{SHOP_BASIS}{PRODUKTLISTE_PFAD}"
SEITEN_MUSTER = re.compile(r'href=["\']https://dreikraut\.de/_s(\d+)["\']', re.I)
ARTIKELNUMMER_MUSTER = re.compile(r"(?:/|\b)(\d{5,})_[^/\s\"']+", re.I)


@dataclass(frozen=True)
class ShopProdukt:
    name: str
    artikelnummer: str | None
    website_url: str


class _ProduktParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.produkte: list[ShopProdukt] = []
        self._produkt_tiefe = 0
        self._titel_tiefe = 0
        self._name_teile: list[str] = []
        self._url: str | None = None
        self._artikelnummer: str | None = None

    @staticmethod
    def _klassen(attribute: dict[str, str | None]) -> set[str]:
        return set((attribute.get("class") or "").split())

    def handle_starttag(self, tag: str, attrs):
        attribute = dict(attrs)
        klassen = self._klassen(attribute)
        if tag == "div" and not self._produkt_tiefe and "product-wrapper" in klassen:
            self._produkt_tiefe = 1
            self._titel_tiefe = 0
            self._name_teile = []
            self._url = None
            self._artikelnummer = None
        elif self._produkt_tiefe and tag == "div":
            self._produkt_tiefe += 1

        if not self._produkt_tiefe:
            return
        if tag == "div" and "productbox-title" in klassen:
            self._titel_tiefe = self._produkt_tiefe
        if tag == "a" and self._titel_tiefe:
            self._url = attribute.get("href") or self._url
        if not self._artikelnummer:
            for wert in attribute.values():
                treffer = ARTIKELNUMMER_MUSTER.search(wert or "")
                if treffer:
                    self._artikelnummer = treffer.group(1)
                    break

    def handle_data(self, data: str):
        if self._produkt_tiefe and self._titel_tiefe and data.strip():
            self._name_teile.append(data.strip())

    def handle_endtag(self, tag: str):
        if not self._produkt_tiefe or tag != "div":
            return
        if self._titel_tiefe == self._produkt_tiefe:
            self._titel_tiefe = 0
        self._produkt_tiefe -= 1
        if self._produkt_tiefe:
            return

        name = " ".join(" ".join(self._name_teile).split())
        if name and self._url and _ist_shop_produkt_url(self._url):
            self.produkte.append(ShopProdukt(
                name=html.unescape(name),
                artikelnummer=self._artikelnummer,
                website_url=self._url.split("?", 1)[0],
            ))


def _ist_shop_produkt_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme == "https" and parsed.netloc == "dreikraut.de" and bool(parsed.path.strip("/"))


def produktseite_auslesen(text: str) -> list[ShopProdukt]:
    parser = _ProduktParser()
    parser.feed(text)
    return parser.produkte


def seitenzahl_ermitteln(text: str) -> int:
    nummern = [int(nummer) for nummer in SEITEN_MUSTER.findall(text)]
    return max(nummern, default=1)


def _seite_laden(url: str) -> str:
    request = Request(url, headers={"User-Agent": "Krautl Produktabgleich/1.0"})
    with urlopen(request, timeout=30) as antwort:
        return antwort.read().decode("utf-8", errors="replace")


def shop_katalog_laden() -> list[ShopProdukt]:
    erste_seite = _seite_laden(ERSTE_PRODUKTSEITE)
    seiten = [erste_seite]
    for nummer in range(2, seitenzahl_ermitteln(erste_seite) + 1):
        # JTL zeigt in der Seitennavigation verkürzte Links wie ``/_s2``.
        # Direkt abrufbar bleibt der Produktlisten-Kontext über ``/Blueten_s2``.
        seiten.append(_seite_laden(f"{SHOP_BASIS}{PRODUKTLISTE_PFAD}_s{nummer}"))

    nach_url: dict[str, ShopProdukt] = {}
    for seite in seiten:
        for produkt in produktseite_auslesen(seite):
            nach_url[produkt.website_url.casefold()] = produkt
    if not nach_url:
        raise RuntimeError("Der Shop hat keine Produkte geliefert")
    return list(nach_url.values())


async def shop_katalog_speichern(session, katalog: list[ShopProdukt]) -> dict[str, int]:
    vorhandene = (await session.execute(select(Produkt))).scalars().all()
    nach_artikelnummer = {
        produkt.artikelnummer.casefold(): produkt
        for produkt in vorhandene if produkt.artikelnummer
    }
    nach_url = {
        produkt.website_url.rstrip("/").casefold(): produkt
        for produkt in vorhandene if produkt.website_url
    }
    nach_name = {produkt.name.casefold(): produkt for produkt in vorhandene}

    angelegt = 0
    aktualisiert = 0
    for shop_produkt in katalog:
        produkt = None
        if shop_produkt.artikelnummer:
            produkt = nach_artikelnummer.get(shop_produkt.artikelnummer.casefold())
        produkt = produkt or nach_url.get(shop_produkt.website_url.rstrip("/").casefold())
        produkt = produkt or nach_name.get(shop_produkt.name.casefold())

        if produkt is None:
            produkt = Produkt(
                name=shop_produkt.name,
                artikelnummer=shop_produkt.artikelnummer,
                aliases=[],
                website_url=shop_produkt.website_url,
                aktiv=True,
            )
            session.add(produkt)
            vorhandene.append(produkt)
            angelegt += 1
        else:
            # Die Zuordnung zu einer Produktfamilie und eigene Suchbegriffe sind
            # redaktionell gepflegt und werden beim Shop-Abgleich nicht angetastet.
            produkt.name = shop_produkt.name
            produkt.website_url = shop_produkt.website_url
            produkt.artikelnummer = shop_produkt.artikelnummer or produkt.artikelnummer
            produkt.aktiv = True
            aktualisiert += 1

    await session.commit()
    return {
        "im_shop": len(katalog),
        "angelegt": angelegt,
        "aktualisiert": aktualisiert,
    }
