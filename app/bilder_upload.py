"""Explicit image writes: durable intent, no automatic replay of mutations."""
import base64
import copy
import hashlib
import json
import re
from io import BytesIO
import httpx
from PIL import Image, ImageOps
from . import bilder_speicher as store
from .bilder_abgleich import bild_laden, vorschaubild, ident
from .jtl_client import JtlFehler

SHOP = "2-2-1"
# User excludes the POS image channel; installed Wawi rejects this readback ID on write.
IGNORIERTE_BILDKANAELE = frozenset({"9-7-8-0"})


def journal():
    return store.datenbank()


def tabelle(db):
    db.execute("CREATE TABLE IF NOT EXISTS bildauftraege (id TEXT PRIMARY KEY, artikel TEXT NOT NULL, daten TEXT NOT NULL, datei BLOB NOT NULL)")


def auftraege(artikel=None):
    with journal() as db:
        tabelle(db)
        rows = db.execute("SELECT daten FROM bildauftraege" + (" WHERE artikel=?" if artikel else ""), (artikel,) if artikel else ()).fetchall()
    return [json.loads(r[0]) for r in rows]


def sichern(job, datei=None):
    with journal() as db:
        tabelle(db)
        if datei is not None:
            db.execute("INSERT INTO bildauftraege VALUES (?, ?, ?, ?)", (job["id"], job["artikel"], json.dumps(job), datei))
        else:
            db.execute("UPDATE bildauftraege SET daten=? WHERE id=?", (json.dumps(job), job["id"]))


def oeffentlich(job):
    return {k: job.get(k) for k in ("id", "artikel", "bild_id", "neu_id", "status", "meldung", "erstellt", "position", "art", "reihenfolge")}


def ablehnungsdetails(response):
    """Keep bounded validation details in the local journal, never in API output."""
    try:
        body = response.json()
    except ValueError:
        return "Keine strukturierte Fehlerantwort der Wawi."
    if not isinstance(body, dict):
        return "Keine strukturierte Fehlerantwort der Wawi."
    selected = {k: v for k, v in body.items()
                if k.lower() in {"title", "detail", "message", "errors", "status"}}
    text = json.dumps(selected, ensure_ascii=False)
    auth = response.request.headers.get("Authorization", "")
    for secret in (auth, auth.removeprefix("Wawi ")):
        if secret:
            text = text.replace(secret, "[ausgeblendet]")
    text = re.sub(r'https?://[^\s"<>]+', '[URL]', text)
    text = re.sub(r'[A-Za-z0-9_+/=-]{32,}', '[lange Kennung]', text)
    return text[:4000]


def datei_pruefen(raw):
    if not raw or len(raw) > 20 * 1024 * 1024:
        raise ValueError("Bilddatei muss zwischen 1 Byte und 20 MB groß sein.")
    try:
        with Image.open(BytesIO(raw)) as im:
            if im.format not in {"JPEG", "PNG", "WEBP"} or getattr(im, "n_frames", 1) != 1 or im.width * im.height > 40_000_000:
                raise ValueError()
            im = ImageOps.exif_transpose(im)
            out = BytesIO()
            # Lossless PNG, no unsafe filename or metadata forwarded to Wawi.
            im.convert("RGBA" if "A" in im.getbands() else "RGB").save(out, "PNG")
            data = out.getvalue()
            if len(data) > 20 * 1024 * 1024:
                raise ValueError()
            return data
    except (OSError, ValueError, Image.DecompressionBombError):
        raise ValueError("Bitte ein einzelnes JPG-, PNG- oder WebP-Bild bis 40 Megapixel wählen; die aufbereitete Datei darf 20 MB nicht überschreiten.") from None


def bildinhalt_bestaetigt(job, thumb):
    """Compare decoded preview pixels, never relax to perceptual similarity."""
    if hashlib.sha256(thumb).hexdigest() == job["thumb_hash"]:
        return True
    with journal() as db:
        row = db.execute("SELECT datei FROM bildauftraege WHERE id=?", (job["id"],)).fetchone()
    if not row or not row[0]:
        return False
    expected = vorschaubild(row[0])
    if hashlib.sha256(expected).hexdigest() != job["thumb_hash"]:
        return False
    try:
        with Image.open(BytesIO(expected)) as left, Image.open(BytesIO(thumb)) as right:
            if left.size != right.size:
                return False
            return left.convert("RGBA").tobytes() == right.convert("RGBA").tobytes()
    except (OSError, ValueError):
        return False


