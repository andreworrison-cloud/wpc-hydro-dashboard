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

- Operational on `main`: NLDAS-3 Soil Texture, NLDAS-3 Land Use / Vegetation, and NLDAS-3 / MERIT Terrain Slope.
- These products are static land-surface context. They have **no recurring GitHub schedule** and are excluded from the dashboard's 15-minute dynamic refresh loop.
- Retained GitHub Actions are manual maintenance tools only (`workflow_dispatch`) for source probing and reproducible static-asset rebuilding.
- The superseded feature-branch publishing workflow has been removed.
- `tools/build_nldas3_static.py` reproducibly builds the CONUS soil-texture and land-use/vegetation display derivatives directly from NASA S3.
- `tools/build_nldas3_slope.py` reproducibly builds the descriptive CONUS percent-slope display derivative from the NLDAS-3 / MERIT `SLOPE` field.
- `tools/validate_dashboard.py` enforces source-variable, category/bin, bounds, image-dimension, nearest-neighbor/no-smoothing, display-vs-science, layer-order, and static-refresh safeguards.
- HYMAP basin IDs and routing coefficients remain research/model inputs until their semantics and units are sufficiently documented for a forecaster-facing display.
- Future full NLDAS-3 Noah-MP rollout remains reserved for dynamic fields such as SoilMoist, Qs, Qsb, SoilTemp, WaterTableD, TWS, and routing outputs when NASA releases them publicly.
