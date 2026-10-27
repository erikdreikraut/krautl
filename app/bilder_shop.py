"""Read-only publication checks against the public shop, bound to exact local snapshots."""
import asyncio
import hashlib
import json
import logging
import time
from html.parser import HTMLParser
from io import BytesIO
from urllib.parse import urlencode, urljoin, urlsplit

import httpx
from PIL import Image, ImageOps, ImageChops, ImageStat
from . import bilder_speicher as store
from .shop_import import artikelnummer_aus_detail

ORIGIN = "https://dreikraut.de"


def signatur(a, api_ziel):
    value = [api_ziel,a["id"],a["sku"],a["revision"],a.get("ausgeblendet"),
             [(b["id"],b.get("thumb"),b.get("version"),b.get("position"),b.get("hauptbild")) for b in a["bilder"]]]
    return hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()


def tabelle(db):
    db.execute("CREATE TABLE IF NOT EXISTS shoppruefung (artikel TEXT PRIMARY KEY, daten TEXT NOT NULL)")


def staende():
    with store.datenbank() as db:
        tabelle(db)
        return {a:json.loads(d) for a,d in db.execute("SELECT artikel,daten FROM shoppruefung")}


def speichern(a, status):
    with store.datenbank() as db:
        tabelle(db)
        db.execute("INSERT OR REPLACE INTO shoppruefung VALUES (?, ?)",(a,json.dumps(status)))


def aktuell(a, api_ziel, status):
    if not status or status.get("signatur") != signatur(a,api_ziel):
        return {"status":"wartet","meldung":"Shop-Veröffentlichung noch nicht geprüft"}
    result=dict(status)
    if result.get("status")=="bestaetigt" and time.time()-result.get("zeit",0)>21600:
        result.update(status="wartet",meldung="Shop-Bestätigung älter als sechs Stunden; erneute Prüfung steht an")
    return result


def sicher(url):
    p=urlsplit(url)
    if p.scheme!="https" or p.hostname!="dreikraut.de" or p.port not in (None,443) or p.username or p.password:
        raise ValueError("Unerwartete Shop-Adresse")
    return url


async def laden(c,url,limit):
    url=sicher(url)
    for _ in range(5):
        async with c.stream("GET",url,headers={"Cache-Control":"no-cache"}) as r:
            if r.status_code in (301,302,303,307,308):
                url=sicher(urljoin(url,r.headers.get("location","")))
                continue
            r.raise_for_status()
            body=bytearray()
            async for chunk in r.aiter_bytes():
                body.extend(chunk)
                if len(body)>limit:raise ValueError("Shop-Antwort zu groß")
            return bytes(body),url
    raise ValueError("Zu viele Shop-Weiterleitungen")


class Galerie(HTMLParser):
    def __init__(self):
        super().__init__();self.tiefe=0;self.bilder=[];self.varianten=[];self.anzahl=0
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=="div":
            if a.get("id")=="gallery":self.tiefe=1;self.anzahl+=1
            elif self.tiefe:self.tiefe+=1
        if self.tiefe and tag=="img" and a.get("data-list"):
            data=json.loads(a["data-list"])
            self.bilder.append(sicher(data["md"]["src"]))
        if tag=="option" and a.get("data-ref","").isdigit():
            self.varianten.append(ORIGIN+"/?"+urlencode({"a":a["data-ref"]}))
    def handle_endtag(self,tag):
        if tag=="div" and self.tiefe:self.tiefe-=1


async def seite(c,a,artikel,cached=None):
    urls=[]
    if cached:urls.append(cached)
    urls.append(ORIGIN+"/?"+urlencode({"qs":a["sku"]}))
    parent=next((p for p in artikel if p["id"]==a.get("parent_id")),None)
    if parent:urls.append(ORIGIN+"/?"+urlencode({"qs":parent["sku"]}))
    seen=set()
    while urls and len(seen)<24:
        url=urls.pop(0)
        if url in seen:continue
        seen.add(url)
        try:
            raw,final=await laden(c,url,2_000_000)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (404,410):continue
            raise
        html=raw.decode("utf-8",errors="replace")
        parser=Galerie();parser.feed(html)
        if artikelnummer_aus_detail(html)==a["sku"]:
            if parser.anzahl!=1 or not parser.bilder:raise ValueError("Keine eindeutige Shop-Galerie gefunden")
            if len(parser.bilder)>100:raise ValueError("Shop-Galerie zu groß")
            return final,parser.bilder
        if parent and artikelnummer_aus_detail(html)==parent["sku"]:
            urls.extend(parser.varianten)
    raise ValueError("Shopseite für diese Artikelnummer noch nicht eindeutig gefunden")


