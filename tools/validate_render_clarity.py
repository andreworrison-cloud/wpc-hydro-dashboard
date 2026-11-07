#!/usr/bin/env python3
from pathlib import Path
import re, sys

ROOT = Path(__file__).resolve().parents[1]
errors = []

files = {
    'RAP': ROOT / 'fetch_rap.py',
    'CAM Nowcasts': ROOT / 'fetch_cam.py',
    'Day 1 ERO CAMs': ROOT / 'fetch_cam_ero.py',
}
texts = {}
for label, path in files.items():
    if not path.exists():
        errors.append(f'Missing {label} script: {path.name}')
        continue
    txt = path.read_text(encoding='utf-8')
    texts[label] = txt
    if 'MAP_RENDER_DPI = 450' not in txt:
        errors.append(f'{label}: MAP_RENDER_DPI is not 450.')
    if 'map_pixel_dimensions' not in txt or '[4500, 2700]' not in txt:
        errors.append(f'{label}: 4500x2700 render metadata missing.')
    if "figsize=(10, 6), dpi=MAP_RENDER_DPI" not in txt:
        errors.append(f'{label}: map figure does not use fixed 10x6 physical size with render DPI.')
    if "transparent=True, dpi=MAP_RENDER_DPI" not in txt:
        errors.append(f'{label}: explicit high-density savefig DPI missing.')

rap = texts.get('RAP', '')
if rap:
    if 'LEGEND_RENDER_DPI = 200' not in rap:
        errors.append('RAP: legend DPI is not 200.')
    for required in [
        'pwat_smooth = safe_smooth(pwat, 1.0, 0.25)',
        'mucape_smooth = safe_smooth(mucape, 1.5, 100)',
        'trans_850_smooth = safe_smooth(trans_850, 1.5, 50)',
    ]:
        if required not in rap:
            errors.append(f'RAP: existing field-processing contract changed: {required}')

for label in ('CAM Nowcasts', 'Day 1 ERO CAMs'):
    txt = texts.get(label, '')
    if not txt:
        continue
    if "method='linear'" not in txt:
        errors.append(f'{label}: existing REFS-to-HREF linear interpolation contract changed.')
    if 'prob_levels = [10, 30, 50, 70, 90, 100]' not in txt:
        errors.append(f'{label}: probability contour thresholds changed.')

if errors:
    print('RAP/CAM Render Clarity Phase-1 validation: FAIL')
    for e in errors:
        print(' -', e)
    sys.exit(1)

print('RAP/CAM Render Clarity Phase-1 validation: PASS')
print(' - Map PNG target: 4500x2700 px (450 DPI at 10x6 in)')
print(' - RAP legends: 200 DPI')
print(' - RAP field processing/smoothing contract preserved')
print(' - CAM probability thresholds preserved')
print(' - CAM REFS-to-HREF interpolation contract preserved')