def bildblock(detail):
    block = detail.get("images")
    if not isinstance(block, dict):
        raise ValueError("Bildzuordnungen fehlen in der Wawi.")
    specs = {"defaultImages":None, "platformImages":"platformId", "saleschannelImages":"saleschannelId", "ebayImages":"ebayAccountId"}
    if set(block) - set(specs):
        raise ValueError("Unbekannte Bildzuordnungen; keine Änderung ausgeführt.")
    def image(b):
        bid = ident(b.get("blobIdentifier"))
        if type(b.get("sortNumber")) is not int or type(b.get("isMainImage")) is not bool:
            raise ValueError("Uneindeutige Bildposition.")
        return {"blobIdentifier":bid,"sortNumber":b["sortNumber"],"isMainImage":b["isMainImage"]}
    result = {}
    for field, groupkey in specs.items():
        rows = block.get(field) or []
        if not isinstance(rows, list):
            raise ValueError("Ungültige Bildzuordnungen.")
        if groupkey:
            groups = []
            seen = set()
            for g in rows:
                key = g.get(groupkey)
                if type(key) not in (str, int) or key == "":
                    raise ValueError(f"Bildzuordnung {field}: {groupkey} fehlt oder hat ein ungültiges Format. Keine Änderung ausgeführt.")
                # Non-target groups may repeat in installed Wawi responses. Preserve
                # every entry; only the shop group must be unique for mutation.
                if field == "saleschannelImages" and key == SHOP and key in seen:
                    raise ValueError(f"Bildzuordnung {field}: {groupkey} ist mehrfach enthalten. Keine Änderung ausgeführt.")
                seen.add(key)
                groups.append({groupkey:key,"images":[image(b) for b in g.get("images", [])]})
            result[field] = groups
        else:
            result[field] = [image(b) for b in rows]
    return result


def shop(block):
    matches = [g for g in block["saleschannelImages"] if g["saleschannelId"] == SHOP]
    if len(matches) > 1:
        raise ValueError("Shop-Bildkanal ist nicht eindeutig.")
    return matches[0]["images"] if matches else []


def schreibblock(block):
    """Prepare writable assignments; omit explicitly irrelevant POS channel."""
    result = copy.deepcopy(block)
    for field in ("platformImages", "saleschannelImages", "ebayImages"):
        seen = set()
        groups = []
        for group in result.get(field, []):
            if field == "saleschannelImages" and group.get("saleschannelId") in IGNORIERTE_BILDKANAELE:
                continue
            normalized = {**group, "images": sorted(
                group["images"], key=lambda b: json.dumps(b, sort_keys=True))}
            key = json.dumps(normalized, sort_keys=True)
            if key not in seen:
                groups.append(group)
                seen.add(key)
        result[field] = groups
    return result


def fingerprint(block):
    def canonical(value):
        if isinstance(value, dict):
            return {k:canonical(v) for k,v in value.items()}
        if isinstance(value, list):
            return sorted((canonical(v) for v in value), key=lambda v:json.dumps(v,sort_keys=True))
        return value
    return json.dumps(canonical(schreibblock(block)), sort_keys=True)


async def detail_lesen(c, artikel, sku):
    d = await c._request("GET", "/v2/items/" + artikel)
    if d.get("id") != artikel or d.get("identifiers", {}).get("sku") != sku:
        raise ValueError("Wawi-Artikel stimmt nicht mit der Auswahl überein.")
    return d


def lokal(artikel, revision=None):
    data = store.lesen()
    a = next((a for a in data["artikel"] if a["id"] == artikel), None)
    if not a or a["ausgeblendet"] or (revision is not None and a["revision"] != revision):
        raise ValueError("Artikel fehlt, ist ausgeblendet oder wurde geändert. Bitte neu laden.")
    if any(u["id"] == artikel for u in data.get("ungeprueft", [])):
        raise ValueError("Artikel ist ungeprüft. Zuerst aktualisieren.")
    return a, data


async def uebertragen(c, artikel, bild_id, revision, anfrage_id, raw, nutzer):
    if bild_id:
        from .bilder_ersetzen import ersetzen
        return await ersetzen(c, artikel, bild_id, revision, anfrage_id, raw, nutzer)
    previous = next((j for j in auftraege() if j["id"] == anfrage_id), None)
    a = next((a for a in store.lesen()["artikel"] if a["id"] == artikel), {})
    if (previous and previous.get("art") == "hinzufuegen_v1") or a.get("bild_api") == "v1" or any(b.get("v1_id") for b in a.get("bilder", [])):
        from .bilder_ersetzen import hinzufuegen
        return await hinzufuegen(c, artikel, revision, anfrage_id, raw, nutzer)
    return await upload_neuanlage(c, artikel, bild_id, revision, anfrage_id, raw, nutzer)