def normalisieren(raw):
    with Image.open(BytesIO(raw)) as source:
        if source.width*source.height>40_000_000:raise ValueError("Bild zu groß")
        rgba=ImageOps.exif_transpose(source).convert("RGBA")
        im=Image.new("RGB",rgba.size,"white");im.paste(rgba,mask=rgba.getchannel("A"))
        diff=ImageChops.difference(im,Image.new("RGB",im.size,"white")).convert("L")
        bbox=diff.point(lambda x:255 if x>18 else 0).getbbox()
        if not bbox:raise ValueError("Bildinhalt nicht eindeutig erkennbar")
        im=ImageOps.contain(im.crop(bbox),(96,96))
        canvas=Image.new("RGB",(96,96),"white")
        canvas.paste(im,((96-im.width)//2,(96-im.height)//2))
        return canvas


def abstand(a,b):
    return sum(ImageStat.Stat(ImageChops.difference(a,b)).mean)/3


def vergleichen(local,remote):
    if len(local)!=len(remote) or not local:return False,"Anzahl der Shop-Bilder stimmt noch nicht überein"
    left=[normalisieren(b) for b in local];right=[normalisieren(b) for b in remote]
    matrix=[[abstand(a,b) for b in left] for a in right]
    for i,row in enumerate(matrix):
        # Strict absolute match, and a clear margin to every alternative in both directions.
        if row[i]>7:return False,"Bildinhalt oder Reihenfolge im Shop noch abweichend"
        alternatives=[v for j,v in enumerate(row) if j!=i]+[r[i] for j,r in enumerate(matrix) if j!=i]
        if alternatives and min(alternatives)-row[i]<10:
            return False,"Ähnliche Bilder lassen sich noch nicht eindeutig zuordnen"
    return True,"Bilder und Reihenfolge im Shop bestätigt"


async def artikel_pruefen(c,a,data,previous):
    stamp=signatur(a,data.get("api_ziel"))
    result={"signatur":stamp,"zeit":time.time(),"geprueft_am":store.jetzt(),"status":"wartet"}
    try:
        async with asyncio.timeout(60):
            url,urls=await seite(c,a,data["artikel"],previous.get("url"))
            result["url"]=url
            ordered=sorted(a["bilder"],key=lambda b:b["position"])
            if not ordered or [b.get("hauptbild") for b in ordered]!=[True]+[False]*(len(ordered)-1):
                raise ValueError("Wawi-Hauptbild ist noch nicht eindeutig")
            if any(not b.get("thumb") for b in ordered):raise ValueError("Vergleichsvorschauen fehlen")
            local=[store.thumb_lesen(a["id"],b["thumb"]) for b in ordered]
            if not all(local):raise ValueError("Vergleichsvorschauen fehlen")
            if len(urls)!=len(local):raise ValueError("Anzahl der Shop-Bilder stimmt noch nicht überein")
            remote=[]
            for u in urls:
                # A fresh cache key also prevents stale intermediary image responses after replacement.
                u += ("&" if "?" in u else "?")+urlencode({"krautl_check":int(result["zeit"])})
                raw,_=await laden(c,u,8_000_000);remote.append(raw)
            ok,msg=vergleichen(local,remote)
            result.update(status="bestaetigt" if ok else "wartet",meldung=msg)
    except ValueError as exc:
        result["meldung"]=str(exc)
    except Exception:
        result["meldung"]="Shop-Prüfung derzeit nicht möglich; erneuter Versuch folgt"
    # Guard against changed/hiding/replaced snapshots during public HTTP fetches.
    try:
        with store.Laufsperre():
            fresh=store.lesen()
            current=next((x for x in fresh["artikel"] if x["id"]==a["id"]),None)
            if current and not current["ausgeblendet"] and signatur(current,fresh.get("api_ziel"))==stamp:
                speichern(a["id"],result)
    except store.Belegt:
        pass  # A write/sync is active; discard this observation and retry later.
    return result


async def durchlauf():
    from .bilder_upload import auftraege
    data=store.lesen();saved=staende();jobs=auftraege()
    blocked={j["artikel"] for j in jobs if j.get("status") in ("sendet","unklar")}
    blocked.update(x["id"] for x in data.get("ungeprueft",[]))
    changed={j["artikel"] for j in jobs if j.get("status")=="wawi"}
    pending=[]
    for a in data["artikel"]:
        if a["ausgeblendet"] or a["id"] in blocked or not a["bilder"]:continue
        old=saved.get(a["id"],{})
        same=old.get("signatur")==signatur(a,data.get("api_ziel"))
        interval=21000 if old.get("status")=="bestaetigt" else 300
        if same and time.time()-old.get("zeit",0)<interval:continue
        pending.append(a)
    pending.sort(key=lambda a:(a["id"] not in changed,saved.get(a["id"],{}).get("zeit",0)))
    async with httpx.AsyncClient(timeout=15,follow_redirects=False,trust_env=False,
                                 headers={"User-Agent":"Krautl Shopbild-Pruefung/1.0"}) as c:
        for a in pending[:5]:
            # No Wawi lock during network IO: uploads and refreshes remain available.
            await artikel_pruefen(c,a,data,saved.get(a["id"],{}))


async def ueberwachen():
    await asyncio.sleep(15)
    while True:
        try:
            with store.Laufsperre("shop.lock"):
                await durchlauf()
        except store.Belegt:
            pass
        except Exception:logging.getLogger(__name__).exception("Shop-Bildprüfung fehlgeschlagen")
        await asyncio.sleep(30)

