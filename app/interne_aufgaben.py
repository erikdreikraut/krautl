"""Feste Erkennung für von dreikraut-Systemen erzeugte Aufgabenhinweise."""


LAGER_MARKER = (
    "lagerbestand",
    "lagerbestände",
    "lagerbestaende",
    "bestandsinformation",
    "bestandsabweichung",
    "bestandswarnung",
    "bestand niedrig",
    "bestand unterschritten",
    "negativer bestand",
    "fehlbestand",
    "nicht auf lager",
    "low stock",
    "stock alert",
    "inventory alert",
)

ADRESS_MARKER = (
    "adressfehler",
    "adresse fehlerhaft",
    "adresse möglicherweise fehlerhaft",
    "adresse moeglicherweise fehlerhaft",
    "möglicher adressfehler",
    "moeglicher adressfehler",
    "adresse prüfen",
    "adresse pruefen",
    "adressprüfung",
    "adresspruefung",
    "ungültige adresse",
    "ungueltige adresse",
    "lieferadresse prüfen",
    "lieferadresse pruefen",
    "address error",
    "invalid address",
)


def ist_dreikraut_absender(absender_adresse: str | None) -> bool:
    adresse = str(absender_adresse or "").strip().casefold()
    domain = adresse.rsplit("@", 1)[-1].rstrip(".") if "@" in adresse else ""
    return domain == "dreikraut.de" or domain.endswith(".dreikraut.de")


def ist_interne_aufgabenmail(
    absender_adresse: str | None,
    betreff: str | None,
    text: str | None,
) -> bool:
    if not ist_dreikraut_absender(absender_adresse):
        return False
    inhalt = f"{betreff or ''}\n{text or ''}".casefold()
    return any(marker in inhalt for marker in (*LAGER_MARKER, *ADRESS_MARKER))
