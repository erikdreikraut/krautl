"""Importiert historische Rechnungen aus den vier operativen Maileingängen.

Der Lauf liest IMAP ausschließlich. Mails werden weder markiert noch verschoben
oder gelöscht. Nur tatsächliche Rechnungen werden als ausgeblendete Quellmail
und als Rechnungsdatensatz in Krautl gespeichert. Die Originale landen im
angegebenen Dropbox-Ordner. Der Lauf ist dank Message-ID, Rechnungsschlüssel
und deterministischen Dateinamen wiederholbar.
"""

import argparse
import asyncio
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from imapclient import IMAPClient
from sqlalchemy import select

from app.db import SessionLocal
from app.imap_client import PostfachConfig, lade_postfaecher
from app.mail_parser import parse_eml, rechnungsanhaenge
from app.models import Aktionslog, Mail, Postfach
from app.rechnungen import rechnung_aus_rohdaten_verarbeiten


QUELLFUNKTIONEN = {"info", "service", "einkauf", "marketing"}
QUELLORDNER = "INBOX"
STANDARD_START = date(2026, 2, 1)
STANDARD_ENDE_EINSCHLIESSLICH = date(2026, 4, 30)
STANDARD_ZIELORDNER = "/Rechnungen/Eingang"
BATCH_GROESSE = 25


def _eingangsdatum_normalisieren(wert: datetime) -> datetime:
    if wert.tzinfo is None:
        return wert.replace(tzinfo=timezone.utc)
    return wert.astimezone(timezone.utc)


def _liegt_im_zeitraum(
    eingegangen_am: datetime,
    start: date,
    ende_exklusiv: date,
) -> bool:
    lokales_datum = _eingangsdatum_normalisieren(eingegangen_am).astimezone(
        ZoneInfo("Europe/Berlin")
    ).date()
    return start <= lokales_datum < ende_exklusiv


def _rechnungskandidaten_laden(
    config: PostfachConfig,
    ordner: str,
    start: date,
    ende_exklusiv: date,
) -> tuple[int, list[dict]]:
    """Ermittelt zeitlich passende UIDs, ohne vollständige Mails zu laden.

    Das IMAP-Suchergebnis wird anhand von INTERNALDATE nochmals lokal geprüft.
    So kann ein Server, der die Datumsbedingung ungenau auswertet, keine fremden
    Zeiträume in die teurere Rechnungsanalyse einschleusen.
    """
    with IMAPClient(config.host, ssl=True, timeout=60) as client:
        client.login(config.user, config.password)
        client.select_folder(ordner, readonly=True)
        uids = client.search(["SINCE", start, "BEFORE", ende_exklusiv])
        uids_im_zeitraum = []
        eingangszeiten = {}
        for position in range(0, len(uids), BATCH_GROESSE):
            batch = uids[position:position + BATCH_GROESSE]
            metadaten = client.fetch(batch, ["INTERNALDATE"])
            for uid in batch:
                eingegangen_am = metadaten.get(uid, {}).get(b"INTERNALDATE")
                if eingegangen_am is None:
                    continue
                eingegangen_am = _eingangsdatum_normalisieren(eingegangen_am)
                if not _liegt_im_zeitraum(eingegangen_am, start, ende_exklusiv):
                    continue
                uids_im_zeitraum.append(uid)
                eingangszeiten[uid] = eingegangen_am

        kandidaten = [
            {
                "uid": uid,
                "ordner": ordner,
                "eingegangen_am": eingangszeiten[uid],
            }
            for uid in uids_im_zeitraum
        ]
        return len(uids_im_zeitraum), kandidaten


def _rohdaten_batch_laden(
    config: PostfachConfig,
    ordner: str,
    uids: list[int],
) -> dict[int, bytes]:
    """Lädt höchstens einen kleinen Batch vollständiger Mails aus INBOX."""
    with IMAPClient(config.host, ssl=True, timeout=60) as client:
        client.login(config.user, config.password)
        client.select_folder(ordner, readonly=True)
        daten = client.fetch(uids, ["RFC822"])
        return {
            uid: eintrag[b"RFC822"]
            for uid, eintrag in daten.items()
            if eintrag.get(b"RFC822")
        }


