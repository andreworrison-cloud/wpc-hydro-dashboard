#!/usr/bin/env python3
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
app = (ROOT / 'app.js').read_text(encoding='utf-8')
index = (ROOT / 'index.html').read_text(encoding='utf-8')
css = (ROOT / 'style.css').read_text(encoding='utf-8')

errors = []

required_sections = [
    'Active Hazards & Warnings',
    'Radar and Satellite Data (Real-Time)',
    'Antecedent Hydrologic Conditions',
    'RAP Mesoanalysis Data',
    'CAM Nowcasts (+3h to +9h)',
    'CAM Nowcasts (+9h to +15h)',
    'Day 1 ERO CAMs (12Z-12Z)',
    'Experimental Models',
]
positions = []
for section in required_sections:
    position = app.find(f"title: '{section}'")
    if position < 0:
        errors.append(f'Missing section: {section}')
    positions.append(position)
if all(position >= 0 for position in positions) and positions != sorted(positions):
    errors.append('Dashboard sections are not in the required order.')

required_labels = [
    'Active Hydro Warnings & Advisories',
    'NEXRAD Radar (2-Hour Loop)',
    'NWM Soil Saturation (0-40cm)',
    'SPoRT-LIS Soil Moisture Percentile (0-100cm)',
    'Precipitable Water (PWAT)',
    '3-Hour PWAT Change',
    '+3h Forecast:</b> PWAT',
    '850mb Moisture Transport',
    '3-Hour 850mb Moisture Transport Change',
    '+3h Forecast:</b> 850mb Moisture Transport',
    '<b>SuperEnsemble</b>: Max FFG Exceedance',
    '<b>SuperEnsemble [ERO]</b>: Max FFG Exceedance',
]
for label in required_labels:
    if label not in app:
        errors.append(f'Missing required layer label: {label}')

ids = re.findall(r"\{id: '([a-z0-9-]+)', label:", app)
duplicates = sorted({item for item in ids if ids.count(item) > 1})
if duplicates:
    errors.append(f'Duplicate layer ids: {duplicates}')

if 'const groupedOverlays' in app or 'L.control.groupedLayers' in app:
    errors.append('Legacy grouped-layer menu code is still active.')
if 'leaflet-groupedlayercontrol' in index:
    errors.append('Legacy grouped-layer-control dependency is still loaded.')
if 'id="dashboard-sidebar"' not in index:
    errors.append('Sidebar markup is missing from index.html.')
if 'window.WPCDashboard' not in app or 'registerLayer: registerDashboardLayer' not in app:
    errors.append('Plug-and-play layer registration API is missing.')
if '.dashboard-sidebar' not in css or '.dashboard-section' not in css:
    errors.append('Sidebar styles are missing.')

if errors:
    print('Dashboard validation FAILED:')
    for error in errors:
        print(f' - {error}')
    sys.exit(1)

print(f'Dashboard validation passed: {len(ids)} registered layers; required order and labels preserved.')
