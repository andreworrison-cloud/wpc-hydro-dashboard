WPC Hydrometeorological Dashboard — WFIGS Phase 4
Rolling Five-Year Historical Wildfire Perimeters + UI Clarification
=================================================================

PURPOSE
-------
Phase WFIGS-4 extends the validated Current + current-year YTD WFIGS system with
one user-selectable historical layer covering the five completed calendar years
immediately before the current year.

For 2026 the historical selector is:
  2025, 2024, 2023, 2022, 2021

The current year remains separate in the YTD layer. On a future annual rollover,
the history builder derives the new five-year window automatically.

SCIENTIFIC / OPERATIONAL DEFINITIONS
------------------------------------
Current WFIGS
  Current/actively maintained wildfire perimeter footprints. The authoritative
  WFIGS Current service uses fall-off rules, so incidents can disappear from
  Current as they close, age, or stop being maintained.

Current-year YTD WFIGS
  All mapped wildfire footprints for the current calendar year in the WFIGS YTD
  service. No Current-service fall-off rules are applied to that YTD collection.

Historical WFIGS
  One completed calendar year selected by the user. The historical year is
  defined by attr_FireDiscoveryDateTime in UTC and comes from the NIFC/WFIGS
  Interagency Fire Perimeters full-history service.

WFIGS perimeter means mapped fire extent. It does NOT represent soil-burn
severity or hydrologic-response severity. BAER/MTBS remain scientifically
separate future layers.

WHY THE ROLLING WINDOW STARTS WITH MODERN WFIGS
-----------------------------------------------
The NIFC metadata for the full-history service documents records before 2021 as
incomplete and still being incorporated. Phase 4 therefore intentionally stays
inside the modern WFIGS era rather than silently mixing older incomplete history
into an operational five-year product.

HISTORICAL QUERY POLICY
-----------------------
The NIFC metadata warns against repeatedly using relative date filters such as
CURRENT_TIMESTAMP against the full-history service. Phase 4 does not do that.
Each historical year uses an absolute fixed UTC TIMESTAMP range, for example:

  attr_IncidentTypeCategory = 'WF' AND
  attr_FireDiscoveryDateTime >= TIMESTAMP '2025-01-01 00:00:00' AND
  attr_FireDiscoveryDateTime <  TIMESTAMP '2026-01-01 00:00:00'

The workflow is manual-only for the initial validation stage.

FILES IN THIS PACKAGE
---------------------
Replace / add these paths on main:

  app.js
  index.html
  fetch_wfigs_history.py
  tools/validate_dashboard.py
  tools/validate_wfigs_history.py
  .github/workflows/update_wfigs_history.yml

The existing Phase-2.2-or-newer fetch_wfigs_operational.py MUST remain in the
repository. The history builder imports its proven geometry normalization,
mixed-dimension repair, post-rounding repair, acreage, and chunking routines.
The history script fails early if that geometry core is older than v1.2.

NO existing Current/YTD workflow or WFIGS data file is replaced by this package.

BACKEND OUTPUT
--------------
The new workflow publishes to the existing wfigs-data branch:

  static/wfigs/history/manifest.json
  static/wfigs/history/2025/manifest.json
  static/wfigs/history/2025/chunks/*.geojson
  static/wfigs/history/2024/...
  static/wfigs/history/2023/...
  static/wfigs/history/2022/...
  static/wfigs/history/2021/...

Each annual archive uses the same state + 5-degree representative-point chunking
and actual full-geometry chunk bounding boxes proven by the 2026 YTD build.

YEAR-SPECIFIC CHANGE DETECTION
------------------------------
The full-history service itself changes frequently because it also contains the
current year. Rebuilding five historical years every time the service edit time
changes would be wasteful.

For each fixed year, Phase 4 therefore computes a year-specific signature from:
  * the sorted OBJECTID inventory;
  * maximum poly_DateCurrent;
  * maximum attr_ModifiedOnDateTime_dt.

If a historical year's signature is unchanged and its existing delivery is
complete, that year is retained without downloading its geometry again.

FRONTEND CHANGES
----------------
The Wildfire / Burn Scar Context section becomes three opt-in layers:

  NIFC/WFIGS Current Wildfire Perimeters
  NIFC/WFIGS <current year> YTD Wildfire Perimeters
  NIFC/WFIGS Historical Wildfire Perimeters

Short descriptions beneath Current and YTD explain their difference directly in
the sidebar. The YTD year is no longer hardcoded to 2026; it follows the current
UTC year automatically.

The Historical layer includes a single-year dropdown. It exposes only the five
years published by the validated rolling history index. Only one historical year
is drawn at once.

Historical geometry is viewport-lazy-loaded exactly like YTD. The existing
archive display-density rules are retained:
  zoom < 6 : no archive geometry loaded
  zoom 6   : >= 500 mapped acres displayed
  zoom 7   : >= 100 mapped acres displayed
  zoom 8   : >= 20 mapped acres displayed
  zoom 9+  : all available mapped perimeter sizes displayed

These are CARTOGRAPHIC display thresholds only. Small wildfire records remain in
the annual data products and are not declared hydrologically irrelevant.

Current wildfire duplicates are suppressed from both YTD and historical display
when Current is simultaneously active, using the Current active_fire_ids list.

FIRST LIVE TEST
---------------
1. Commit the six Phase-4 files to main.
2. Run: Actions -> Update WFIGS Rolling 5-Year Wildfire History.
3. Leave force_rebuild = false.
4. The first run should build all five years because no history delivery exists.
5. Send Sol the workflow log and the artifact named wfigs-history-manifests.
6. If the history backend validates and publishes, run the normal dashboard
   validation workflow, hard-refresh the dashboard, activate Historical WFIGS,
   and test several years / viewports / hover and click interactions.

The first historical build may take materially longer than a normal Current/YTD
update because it is establishing five complete annual archives. Subsequent runs
should usually skip unchanged years.

SCHEDULING AFTER VISUAL APPROVAL
--------------------------------
Do not enable a recurring historical schedule until the first live five-year
build and dashboard display have been inspected.

After approval, a low-frequency cadence is appropriate for history (for example,
weekly), while Current and current-year YTD remain on their separate operational
cadences. The history workflow already uses fixed date ranges and year-specific
signatures so a periodic check does not imply repeatedly rebuilding all geometry.

LOCAL / STATIC VALIDATION PERFORMED BEFORE PACKAGING
----------------------------------------------------
* app.js: node --check PASS
* fetch_wfigs_history.py: Python compile PASS
* tools/validate_wfigs_history.py: Python compile PASS
* tools/validate_dashboard.py: Python compile PASS
* update_wfigs_history.yml: YAML parse PASS
* Phase-4 frontend WFIGS unit/stub harness PASS
* Offline five-year synthetic history build + full serialized-geometry validator PASS
* Registered dashboard IDs: 140 total / 140 unique
* Frontend direct NIFC ArcGIS URL: absent

A live NIFC historical query cannot be executed from the packaging container due
network/DNS restrictions. The first GitHub Actions run is therefore the live
integration test, just as Phase WFIGS-1/2 were validated against the authoritative
service through GitHub Actions.
