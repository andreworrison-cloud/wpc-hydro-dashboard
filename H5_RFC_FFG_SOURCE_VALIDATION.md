# H5: official RFC FFG source validation

Status: diagnostic prototype only. No dashboard registration or operational ingest.
Burn-severity development remains with Sol. No changes to existing layers or schedules.

## Run

Python 3.11+; no third-party dependencies:

```sh
python -m unittest discover -s tools -p 'test_probe_rfc_ffg.py' -v
python tools/probe_rfc_ffg.py --output-dir diagnostics/rfc_ffg
```

Each invocation creates a unique timestamped observation directory with source
metadata, raw identify responses, catalog records before/after export, official
legends, request hashes/HTTP headers, errors, and three display-only PNG previews.
The workflow runs on relevant pull-request changes and supports manual dispatch
once available on the default branch. It has read-only repository permissions,
no schedule and no commit/publish step. Re-run the PR diagnostic across cycles
for additional observations. An observation completing does NOT mean production
readiness, complete coverage, verified units, or fresh underlying RFC guidance.

## Initial direct observations: 2026-10-17 approximately 15Z

- All three duration catalogs and PNG exports were accessible.
- The catalogs gave a 12Z reference time and a 14:38:51Z GIS file timestamp.
  GIS ingestion was 14:38:56Z (1h) / 14:38:57Z (3h and 6h).
- Period-end fields were 13Z, 15Z and 18Z respectively. Do not use these as
  expiration times without confirming source semantics.
- Each catalog contained one national mosaic record, not separate RFC records.
  Individual RFC issue times are therefore still unknown through this pathway.
- The service advertises EPSG:3857; previews request EPSG:4326. This does not
  establish the native scientific grid or its exact resolution.
- Identify returns values, including Oklahoma 50.0007 / 61.9989 / 78.9993.
  Units/scaling remain unverified. The official legend uses inches; that does
  NOT prove the numeric identify values use inches. No conversion is applied.
- Coastal Washington and an offshore point return NoData, as expected.
- Additional interior samples also returned NoData: Minneapolis, Phoenix,
  Atlanta and Florida in all three durations; Memphis in 1h/3h but not 6h.
  Broad blank areas were also visible in the 3h preview. These are unresolved
  source/service coverage gaps, not evidence of zero thresholds or low risk.
- All three catalogs remained stable around their preview exports in the
  initial observation. This does not guarantee all samples share one snapshot.

Compact query evidence is retained in `tools/rfc_ffg_initial_observation.json`.
Full reports and previews are retained as workflow artifacts when run on GitHub.

## Required gates before dashboard integration

1. Explain the interior NoData pattern and establish expected coverage masks.
   Compare against an independent official numerical source; do not fill gaps.
2. Verify numeric units/scaling and obtain a defensible full-grid source.
   MapServer TIFF/PNG exports are display products until proven otherwise.
   Point access alone is not adequate for H8 scientific grid calculations.
3. Confirm reference/end timestamp semantics. Preserve retrieval, mosaic and
   underlying RFC times separately. Unknown RFC times must remain unknown.
4. Observe several mosaic refreshes, including a synoptic RFC update and, when
   available, an event-driven update. The initial snapshot is not a latency audit.
5. Establish exact numerical grid, mask, CRS, resolution and RFC boundary source.
   A mosaic footprint is not an RFC boundary layer.
6. Build production last-good retention with age/coverage checks, immutable
   snapshots and consistent image/metadata publication; then integrate the
   1/3/6h layers, legends, freshness labels and dashboard regression checks.

RFC issuance context supplied by Andrew: 00/06/12/18Z plus event-driven updates.
The hourly national mosaic refresh is a separate process. Static NLDAS-3,
SPoRT-LIS, burn severity, and experimental guidance are outside this change.

## Authoritative service references

- https://mapservices.weather.noaa.gov/raster/rest/services/precip/rfc_gridded_ffg/MapServer
- https://mapservices.weather.noaa.gov/raster/rest/services/precip/rfc_gridded_ffg/MapServer/2
- https://mapservices.weather.noaa.gov/raster/rest/services/precip/rfc_gridded_ffg/MapServer/info/iteminfo
