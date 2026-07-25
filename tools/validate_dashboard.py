#!/usr/bin/env python3
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
app = (ROOT / "app.js").read_text(encoding="utf-8")
index = (ROOT / "index.html").read_text(encoding="utf-8")
css = (ROOT / "style.css").read_text(encoding="utf-8")

errors = []

# Preserve the exact operational menu order. Dashboard Utilities is rendered
# immediately after the registered data sections rather than being stored as
# another dashboardSections entry.
required_sections = [
    "Active Hazards & Warnings",
    "Radar and Satellite Data (Real-Time)",
    "Antecedent Hydrologic Conditions",
    "RAP Mesoanalysis Data",
    "CAM Nowcasts (+3h to +9h)",
    "CAM Nowcasts (+9h to +15h)",
    "Day 1 ERO CAMs (12Z-12Z)",
    "Experimental Models",
    "Dashboard Utilities",
]

section_positions = []
for section in required_sections:
    marker = (
        f"title: '{section}'"
        if section != "Dashboard Utilities"
        else '<span class="section-title">Dashboard Utilities</span>'
    )
    position = app.find(marker)
    if position < 0:
        errors.append(f"Missing section: {section}")
    section_positions.append(position)

if (
    all(position >= 0 for position in section_positions)
    and section_positions != sorted(section_positions)
):
    errors.append("Dashboard sections are not in the required order.")

required_labels = [
    "Active Hydro Warnings & Advisories",
    "NEXRAD Radar (2-Hour Loop)",
    "NWM Soil Saturation (0-40cm)",
    "NLDAS-2 Noah Relative Soil Moisture (0-10 cm)",
    "NLDAS-2 Noah Relative Soil Moisture (0-100 cm)",
    "NASA SPoRT-LIS VSM Percentile (0–100 cm)",
    "Precipitable Water (PWAT)",
    "3-Hour PWAT Change",
    "+3h Forecast:</b> PWAT",
    "850mb Moisture Transport",
    "3-Hour 850mb Moisture Transport Change",
    "+3h Forecast:</b> 850mb Moisture Transport",
    "<b>SuperEnsemble</b>: Max FFG Exceedance",
    "<b>SuperEnsemble [ERO]</b>: Max FFG Exceedance",
]

for label in required_labels:
    if label not in app:
        errors.append(f"Missing required layer label: {label}")

# Enforce the agreed order within Antecedent Hydrologic Conditions.
antecedent_start = app.find("title: 'Antecedent Hydrologic Conditions'")
rap_start = app.find("title: 'RAP Mesoanalysis Data'")
if antecedent_start >= 0 and rap_start > antecedent_start:
    antecedent_block = app[antecedent_start:rap_start]
    antecedent_labels = [
        "NWM Soil Saturation (0-40cm)",
        "NLDAS-2 Noah Relative Soil Moisture (0-10 cm)",
        "NLDAS-2 Noah Relative Soil Moisture (0-100 cm)",
        "NASA SPoRT-LIS VSM Percentile (0–100 cm)",
    ]
    antecedent_positions = [
        antecedent_block.find(label) for label in antecedent_labels
    ]
    if any(position < 0 for position in antecedent_positions):
        errors.append(
            "Antecedent Hydrologic Conditions is missing a required layer."
        )
    elif antecedent_positions != sorted(antecedent_positions):
        errors.append(
            "Antecedent Hydrologic Conditions layers are not in the "
            "required order."
        )

# Confirm the new NLDAS files, metadata, legends, and time boxes are wired in.
required_nldas_fragments = [
    "static/nldas_rsm_0_10cm.png",
    "static/nldas_rsm_0_100cm.png",
    "static/nldas_rsm_metadata.json",
    "fetchNLDASRSMMetadata",
    "nldas-rsm-010-time-box",
    "nldas-rsm-0100-time-box",
    "nldasRsm010LegendHTML",
    "nldasRsm0100LegendHTML",
]
for fragment in required_nldas_fragments:
    if fragment not in app:
        errors.append(f"Missing NLDAS RSM integration fragment: {fragment}")

if "NASA SPoRT-LIS Volumetric Soil Moisture Percentile (0–100 cm)" not in app:
    errors.append("Updated SPoRT-LIS legend heading is missing.")

ids = re.findall(r"\{id: '([a-z0-9-]+)', label:", app)
duplicates = sorted({item for item in ids if ids.count(item) > 1})
if duplicates:
    errors.append(f"Duplicate layer ids: {duplicates}")

expected_layer_count = 98
if len(ids) != expected_layer_count:
    errors.append(
        f"Expected {expected_layer_count} registered layers, found {len(ids)}."
    )

if "const groupedOverlays" in app or "L.control.groupedLayers" in app:
    errors.append("Legacy grouped-layer menu code is still active.")
if "leaflet-groupedlayercontrol" in index:
    errors.append("Legacy grouped-layer-control dependency is still loaded.")
if 'id="dashboard-sidebar"' not in index:
    errors.append("Sidebar markup is missing from index.html.")
if (
    "window.WPCDashboard" not in app
    or "registerLayer: registerDashboardLayer" not in app
):
    errors.append("Plug-and-play layer registration API is missing.")
if ".dashboard-sidebar" not in css or ".dashboard-section" not in css:
    errors.append("Sidebar styles are missing.")

if "const LEGEND_DOCK_SESSION_KEY" not in app:
    errors.append("Responsive legend-dock controller is missing.")
if (
    'id="legend-dock-toggle"' not in app
    or 'id="legend-dock-body"' not in app
):
    errors.append("Legend-dock controls are missing from app.js.")
if "rapTimeControl" in app or "const legendControl" in app:
    errors.append("Legacy separate legend/time controls are still active.")
if ".legend-dock" not in css or ".legend-dock.is-collapsed" not in css:
    errors.append("Responsive legend-dock styles are missing.")
if "nldas-rsm-v1" not in index:
    errors.append(
        "Frontend cache-busting token for NLDAS RSM integration is missing."
    )

if errors:
    print("Dashboard validation FAILED:")
    for error in errors:
        print(f" - {error}")
    sys.exit(1)

print(
    "Dashboard validation passed: "
    f"{len(ids)} registered layers; menu order, antecedent order, "
    "NLDAS RSM mappings, and required labels preserved."
)
