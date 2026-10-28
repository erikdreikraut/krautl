"""Read-only audit of an interrupted image upload. Never repairs or replays writes."""
import argparse
import asyncio
import hashlib
import json
import re
from io import BytesIO
from urllib.parse import urlsplit
from uuid import UUID
from PIL import Image
from app import bilder_speicher as store
from app.bilder_upload import auftraege
from app.bilder_abgleich import bildantwort, vorschaubild
from app.jtl_onprem import OnPremClient
from app.bilder_ersetzen import zuordnungen


def pixelgleich(left, right):
    with Image.open(BytesIO(left)) as a, Image.open(BytesIO(right)) as b:
        return a.size == b.size and a.convert('RGBA').tobytes() == b.convert('RGBA').tobytes()


def hinweise(image):
    # Never expose signed query strings, file paths, or image data.
    result = {'felder': sorted(image), 'position': image.get('sortNumber'),
              'hauptbild': image.get('isMainImage'), 'kennungen': {}}
    for key, value in image.items():
        if isinstance(value, str):
            try:
                result['kennungen'][key] = str(UUID(value))
            except (ValueError, TypeError):
                pass
            if key.lower() in ('url', 'previewurl'):
                path = urlsplit(value).path
                result[key] = {'pfad_uuids': re.findall(
                    r'[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}', path),
                    'platzhalter': '{' in path or '%7b' in path.lower()}
        elif key.lower().endswith('id') and type(value) is int:
            result['kennungen'][key] = value
    return result


async def untersuchen(c, job, expected, emit=print):
    if c.url != job['api_ziel']:
        raise ValueError('API-Ziel stimmt nicht mit dem Auftrag überein.')
    detail = await c._request('GET', '/v2/items/' + job['artikel'])
    if detail.get('id') != job['artikel'] or detail.get('identifiers', {}).get('sku') != job['sku']:
        raise ValueError('Artikelidentität stimmt nicht überein.')
    for field, groups in detail.get('images', {}).items():
        if field == 'defaultImages': groups = [{'images': groups}]
        for group in groups or []:
            for image in group.get('images', []):
                if image.get('blobIdentifier') is None:
                    emit(json.dumps({'bereich': field, 'kanal': {k: v for k, v in group.items() if k.endswith('Id')},
                                     **hinweise(image)}, ensure_ascii=False))
    rows = await c._request('GET', '/v1/items/' + job['artikel'] + '/images', expected_type=list)
    actual = zuordnungen(rows)
    before = job.get('v1_vorher')
    if before is not None:
        emit('Zuordnung: [Artikelnummer intern, Bildnummer, Kanal, Ebay-Konto, Position]')
        emit(json.dumps({'auftrags_bild': job.get('v1_id'), 'schreibversuch': job.get('v1_schreibversuch'),
                         'http_status': job.get('v1_http_status'),
                         'fehlt': [r for r in before if r not in actual],
                         'hinzu': [r for r in actual if r not in before]}, ensure_ascii=False))
    # Include non-shop images: a channel-specific replacement may leave the old
    # image in other channels or allocate a new image number only for the shop.
    candidates = {r.get('ImageId') for r in rows}
    if not candidates or len(candidates) > 30 or any(type(i) is not int or i <= 0 for i in candidates):
        raise ValueError('Keine begrenzte, eindeutige v1-Bildliste verfügbar.')
    matches = []
    for image_id in sorted(candidates):
        async with c.http.stream('GET', c.url + '/v1/items/imagedata/' + str(image_id)) as response:
            thumb = await bildantwort(response)
        equal = pixelgleich(expected, thumb)
        if equal: matches.append(image_id)
        emit(json.dumps({'v1_bild': image_id, 'pixelgleich': equal,
                         'zuordnungen': [{'kanal': r.get('SalesChannelId'), 'position': r.get('SortNumber')}
                                         for r in rows if r.get('ImageId') == image_id]}, ensure_ascii=False))
    if zuordnungen(await c._request('GET', '/v1/items/' + job['artikel'] + '/images', expected_type=list)) != actual:
        raise ValueError('Bildzuordnungen während der Diagnose verändert; Ergebnisse nicht als stabil verwenden.')
    emit('Pixelgleiche v1-Bilder: ' + json.dumps(matches))
    emit('Nur gelesen. Keine Zuordnung geändert und kein Upload wiederholt.')
    return matches


async def main(sku):
    jobs = sorted((j for j in auftraege() if j.get('sku') == sku and j.get('thumb_hash') and not j.get('ruecksetzung')),
                  key=lambda j: j.get('erstellt', ''))
    if not jobs: raise ValueError('Kein Uploadauftrag gefunden.')
    job = jobs[-1]
    with store.datenbank() as db:
        row = db.execute('SELECT datei FROM bildauftraege WHERE id=?', (job['id'],)).fetchone()
    if not row or not row[0]: raise ValueError('Gespeicherte Uploaddatei fehlt.')
    expected = vorschaubild(row[0])
    if hashlib.sha256(expected).hexdigest() != job['thumb_hash']:
        raise ValueError('Gespeicherter Vergleichswert ist nicht reproduzierbar.')
    print('Auftrag:', job['id'], '| Artikel:', sku, '| Status:', job['status'])
    async with OnPremClient.aus_umgebung() as c:
        await untersuchen(c, job, expected)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('sku')
    args = parser.parse_args()
    asyncio.run(main(args.sku))
