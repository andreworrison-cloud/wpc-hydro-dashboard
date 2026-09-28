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

- Feature branch: `feature/nldas3-static-land-surface`
- Added `tools/probe_nldas3_static.py` to inspect the live NASA NetCDF schemas
  without assuming variable names or category definitions.
- Added `.github/workflows/probe_nldas3_static.yml` to run the source inventory.
- Next gate: inspect the generated inventory and source attributes/class metadata.
- After that gate: build retained CONUS scientific rasters, dashboard display
  derivatives, metadata JSON, Leaflet overlays, legends, and layer registration.

## Live-source validation findings (2026-09-28)

The first two guarded GitHub Actions probes reached both public NASA S3 objects successfully.
The dominant source is a 6500 x 11700 regular 0.01-degree grid with 1-D latitude/longitude
coordinates. The live source variable names are `Landcover_inst` and `Soiltype_inst`.

Observed sampled values are integer-like even though both arrays are stored as float32.
The soil sample conforms to the documented STATSGO index and includes water as code 14.
The land-cover sample includes code 21 in addition to the standard IGBP/NCEP classes.
LISF documentation identifies the 21st surface type as the added open-water surface type;
class 21 must therefore remain water/transparent in the dashboard rather than being
silently remapped to a terrestrial class.

The HyMAP/Noah-MP static file exposes 42 data variables, including LANDMASK, LANDCOVER,
TEXTURE, ELEVATION, SLOPE, ASPECT, monthly GREENNESS, and multiple HYMAP routing fields
such as river geometry, drainage area, basin IDs, flow-direction components, and routing
time-delay parameters. These routing fields remain research-only until their semantics,
encodings, and forecaster value are validated individually.