async def upload_neuanlage(c, artikel, bild_id, revision, anfrage_id, raw, nutzer):
    digest = hashlib.sha256(raw).hexdigest()
    previous = next((j for j in auftraege() if j["id"] == anfrage_id), None)
    if previous:
        if previous.get("art") == "reihenfolge" or (previous["artikel"], previous["bild_id"], previous["eingang_hash"]) != (artikel, bild_id, digest):
            raise ValueError("Auftragskennung wurde bereits anders verwendet.")
        return oeffentlich(previous)
    a, stand = lokal(artikel, revision)
    if stand.get("api_ziel") != c.url:
        raise ValueError("Wawi-Ziel passt nicht zum Bilderbestand.")
    if any(j["status"] in {"sendet", "unklar"} for j in auftraege(artikel)):
        raise ValueError("Ein früherer Bildauftrag ist noch ungeklärt. Zuerst dessen Wawi-Stand prüfen.")
    raw = datei_pruefen(raw)
    d = await detail_lesen(c, artikel, a["sku"])
    before = bildblock(d)
    current = shop(before)
    snapshot = sorted((b["id"],b["position"],b["hauptbild"]) for b in a["bilder"])
    if snapshot != sorted((b["blobIdentifier"],b["sortNumber"],b["isMainImage"]) for b in current):
        raise ValueError("Wawi-Bilder haben sich geändert. Bitte zuerst aktualisieren.")
    target = next((b for b in current if b["blobIdentifier"] == bild_id), None)
    if bild_id and target is None:
        raise ValueError("Das gewählte Bild gehört nicht mehr zum Shop.")
    # Verify v1 access before recording a mutation; actual write rights remain server enforced.
    await c._request("GET", "/v1/items/" + artikel + "/images", expected_type=list)
    job = {"id":anfrage_id,"artikel":artikel,"sku":a["sku"],"bild_id":bild_id,"eingang_hash":digest,
           "erstellt":store.jetzt(),"nutzer":nutzer,"api_ziel":c.url,"vorher":before,
           "dateiname":"krautl-" + anfrage_id + ".png", "status":"sendet", "phase":"upload",
           "meldung":"Übertragung an Wawi läuft.", "revision":revision,
           "thumb_hash":hashlib.sha256(vorschaubild(raw)).hexdigest()}
    if not store.freigegeben(artikel, revision):
        raise ValueError("Artikel wurde während der Prüfung geändert.")
    sichern(job, raw)
    try:
        # A single POST, never retried, even after a timeout or lost response.
        response = await c.http.post(c.url + "/v1/items/" + artikel + "/images", json={
            "ImageData":base64.b64encode(raw).decode(),"Filename":job["dateiname"],"SalesChannelId":SHOP})
        if response.status_code in {400, 401, 402, 403, 404, 413, 415, 422}:
            job.update(status="abgelehnt", meldung=f"Wawi hat den Upload abgelehnt (HTTP {response.status_code}). Es wurde keine Bildzuordnung geändert. Bei HTTP 403 fehlen Bildschreibrechte des bestehenden Zugangs.")
            sichern(job)
            return oeffentlich(job)
        if response.status_code != 201:
            raise JtlFehler(f"Bildanlage: HTTP {response.status_code}. Ausgang muss geprüft werden.")
        after = await detail_lesen(c, artikel, a["sku"])
        block = bildblock(after)
        oldids = {b["blobIdentifier"] for b in current}
        added = [b for b in shop(block) if b["blobIdentifier"] not in oldids]
        if len(added) != 1:
            raise ValueError("Neue Wawi-Bildzuordnung ist nicht eindeutig.")
        new = added[0]
        without_new = copy.deepcopy(block)
        shop(without_new).remove(new)
        # An empty shop group may have been created by the POST.
        if not any(g["saleschannelId"] == SHOP for g in before["saleschannelImages"]):
            without_new["saleschannelImages"] = [g for g in without_new["saleschannelImages"] if g["saleschannelId"] != SHOP]
        if fingerprint(without_new) != fingerprint(before):
            raise ValueError("Wawi-Zuordnungen haben sich während der Bildanlage verändert.")
        source = next(b for g in after["images"]["saleschannelImages"] if g["saleschannelId"] == SHOP for b in g["images"] if b["blobIdentifier"] == new["blobIdentifier"])
        thumb = await bild_laden(c, new["blobIdentifier"], source)
        if not bildinhalt_bestaetigt(job, thumb):
            raise ValueError("Zurückgelesenes Bild stimmt nicht mit der gewählten Datei überein.")
        desired = copy.deepcopy(block)
        images = shop(desired)
        for b in images:
            if b["blobIdentifier"] == new["blobIdentifier"]:
                b["sortNumber"] = target["sortNumber"] if target else max((b["sortNumber"] for b in current), default=0)+1
                b["isMainImage"] = target["isMainImage"] if target else not current
        images[:] = [b for b in images if not bild_id or b["blobIdentifier"] != bild_id]
        images.sort(key=lambda b:(b["sortNumber"],b["blobIdentifier"]))
        job.update(neu_id=new["blobIdentifier"], ziel=desired, position=next(b["sortNumber"] for b in images if b["blobIdentifier"] == new["blobIdentifier"]), phase="zuordnung")
        sichern(job)
        if not store.freigegeben(artikel, revision):
            raise ValueError("Artikel wurde inzwischen ausgeblendet oder geändert; Bild angelegt, Zuordnung noch offen.")
        if fingerprint(bildblock(await detail_lesen(c,artikel,a["sku"]))) != fingerprint(block):
            raise ValueError("Bilder wurden zwischenzeitlich geändert; Zuordnung noch offen.")
        # No binary replacement/deletion: retain every other channel's references.
        if fingerprint(desired) != fingerprint(block):
            response = await c.http.patch(c.url + "/v2/items/" + artikel, json={"images":schreibblock(desired)})
            if response.status_code != 200:
                raise JtlFehler(f"Bildzuordnung: HTTP {response.status_code}. Ausgang muss geprüft werden.")
        return await pruefen(c, job)
    except (httpx.HTTPError, JtlFehler, ValueError, KeyError, TypeError) as exc:
        job.update(status="unklar", meldung="Übertragung nicht vollständig bestätigt. Nicht erneut hochladen; Wawi-Stand prüfen. " + (str(exc) if isinstance(exc, (JtlFehler, ValueError)) else "Verbindung oder Antwort unklar."))
        sichern(job)
        return oeffentlich(job)


