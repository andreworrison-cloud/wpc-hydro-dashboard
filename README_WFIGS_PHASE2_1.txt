WPC Hydro Dashboard — WFIGS Phase 2.1 Geometry Validity Patch
==============================================================

Why this patch exists
---------------------
The first operational Current build succeeded and published 193 unique wildfire
features. Independent QA of the exact browser GeoJSON found two MultiPolygon
features (Little Giant and Big Grass) whose tiny component rings became invalid
only after the final 6-decimal coordinate rounding step.

The source polygons and main fire perimeters were not missing. This is a
serialization/display-geometry edge case: coordinate rounding collapsed a tiny
ring to fewer than three unique vertices.

What changes
------------
Replace only:
  /fetch_wfigs_operational.py
  /tools/validate_wfigs_phase2.py

No workflow, dashboard, cron, or wfigs-data files are manually edited.

The fetcher now validates the *post-rounding* geometry and repairs it with
Shapely make_valid before serialization. It never re-rounds after repair.
The validator now checks every serialized Current and YTD polygon for validity,
not only schema/count/checksum contracts.

Processor version
-----------------
wfigs_phase2_operational_v1_1

Because the processor version changed, the next manual Current run rebuilds even
if the WFIGS source edit timestamp has not changed.

Recommended sequence
--------------------
1. Commit the two replacement files on main.
2. Run "Update WFIGS Current Wildfire Perimeters" with force_rebuild=false.
3. Share the new current manifest.json and perimeters.geojson for verification.
4. Only after Current passes post-serialization geometry QA, run the first YTD build.
