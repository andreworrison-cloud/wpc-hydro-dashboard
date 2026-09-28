# NLDAS-3 Static Land-Surface Integration — Phase 1

## Goal

Add currently public NLDAS-3 static land-surface information to the WPC Real-Time
Hydrometeorological Dashboard without conflating it with operational/dynamic FFG.
The same retained scientific fields will later support the experimental hourly FFG
research framework.

## Public NASA sources

1. `s3://nasa-waterinsight/NLDAS3/static/NLDAS-3_dominant-soil-vegetation.nc`
   - full NLDAS-3 domain
   - latitude / longitude
   - `surface_class`: land use / vegetation integer class
   - `soil_class`: soil texture integer class

2. `s3://nasa-waterinsight/NLDAS3/static/lis_input.nldas3.noahmp401.1km.hymap.nc`
   - tiled static parameters used by Noah-MP / HyMAP
   - land mask
   - surface class
   - soil texture
   - surface geometry
   - catchment ID
   - other time-invariant model/routing parameters

NASA documentation states the NLDAS-3 domain is a 6,500 x 11,700 grid spanning
7–72 N and 169 W–52 W, with 26,546,611 valid land points.

## Dashboard placement

Initial public-facing layers belong under the existing
**Land-Surface Runoff Sensitivity** section, beside NRCS HSG and Annual NLCD
fractional impervious surface:

- NLDAS-3 Soil Texture
- NLDAS-3 Land Use / Vegetation

The routing/static file will be inventoried first. Catchment/routing displays will
be added only if the source geometry and identifier semantics prove useful for
forecaster interpretation.

## Science / rendering safeguards

- Preserve NASA integer category codes exactly.
- Do not infer category labels from code values.
- Do not smooth categorical fields.
- Use nearest-neighbor resampling only for categorical display derivatives.
- Keep retained scientific rasters separate from browser PNG/WebP derivatives.
- Do not use browser display images as inputs to future infiltration/FFG
  calculations.
- Keep NLDAS-3 soil texture distinct from NRCS Hydrologic Soil Group. They are
  complementary properties, not interchangeable classifications.
- Keep static NLDAS-3 vegetation distinct from current burn-scar/burn-severity
  datasets.
- Label these products as static land-surface context, not dynamic soil moisture
  or FFG.

## Hourly experimental FFG linkage

Phase 1 creates the static parameter foundation for later calculations such as:

`FFG_exp(t) = f(static soil/surface properties, dynamic soil moisture,
recent QPE, terrain, imperviousness, burn severity, watershed state)`

Current NLDAS-3 static fields should be treated as explanatory/model parameters,
not as a standalone proxy for infiltration rate or flash-flood threshold.

Future NLDAS-3 Noah-MP rollout can extend this framework with SoilMoist, Qs, Qsb,
SoilTemp, WaterTableD, TWS, and routing outputs when NASA releases them publicly.

## Implementation status

- Current integration branch: `feature/nldas3-static-land-surface-current`, rebuilt from the current dashboard `main` rather than the earlier diverged prototype branch.
- Live NASA source probe completed successfully against both public static NetCDF files.
- `tools/build_nldas3_static.py` reproducibly builds the CONUS soil-texture and land-use/vegetation display derivatives directly from NASA S3.
- `static/nldas3_soil_texture.png`, `static/nldas3_landcover.png`, and `static/nldas3_static_metadata.json` are generated and published on the feature branch only.
- `app.js` registers both products under **Land-Surface Runoff Sensitivity**, with categorical legends, static-product time/source boxes, metadata fail-closed checks, and no 15-minute dynamic refresh.
- `tools/validate_dashboard.py` enforces the NLDAS-3 source-variable, category-code, bounds, image-dimension, nearest-neighbor/no-smoothing, display-vs-science, and layer-order contracts.
- Dashboard validation, NLDAS-3 build, and guarded feature-branch publication are passing.
- The larger Noah-MP/HyMAP static file also contains MERIT ~1-km elevation and slope, monthly greenness climatology, drainage area/basin structure, river geometry/roughness, flow-direction fields, and runoff/baseflow timing parameters.
- **Next static-display candidate:** MERIT/NLDAS-3 terrain slope. HYMAP basin IDs and routing coefficients remain research/model inputs until their semantics and units are sufficiently documented for a forecaster-facing display.
- Future full NLDAS-3 Noah-MP rollout remains reserved for dynamic fields such as SoilMoist, Qs, Qsb, SoilTemp, WaterTableD, TWS, and routing outputs when NASA releases them publicly.

