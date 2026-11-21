WPC Real-Time Hydrometeorological Dashboard
Phase WFIGS-3 — Dashboard Integration
==========================================

Purpose
-------
This package integrates the already validated Phase WFIGS-2 operational data
products into the production dashboard frontend. It is intentionally additive:
no WFIGS ArcGIS service is queried directly by the browser, no existing
meteorological/hydrologic layer is removed, and the MRMS RALA v2.10 viewer
behavior is preserved.

Files changed
-------------
  app.js
  index.html
  tools/validate_dashboard.py

No changes are made to:
  style.css
  fetch_wfigs_operational.py
  WFIGS update workflows
  wfigs-data contents
  MRMS/RAP/FFG/FLASH/soil-moisture backend logic

New dashboard section
---------------------
Wildfire / Burn Scar Context

Layers:
  1. NIFC/WFIGS Current Wildfire Perimeters
  2. NIFC/WFIGS 2026 Wildfire Perimeters

Both layers are opt-in at startup.

Science / interpretation
------------------------
WFIGS polygons represent mapped wildfire perimeter extent. They do NOT
represent soil-burn severity or a direct estimate of post-fire hydrologic
response. BAER/MTBS severity products remain separate future context layers.
The mapped-perimeter acreage shown to the forecaster comes from the normalized
Phase-2 attributes, not from recomputing area from the display-generalized
browser geometry.

Current layer behavior
----------------------
Source consumed by the browser:
  https://raw.githubusercontent.com/andreworrison-cloud/wpc-hydro-dashboard/
  wfigs-data/static/wfigs/current/manifest.json

The manifest points to the validated Current GeoJSON snapshot. The browser:
  - loads Current only after the layer is enabled;
  - refresh-checks the manifest every 2 minutes while active;
  - swaps to a new GeoJSON layer only after the replacement fetch validates;
  - keeps the last successful snapshot if a refresh fails;
  - shows a freshness caution if the source edit time is >45 minutes old;
  - retains active_fire_ids for Current-vs-YTD de-duplication.

YTD / 2026 archive behavior
---------------------------
The browser loads the YTD manifest only after the layer is enabled. It never
loads the complete national archive at dashboard startup.

The Phase-2 manifest contains actual full-geometry bounding boxes for every
regional chunk. Phase WFIGS-3 loads only chunks whose bbox intersects the
current Leaflet viewport.

Minimum YTD loading zoom: 6.
Session chunk-cache limit: 36.
YTD manifest refresh check while active: 15 minutes.

Cartographic display-density thresholds:
  zoom 6 : mapped perimeter >= 500 acres
  zoom 7 : mapped perimeter >= 100 acres
  zoom 8 : mapped perimeter >= 20 acres
  zoom 9+: all available perimeter sizes

These are DISPLAY thresholds only. They are not hydrologic thresholds and do
not remove smaller fires from the underlying archive. Small burns can be highly
important in steep terrain, confined drainage basins, burn-sensitive canyons,
or developed watersheds, so the complete archive remains available as the
forecaster zooms in.

Current / YTD de-duplication
----------------------------
When both layers are active, a YTD feature whose fire_id is listed in the
Current manifest's active_fire_ids is suppressed. Turning Current off restores
the corresponding YTD representation.

Forecaster interaction
----------------------
Hover (desktop): sticky tooltip with, when available:
  - fire / incident name
  - mapped perimeter acreage
  - county and state
  - percent contained
  - discovery date

Click/tap popup:
  - mapped perimeter acreage
  - reported incident size
  - percent contained
  - location
  - discovery time
  - perimeter observation time
  - fire cause / cause detail
  - mapping method
  - source dataset
  - explicit note that perimeter extent is not burn severity

Missing metadata are omitted rather than rendered as null values.

Styling
-------
Current: solid orange-red outline with subtle red fill.
2026 archive: dashed amber outline with very light amber fill.
Hover temporarily brightens/thickens the selected perimeter.

WFIGS-specific tooltip/popup CSS is injected from app.js. style.css is not
modified by this phase.

Legend / time-status dock
-------------------------
The existing legend dock is preserved. When either WFIGS layer is active it
adds a compact Wildfire / Burn Scar Context legend. Separate Current and YTD
status boxes report source/snapshot time and useful loading information.

For YTD the status box also reports the current cartographic threshold, number
of viewport chunks loaded, and number of displayed perimeters.

Data delivery architecture
--------------------------
The browser reads only the validated rolling branch:
  wfigs-data

It must NOT query the authoritative NIFC ArcGIS FeatureServer directly. The
Phase-2 backend remains responsible for source retrieval, de-duplication,
geometry repair, display generalization, normalization, atomic publication,
and data QA.

Validation performed before packaging
-------------------------------------
  - node --check app.js : PASS
  - python -m py_compile tools/validate_dashboard.py : PASS
  - WFIGS JavaScript unit/stub harness : PASS
  - registry IDs: 139 total / 139 unique : PASS
  - required section order: PASS
  - Current/YTD manifest assumptions checked against the validated Phase-2
    manifests supplied from the successful operational runs.

A complete local run of tools/validate_dashboard.py is not possible from this
frontend package alone because the validator intentionally reads additional
production-repository files (style.css, GLM/LightningCast/HRRR-TLE/MRMS
backend files and workflows). Run the normal GitHub "Validate Dashboard
Interface" workflow after these files are committed to main.

Deployment / first operational test
-----------------------------------
1. Replace on main:
     app.js
     index.html
     tools/validate_dashboard.py
2. Leave style.css and all backend/data-branch files unchanged.
3. Commit the three files together.
4. Run the existing "Validate Dashboard Interface" GitHub workflow.
5. Open the dashboard with a hard refresh.
6. Test "NIFC/WFIGS Current Wildfire Perimeters" first:
     - polygons render;
     - hover tooltip follows the selected fire;
     - click popup contains the expected metadata;
     - Current status box shows source last-edit time.
7. Then test "NIFC/WFIGS 2026 Wildfire Perimeters":
     - below zoom 6, archive remains unloaded and asks the user to zoom in;
     - at zoom 6+, only viewport-intersecting chunks load;
     - progressively smaller fires appear from zoom 6 through zoom 9;
     - hover/click behavior works;
     - when Current is also enabled, duplicate Current identities are not drawn
       by YTD.
8. Test at least one western CONUS area with many burns and one OCONUS area
   (e.g., Alaska or Hawaii) before scheduling automated WFIGS updates.

Scheduling
----------
Do NOT schedule the WFIGS update workflows as part of this frontend package.
After visual/operational approval, the intended cadence remains approximately:
  Current: every 5 minutes
  YTD: every 6 hours
with Current staggered away from the MRMS RALA cron schedule.
