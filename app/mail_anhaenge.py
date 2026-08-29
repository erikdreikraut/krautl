"""Lädt einzelne Mail-Anhänge bei Bedarf erneut aus IMAP.

Anhangs-Inhalte werden bewusst nicht in der Datenbank gehalten (nur die
Dateinamen stehen in Mail.anhang_dateinamen) — beim Ansehen/Herunterladen
wird die Original- oder bereits verschobene Mail per Message-ID erneut
geladen, nach demselben Muster wie die Rechnungsanhänge in rechnungen.py.
"""
import asyncio

from .imap_client import lade_postfaecher, mail_rohdaten_nach_message_id_laden
from .mail_parser import alle_anhaenge
from .models import Mail


async def mail_rohdaten_aus_ablage_laden(
    mail: Mail,
    quellpostfach: str | None,
    zielpostfach: str | None,
    zielordner: str | None,
) -> bytes:
    """Lädt die Originalmail aus ihrem aktuellen oder ursprünglichen Ablageort."""
    configs = {config.user.casefold(): config for config in lade_postfaecher()}
    orte: list[tuple[str, str]] = []
    if zielpostfach:
        orte.append((zielpostfach, zielordner or "INBOX"))
    if quellpostfach:
        quellort = (quellpostfach, "INBOX")
        if quellort not in orte:
            orte.append(quellort)

    fehler: list[str] = []
    for adresse, ordner in orte:
        config = configs.get(adresse.casefold())
        if config is None:
            fehler.append(f"{adresse}/{ordner}: Postfach nicht konfiguriert")
            continue
        try:
            return await asyncio.to_thread(
                mail_rohdaten_nach_message_id_laden, config, mail.message_id, ordner,
            )
        except Exception as exc:
            fehler.append(f"{adresse}/{ordner}: {exc}")
    raise RuntimeError(" | ".join(fehler) or "Kein IMAP-Ablageort bekannt")


async def anhang_aus_mail_laden(
    mail: Mail,
    index: int,
    quellpostfach: str | None,
    zielpostfach: str | None,
    zielordner: str | None,
) -> tuple[str, bytes]:
    """Lädt einen einzelnen Anhang aus der Original- oder verschobenen Mail."""
    eml = await mail_rohdaten_aus_ablage_laden(
        mail, quellpostfach, zielpostfach, zielordner,
    )
    anhaenge = await asyncio.to_thread(alle_anhaenge, eml)
    if not 0 <= index < len(anhaenge):
        raise IndexError(
            f"Anhang-Index {index} existiert nicht (nur {len(anhaenge)} Anhänge vorhanden)"
        )
    anhang = anhaenge[index]
    return anhang["dateiname"], anhang["inhalt"]
