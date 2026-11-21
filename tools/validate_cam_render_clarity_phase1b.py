#!/usr/bin/env python3
from pathlib import Path
import ast
import sys

ROOT = Path(__file__).resolve().parents[1]
errors = []

for filename, label, revision in [
    ('fetch_cam.py', 'CAM Nowcasts', 'cam-display-density-v1b'),
    ('fetch_cam_ero.py', 'Day 1 ERO CAMs', 'ero-cam-display-density-v1b'),
]:
    path = ROOT / filename
    if not path.exists():
        errors.append(f'{label}: missing {filename}')
        continue
    text = path.read_text(encoding='utf-8')
    try:
        ast.parse(text)
    except SyntaxError as exc:
        errors.append(f'{label}: Python syntax error: {exc}')
        continue

    required = [
        'MAP_RENDER_DPI = 600',
        f'RENDER_REVISION = "{revision}"',
        'map_pixel_dimensions": [6000, 3600]',
        'figsize=(10, 6), dpi=MAP_RENDER_DPI',
        'transparent=True, dpi=MAP_RENDER_DPI',
        'antialiased=True',
        '"contour_antialiasing_display_only": True',
        'prob_levels = [10, 30, 50, 70, 90, 100]',
        "method='linear'",
    ]
    for fragment in required:
        if fragment not in text:
            errors.append(f'{label}: missing required Phase 1B/science-contract fragment: {fragment}')

    forbidden = [
        'gaussian_filter(',
        'GaussianFilter',
        'bicubic',
        'cubic',
    ]
    for fragment in forbidden:
        if fragment in text:
            errors.append(f'{label}: unexpected smoothing/resampling fragment introduced: {fragment}')

if errors:
    print('CAM Render Clarity Phase 1B validation: FAIL')
    for error in errors:
        print(' -', error)
    sys.exit(1)

print('CAM Render Clarity Phase 1B validation: PASS')
print(' - CAM map PNG target: 6000x3600 px (600 DPI at 10x6 in)')
print(' - Filled-contour antialiasing explicitly enabled at render time')
print(' - Probability bins remain 10/30/50/70/90/100%')
print(' - Existing REFS-to-HREF linear interpolation contract preserved')
print(' - No new meteorological smoothing or bicubic/cubic resampling introduced')
