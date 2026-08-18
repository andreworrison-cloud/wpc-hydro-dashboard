#!/usr/bin/env python3
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
app = (ROOT / "app.js").read_text(encoding="utf-8")
index = (ROOT / "index.html").read_text(encoding="utf-8")
css = (ROOT / "style.css").read_text(encoding="utf-8")
glm_generator = (ROOT / "fetch_glm_mosaic.py").read_text(encoding="utf-8")
glm_workflow = (ROOT / ".github" / "workflows" / "update_glm_mosaic.yml").read_text(encoding="utf-8")
lightningcast_generator = (ROOT / "fetch_lightningcast.py").read_text(encoding="utf-8")
lightningcast_workflow = (ROOT / ".github" / "workflows" / "update_lightningcast.yml").read_text(encoding="utf-8")
hrrr_tle_generator = (ROOT / "fetch_hrrr_tle.py").read_text(encoding="utf-8")
hrrr_tle_workflow = (ROOT / ".github" / "workflows" / "update_hrrr_tle.yml").read_text(encoding="utf-8")

errors = []

# HRRR-TLE dashboard integration adds 18 registered layers to the 105-layer LightningCast-era registry.
EXPECTED_LAYER_COUNT = 123
LIGHTNINGCAST_LAYER_ID = "lightningcast-probability-60min"

# Preserve the exact operational menu order. Dashboard Utilities is rendered
# immediately after the registered data sections rather than being stored as
# another dashboardSections entry.
required_sections = [
    "Active Hazards & Warnings",
    "Radar and Satellite Data (Real-Time)",
    "Antecedent Hydrologic Conditions",
    "RAP Mesoanalysis Data",
    "HRRR-TLE Flash Flood Guidance - Experimental",
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
    "GOES GLM Controlled Mosaic — Convective Trend (15 min)",
    "CIMSS/SSEC LightningCast — Probability of Lightning in Next 60 Minutes",
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
    "FFG Exceedance Consensus",
    "Median Neighborhood-Max QPF / FFG Ratio",
    "1-h FFG Exceedance",
    "3-h FFG Exceedance",
    "6-h FFG Exceedance",
    "1-h QPF ≥ 1 in",
    "1-h QPF ≥ 2 in",
    "1-h QPF ≥ 3 in",
    "≥1 in in 2 of 3 Hours",
    "Rolling 3-h QPF ≥ 2 in",
    "Rolling 3-h QPF ≥ 3 in",
    "FFG Exceedance +00–03 h",
    "FFG Exceedance +03–06 h",
    "FFG Exceedance +06–09 h",
    "FFG Exceedance +09–12 h",
    "Prior 3 HRRR Cycles",
    "Latest 3 HRRR Cycles",
    "Run-to-Run Signal Change",
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
        "{id: 'glm-convective-trend-15min'",
        "{id: 'lightningcast-probability-60min'",
    ]
    glm_radar_positions = [radar_block.find(label) for label in glm_radar_labels]
    if any(position < 0 for position in glm_radar_positions):
        errors.append("Radar and Satellite Data is missing a required GOES/LightningCast layer.")
    elif glm_radar_positions != sorted(glm_radar_positions):
        errors.append("GOES GLM and LightningCast layers are not in the required radar-section order.")

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
    "static/glm_convective_trend_15min_metadata.json",
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
    "GOES GLM Controlled Mosaic — Convective Trend (15 min)",
    "embedded_png_base64",
    "glm-convective-trend-15min",
    "color: '#ff4848'",
    "color: '#ffaa40'",
    "color: '#ffe878'",
    "color: '#4ceaff'",
    "color: '#3876ff'",
    "GLM_MANIFEST_URL",
    "GLM_MANIFEST_POLL_INTERVAL_MS = 90 * 1000",
    "refreshGLMFromManifest",
    "expectedWindowEnd",
    "requireComplete",
    "document.addEventListener('visibilitychange'",
    "window.addEventListener('focus'",
    "window.addEventListener('online'",
]
for fragment in required_glm_fragments:
    if fragment not in app:
        errors.append(f"Missing GOES GLM integration fragment: {fragment}")



required_lightningcast_fragments = [
    "CIMSS/SSEC LightningCast — Probability of Lightning in Next 60 Minutes",
    "static/lightningcast_conus_probability_60min.png",
    "static/lightningcast_conus_probability_60min_metadata.json",
    "static/lightningcast_manifest.json",
    "lightningcast_dashboard_v1e",
    "lightningcast_dashboard_manifest_v1",
    "lightningcast-probability-60min",
    "lightningcast-time-box",
    "buildLightningCastLegendHTML",
    "refreshLightningCastFromManifest",
    "LIGHTNINGCAST_MANIFEST_POLL_INTERVAL_MS = 90 * 1000",
    "Probability of lightning in the next 60 minutes",
    "LightningCast data courtesy CIMSS/SSEC",
    "cross_satellite_family_splitting",
]
for fragment in required_lightningcast_fragments:
    if fragment not in app:
        errors.append(f"Missing LightningCast dashboard integration fragment: {fragment}")

