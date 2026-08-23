"""Importiert historische Rechnungen aus den vier operativen Postfächern.

Der Lauf liest IMAP ausschließlich. Mails werden weder markiert noch verschoben
oder gelöscht. Nur tatsächliche Rechnungen werden als ausgeblendete Quellmail
und als Rechnungsdatensatz in Krautl gespeichert. Die Originale landen im
angegebenen Dropbox-Ordner. Der Lauf ist dank Message-ID, Rechnungsschlüssel
und deterministischen Dateinamen wiederholbar.
"""

import argparse
import asyncio
from datetime import date, datetime, timedelta, timezone

from imapclient import IMAPClient
from sqlalchemy import select

from app.db import SessionLocal
from app.imap_client import PostfachConfig, lade_postfaecher
from app.mail_parser import parse_eml, rechnungsanhaenge
from app.models import Aktionslog, Mail, Postfach
from app.rechnungen import rechnung_aus_rohdaten_verarbeiten


QUELLFUNKTIONEN = {"info", "service", "einkauf", "marketing"}
AUSGESCHLOSSENE_ORDNERTYPEN = {
    "\\sent", "\\drafts", "\\trash", "\\junk", "\\noselect",
}
STANDARD_START = date(2026, 2, 1)
STANDARD_ENDE_EINSCHLIESSLICH = date(2026, 4, 30)
STANDARD_ZIELORDNER = "/Rechnungen/Eingang"
BATCH_GROESSE = 25


def _flag_text(flag) -> str:
    if isinstance(flag, bytes):
        return flag.decode("ascii", errors="ignore").casefold()
    return str(flag).casefold()


def _durchsuchbare_ordner(config: PostfachConfig) -> list[str]:
    with IMAPClient(config.host, ssl=True, timeout=60) as client:
        client.login(config.user, config.password)
        ordner = []
        for flags, _trennzeichen, name in client.list_folders():
            normalisierte_flags = {_flag_text(flag) for flag in flags}
            if normalisierte_flags & AUSGESCHLOSSENE_ORDNERTYPEN:
                continue
            ordner.append(name)
        return ordner


def _rechnungskandidaten_laden(
    config: PostfachConfig,
    ordner: str,
    start: date,
    ende_exklusiv: date,
) -> tuple[int, list[dict]]:
    """Lädt nur Mails mit einem technisch unterstützten Rechnungsanhang."""
    with IMAPClient(config.host, ssl=True, timeout=60) as client:
        client.login(config.user, config.password)
        client.select_folder(ordner, readonly=True)
        uids = client.search(["SINCE", start, "BEFORE", ende_exklusiv])
        kandidaten = []
        for position in range(0, len(uids), BATCH_GROESSE):
            batch = uids[position:position + BATCH_GROESSE]
            daten = client.fetch(batch, ["RFC822", "INTERNALDATE"])
            for uid in batch:
                eintrag = daten.get(uid, {})
                raw = eintrag.get(b"RFC822")
                if not raw or not rechnungsanhaenge(raw):
                    continue
                eingegangen_am = eintrag.get(b"INTERNALDATE")
                if eingegangen_am is None:
                    eingegangen_am = parse_eml(raw)["empfangen_am"]
                elif eingegangen_am.tzinfo is None:
                    eingegangen_am = eingegangen_am.replace(tzinfo=timezone.utc)
                else:
                    eingegangen_am = eingegangen_am.astimezone(timezone.utc)
                kandidaten.append({
                    "uid": uid,
                    "ordner": ordner,
                    "raw": raw,
                    "eingegangen_am": eingegangen_am,
                })
        return len(uids), kandidaten


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
        try:
            ordnerliste = await asyncio.to_thread(_durchsuchbare_ordner, config)
        except Exception as exc:
            ergebnis["fehler"].append(f"{config.user}: Ordnerliste: {exc}")
            continue
        for ordner in ordnerliste:
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
            ergebnis["kandidaten"] += len(kandidaten)
            print(
                f"{config.user}/{ordner}: {anzahl} Mail(s), "
                f"{len(kandidaten)} Anhang-Kandidat(en)"
            )

            for kandidat in kandidaten:
                geparst = parse_eml(kandidat["raw"])
                message_id = geparst["message_id"]
                if message_id in bekannte_message_ids:
                    continue
                bekannte_message_ids.add(message_id)

                async with SessionLocal() as session:
                    mail = (await session.execute(
                        select(Mail).where(Mail.message_id == message_id)
                    )).scalar_one_or_none()
                    neue_mail = mail is None
                    if neue_mail:
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
                            anhang_dateinamen=(
                                geparst.get("anhang_dateinamen") or None
                            ),
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
                            ergebnis["keine_rechnung"] += 1
                        else:
                            ergebnis["fehler"].append(
                                f"{config.user}/{ordner}/UID {kandidat['uid']}: {exc}"
                            )
                        continue
                    except Exception as exc:
                        await session.rollback()
                        ergebnis["fehler"].append(
                            f"{config.user}/{ordner}/UID {kandidat['uid']}: {exc}"
                        )
                        continue

                    rechnungen = verarbeitet["rechnungen"]
                    ergebnis["rechnungen"] += len(rechnungen)
                    ergebnis["dubletten"] += sum(
                        1 for rechnung in rechnungen if rechnung["dublette"]
                    )
                    session.add(Aktionslog(
                        mail_id=mail.id,
                        ereignis="historische_rechnung_importiert",
                        ausgeloest_von="Krautl",
                        detail=(
                            f"{len(rechnungen)} Rechnung(en) aus "
                            f"{config.user}/{ordner} nach "
                            f"/{zielordner.strip('/')} abgelegt"
                        ),
                    ))
                    await session.commit()

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