async def pruefen(c, job):
    if job.get('bruecke'):
        from .bilder_bruecke import bestaetigen
        return await bestaetigen(c, job)
    if job.get("art") == "hinzufuegen_v1":
        from .bilder_ersetzen import hinzufuegen_pruefen
        return await hinzufuegen_pruefen(c, job)
    if job.get("art") == "reihenfolge_v1":
        from .bilder_ersetzen import reihenfolge_pruefen
        return await reihenfolge_pruefen(c, job)
    if job.get("art") == "ersetzen_alle":
        from .bilder_ersetzen import pruefen as v1_pruefen
        return await v1_pruefen(c, job)
    if job["api_ziel"] != c.url:
        raise ValueError("Wawi-Ziel passt nicht zum Auftrag.")
    d = await detail_lesen(c,job["artikel"],job["sku"])
    if not job.get("ziel") or fingerprint(bildblock(d)) != fingerprint(job["ziel"]):
        job.update(status="unklar",meldung="Wawi-Zuordnung entspricht noch nicht dem Ziel. Keine automatische Wiederholung; Auftrag muss geprüft werden.")
        sichern(job)
        return oeffentlich(job)
    if job.get("art") != "reihenfolge":
        source = next(b for g in d["images"]["saleschannelImages"] if g["saleschannelId"] == SHOP for b in g["images"] if b["blobIdentifier"] == job["neu_id"])
        thumb = await bild_laden(c,job["neu_id"],source)
        if not bildinhalt_bestaetigt(job, thumb):
            raise ValueError("Bildinhalt wurde nicht bestätigt.")
    a, _ = lokal(job["artikel"])
    if a["revision"] != job["revision"]:
        raise ValueError("Artikelrevision geändert; vor Übernahme prüfen.")
    old = {b["id"]:b for b in a["bilder"]}
    result=[]
    for b in shop(job["ziel"]):
        bid=b["blobIdentifier"]
        if bid == job.get("neu_id"):
            value={"id":bid,"thumb":store.thumb_speichern(thumb),"fehler":None,"version":None,"dateiname":job["dateiname"]}
        elif bid in old:
            value=dict(old[bid])
        else:
            raise ValueError("Unbekanntes Bild beim Übernehmen.")
        value.update(position=b["sortNumber"],hauptbild=b["isMainImage"])
        result.append(value)
    a["bilder"]=result
    a["aktualisiert_am"]=store.jetzt()
    store.zwischenstand(a,a["revision"],c.url,abgleich=False)
    job.update(status="wawi",meldung="In Wawi bestätigt. Veröffentlichung im Shop noch nicht geprüft.")
    sichern(job)
    return oeffentlich(job)


