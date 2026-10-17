# H6 SPoRT-LIS depth expansion — source qualification

Status: 2026-10-17. Feature branch only. Existing operational 0–100 cm layer, renderer and four-times-daily retrieval schedule remain unchanged.

## Verified source evidence

The live NASA directory and downloaded original floating-point GeoTIFFs provide 0–10, 0–40, 0–100 and 0–200 cm percentile fields for 2026-10-17 00Z. All four have a 929 by 1929 EPSG:4326 grid, 0.03-degree spacing, identical transforms and bounds, and exactly 1,305,700 valid cells. All four validity masks match exactly in this sample. Bounds: west -124.94, south 25.06, east -67.07, north 52.93. Nominal model resolution is 3 km; degree-grid spacing does not imply uniform physical cell size.

Values are floating-point percentiles, with 9999 as missing and no declared TIFF nodata. Mask missing/nonfinite/out-of-range cells before interpolation. This sample spans approximately 0.433–99.995 percentile. Source hashes and all numerical diagnostics are in review/sport_depth_source_audit.json. GeoTIFF tags contain AREA_OR_POINT only; valid time and depth are identified by the dated source filenames, not independently embedded time tags.

## Timing finding

For the latest ten valid dates, directory modification minus valid time ranges from 16.41 to 46.47 hours. October 17 fields were modified around 16:24Z; many prior dates show next-day modifications around 22:24Z. These timestamps do not prove first-publication latency or rule out replacement/backfill. Keep multiple daily checks and measure first-seen times prospectively before changing cadence. Do not apply H5's 3-hour snapshot freshness threshold to these daily products.

## Implementation contract

Refactor fetch_sport.py around a single depth configuration, preserving its existing 0–100 cm public filenames and metadata compatibility. Keep sport-wet-tail-v4 colors and bins (70, 80, 90, 95, 98), continuous-field bilinear display reprojection, nearest-neighbor validity masking, EPSG:3857 output, and maximum 3000 pixels. Retain source floats independently from PNGs.

Prefer a complete same-valid-time four-depth generation for comparisons. If the newest date is incomplete, retain the previous validated suite and expose the failed attempt; never silently combine dates. Track per-depth source URL/hash, valid time, file modification time, retrieval time, coverage, and status. Publish generation assets before the metadata pointer and enforce clock-based freshness in the browser. Design the daily-product freshness limits explicitly after further latency review.

Next milestone: implement the shared-depth ingest and last-good behavior on this branch, render all four maps with the existing palette, then review browser legends, depth switching and alignment before production integration. Forecast interpretation must distinguish daily near-surface antecedent state from hourly wetting response; percentile is neither volumetric water content nor percent saturation.

## Reproduce

Install numpy and rasterio, then run:

    python tools/probe_sport_depths.py --output /tmp/sport-depth-audit

The diagnostic downloads the newest listed complete suite, checks raster structure/ranges, compares all grids/masks, and writes source files and a JSON report outside production assets. It fails on an incomplete newest suite or invalid raster. It does not publish data or change schedules.

## Shared ingest and clarity review implemented

`fetch_sport.py --suite-dir <directory>` opts into the shared-depth ingest; invoking without arguments retains the existing 0–100 cm production path. Live retrieval of all four depths succeeded. Seven failure/freshness tests passed. An exact comparison against the original script confirmed identical legacy numerical display arrays, bounds and RGBA pixels. Sources and all four PNGs are staged together in content-addressed generations; the JSON pointer changes only after validation. Partial failures retain the complete prior suite. No production integration or schedule change is included.

Review policy is explicitly provisional: warn at 72 h, hide at 96 h from valid time. This allows the observed roughly 46 h modification delay plus a daily interval; it is not an approved operational freshness standard.

The actual current image is 1808×1147, despite a 3000-pixel upper cap. Review compares it against 4000×2538 bilinear-field and nearest-field outputs, with the identical RGBA palette. Crisp CSS is scoped to candidate SPoRT image overlays. Higher rendering resolution does not increase nominal 3-km scientific resolution. The nearest-field option has visibly more speckle; the bilinear-field candidate is the preferred review option.

Run tools/build_sport_depth_review.py with --source-dir, --date, --vendor-dir review/vendor, and --output-dir to reproduce the self-contained three-map HTML and static figures. All four depths, synchronized map views, dark/light canvas, optional Esri basemap, legends and state boundaries are included. Static figures were visually inspected; the HTML scripts passed syntax checks. Automated live browser interaction with the local HTML was blocked by the cloud browser URL policy, so interactive visual verification remains pending user review.
