WFIGS Phase 4.3 — CONUS Archive Visibility
==========================================

Purpose
-------
Fix the operational ambiguity created when the WFIGS YTD and historical archive
layers showed no fire perimeters at the dashboard's default zoomed-out CONUS
view. Current WFIGS remains unchanged.

Design
------
The archive now uses a two-tier display architecture:

1. Zoomed-out national overview (zoom 4–5)
   - Z4: show mapped perimeters >= 10,000 acres
   - Z5 (dashboard default CONUS view): show mapped perimeters >= 5,000 acres
   - Data come from a new lightweight overview.geojson product.

2. Existing viewport chunk archive (zoom 6+)
   - Z6: >= 500 acres
   - Z7: >= 100 acres
   - Z8: >= 20 acres
   - Z9+: all available mapped perimeter sizes

The acreage thresholds are cartographic display thresholds only. No source fire
record is removed from the full YTD or historical archive. The national overview
exists solely to give forecasters immediate visual evidence of meaningful fire
footprints without forcing the browser to download an entire annual archive.

Why a separate overview product?
--------------------------------
Simply lowering the old minimum zoom from 6 to 5 would cause a CONUS viewport to
request most regional chunks. With several historical years selected, that could
approach the full ~81 MB five-year archive. Phase 4.3 instead publishes a compact
large-fire overview for YTD and for each historical year, then switches to the
existing viewport/chunk architecture when the forecaster zooms in.

Files to replace on main
------------------------
app.js
index.html
fetch_wfigs_operational.py
fetch_wfigs_history.py
tools/validate_dashboard.py
tools/validate_wfigs_phase2.py
tools/validate_wfigs_history.py

No GitHub workflow YAML changes are required. Existing WFIGS workflows publish
entire build directories with rsync, so the new overview.geojson files are
included automatically.

Required one-time data refresh after installing this patch
----------------------------------------------------------
1. Run "Update WFIGS Year-To-Date Wildfire Perimeters" once.
   - force_rebuild can remain FALSE.
   - Processor v1.3 differs from the existing v1.2 manifest, so YTD will rebuild
     and publish static/wfigs/ytd/overview.geojson.

2. Run "Update WFIGS Rolling 5-Year Wildfire History" once.
   - force_rebuild can remain FALSE.
   - History processor v1.1 differs from the existing v1.0 annual manifests, so
     the five years will rebuild and each will publish YYYY/overview.geojson.

3. Run the normal dashboard validation Action and hard-refresh the browser.

Expected operational behavior
-----------------------------
At the dashboard's default CONUS zoom (5), turning on 2026 YTD or any historical
year should immediately show mapped fire perimeters >= 5,000 acres in that
layer's established bright color. Multiple historical years may still be shown
simultaneously. As the map is zoomed in, the frontend switches automatically to
regional chunks and progressively reveals smaller fires.

Current WFIGS remains a full compact national snapshot and is unaffected.

Validation completed before packaging
-------------------------------------
- node --check app.js: PASS
- Python compilation of all modified Python files: PASS
- Synthetic YTD overview build + internal manifest validation: PASS
- Synthetic rolling five-year history build + history validator: PASS
- Dashboard registry: 140/140 unique layer IDs: PASS
- No direct NIFC/WFIGS ArcGIS request in frontend: PASS
- New national-overview/static contract checks: PASS

Scientific guardrail
--------------------
WFIGS polygons depict mapped wildfire extent. They do not indicate soil-burn
severity or hydrologic-response severity. BAER/MTBS remain separate future
severity/context datasets.