def positionsstand(bilder):
    return sorted((b["id"], b["position"], b["hauptbild"]) for b in bilder)


async def umordnen(c, artikel, revision, anfrage_id, reihenfolge, vorher, nutzer):
    previous = next((j for j in auftraege() if j["id"] == anfrage_id), None)
    a = next((a for a in store.lesen()["artikel"] if a["id"] == artikel), {})
    if (previous and previous.get("art") == "reihenfolge_v1") or a.get("bild_api") == "v1" or any(b.get("v1_id") for b in a.get("bilder", [])):
        from .bilder_ersetzen import reihenfolge as v1_reihenfolge
        return await v1_reihenfolge(c, artikel, revision, anfrage_id, reihenfolge, vorher, nutzer)
    return await umordnen_v2(c, artikel, revision, anfrage_id, reihenfolge, vorher, nutzer)


async def umordnen_v2(c, artikel, revision, anfrage_id, reihenfolge, vorher, nutzer):
    request_hash = hashlib.sha256(json.dumps([artikel, revision, reihenfolge, vorher], sort_keys=True).encode()).hexdigest()
    previous = next((j for j in auftraege() if j["id"] == anfrage_id), None)
    if previous:
        if previous.get("art") != "reihenfolge" or previous.get("eingang_hash") != request_hash:
            raise ValueError("Auftragskennung wurde bereits anders verwendet.")
        return oeffentlich(previous)
    a, stand = lokal(artikel, revision)
    if stand.get("api_ziel") != c.url:
        raise ValueError("Wawi-Ziel passt nicht zum Bilderbestand.")
    if any(j["status"] in {"sendet", "unklar"} for j in auftraege(artikel)):
        raise ValueError("Ein Bildauftrag ist noch ungeklärt. Zuerst dessen Wawi-Stand prüfen.")
    ids = [b["id"] for b in a["bilder"]]
    if not ids or len(set(ids)) != len(ids) or len(set(reihenfolge)) != len(reihenfolge) or set(reihenfolge) != set(ids):
        raise ValueError("Die Reihenfolge muss jedes vorhandene Shop-Bild genau einmal enthalten.")
    if positionsstand(vorher) != positionsstand(a["bilder"]):
        raise ValueError("Die angezeigte Reihenfolge ist veraltet. Bitte neu laden.")
    before = bildblock(await detail_lesen(c, artikel, a["sku"]))
    if positionsstand(vorher) != sorted((b["blobIdentifier"],b["sortNumber"],b["isMainImage"]) for b in shop(before)):
        raise ValueError("Wawi-Bilder wurden geändert. Bitte zuerst aktualisieren.")
    desired = copy.deepcopy(before)
    shop(desired)[:] = [{"blobIdentifier":bid,"sortNumber":i+1,"isMainImage":i==0} for i,bid in enumerate(reihenfolge)]
    if not store.freigegeben(artikel, revision):
        raise ValueError("Artikel wurde inzwischen geändert.")
    if fingerprint(bildblock(await detail_lesen(c,artikel,a["sku"]))) != fingerprint(before):
        raise ValueError("Wawi-Bilder wurden während der Prüfung geändert.")
    job={"id":anfrage_id,"artikel":artikel,"sku":a["sku"],"art":"reihenfolge","eingang_hash":request_hash,
         "erstellt":store.jetzt(),"nutzer":nutzer,"api_ziel":c.url,"vorher":before,"ziel":desired,
         "status":"sendet","meldung":"Neue Reihenfolge wird an Wawi übertragen.","revision":revision,"reihenfolge":reihenfolge}
    sichern(job,b"")
    try:
        if fingerprint(before) != fingerprint(desired):
            response=await c.http.patch(c.url+"/v2/items/"+artikel,json={"images":schreibblock(desired)})
            if response.status_code in {400,401,402,403,404,413,415,422}:
                job.update(status="abgelehnt",meldung=f"Wawi hat die Reihenfolge abgelehnt (HTTP {response.status_code}).", diagnose=ablehnungsdetails(response))
                sichern(job)
                return oeffentlich(job)
            if response.status_code != 200:
                raise JtlFehler(f"Reihenfolge: HTTP {response.status_code}.")
        return await pruefen(c,job)
    except (httpx.HTTPError,JtlFehler,ValueError,KeyError,TypeError):
        job.update(status="unklar",meldung="Reihenfolge nicht vollständig bestätigt. Wawi-Stand prüfen; kein automatisches erneutes Schreiben.")
        sichern(job)
        return oeffentlich(job)
