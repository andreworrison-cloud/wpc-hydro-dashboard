"""Exact definitions and publication contract for the GDI companion overlays."""
import datetime as dt
import hashlib
import json
import re
from pathlib import Path
from PIL import Image
from dynamics import RECIPE, SIGMA_KM

DEFINITIONS = {
 'mfc': {'label':'Moisture convergence', 'unit':'g kg⁻¹ h⁻¹', 'layer':'950–700 hPa · above-ground segments', 'levels':[-8,-4,-2,-1,1,2,4,8], 'color':'#56f29a', 'negative_color':'#dcab82', 'kind':'contours'},
 'div': {'label':'Upper divergence', 'unit':'10⁻⁵ s⁻¹', 'layer':'400–200 hPa', 'levels':[-12,-8,-4,-2,2,4,8,12], 'color':'#ffe16b', 'negative_color':'#91b8ff', 'kind':'contours'},
 'rh': {'label':'Upper humidity', 'unit':'%', 'layer':'400–300 hPa', 'levels':[30,50,70,90], 'color':'#f4b5c8', 'kind':'contours'},
 'pw': {'label':'Precipitable water', 'unit':'in', 'layer':'Total atmospheric column', 'levels':[.5,1,1.5,2,2.5,3,3.5], 'color':'#72e3ff', 'kind':'contours'},
 'low': {'label':'Low-level flow', 'unit':'kt', 'layer':'1000–850 hPa · above-ground segments', 'color':'#f5f5ef', 'kind':'barbs'},
 'upper': {'label':'Upper-level flow', 'unit':'kt', 'layer':'400–200 hPa', 'color':'#a8c2ff', 'kind':'barbs'},
}


def verify_metadata(m):
    if (m.get('schema') != 'gdi_dynamics_suite_v1' or m.get('recipe') != RECIPE or m.get('model') != 'rap'
        or m.get('crs') != 'EPSG:3857' or [m.get('width'),m.get('height')] != [2400,1360]
        or m.get('bounds') != [[24,-125],[50,-66]] or m.get('smoothing_sigma_km') != SIGMA_KM
        or not re.fullmatch(r'\d{10}-[a-f0-9]{12}-v1', m.get('generation',''))
        or m.get('definitions') != DEFINITIONS):
        raise ValueError('Invalid RAP dynamics definition')
    cycle = dt.datetime.fromisoformat(m['cycle'])
    if cycle.utcoffset() != dt.timedelta(0) or cycle.minute or cycle.second or cycle.microsecond:
        raise ValueError('Invalid cycle')
    if dt.datetime.fromisoformat(m['expires_at']) != cycle+dt.timedelta(hours=6):
        raise ValueError('Invalid dynamics expiry')
    expected = {f'{name}_{lead}' for name in DEFINITIONS for lead in (0,3)}
    if set(m.get('products',{})) != expected or set(m.get('assets',{})) != expected:
        raise ValueError('Incomplete dynamics suite')
    for key, product in m['products'].items():
        name, lead = key.rsplit('_',1)
        if product.get('field') != name or product.get('lead') != int(lead) or product.get('cycle') != m['cycle'] or dt.datetime.fromisoformat(product['valid_time']) != cycle+dt.timedelta(hours=int(lead)):
            raise ValueError('Misaligned dynamics product')
        asset = m['assets'][key]
        if asset.get('path') != f"generations/{m['generation']}/{key}.png" or not re.fullmatch(r'[a-f0-9]{64}',asset.get('sha256','')):
            raise ValueError('Invalid dynamics asset')
    if len(m.get('source_metadata',[])) != 2:
        raise ValueError('Missing dynamics provenance')
    grids = set()
    for lead, source in zip((0,3),m['source_metadata']):
        if source.get('cycle') != m['cycle'] or source.get('lead') != lead or source.get('model') != 'rap' or source.get('recipe') != RECIPE or not source.get('sources'):
            raise ValueError('Invalid dynamics source time')
        grids.add(source['grid_md5'])
    if len(grids) != 1:
        raise ValueError('Mixed dynamics grids')


def verify_publication(root):
    root = Path(root)
    m = json.loads((root/'metadata.json').read_text())
    verify_metadata(m)
    for asset in m['assets'].values():
        p = root/asset['path']
        if hashlib.sha256(p.read_bytes()).hexdigest() != asset['sha256']:
            raise ValueError('Dynamics checksum mismatch')
        with Image.open(p) as im:
            if im.size != (2400,1360) or im.mode != 'RGBA':raise ValueError('Dynamics image dimensions/mode')
            im.verify()
