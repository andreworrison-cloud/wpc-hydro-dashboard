CAM Render Clarity Phase 1B
===========================

Purpose
-------
Reduce residual stair-stepping / graininess along CAM probability contour edges at
regional Leaflet zoom levels without changing the meteorological probability fields.

Replace only
------------
- fetch_cam.py
- fetch_cam_ero.py

Display-only changes
--------------------
1. Main CAM PNG render density increased from 450 DPI (4500x2700) to 600 DPI
   (6000x3600) while retaining the exact 10x6-inch figure footprint.
2. Matplotlib filled-contour edge antialiasing is explicitly enabled with
   antialiased=True.
3. Rendering metadata revision advanced to *-display-density-v1b and records the
   6000x3600 target plus the display-only antialiasing flag.

Scientific contracts deliberately unchanged
--------------------------------------------
- HREF data/grid: unchanged.
- REFS data/grid decoding: unchanged.
- Existing REFS -> HREF interpolation: unchanged and remains linear.
- SuperEnsemble calculation: unchanged.
- FFG/QPF probability values: unchanged.
- Probability bins: 10, 30, 50, 70, 90, 100 percent.
- No Gaussian smoothing added.
- No bicubic/cubic display resampling added.
- Leaflet bounds/georegistration logic: unchanged.

Operational test
----------------
After committing the two Python files, manually run:
- Update CAM SuperEnsemble
- Update Day 1 ERO CAMs

Recommended A/B visual checks
-----------------------------
- CAM Nowcast SuperEnsemble Max Prob > 0.5 in/hr over NM/AZ.
- CAM Nowcast SuperEnsemble Max FFG Exceedance over NM/AZ or FL.
- Day 1 ERO SuperEnsemble Max Prob > 1.0 in/hr over FL.
- Day 1 ERO SuperEnsemble Max FFG Exceedance.

Watch workflow runtime and generated PNG/repository size. Phase 1B intentionally
stops at 600 DPI; do not increase further unless the visual gain is operationally
worth the added file size and rendering time.

Validation
----------
Run:
  python tools/validate_cam_render_clarity_phase1b.py