required_lightningcast_generator_fragments = [
    '"metadata_mode": "lightningcast_dashboard_v1e"',
    'THRESHOLDS = (10, 30, 50, 70, 90)',
    '"contour_lines_only": True',
    '"polygon_fill_inference": False',
    '"cross_satellite_family_splitting": False',
]
for fragment in required_lightningcast_generator_fragments:
    if fragment not in lightningcast_generator:
        errors.append(f"Missing LightningCast v1E generator contract: {fragment}")

required_lightningcast_workflow_fragments = [
    "Update LightningCast",
    "workflow_dispatch:",
    "workflow_run:",
    'workflows: ["Update GOES GLM Mosaic"]',
    "lightningcast_dashboard_v1e",
    "lightningcast_conus_probability_60min.png",
    "lightningcast_manifest.json",
]
for fragment in required_lightningcast_workflow_fragments:
    if fragment not in lightningcast_workflow:
        errors.append(f"Missing LightningCast workflow integration fragment: {fragment}")


# HRRR-TLE V3.3 dashboard integration contract.
required_hrrr_tle_app_fragments = [
    "HRRR-TLE Flash Flood Guidance - Experimental",
    "HRRR_TLE_LAYER_CONFIGS",
    "static/hrrr_tle_manifest.json",
    "static/hrrr_tle_metadata.json",
    "hrrr-tle-time-box",
    "buildHRRRTLELegendHTML",
    "refreshHRRRTLEFromManifest",
    "hrrr_tle_dashboard_v3_3",
    "Core FFG Guidance",
    "Heavy Rain / Persistence",
    "Timing / Evolution",
    "dashboard-layer-group",
    "hrrr-tle-ffg-consensus",
    "hrrr-tle-median-ratio",
    "hrrr-tle-run-change",
]
for fragment in required_hrrr_tle_app_fragments:
    if fragment not in app:
        errors.append(f"Missing HRRR-TLE dashboard integration fragment: {fragment}")

# Enforce exact section placement below RAP and above the first CAM Nowcast section.
rap_start = app.find("title: 'RAP Mesoanalysis Data'")
hrrr_tle_start = app.find("title: 'HRRR-TLE Flash Flood Guidance - Experimental'")
cam_start = app.find("title: 'CAM Nowcasts (+3h to +9h)'")
if not (rap_start >= 0 and hrrr_tle_start > rap_start and cam_start > hrrr_tle_start):
    errors.append("HRRR-TLE section is not directly ordered between RAP and CAM Nowcasts.")

hrrr_tle_ids = [
    "hrrr-tle-ffg-consensus", "hrrr-tle-median-ratio",
    "hrrr-tle-ffg-1h", "hrrr-tle-ffg-3h", "hrrr-tle-ffg-6h",
    "hrrr-tle-qpf1h-1in", "hrrr-tle-qpf1h-2in", "hrrr-tle-qpf1h-3in",
    "hrrr-tle-persist-1in", "hrrr-tle-persist-3h-2in", "hrrr-tle-persist-3h-3in",
    "hrrr-tle-evol-00-03", "hrrr-tle-evol-03-06",
    "hrrr-tle-evol-06-09", "hrrr-tle-evol-09-12",
    "hrrr-tle-prior3", "hrrr-tle-latest3", "hrrr-tle-run-change",
]
for layer_id in hrrr_tle_ids:
    if app.count(f"id: '{layer_id}'") != 1:
        errors.append(f"Expected exactly one HRRR-TLE layer registry entry: {layer_id}")

required_hrrr_tle_generator_fragments = [
    "TLE_MEMBER_COUNT = 6",
    "TLE_COMMON_HOURS = 12",
    "MIN_TLE_MEMBERS = 6",
    "NEIGHBORHOOD_KM = 40.0",
    "aligned_member_fxx",
    "candidate_is_complete",
    "find_latest_tle_cycle",
    "hrrr_tle_dashboard_v3_3",
    "hrrr_tle_dashboard_manifest_v1",
    "hrrr_tle_ffg_consensus.png",
    "hrrr_tle_run_change.png",
    "Member frequency / consensus; NOT calibrated probability.",
]
for fragment in required_hrrr_tle_generator_fragments:
    if fragment not in hrrr_tle_generator:
        errors.append(f"Missing HRRR-TLE V3.3 generator contract: {fragment}")

