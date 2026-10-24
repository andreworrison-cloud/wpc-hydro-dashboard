WPC Hydro Dashboard — WFIGS Phase 2.2 Mixed-Dimension Geometry Repair
=====================================================================

Purpose
-------
This surgical patch addresses the YTD build failure:

  shapely.errors.GEOSException:
  IllegalArgumentException: Overlay input is mixed-dimension

The failure occurred inside Shapely/GEOS make_valid() while processing legacy
Year-To-Date WFIGS perimeter geometry. Current WFIGS had already passed, but the
larger YTD archive exposed a topology pathology not present in the Current set.

Files to replace on main
------------------------
1. /fetch_wfigs_operational.py
2. /tools/validate_wfigs_phase2.py

No workflow, frontend, cron, or wfigs-data file changes are required.

What changed
------------
* Processor version advances to wfigs_phase2_operational_v1_2.
* Geometry repair is now exception-safe: one malformed fire perimeter cannot
  terminate the national YTD build merely because one GEOS repair strategy
  throws an exception.
* Repair cascade:
    1. valid polygon passthrough
    2. Shapely >=2.1 make_valid(method="structure") when available
    3. buffer(0) fallback
    4. default make_valid linework fallback
    5. component-wise Polygon/MultiPolygon repair
* GeometryCollection outputs are stripped to polygonal members; collapsed line
  or point remnants are never published as wildfire perimeter geometry.
* The exact post-rounding browser geometry is still revalidated.
* The generated manifest now records repair_method_counts for QA/monitoring.
* No acreage threshold is introduced; small wildfire perimeters remain retained.
* WFIGS polygons remain cartographic mapped extent, not burn-severity analysis.

Why this is safe operationally
------------------------------
The failed YTD run stopped during the build step, before the workflow's validate,
rsync, commit, or push steps. Therefore the existing wfigs-data Current product
was not replaced and no partial YTD tree was published.

Offline validation performed
----------------------------
* Python compilation: PASS
* Phase-2 static code/workflow contract validation: PASS
* Phase-1 complete Current raw geometry: 192/192 valid after processing
* Phase-1 representative YTD geometry sample: 257/257 valid after processing
* Phase-2.1 published Current product: 193/193 valid after processing
* Forced synthetic GEOS mixed-dimension make_valid exception: safely repaired
  through the independent buffer(0) fallback path

Next run
--------
After replacing the two files, run:

  Actions -> Update WFIGS Year-To-Date Wildfire Perimeters

Leave force_rebuild=false. The prior YTD run did not publish a manifest, so a
new YTD build will proceed normally.
