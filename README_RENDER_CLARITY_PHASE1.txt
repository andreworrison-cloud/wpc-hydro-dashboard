WPC Hydrometeorological Dashboard
RAP + CAM Render Clarity Phase 1

PURPOSE
-------
Increase dashboard PNG pixel density so RAP and CAM overlays remain sharper when
Leaflet enlarges them during regional zooming. This is a display-resolution change,
not a meteorological-resolution change.

FILES
-----
fetch_rap.py       -> replace repository fetch_rap.py
fetch_cam.py       -> replace repository fetch_cam.py
fetch_cam_ero.py   -> replace repository fetch_cam_ero.py
tools/validate_render_clarity.py -> optional standalone source-contract validator

RENDER CHANGE
-------------
Existing main-map render: 10 x 6 inches at 300 DPI = 3000 x 1800 px
Phase-1 main-map render: 10 x 6 inches at 450 DPI = 4500 x 2700 px

This is +50% linear pixel density and 2.25x total raster pixels while preserving
the same physical figure dimensions. RAP labels, contour lines, and barbs therefore
retain their relative cartographic size while rasterizing at higher pixel density.

RAP legends are increased from 100 DPI to 200 DPI for sharper text/color bars.

SCIENTIFIC CONTRACT PRESERVED
-----------------------------
RAP:
- No RAP grid interpolation or artificial meteorological resolution is added.
- Existing field calculations and existing Gaussian smoothing are unchanged in this phase.
- Existing contour levels, color maps, thresholds, barbs, and valid-time logic are unchanged.

CAM Nowcasts + Day 1 ERO CAMs:
- HREF/REFS source data and forecast windows are unchanged.
- Existing REFS-to-HREF linear interpolation used for model-grid harmonization is unchanged.
- Existing super-ensemble averaging is unchanged.
- Probability thresholds remain 10/30/50/70/90/100 percent.
- No new display smoothing or meteorological interpolation is introduced.

METADATA
--------
Each script now records a small rendering block in its existing metadata JSON with
render revision, 4500x2700 dimensions, and DPI. Existing frontend consumers can
ignore these extra fields safely.

TESTING
-------
Before packaging:
- python -m py_compile: PASS for all three scripts
- tools/validate_render_clarity.py: PASS

RECOMMENDED OPERATIONAL TEST
----------------------------
1. Commit the three replacement fetch scripts together.
2. Run RAP, CAM Nowcasts, and Day 1 ERO CAM workflows manually once.
3. Compare default CONUS and regional zoom views, especially:
   - RAP PWAT
   - RAP MUCAPE
   - RAP 850-mb Moisture Transport
   - CAM QPF exceedance probability
   - CAM FFG exceedance probability
4. Check GitHub Action runtime and generated PNG sizes before deciding whether a
   still-higher render density is warranted.

NOTE ON RAP SMOOTHING
---------------------
The current RAP script applies Gaussian smoothing to many fields before plotting.
That behavior predates this render-density change and has deliberately NOT been
altered here, so Phase 1 isolates display sharpness from scientific-field processing.
A separate controlled audit can compare native/less-smoothed RAP fields later if desired.
