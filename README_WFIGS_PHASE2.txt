WPC Real-Time Hydrometeorological Dashboard
Phase WFIGS-2 — Operational Backend / Data Delivery
===================================================

Purpose
-------
Phase WFIGS-2 turns the successful Phase-1 NIFC/WFIGS source discovery into
operational rolling data products. This package remains BACKEND ONLY. It does
not modify app.js, index.html, style.css, the dashboard sidebar, or any existing
meteorological/hydrological layer.

Authoritative sources
---------------------
Current:
  WFIGS Current Interagency Fire Perimeters
  https://services3.arcgis.com/T4QMspbfLg3qTGWY/ArcGIS/rest/services/
  WFIGS_Interagency_Perimeters_Current/FeatureServer/0

Year-To-Date:
  WFIGS Wildland Fire Perimeters Year To Date
  https://services3.arcgis.com/T4QMspbfLg3qTGWY/ArcGIS/rest/services/
  WFIGS_Interagency_Perimeters_YearToDate/FeatureServer/0

Candidate dashboard records are wildfire (WF) only. Prescribed-fire (RX)
records are intentionally not mixed into the wildfire/burn-scar context layer.

Files to add to the MAIN branch
-------------------------------
1. /fetch_wfigs_operational.py
2. /.github/workflows/update_wfigs_current.yml
3. /.github/workflows/update_wfigs_ytd.yml
4. /tools/validate_wfigs_phase2.py
5. /README_WFIGS_PHASE2.txt

Suggested commit message
------------------------
Add WFIGS operational backend and rolling data delivery

Rolling data branch
-------------------
The workflows create/use a dedicated branch named:

  wfigs-data

Generated files are written only to that branch under:

  static/wfigs/current/
      manifest.json
      perimeters.geojson

  static/wfigs/ytd/
      manifest.json
      chunks/*.geojson

This prevents high-frequency WFIGS updates from accumulating on the dashboard
code branch. Both workflows share one non-cancelling concurrency group so they
cannot publish to wfigs-data simultaneously.

Current collection design
-------------------------
* All WF records are retained; there is NO acreage threshold.
* Duplicate incident identities are collapsed to one canonical latest record.
* Geometry is display-generalized at 0.00008 degree (~9 m or finer in the
  east-west direction at higher latitude) with topology-preserving cleanup.
* The source GIS acreage attribute is retained and is the primary mapped-area
  value. The auto-calculated acreage is a fallback only.
* The manifest includes active_fire_ids so Phase WFIGS-3 can suppress duplicate
  YTD rendering when a fire is also in Current.
* Current is designed for an external 5-minute check after validation.

Year-To-Date collection design
------------------------------
* All WF records are retained after identity de-duplication.
* No small-fire removal is performed. Small burns may be hydrologically
  important in steep, burned, urban, or otherwise sensitive watersheds.
* Geometry uses the same display-only generalization as Current.
* Each fire is assigned to exactly one state + 5-degree geographic chunk using
  a representative point.
* Every chunk manifest entry stores the ACTUAL union bounding box of all full
  fire polygons in that chunk. Phase WFIGS-3 can therefore request only chunks
  whose true bounds intersect the current map viewport without missing a large
  fire simply because its representative point lies outside the viewport.
* YTD is designed for an external ~6-hour update after validation. It does not
  need the same cadence as actively changing Current perimeters.

Acreage handling
----------------
Phase-1 showed that poly_GISAcres and poly_Acres_AutoCalc usually agree, but
there are occasional large source discrepancies. Therefore Phase-2 uses:

  mapped_acres = poly_GISAcres
  fallback      = poly_Acres_AutoCalc only when GIS acreage is unavailable

Both values and attr_IncidentSize are preserved independently. Phase WFIGS-3
can show mapped perimeter acreage and reported incident size as distinct values.

Scientific guardrail
--------------------
A WFIGS perimeter is mapped wildfire EXTENT. It is NOT a soil-burn-severity
field and is not by itself a flash-flood susceptibility forecast. BAER and MTBS
remain separate future layers. The longer-term post-fire hydrologic framework
will combine perimeter/burn severity with terrain, antecedent soil state,
precipitation, FFG, MRMS FLASH, and other hydro-meteorological information.

Failure / stale-data behavior
-----------------------------
The Python builder writes to a temporary build directory first. Existing
wfigs-data products are not touched unless the complete new build succeeds and
passes validation. If NIFC/WFIGS is unavailable or a schema/geometry check fails,
the workflow fails and the previously published snapshot remains intact.

The builder also reads the existing manifest. When the authoritative WFIGS
source edit timestamp and processor version are unchanged, it exits cleanly
without creating another data-branch commit. A workflow_dispatch input named
force_rebuild is available for intentional rebuilds after code changes/testing.

GitHub scheduling
-----------------
Both workflows are workflow_dispatch ONLY. No native GitHub schedule is added.
After the first Current and YTD builds are verified, cron-job.org can trigger:

  Current: every 5 minutes, offset from MRMS
  YTD:     every 6 hours

Do not configure those recurring calls until both manual Phase-2 tests pass.

Recommended first test
----------------------
1. Upload/commit the five Phase-2 files to main.
2. Run:
     Update WFIGS Current Wildfire Perimeters
   with force_rebuild = false.
3. Confirm the workflow creates wfigs-data and publishes:
     static/wfigs/current/manifest.json
     static/wfigs/current/perimeters.geojson
4. Share the Current workflow log and manifest.
5. Then run:
     Update WFIGS Year-To-Date Wildfire Perimeters
6. Confirm YTD publishes a manifest and chunk directory.
7. Share the YTD workflow log and manifest.
8. Only after both products are verified should we proceed to Phase WFIGS-3
   (dashboard integration, styling, hover tooltip, click popup, freshness UI,
   viewport lazy loading, and Current-vs-YTD visual de-duplication).

Expected future Phase WFIGS-3 hover fields
------------------------------------------
* Fire name
* Mapped perimeter acreage
* Reported incident acreage (when available)
* Percent contained (when available)
* State / county
* Discovery time
* Perimeter observation time (when available)
* Fire cause / map method in the expanded click popup

Version
-------
Processor contract: wfigs_phase2_operational_v1