async def _postfaecher_sicherstellen(
    configs: list[PostfachConfig],
) -> dict[str, int]:
    ids = {}
    async with SessionLocal() as session:
        for config in configs:
            postfach = (await session.execute(
                select(Postfach).where(Postfach.adresse == config.user)
            )).scalar_one_or_none()
            if postfach is None:
                postfach = Postfach(
                    adresse=config.user,
                    funktion=config.funktion,
                    imap_host=config.host,
                )
                session.add(postfach)
                await session.flush()
            ids[config.user.casefold()] = postfach.id
        await session.commit()
    return ids


async def _kandidat_verarbeiten(
    config: PostfachConfig,
    ordner: str,
    kandidat: dict,
    postfach_ids: dict[str, int],
    zielordner: str,
    bekannte_message_ids: set[str],
) -> dict:
    geparst = parse_eml(kandidat["raw"])
    message_id = geparst["message_id"]
    if message_id in bekannte_message_ids:
        return {"status": "uebersprungen"}
    bekannte_message_ids.add(message_id)

    async with SessionLocal() as session:
        mail = (await session.execute(
            select(Mail).where(Mail.message_id == message_id)
        )).scalar_one_or_none()
        if mail is None:
            mail = Mail(
                message_id=message_id,
                imap_uid=None,
                postfach_id=postfach_ids[config.user.casefold()],
                absender_name=geparst["absender_name"],
                absender_adresse=geparst["absender_adresse"],
                antwort_an_adresse=geparst.get("antwort_an_adresse"),
                betreff=geparst["betreff"],
                text_auszug=geparst["text_auszug"],
                empfangen_am=kandidat["eingegangen_am"],
                spam_score=geparst["spam_score"],
                anhang_dateinamen=geparst.get("anhang_dateinamen") or None,
                pruefstatus="geprueft",
                im_krautl_posteingang=False,
                zustaendig_admin=True,
                zustaendig_sachbearbeiter=False,
            )
            session.add(mail)
            await session.flush()
        try:
            verarbeitet = await rechnung_aus_rohdaten_verarbeiten(
                session,
                mail,
                kandidat["raw"],
                zielordner=zielordner,
                jahresordner=False,
                dubletten_erneut_ablegen=True,
            )
        except RuntimeError as exc:
            await session.rollback()
            if "enthalten laut Auswertung keine Rechnung" in str(exc):
                return {"status": "keine_rechnung"}
            return {"status": "fehler", "detail": str(exc)}
        except Exception as exc:
            await session.rollback()
            return {"status": "fehler", "detail": str(exc)}

        rechnungen = verarbeitet["rechnungen"]
        session.add(Aktionslog(
            mail_id=mail.id,
            ereignis="historische_rechnung_importiert",
            ausgeloest_von="Krautl",
            detail=(
                f"{len(rechnungen)} Rechnung(en) aus {config.user}/{ordner} "
                f"nach /{zielordner.strip('/')} abgelegt"
            ),
        ))
        await session.commit()
        return {
            "status": "verarbeitet",
            "rechnungen": len(rechnungen),
            "dubletten": sum(
                1 for rechnung in rechnungen if rechnung["dublette"]
            ),
        }


