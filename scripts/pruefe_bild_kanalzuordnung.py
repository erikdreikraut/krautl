"""One journaled v1 assignment probe, without image data or automatic retries."""
import argparse
import asyncio
import copy
import json
import httpx
from app import bilder_speicher as store
from app.bilder_ersetzen import liste, bild, zuordnungen
from app.bilder_upload import auftraege, sichern, lokal, detail_lesen, bildinhalt_bestaetigt
from app.jtl_onprem import OnPremClient


async def pruefen(c, job, kanal, ausfuehren=False):
    if job.get('ruecksetzung') or job.get('art') != 'ersetzen_alle' or job.get('status') != 'unklar':
        raise ValueError('Kein offener v1-Austauschauftrag.')
    if c.url != job['api_ziel']:
        raise ValueError('Wawi-Ziel stimmt nicht überein.')
    if kanal in ('2-2-1', '1-1-1'):
        raise ValueError('Shop und mehrdeutiger Standardkanal sind für diesen Einzeltest ausgeschlossen.')
    a, data = lokal(job['artikel'], job['revision'])
    if data.get('api_ziel') != c.url:
        raise ValueError('Lokaler Bestand gehört zu einem anderen Wawi-Ziel.')
    await detail_lesen(c, a['id'], job['sku'])
    rows = await liste(c, a['id'])
    actual = zuordnungen(rows)
    attempt = job.get('kanaltest')
    if attempt:
        if attempt['kanal'] != kanal:
            raise ValueError('Ein Kanaltest wurde bereits protokolliert. Kein weiterer Schreibversuch.')
    else:
        before = job['v1_vorher']
        old = job['v1_id']
        shop = [r for r in before if r[1] == old and r[2] == '2-2-1']
        if len(shop) != 1:
            raise ValueError('Ursprüngliche Shopzuordnung nicht eindeutig.')
        current = [r for r in actual if r[2] == '2-2-1' and r[4] == shop[0][4]]
        if len(current) != 1 or current[0][1] == old:
            raise ValueError('Keine eindeutige neue Bildnummer im Shop.')
        new = current[0][1]
        if new in {r[1] for r in before}:
            raise ValueError('Neues Bild war bereits im Ausgangsbestand vorhanden.')
        extra = [r for r in actual if r not in before]
        if [r for r in before if r not in actual] != shop or any(
            r[1] != new or r[2] not in ('2-2-1', '1-1-1') for r in extra
        ):
            raise ValueError('Bestand weicht über den bekannten Shop-Austausch hinaus ab.')
        target = [r for r in before if r[1] == old and r[2] == kanal]
        if len(target) != 1 or target[0][3]:
            raise ValueError('Zielkanal nicht eindeutig oder benötigt eine separate eBay-Kontokennung.')
        if any(r[1] == new and r[2] == kanal for r in actual):
            raise ValueError('Neues Bild ist bereits im Zielkanal zugeordnet.')
        expected = copy.deepcopy(actual)
        expected.remove(target[0])
        expected.append([target[0][0], new, kanal, '', target[0][4]])
        expected.sort()
        if not bildinhalt_bestaetigt(job, await bild(c, new)):
            raise ValueError('Neues Bild stimmt nicht mit der gespeicherten Datei überein.')
        print(f'Einzeltest: vorhandenes Bild {new}, Kanal {kanal}, Position {target[0][4]}. Keine Bilddaten, kein Löschen.')
        if not ausfuehren:
            print('Nur vorbereitet; für genau einen PATCH --ausfuehren verwenden.')
            return
        if zuordnungen(await liste(c, a['id'])) != actual or not store.freigegeben(a['id'], job['revision']):
            raise ValueError('Bestand vor dem Schreibversuch verändert.')
        attempt = dict(kanal=kanal, bild=new, position=target[0][4], vorher=actual,
                       ziel=expected, zeit=store.jetzt())
        job['kanaltest'] = attempt
        sichern(job)  # Durable intent before the only possible PATCH.
        try:
            response = await c.http.patch(c.url+'/v1/items/'+a['id']+'/images/'+str(new),
                                         json={'SalesChannelId':kanal, 'SortNumber':target[0][4]})
            attempt['http_status'] = response.status_code
        except httpx.HTTPError:
            attempt['antwort_unbekannt'] = True
        sichern(job)
        rows = await liste(c, a['id'])
        actual = zuordnungen(rows)
    attempt['ist'] = actual
    attempt['ziel_bestaetigt'] = actual == attempt['ziel'] and bildinhalt_bestaetigt(job, await bild(c, attempt['bild']))
    sichern(job)
    print(json.dumps({'kanal':kanal, 'http_status':attempt.get('http_status'),
                      'ziel_bestaetigt':attempt['ziel_bestaetigt'],
                      'fehlt': [r for r in attempt['ziel'] if r not in actual],
                      'hinzu': [r for r in actual if r not in attempt['ziel']]}, ensure_ascii=False))
    print('Gesamtauftrag bleibt ungeklärt. Kein weiterer PATCH und keine automatische Bereinigung.')


async def main(sku, kanal, ausfuehren):
    with store.Laufsperre():
        jobs = [j for j in auftraege() if j.get('sku') == sku and not j.get('ruecksetzung')
                and j.get('art') == 'ersetzen_alle' and j.get('status') == 'unklar']
        if len(jobs) != 1:
            raise ValueError('Offener Austauschauftrag nicht eindeutig.')
        async with OnPremClient.aus_umgebung() as c:
            await pruefen(c, jobs[0], kanal, ausfuehren)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('sku'); p.add_argument('--kanal', required=True)
    p.add_argument('--ausfuehren', action='store_true')
    args = p.parse_args()
    asyncio.run(main(args.sku, args.kanal, args.ausfuehren))
