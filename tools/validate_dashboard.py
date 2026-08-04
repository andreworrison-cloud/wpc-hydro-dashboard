#!/usr/bin/env python3
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
app = (ROOT / "app.js").read_text(encoding="utf-8")
index = (ROOT / "index.html").read_text(encoding="utf-8")
css = (ROOT / "style.css").read_text(encoding="utf-8")
glm_generator = (ROOT / "fetch_glm_mosaic.py").read_text(encoding="utf-8")

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
    "MRMS FLASH CREST Unit Q — Rolling 24-Hour Maximum",
    "MRMS FLASH FFD — Rolling 24-Hour Maximum Category",
    "GOES GLM Controlled Mosaic — Latest 5-Minute FED",
    "GOES GLM Controlled Mosaic — Rolling 30-Minute Accumulation",
    "GOES GLM Controlled Mosaic — Rolling 60-Minute Accumulation",
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

# Enforce the agreed placement of the two rolling MRMS FLASH layers within
# Radar and Satellite Data. They belong directly after MRMS 24-Hour QPE and
# before the longer-duration MRMS QPE layers.
radar_start = app.find("title: 'Radar and Satellite Data (Real-Time)'")
antecedent_start = app.find("title: 'Antecedent Hydrologic Conditions'")
if radar_start >= 0 and antecedent_start > radar_start:
    radar_block = app[radar_start:antecedent_start]
    radar_labels = [
        "{id: 'mrms-qpe-24h'",
        "{id: 'mrms-flash-crest-24h'",
        "{id: 'mrms-flash-ffd-24h'",
        "{id: 'mrms-qpe-48h'",
    ]
    radar_positions = [radar_block.find(label) for label in radar_labels]
    if any(position < 0 for position in radar_positions):
        errors.append(
            "Radar and Satellite Data is missing a required MRMS FLASH layer."
        )
    elif radar_positions != sorted(radar_positions):
        errors.append(
            "MRMS FLASH rolling layers are not in the required radar-section order."
        )

    glm_radar_labels = [
        "{id: 'goes-west-ir'",
        "{id: 'glm-mosaic-5min'",
        "{id: 'glm-mosaic-30min'",
        "{id: 'glm-mosaic-60min'",
    ]
    glm_radar_positions = [radar_block.find(label) for label in glm_radar_labels]
    if any(position < 0 for position in glm_radar_positions):
        errors.append("Radar and Satellite Data is missing a primary GLM mosaic layer.")
    elif glm_radar_positions != sorted(glm_radar_positions):
        errors.append("Primary GLM mosaic layers are not in the required radar-section order.")

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

# Confirm the rolling MRMS FLASH files, metadata, legends, and time boxes are
# wired into the dashboard.
required_mrms_flash_fragments = [
    "static/mrms_crest_unitq_max24h.png",
    "static/mrms_crest_unitq_max24h_metadata.json",
    "static/mrms_ffd_max24h.png",
    "static/mrms_ffd_max24h_metadata.json",
    "fetchMRMSFlash24hMetadata",
    "mrms-crest-24h-time-box",
    "mrms-ffd-24h-time-box",
    "mrmsCrest24hLegendHTML",
    "mrmsFfd24hLegendHTML",
]
for fragment in required_mrms_flash_fragments:
    if fragment not in app:
        errors.append(
            f"Missing MRMS FLASH 24-hour integration fragment: {fragment}"
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

required_glm_fragments = [
    "static/glm_conus_mosaic_5min.png",
    "static/glm_conus_mosaic_30min.png",
    "static/glm_conus_mosaic_60min.png",
    "glm_dashboard_v1",
    "fetchGLMMetadata",
    "glm-time-box",
    "buildGLMLegendHTML",
    "glmLegendHTMLFromMetadata",
    "validateGLMRenderingMetadata",
    "metadata.rendering",
    "grid-template-columns: repeat(2, minmax(0, 1fr))",
    "enforceExclusiveGLMSelection",
    "exclusiveGroup: 'glm-primary'",
    "glm_convective_trend_v1",
    "glm-trend-card",
    "GLM_TREND_SESSION_KEY",
    "buildGLMTrendSparkline",
    "updateGLMTrendCard",
    "Rapidly Increasing",
    "Strongest acceleration",
]
for fragment in required_glm_fragments:
    if fragment not in app:
        errors.append(f"Missing GOES GLM integration fragment: {fragment}")

if "const glmFiveMinuteLegendHTML" in app or "const glmRollingLegendHTML" in app:
    errors.append("GOES GLM legends are still hardcoded separately from product metadata.")

required_glm_generator_fragments = [
    "FIVE_MIN_BINS = [1, 2, 4, 8, 16, 32, 64, 128, 256]",
    '"128–255", "≥256"',
    "ROLLING_BINS = [1, 2, 4, 8, 16, 32, 64, 128, 256, 512]",
    '"128–255", "256–511", "≥512"',
    '"rendering": {',
    '"bins": list(bins)',
    '"labels": list(labels)',
    '"rgba": [list(color) for color in colors]',
    "UFVS_TREND_DOMAINS = [",
    "TREND_HISTORY_MINUTES = 60",
    "TREND_RECENT_SLOT_COUNT = 3",
    "build_convective_trend_analysis",
    "classify_convective_trend",
    '"metadata_mode": "glm_convective_trend_v1"',
    'metadata["convective_trend"] = convective_trend',
]
for fragment in required_glm_generator_fragments:
    if fragment not in glm_generator:
        errors.append(f"Missing GOES GLM generator legend contract: {fragment}")


for forbidden in [
    "glm-debug-g18-5min",
    "glm-debug-g19-5min",
    "glm-debug-ownership",
    "GLM Debug Layers",
]:
    if forbidden in app:
        errors.append(f"Production dashboard still exposes forbidden GLM debug control: {forbidden}")

ids = re.findall(r"\{id: '([a-z0-9-]+)', label:", app)
duplicates = sorted({item for item in ids if ids.count(item) > 1})
if duplicates:
    errors.append(f"Duplicate layer ids: {duplicates}")

expected_layer_count = 103
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
if "glm-v1" not in index and "glm-v2" not in index:
    errors.append(
        "Frontend cache-busting token for GOES GLM integration is missing."
    )

if errors:
    print("Dashboard validation FAILED:")
    for error in errors:
        print(f" - {error}")
    sys.exit(1)

print(
    "Dashboard validation passed: "
    f"{len(ids)} registered layers; menu order, MRMS FLASH order, "
    "antecedent order, MRMS/NLDAS/GLM mappings, compact legends, "
    "and the GLM trend diagnostic preserved."
)
