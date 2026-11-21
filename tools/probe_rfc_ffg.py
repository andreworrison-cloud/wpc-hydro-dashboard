#!/usr/bin/env python3
"""Read-only H5 source diagnostic. Never publishes dashboard assets.

Python standard library only. Each invocation saves an immutable observation;
repeat across cycles to measure availability. Numeric units remain UNVERIFIED.
"""
import argparse
import concurrent.futures
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import struct
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen

SERVICE = 'https://mapservices.weather.noaa.gov/raster/rest/services/precip/rfc_gridded_ffg/MapServer'
LAYERS = {1: (0, 2, 3), 3: (4, 6, 7), 6: (8, 10, 11)}
POINTS = {'oklahoma': (-97, 35), 'pennsylvania': (-77, 41),
          'coastal_washington': (-123.5, 47), 'pacific_ocean': (-130, 35), 'denver': (-105, 40),
          'memphis': (-90, 35), 'minneapolis': (-93, 45),
          'phoenix': (-112, 33), 'atlanta': (-84.4, 33.7), 'florida': (-81, 28)}
FIELDS = ('idp_issueddate', 'idp_validtime', 'idp_filedate', 'idp_ingestdate')


def utc():
    return datetime.now(timezone.utc).isoformat()


def iso_ms(value):
    if value is None:
        return None
    return datetime.fromtimestamp(float(value) / 1000, timezone.utc).isoformat()


def fetch(path, params):
    url = SERVICE + path + '?' + urlencode(params)
    for attempt in range(3):
        try:
            with urlopen(Request(url, headers={'User-Agent': 'WPC-Hydro-H5-Source-Probe/0.1'}), timeout=35) as r:
                raw = r.read(20_000_001)
                if len(raw) > 20_000_000:
                    raise ValueError('Response exceeds diagnostic size limit')
                headers = {k: r.headers.get(k) for k in ('Date', 'Last-Modified', 'ETag', 'Content-Type')}
            return raw, {'url': url, 'retrieved_at': utc(), 'headers': headers,
                         'sha256': hashlib.sha256(raw).hexdigest()}
        except Exception:
            if attempt == 2:
                raise
            time.sleep(attempt + 1)


def get_json(path, **params):
    raw, request = fetch(path, dict(params, f='json'))
    data = json.loads(raw)
    if 'error' in data:
        raise ValueError(f'ArcGIS error: {data["error"]}')
    return {'data': data, 'request': request}


def footprint(layer):
    result = get_json(f'/{layer}/query', where='1=1', outFields='*', returnGeometry='false')
    d = result['data']
    if d.get('exceededTransferLimit') or not d.get('features'):
        raise ValueError('Missing or truncated footprint records')
    return result


def identity(result):
    return sorted((f['attributes']['objectid'], f['attributes'].get('idp_filedate'),
                   f['attributes'].get('idp_issueddate')) for f in result['data']['features'])


def validate_png(raw):
    if len(raw) < 33 or raw[:8] != b'\x89PNG\r\n\x1a\n' or raw[12:16] != b'IHDR':
        raise ValueError('Export is not a PNG')
    width, height = struct.unpack('>II', raw[16:24])
    if (width, height) != (1200, 600) or b'IEND' not in raw[-12:]:
        raise ValueError('Unexpected PNG dimensions or missing end marker')
    return width, height


def probe_duration(hours, folder):
    group, catalog, image = LAYERS[hours]
    print(f'{hours}h: reading source metadata and rendering preview', flush=True)
    before = footprint(catalog)
    layer = get_json(f'/{group}')
    raster = get_json(f'/{image}')
    raw, request = fetch('/export', dict(f='image', bbox='-126,24,-66,50', bboxSR=4326,
        imageSR=4326, size='1200,600', format='png32', transparent='true', layers=f'show:{image}'))
    dimensions = validate_png(raw)
    (folder / f'ffg_{hours}h_preview.png').write_bytes(raw)
    after = footprint(catalog)
    records = []
    for feature in after['data']['features']:
        a = feature['attributes']
        records.append({'name': a.get('name'), 'times_utc': {k: iso_ms(a.get(k)) for k in FIELDS},
                        'source_duration_field': a.get('idp_fcst_hour')})
    return {'hours': hours, 'catalog_before': before, 'catalog_after': after,
            'catalog_stable_during_export': identity(before) == identity(after),
            'records': records, 'group_metadata': layer, 'raster_metadata': raster,
            'preview': {'request': request, 'dimensions': dimensions,
                        'role': 'display_only_not_scientific_input'},
            'underlying_rfc_issue_times': None}


def probe_point(name, coordinates):
    print(f'Point query: {name}', flush=True)
    result = get_json('/identify', geometry=','.join(map(str, coordinates)),
        geometryType='esriGeometryPoint', sr=4326, layers='all:3,7,11', tolerance=0,
        mapExtent='-132,24,-66,50', imageDisplay='1200,600,96', returnGeometry='false')
    return {'coordinates_lon_lat': coordinates, 'response': result,
            'numeric_units': 'UNVERIFIED', 'missing_is_not_zero': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    folder = args.output_dir / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    folder.mkdir(parents=True, exist_ok=False)
    report = {'revision': 'h5-source-probe-v0.1', 'started_at': utc(), 'service': SERVICE,
              'production_ready': False, 'numeric_grid_access_proven': False,
              'numeric_units': 'UNVERIFIED', 'source_freshness': 'NOT_YET_VALIDATED',
              'rfc_cycle_context': '00/06/12/18Z plus event-driven updates; mosaic refresh is separate',
              'durations': {}, 'points': {}, 'errors': {}}
    try:
        report['service_metadata'] = get_json('')
        report['legend'] = get_json('/legend')
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            jobs = {pool.submit(probe_duration, h, folder): ('durations', str(h)) for h in LAYERS}
            jobs.update({pool.submit(probe_point, n, c): ('points', n) for n, c in POINTS.items()})
            for job in concurrent.futures.as_completed(jobs):
                section, key = jobs[job]
                try:
                    report[section][key] = job.result()
                except Exception as exc:
                    report['errors'][f'{section}/{key}'] = str(exc)
    except Exception as exc:
        report['errors']['service'] = str(exc)
    report['completed_at'] = utc()
    report['observation_complete'] = (not report['errors'] and len(report['durations']) == 3
        and all(d['catalog_stable_during_export'] for d in report['durations'].values()))
    (folder / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'report': str(folder / 'report.json'), 'complete': report['observation_complete'],
                      'errors': report['errors']}, indent=2), flush=True)
    return 0 if report['observation_complete'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