async def importieren(
    start: date = STANDARD_START,
    ende_einschliesslich: date = STANDARD_ENDE_EINSCHLIESSLICH,
    zielordner: str = STANDARD_ZIELORDNER,
    configs: list[PostfachConfig] | None = None,
) -> dict:
    ende_exklusiv = ende_einschliesslich + timedelta(days=1)
    alle_configs = configs if configs is not None else lade_postfaecher()
    quellconfigs = [
        config for config in alle_configs
        if config.funktion.casefold() in QUELLFUNKTIONEN
    ]
    vorhanden = {config.funktion.casefold() for config in quellconfigs}
    fehlend = sorted(QUELLFUNKTIONEN - vorhanden)
    if fehlend:
        raise RuntimeError(
            "Folgende historische Quellpostfächer sind nicht vollständig "
            f"konfiguriert: {', '.join(fehlend)}"
        )

    postfach_ids = await _postfaecher_sicherstellen(quellconfigs)
    ergebnis = {
        "postfaecher": len(quellconfigs),
        "ordner": 0,
        "mails_im_zeitraum": 0,
        "kandidaten": 0,
        "rechnungen": 0,
        "dubletten": 0,
        "keine_rechnung": 0,
        "fehler": [],
        "zielordner": "/" + zielordner.strip("/"),
    }
    bekannte_message_ids: set[str] = set()

    for config in quellconfigs:
        ordner = QUELLORDNER
        ergebnis["ordner"] += 1
        try:
            anzahl, kandidaten = await asyncio.to_thread(
                _rechnungskandidaten_laden,
                config,
                ordner,
                start,
                ende_exklusiv,
            )
        except Exception as exc:
            ergebnis["fehler"].append(
                f"{config.user}/{ordner}: Abruf: {exc}"
            )
            continue
        ergebnis["mails_im_zeitraum"] += anzahl
        print(
            f"{config.user}/{ordner}: {anzahl} Mail(s) im Zeitraum; "
            "prüfe Anhänge speicherschonend in kleinen Blöcken"
        )

        postfach_kandidaten = 0
        for position in range(0, len(kandidaten), BATCH_GROESSE):
            batch = kandidaten[position:position + BATCH_GROESSE]
            uids = [kandidat["uid"] for kandidat in batch]
            try:
                rohdaten = await asyncio.to_thread(
                    _rohdaten_batch_laden, config, ordner, uids
                )
            except Exception as exc:
                ergebnis["fehler"].append(
                    f"{config.user}/{ordner}/UIDs {uids[0]}–{uids[-1]}: Abruf: {exc}"
                )
                continue

            for kandidat in batch:
                raw = rohdaten.get(kandidat["uid"])
                if not raw or not rechnungsanhaenge(raw):
                    continue
                postfach_kandidaten += 1
                ergebnis["kandidaten"] += 1
                ausgang = await _kandidat_verarbeiten(
                    config,
                    ordner,
                    {**kandidat, "raw": raw},
                    postfach_ids,
                    zielordner,
                    bekannte_message_ids,
                )
                if ausgang["status"] == "keine_rechnung":
                    ergebnis["keine_rechnung"] += 1
                elif ausgang["status"] == "fehler":
                    ergebnis["fehler"].append(
                        f"{config.user}/{ordner}/UID {kandidat['uid']}: "
                        f"{ausgang['detail']}"
                    )
                elif ausgang["status"] == "verarbeitet":
                    ergebnis["rechnungen"] += ausgang["rechnungen"]
                    ergebnis["dubletten"] += ausgang["dubletten"]

            print(
                f"{config.user}/{ordner}: {min(position + len(batch), anzahl)} "
                f"von {anzahl} Mail(s) geprüft; "
                f"{postfach_kandidaten} mit unterstütztem Anhang"
            )

    return ergebnis


def _datum_argument(wert: str) -> date:
    try:
        return date.fromisoformat(wert)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Datum muss YYYY-MM-DD sein") from exc


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=_datum_argument, default=STANDARD_START)
    parser.add_argument(
        "--ende-einschliesslich",
        type=_datum_argument,
        default=STANDARD_ENDE_EINSCHLIESSLICH,
    )
    parser.add_argument("--zielordner", default=STANDARD_ZIELORDNER)
    args = parser.parse_args()
    ergebnis = asyncio.run(importieren(
        start=args.start,
        ende_einschliesslich=args.ende_einschliesslich,
        zielordner=args.zielordner,
    ))
    print("Historischer Rechnungslauf abgeschlossen:")
    for schluessel, wert in ergebnis.items():
        if schluessel == "fehler":
            continue
        print(f"  {schluessel}: {wert}")
    if ergebnis["fehler"]:
        print(f"  fehler: {len(ergebnis['fehler'])}")
        for fehler in ergebnis["fehler"]:
            print(f"    - {fehler}")


if __name__ == "__main__":
    main()