required_hrrr_tle_workflow_fragments = [
    "Update HRRR-TLE Flash Flood Guidance",
    "workflow_dispatch:",
    "schedule:",
    "cron: '55 * * * *'",
    "python fetch_hrrr_tle.py --output-dir static",
    "static/hrrr_tle_*",
]
for fragment in required_hrrr_tle_workflow_fragments:
    if fragment not in hrrr_tle_workflow:
        errors.append(f"Missing HRRR-TLE workflow contract: {fragment}")

required_ufvs_utility_fragments = [
    "UFVS Geographic Domains",
    "ufvs-geographic-domains-toggle",
    "UFVS_GEOGRAPHIC_DOMAINS",
    "UFVS_DOMAINS_SESSION_KEY",
    "ufvsGeographicDomainsLayer",
    "setUFVSGeographicDomainsVisible",
    "map.createPane('ufvsDomains')",
    "label: 'West Coast', west: -125.0, east: -117.0, south: 32.0, north: 49.0",
    "label: 'Southwest', west: -117.0, east: -104.0, south: 28.0, north: 42.0",
    "label: 'Interior Mountain West', west: -117.0, east: -104.0, south: 42.0, north: 49.0",
    "label: 'Northern Plains', west: -104.0, east: -85.0, south: 38.0, north: 49.0",
    "label: 'Southern Plains', west: -104.0, east: -90.0, south: 24.0, north: 38.0",
    "label: 'Southeast', west: -90.0, east: -75.0, south: 24.0, north: 38.0",
    "label: 'Northeast', west: -85.0, east: -66.0, south: 38.0, north: 49.0",
]
for fragment in required_ufvs_utility_fragments:
    if fragment not in app:
        errors.append(f"Missing UFVS Geographic Domains utility fragment: {fragment}")

# The display overlay and GLM regional trend calculations must use the exact
# same authoritative fixed WPC UFVS bounds.
expected_ufvs_domains = [
    ("west-coast", "West Coast", -125.0, -117.0, 32.0, 49.0),
    ("southwest", "Southwest", -117.0, -104.0, 28.0, 42.0),
    ("interior-mountain-west", "Interior Mountain West", -117.0, -104.0, 42.0, 49.0),
    ("northern-plains", "Northern Plains", -104.0, -85.0, 38.0, 49.0),
    ("southern-plains", "Southern Plains", -104.0, -90.0, 24.0, 38.0),
    ("southeast", "Southeast", -90.0, -75.0, 24.0, 38.0),
    ("northeast", "Northeast", -85.0, -66.0, 38.0, 49.0),
]
for domain_id, label, west, east, south, north in expected_ufvs_domains:
    app_fragment = (
        f"id: '{domain_id}', label: '{label}', west: {west:.1f}, "
        f"east: {east:.1f}, south: {south:.1f}, north: {north:.1f}"
    )
    if app_fragment not in app:
        errors.append(
            f"UFVS overlay bounds do not match the WPC definition for {label}."
        )

    generator_pattern = re.compile(
        rf'"id":\s*"{re.escape(domain_id)}".*?'
        rf'"label":\s*"{re.escape(label)}".*?'
        rf'"west":\s*{re.escape(f"{west:.1f}")}.*?'
        rf'"east":\s*{re.escape(f"{east:.1f}")}.*?'
        rf'"south":\s*{re.escape(f"{south:.1f}")}.*?'
        rf'"north":\s*{re.escape(f"{north:.1f}")}',
        re.DOTALL,
    )
    if not generator_pattern.search(glm_generator):
        errors.append(
            f"GLM UFVS trend-calculation bounds do not match the WPC definition for {label}."
        )

if "setInterval(() => fetchGLMMetadata(), 10 * 60 * 1000)" in app:
    errors.append("Legacy blind 10-minute GLM refresh interval is still active.")
if "Trend Framework" in app:
    errors.append("UFVS utility label still contains the rejected words 'Trend Framework'.")

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
    "Authoritative fixed WPC UFVS seven-domain rectangular framework",
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


required_glm_workflow_fragments = [
    "glm_convective_trend_15min_metadata.json",
    "GLM trend-map metadata contract failed",
    "embedded_png_base64",
]
for fragment in required_glm_workflow_fragments:
    if fragment not in glm_workflow:
        errors.append(f"Missing GOES GLM workflow publication fragment: {fragment}")

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

if len(ids) != EXPECTED_LAYER_COUNT:
    errors.append(
        f"Expected {EXPECTED_LAYER_COUNT} registered layers, found {len(ids)}."
    )

if ids.count(LIGHTNINGCAST_LAYER_ID) != 1:
    errors.append(
        f"Expected exactly one registered LightningCast layer id {LIGHTNINGCAST_LAYER_ID!r}, "
        f"found {ids.count(LIGHTNINGCAST_LAYER_ID)}."
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
    "the GLM trend diagnostic/trend map, automatic GLM manifest refresh, "
    "LightningCast v1E integration/manifest refresh, and UFVS Geographic Domains utility preserved."
)
