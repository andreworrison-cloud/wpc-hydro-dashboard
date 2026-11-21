#!/usr/bin/env python3
"""Build an offline, frozen display review from validated ingest output; no publishing."""
import argparse
import base64
import hashlib
import json
from pathlib import Path


def build(public, output):
    metadata = json.loads((public / 'metadata.json').read_text())
    active = metadata['active']
    images = {}
    for hour in ('1', '3', '6'):
        asset = active['assets'][hour]
        path = (public / asset['path']).resolve()
        if not path.is_relative_to(public.resolve()):
            raise ValueError('Asset outside public root')
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != asset['sha256']:
            raise ValueError('Image hash mismatch')
        images[hour] = 'data:image/png;base64,' + base64.b64encode(data).decode()
    if active['legend']['crs'] not in ('EPSG:4326', 'EPSG:3857') or active['legend']['bounds_wsen'] != [-126, 24, -66, 50]:
        raise ValueError('Review map expects geographic display bounds')
    root = Path(__file__).resolve().parents[1]
    mercator = active['legend']['crs'] == 'EPSG:3857'
    name = 'rfc_ffg_leaflet_template.html' if mercator else 'rfc_ffg_review_template.html'
    template = (Path(__file__).parent / name).read_text()
    data = {'metadata': metadata, 'images': images}
    if mercator:
        vendor = root / 'review/vendor'
        data['states'] = json.loads((vendor / 'us-states.json').read_text())
        data['basemaps'] = json.loads((root / 'review/basemaps.json').read_text())
        template = template.replace('/*LEAFLET_JS*/', (vendor / 'leaflet-1.9.4.js').read_text())
        template = template.replace('/*LEAFLET_CSS*/', (vendor / 'leaflet-1.9.4.css').read_text())
    payload = json.dumps(data).replace('<', '\\u003c')
    html = template.replace('/*DISPLAY_CONTRACT*/', (Path(__file__).parent / 'rfc_ffg_display.js').read_text())
    html = html.replace('/*REVIEW_DATA*/', 'const review = ' + payload + ';')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html)
    print(output)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--public-dir', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    build(args.public_dir, args.output)
