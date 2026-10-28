"""Bilderübersicht für Admin und Grafik; manuelle Wawi-Abrufe und lesende Shop-Prüfung."""
import asyncio
import base64
import json
import re
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, StrictBool, StrictInt

from . import bilder_speicher as speicher
from .bilder_abgleich import ausfuehren
from .jtl_client import JtlFehler


def berechtigt(request: Request):
    if request.state.benutzer.get("rolle") not in {"admin", "grafik"}:
        raise HTTPException(403, "Die Bilderverwaltung ist für Admin und Grafik zugänglich.")


router = APIRouter(prefix="/bilder", dependencies=[Depends(berechtigt)])
aufgaben = set()


@router.get("")
def liste(response: Response):
    response.headers["Cache-Control"] = "no-store"
    from .bilder_upload import auftraege, oeffentlich
    from .bilder_shop import staende, aktuell
    data = speicher.zustand()
    shop = staende()
    data["artikel"] = [{**a, "shop_pruefung": aktuell(a, data.get("api_ziel"), shop.get(a["id"]))}
                       for a in data["artikel"]]
    return {**data, "bildauftraege": [oeffentlich(j) for j in auftraege() if not j.get("ruecksetzung")]}


class Sichtbarkeit(BaseModel):
    ausgeblendet: StrictBool
    revision: int = Field(ge=0)


@router.put("/{artikel_id}/ausblenden")
def ausblenden(artikel_id: UUID, body: Sichtbarkeit, request: Request):
    try:
        speicher.ausblenden(str(artikel_id), body.ausgeblendet, body.revision, request.state.benutzer["benutzername"])
    except KeyError:
        raise HTTPException(404, "Artikel nicht gefunden") from None
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None
    return {"status": "gespeichert"}


@router.get("/{artikel_id}/thumb/{thumb_id}")
def thumbnail(artikel_id: UUID, thumb_id: str):
    if not re.fullmatch(r"[0-9a-f]{64}", thumb_id):
        raise HTTPException(404, "Vorschaubild nicht gefunden")
    daten = speicher.thumb_lesen(str(artikel_id), thumb_id)
    if daten is None:
        raise HTTPException(404, "Vorschaubild nicht gefunden")
    return Response(daten, media_type="image/jpeg", headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})


@router.post("/exportvorschau")
async def exportvorschau(request: Request):
    from .bilder_abgleich import vorschaubild
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 1024 * 1024:
            raise HTTPException(413, "Vorschaudatei darf höchstens 1 MB groß sein.")
    try:
        data = json.loads(body)
        if data.get("format") != "krautl-shopvorschau-1" or data.get("kanal") != "2-2-1":
            raise ValueError("Keine passende Shop-Vorschaudatei.")
        sku = data["sku"]
        if not isinstance(sku, str) or not sku.strip():
            raise ValueError("Artikelnummer fehlt.")
        rows = data["bilder"]
        if not isinstance(rows, list) or not 1 <= len(rows) <= 100:
            raise ValueError("Ungültige Bilderliste.")
        bilder = {}
        for row in rows:
            pos = row["position"]
            if type(pos) is not int or pos < 0 or pos in bilder:
                raise ValueError("Ungültige oder doppelte Bildposition.")
            bilder[pos] = vorschaubild(base64.b64decode(row["jpeg"], validate=True))
    except (ValueError, KeyError, TypeError, AttributeError, JtlFehler):
        raise HTTPException(400, "Ungültige Shop-Vorschaudatei oder Bilddaten.") from None
    try:
        with speicher.Laufsperre():
            anzahl = speicher.exportvorschauen(sku, bilder, request.state.benutzer["benutzername"])
    except speicher.Belegt as exc:
        raise HTTPException(409, str(exc)) from None
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None
    return {"sku": sku, "importiert": anzahl}


async def lauf(sperre):
    try:
        await asyncio.wait_for(ausfuehren(), timeout=3600)
    except asyncio.CancelledError:
        speicher.status_setzen(status="fehler", fehler="Aktualisierung unterbrochen. Der bisherige Stand bleibt erhalten.")
        raise
    except Exception as exc:
        detail = str(exc) if isinstance(exc, JtlFehler) else (
            "Zeitlimit nach einer Stunde erreicht." if isinstance(exc, TimeoutError) else "Technischer Fehler beim Bilderabruf.")
        speicher.status_setzen(status="fehler", fehler=detail)
    finally:
        sperre.__exit__(None, None, None)


@router.post("/aktualisieren", status_code=202)
async def aktualisieren():
    sperre = speicher.Laufsperre()
    try:
        sperre.__enter__()
    except speicher.Belegt as exc:
        raise HTTPException(409, str(exc)) from None
    try:
        speicher.status_setzen(status="laeuft", gestartet_am=speicher.jetzt(), fehler=None, fortschritt="Artikelkatalog wird geladen …")
        task = asyncio.create_task(lauf(sperre))
        aufgaben.add(task)
        def erledigt(fertig):
            aufgaben.discard(fertig)
            # Cancellation before the coroutine starts does not execute its finally.
            if not sperre.file.closed:
                try:
                    speicher.status_setzen(status="fehler", fehler="Aktualisierung unterbrochen. Bitte erneut aktualisieren.")
                finally:
                    sperre.__exit__(None, None, None)
        task.add_done_callback(erledigt)
    except BaseException:
        sperre.__exit__(None, None, None)
        raise
    return {"status": "laeuft"}


