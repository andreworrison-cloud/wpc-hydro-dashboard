WPC Real-Time Hydrometeorological Dashboard
Phase WFIGS-1 — NIFC/WFIGS Source Discovery
================================================

PURPOSE
-------
This is a controlled backend-only diagnostic for the next dashboard roadmap item:
NIFC/WFIGS wildfire perimeters and future burn-scar context.

It DOES NOT modify app.js, index.html, style.css, dashboard layers, cron-job.org,
or any operational static files. It does not commit generated WFIGS data.

AUTHORITATIVE SOURCES TESTED
----------------------------
1. WFIGS Current Interagency Fire Perimeters
   https://services3.arcgis.com/T4QMspbfLg3qTGWY/ArcGIS/rest/services/
   WFIGS_Interagency_Perimeters_Current/FeatureServer/0

2. WFIGS Wildland Fire Perimeters Year To Date
   https://services3.arcgis.com/T4QMspbfLg3qTGWY/ArcGIS/rest/services/
   WFIGS_Interagency_Perimeters_YearToDate/FeatureServer/0

The dashboard candidate is intentionally filtered to Incident Type Category WF
(Wildfire). RX (Prescribed Fire) is counted for source awareness but is NOT mixed
into the candidate wildfire/burn-scar layer in Phase 1.

WHY CURRENT + YEAR-TO-DATE
--------------------------
Current WFIGS is the near-real-time active perimeter source, but it applies fall-off
rules and removes incidents after containment/control/out or after source staleness.
That is appropriate for fire operations but not sufficient for hydrologic operations:
a burned watershed can remain highly susceptible to flash flooding and debris flows
long after suppression operations end.

Year-To-Date has no Current-service fall-off rules and is therefore evaluated as the
bridge for preserving recently burned footprints until BAER/MTBS burn-severity context
is added later.

WHAT THE DIAGNOSTIC CHECKS
--------------------------
* Live schema and geometry type for Current and Year-To-Date services.
* Required fields for a future hover/popup interaction:
    - incident name
    - GIS acreage
    - perimeter observation time
    - reported incident acreage
    - percent contained
    - state / county
    - fire discovery time
    - incident type
* WF wildfire count and RX prescribed-fire count.
* Exact wildfire OBJECTID inventory using returnIdsOnly.
* Lean wildfire attributes for all Year-To-Date WF records (no geometry).
* Acreage distribution and null-field statistics.
* Duplicate incident-identity diagnostics.
* Current-vs-YTD incident identity overlap.
* Full Current wildfire geometry when safely sized (<= 2500 features).
* Representative YTD geometry sample emphasizing:
    - newest mapped perimeters
    - largest perimeters
    - multiple acreage-size bands
* Polygon/MultiPolygon coordinate counts as a first dashboard-performance proxy.

OUTPUT ARTIFACT
---------------
The GitHub Action uploads one artifact named:
    wfigs-phase1-diagnostic

Expected files:
    wfigs_phase1_report.json
    wfigs_phase1_summary.txt
    wfigs_current_wildfires.geojson
    wfigs_ytd_geometry_sample.geojson
    wfigs_ytd_wildfire_attributes.json

The GeoJSON properties are deliberately normalized toward the future dashboard UI.
The candidate hover fields include incident_name, gis_acres, percent_contained,
state, county, discovery_time_utc, and perimeter_time_utc. A later click popup can
add reported_acres, fire cause, map method, source dataset, and additional dates.

IMPORTANT SCIENCE / OPERATIONS NOTE
-----------------------------------
A WFIGS perimeter is a mapped wildfire extent. It is NOT a soil-burn-severity field.
Do not infer that the entire polygon has the same hydrologic response. Future BAER
and MTBS integration is intended to add actual burn-severity context.

FILES TO ADD
------------
1. /diagnose_wfigs.py
2. /.github/workflows/diagnose_wfigs.yml
3. /tools/validate_wfigs_phase1.py
4. /README_WFIGS_PHASE1.txt

HOW TO RUN
----------
1. Commit/push the four files above.
2. Open GitHub -> Actions.
3. Select "Diagnose NIFC WFIGS Perimeter Feeds".
4. Click "Run workflow".
5. When it completes, download the "wfigs-phase1-diagnostic" artifact.
6. Share wfigs_phase1_summary.txt and wfigs_phase1_report.json back in this chat.
   If practical, also share the two GeoJSON files so we can inspect payload and
   geometry behavior before designing Phase WFIGS-2.

NEXT DECISION GATE
------------------
Do NOT add the dashboard layer yet.

After the diagnostic run we will decide, from actual observed feature counts and
geometry complexity, whether the smart operational delivery is:
  A. compact rolling national GeoJSON snapshots,
  B. geographically partitioned GeoJSON,
  C. viewport-driven retrieval / caching,
  D. or another vector delivery method.

That decision will then drive Phase WFIGS-2 (operational updater) and Phase WFIGS-3
(dashboard display, hover tooltip, click popup, legend, and freshness handling).
