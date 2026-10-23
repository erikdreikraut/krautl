"""Bilderübersicht für Admin und Grafik; ausschließlich manuell ausgelöste Abrufe."""
import asyncio
import re
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, StrictBool

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
    return speicher.zustand()


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