async def beenden():
    tasks = list(aufgaben)
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


@router.get("/{artikel_id}/gross/{bild_id}")
async def grossbild(artikel_id: UUID, bild_id: UUID):
    from .bilder_upload import lokal, detail_lesen
    from .bilder_abgleich import bild_laden, SHOP
    from .jtl_onprem import OnPremClient
    try:
        a, stand = lokal(str(artikel_id))
        if not any(b["id"] == str(bild_id) for b in a["bilder"]):
            raise ValueError("Bild nicht im Artikelbestand.")
        async with OnPremClient.aus_umgebung() as c:
            if stand.get("api_ziel") != c.url:
                raise ValueError("Wawi-Ziel passt nicht zum Bilderbestand.")
            d = await detail_lesen(c, str(artikel_id), a["sku"])
            local_image = next(b for b in a["bilder"] if b["id"] == str(bild_id))
            if local_image.get("v1_id"):
                from .bilder_ersetzen import liste, bild
                rows = await liste(c, str(artikel_id))
                if not any(r["ImageId"] == local_image["v1_id"] and r["SalesChannelId"] == SHOP for r in rows):
                    raise ValueError("Bild gehört nicht mehr zum Shop. Bitte aktualisieren.")
                data = await bild(c, local_image["v1_id"], (1600, 1200))
                return Response(data, media_type="image/jpeg", headers={"Cache-Control":"private, no-store"})
            matches = [b for g in d.get("images", {}).get("saleschannelImages", []) if g.get("saleschannelId") == SHOP
                       for b in g.get("images", []) if b.get("blobIdentifier") == str(bild_id)]
            if len(matches) != 1:
                raise ValueError("Bildzuordnung verändert. Bitte aktualisieren.")
            data = await bild_laden(c, str(bild_id), matches[0], groesse=(1600, 1200))
        return Response(data, media_type="image/jpeg", headers={"Cache-Control":"private, no-store", "X-Content-Type-Options":"nosniff"})
    except (ValueError, JtlFehler) as exc:
        raise HTTPException(409, str(exc)) from None


@router.post("/{artikel_id}/datei")
async def bild_datei(artikel_id: UUID, request: Request, anfrage_id: UUID, revision: int, bild_id: UUID | None = None):
    from .bilder_upload import uebertragen
    from .jtl_onprem import OnPremClient
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > 20 * 1024 * 1024:
            raise HTTPException(413, "Bilddatei darf höchstens 20 MB groß sein.")
    try:
        with speicher.Laufsperre():
            async with OnPremClient.aus_umgebung() as c:
                return await uebertragen(c, str(artikel_id), str(bild_id) if bild_id else None, revision,
                                         str(anfrage_id), bytes(raw), request.state.benutzer["benutzername"])
    except (speicher.Belegt, ValueError, JtlFehler) as exc:
        raise HTTPException(409, str(exc)) from None


@router.post("/auftraege/{anfrage_id}/pruefen")
async def bild_pruefen(anfrage_id: UUID):
    from .bilder_upload import auftraege, pruefen, oeffentlich
    from .jtl_onprem import OnPremClient
    job = next((j for j in auftraege() if j["id"] == str(anfrage_id)), None)
    if not job:
        raise HTTPException(404, "Bildauftrag nicht gefunden.")
    if job["status"] in {"wawi", "abgelehnt"}:
        return oeffentlich(job)
    try:
        with speicher.Laufsperre():
            async with OnPremClient.aus_umgebung() as c:
                return await pruefen(c, job)
    except (speicher.Belegt, ValueError, JtlFehler) as exc:
        raise HTTPException(409, str(exc)) from None


class BildPosition(BaseModel):
    id: UUID
    position: StrictInt
    hauptbild: StrictBool


class BildReihenfolge(BaseModel):
    revision: int = Field(ge=0)
    anfrage_id: UUID
    reihenfolge: list[UUID] = Field(min_length=1, max_length=100)
    vorher: list[BildPosition] = Field(min_length=1, max_length=100)


@router.post("/{artikel_id}/reihenfolge")
async def reihenfolge_speichern(artikel_id: UUID, body: BildReihenfolge, request: Request):
    from .bilder_upload import umordnen
    from .jtl_onprem import OnPremClient
    try:
        with speicher.Laufsperre():
            async with OnPremClient.aus_umgebung() as c:
                return await umordnen(c, str(artikel_id), body.revision, str(body.anfrage_id),
                    [str(b) for b in body.reihenfolge],
                    [{"id":str(b.id),"position":b.position,"hauptbild":b.hauptbild} for b in body.vorher],
                    request.state.benutzer["benutzername"])
    except (speicher.Belegt, ValueError, JtlFehler) as exc:
        raise HTTPException(409, str(exc)) from None
