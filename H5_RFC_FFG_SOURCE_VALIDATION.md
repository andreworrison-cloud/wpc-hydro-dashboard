# H5: official RFC FFG source validation

Status: direct WPC numerical access verified for two hourly snapshots; diagnostic prototype only. No dashboard registration or operational ingest.
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

## Initial gates (superseded where resolved below)

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


## H5 numeric follow-up: 2026-10-17

The GitHub diagnostic succeeded, but its map-service point availability differed
from the earlier observation despite identical catalog timestamps. For example,
Phoenix/Minneapolis/Atlanta had values in GitHub while Memphis and Florida remained
NoData. The southwest Washington sample also had values in the numerical data and
GitHub response, contrary to the initial local response. Do not hard-code that
particular coordinate as an expected no-data location.

### Direct numerical source established

IEM's published downloader identified the WPC directory:
https://ftp-wpc.ncep.noaa.gov/workoff/ffg/

It provides two observed filename families:

- `5kmffg_YYYYMMDDHH.g2`: hourly snapshots with 1/3/6-hour fields.
- `5kmffg_YYYYMMDDCC.grb2`: cycle-named files that can be revised within the cycle.
  The inspected file also had 12h and empty 24h bands, excluded from this work.

The numerical diagnostic discovers hourly filenames from the live directory;
it does not invent a latest URL or silently fall back to a stale cycle.
A directory can itself be stale: production freshness gates remain to be built.

Direct WPC 13Z and 14Z snapshots both decoded successfully:

- 1082 columns by 794 rows, polar stereographic, sphere radius 6371200 m,
  true-scale latitude 60 N, central meridian 255 E (-105 W).
- Projected spacing 4762.453 by 4762.443 metres (nominal 5-km product).
- Parameter FFLDG, units kg m-2, equivalent to mm of water. Divide by 25.4 for inches.
  NCEP's parameter table independently confirms quantity and units.
- Duration selection uses GRIB time-range metadata and cross-checks timestamps;
  band position is not a duration identifier.
- Hourly files encode NCEP center 7 and missing subcenter 255; the cycle file
  encodes center 7/subcenter 5 (HPC/WPC). Provenance retains this distinction.
- 486607 valid cells at 1h and 486606 at 3h/6h, with unchanged masks between
  the two snapshots. These counts cover the rectangular grid, NOT a CONUS
  land-completeness statistic.
- Native numerical GeoTIFF round trips preserved every value and missing cell.
- The numerical geographic preview has continuous coverage across the sampled
  interior regions where the service exports/identify responses had gaps.
  No missing values were filled or inferred from colors.

### Same-cycle updates demonstrated

Both snapshots encode 12Z reference time, with 13/15/18Z period-end fields for
1/3/6h. Between the 13Z and 14Z snapshots:

| Duration | Changed valid cells | Largest absolute change (mm) |
|---|---:|---:|
| 1h | 13621 | 11.2025 |
| 3h | 13274 | 15.2400 |
| 6h | 13431 | 16.2325 |

The retrieved 14Z hourly data matched the retrieved cycle-named WPC file in all
three numerical fields, while the earlier IEM copy differed. Hash both source
bytes and decoded content as appropriate; never treat a familiar cycle filename
or reference timestamp as proof that nothing changed. The reference time is not
an expiration time. Individual RFC issuance times remain unknown.

### Coverage conclusion and limits

The interior missing values are not a necessary property of the available WPC
numerical product. At Memphis, Minneapolis, Phoenix, Atlanta and Florida, all
three direct numerical fields have positive values. The map-service pathway is
unsuitable as the scientific ingest or sole coverage authority. Its precise
server-side failure mechanism remains unproven; this work does not claim to
repair NOAA's service. Use the direct numerical route for H5 development.

An independent authoritative land/RFC coverage mask is still needed before
claiming every expected grid cell is present. The published Northwest coverage
caveat and the observed numerical footprint need reconciliation, not an invented
geographic mask. Offshore NoData remains missing, never zero.

### Reproduce

```sh
python -m pip install "numpy>=2,<3" "rasterio>=1.4,<2"
python -m unittest discover -s tools -p 'test_probe_rfc_ffg*.py' -v
python tools/probe_rfc_ffg_numeric.py --output-dir diagnostics/rfc_ffg
# Reproduce the initial pair while retained by WPC:
python tools/probe_rfc_ffg_numeric.py --output-dir diagnostics/rfc_ffg --snapshot 2026101714
```

The workflow now runs both service and numerical probes, retaining raw GRIBs,
controlled numerical GeoTIFFs, diagnostic previews, and reports as artifacts.
The compact checked-in evidence is `tools/rfc_ffg_numeric_observation.json`.
All 14 local contract tests passed. The diagnostic's production_ready flag remains
false: last-good publication, stale/coverage policy and dashboard integration
are separate implementation gates.

### Next production work

Build an hourly direct-WPC ingest with source snapshot time, source HTTP modification
time, reference cycle, retrieval time and hashes kept distinct. Add bounded
freshness checks, retain last-good validated fields on failure, and validate the
published metadata/image set as one version. Then review the 1/3/6h maps and
legends on the feature branch before integrating. Continue to observe the source
through synoptic transitions; two historical hourly snapshots do not constitute
a measured posting-latency service-level guarantee.
