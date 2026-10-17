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

### Approved display choice — October 17, 2026

Following PNG review, Andrew approved 4000×2538 rendering for all four depths, retaining bilinear field reprojection, nearest validity-mask reprojection, and the exact existing wet-tail palette. The shared ingest now explicitly upscales to a 4000-pixel maximum dimension. Render revision v2 forces regeneration even when source bytes are unchanged; validated v1 generations remain available for failure retention. The no-argument operational 0–100 cm rendering path remains unchanged. Nine focused tests cover suite integrity, failures, freshness, approved rendering parameters, and revision migration. Dashboard integration and interactive browser review remain pending.

### Dashboard integration review — October 17, 2026

The new `sport_suite_layer.js` adapter is integrated into the actual dashboard sidebar, legend dock, opacity controls and state-border reference pane. The `sportReview=1` query flag exposes 0–10, 0–40, 0–100 and 0–200 cm review selections. Selecting any suite depth deactivates the other suite depths and the legacy SPoRT layer, and selecting legacy deactivates the suite. Normal operation keeps the original 0–100 cm path.

The review metadata URL is `review/sport-suite/metadata.json`, populated in the CI dashboard review artifact from that run's live ingest. The artifact contains the dashboard code/assets and all four generated PNGs; original floats remain in the separate evidence artifact. The bundle is intended for an HTTPS preview host, with `index.html?sportReview=1` as its entry point. This PR does not publish the review bundle to Pages or enable a production suite scheduler.

Every image is SHA-256 checked and decoded at 4000×2538 before the entire suite swaps. All depths must share valid time, geographic bounds and render contract. Metadata failures, missing images, invalid dimensions or checksum mismatches retain the complete previous suite only until its clock-derived cutoff. Browser time is evaluated every 30 seconds, independently of cached producer freshness flags. Metadata is polled every five minutes. Warning at 72 hours and cutoff at 96 hours remain explicitly provisional review settings, not approved operational policy.

Legend labels distinguish depth, percentile bins, valid time, source modification, retrieval time, last ingest attempt and cutoff. Colors retain their exact RGBA values. Transparent areas include both below-70th-percentile and missing cells. These are soil moisture percentiles, not saturation percentages or flash flood probabilities.

Validation: nine Python ingest tests and nineteen Node display/adapter tests pass locally. Node tests exercise the real adapter with mocked Leaflet/network/image decoding; they are not visual browser tests. The earlier local-file browser attempt was blocked by the browser's protocol policy. No interactive visual test is claimed. Remaining release gates: HTTPS-hosted browser review across backgrounds/zoom, final freshness-policy decision, durable publisher integration, and a separate production activation decision.

### SPoRT RSM companion suite — October 17, 2026

Andrew requested RSM as the primary soil-moisture perspective alongside the percentile suite. The confirmed numerical products are NASA float GeoTIFFs in `rsm_0-10cm/` and `rsm_0-2m/` under the same CONUS GeoTIFF root. Both October 17 00Z files were downloaded, decoded and rendered. The NASA viewer lists additional individual-layer RSM and integrated 0–100 cm maps, but matching downloadable 0–40 / 0–100 cm numerical fields are not verified; these are not fabricated from percentile products or activated in the dashboard.

SPoRT RSM is `100 * (theta - theta_wilting) / (theta_saturation - theta_wilting)`; source floats already express percentage values. No extra multiplication by 100 is applied. NASA documentation: https://weather.ndc.nasa.gov/sport/training/articles/20151207175408_NASA-Land-Information-System-LIS-Applications-Training/media/lis-soil-moisture-quick-guide-by-nasa-sport.pdf . This differs from the existing NLDAS metadata formula `100 * theta / Noah_porosity` (percent saturation).

The RSM pair shares EPSG:4326, 929×1929, 0.03-degree source grids and the percentile geographic extent. Its coverage baseline is 1,290,511 valid cells, distinct from the percentile baseline of 1,305,700. Missing values are 9999 with no declared nodata. NASA's guide describes additional urban masking for RSM. The surface field has 363 cells at 100.00000762939453%; an explicit RSM-only 0.0001 percentage-point roundoff tolerance retains these cells and clamps their display values to 100. Larger excursions fail source validation. The legacy percentile rendering path retains zero tolerance.

New modules `tools/sport_rsm_suite.py` and `sport_rsm_layer.js` implement a separate atomic two-depth generation and browser adapter. They retain the prior complete RSM pair on failures and reuse the explicitly provisional 72/96-hour review age policy. All RSM depths must share valid time and grid, independently of the percentile suite. Each legend exposes its own valid time. RSM and percentile data may therefore have different dates, which must remain visible.

The RSM legend uses bins 0–40 / 40–50 / 50–60 / 60–70 / 70–80 / 80–90 / 90–95 / 95–100%, with brown-to-green-to-blue/purple colors. Unlike wet-tail percentiles, low RSM values remain visible. Missing values are transparent. The exact existing percentile palette is untouched. RSM controls precede the percentile review controls, and all SPoRT selections are mutually exclusive to prevent overlapping colors.

Both RSM overlays are 4000×2538, EPSG:3857, bilinear field reprojection with a nearest validity mask. The included `review/sport_rsm_two_depths.png` was visually inspected. Rebuild with `python -m tools.build_sport_rsm_review --suite-dir <RSM directory> --states review/vendor/us-states.json --output <PNG>`. Twenty Python tests and thirty-nine Node tests pass locally across both suites. The workflow repeats these tests, ingests both suites and packages both into the dashboard review artifact. Production activation and scheduling remain unchanged.
