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

## Production-ingest implementation (feature branch, not yet deployed)

`fetch_rfc_ffg.py` now implements ingestion and transaction-safe product output.
It reuses the already-tested numerical decoding/rendering utilities from
`tools/probe_rfc_ffg_numeric.py`. Existing diagnostic callers retain their default
preview size; ingest previews are 3000 x 1300 pixels. These are still the review
palette, not a final operational display design.

```sh
python fetch_rfc_ffg.py \
  --output-dir diagnostics/rfc_ffg_ingest/public \
  --science-dir diagnostics/rfc_ffg_ingest/science
```

### Product contract

- Discover latest eligible `.g2` snapshot from the live WPC directory on every run.
  Re-download and hash even when a filename has been seen; never infer unchanged
  data from a cycle name. No silent fallback to an older source candidate.
- Validate complete GRIB2 messages, FFLDG quantity/units, duration metadata,
  consistent reference times, numerical values, grid geometry and coverage.
- Preserve snapshot hour, encoded reference cycle, encoded period ends, HTTP
  Last-Modified when supplied, retrieval time and acceptance time separately.
  No individual RFC issue times are fabricated.
- Preserve original GRIB and exact native-mm GeoTIFF under the science root.
  Public output contains three rendered maps, legend definition and metadata.
- Stage all three durations in an immutable generation directory. Promote
  `metadata.json` with one atomic filesystem replace only after the generation
  and scientific data are complete. A process lock prevents concurrent writers.
- `metadata.json.active.assets` maps each duration to a version-specific PNG and
  SHA-256. Readers must follow those paths; there are no mutable fixed-name PNGs.
- Keep the most recent 48 generation directories in each root, always preserving
  the active generation. This is a short-term operational cache, not a research
  archive for long-term H8 tendency verification.

### Provisional acceptance policy (explicit in every metadata file)

- Snapshot age at most 3 hours; reference-cycle age at most 9 hours.
- Reject future/inconsistent timestamps (5-minute clock tolerance), backwards
  snapshot/reference transitions, changed grid/CRS, missing/nonfinite/nonpositive
  values or values greater than the conservative 1000-mm sanity ceiling.
- Fixed coverage baseline from the directly validated 2026-10-17 14Z source:
  total valid-cell count changes at most 0.5%; per 100 x 100 native-cell tile,
  changes at most 2% (five-cell allowance for small edge tiles).
- Compare actual missing-data masks against the preceding accepted numerical
  product as well: changes at most 0.5% of its valid cells.
- These are technical integrity checks against an observed baseline, not proof
  of an independently established expected CONUS land/RFC footprint. The Northwest
  coverage question remains a provenance limitation. Legitimate major coverage
  changes require review rather than automatically relearning a degraded baseline.

### Failure and freshness behavior

Successful status is `updated` or `unchanged`. Failed refreshes exit nonzero and
write a failed attempt record while preserving previously verified assets:

| State | Meaning | usable |
|---|---|---|
| retained | Refresh failed; last-good fields remain within age limits | true, with stale=true |
| expired | Last-good fields retained but exceed age limits | false |
| unavailable | No verified last-good product exists | false |

Retention does not mean freshness. The metadata gives snapshot/reference ages
and `freshness.expires_at`, the earlier of their two deadlines. Dashboard readers
must recompute expiration against their current clock, even if no subsequent job
runs. A failed refresh must have a visible stale/retained indicator in the later
UI. Expired data must not be presented as current. No such UI is wired yet.

### Validation and execution

Fourteen new tests exercise retention on outages and malformed GRIB, missing
coverage, regional loss, old/future timestamps, modified content under the same
filename, interrupted publication, corrupted retained assets, expiration,
unchanged reruns, and science/public separation. Combined with the existing
fourteen numerical/source tests, 28 local tests pass.

A live ingest generated all three maps and preserved the native fields. Visual
review found the interior areas populated. Simulated failure and expiration on
a copy of those actual products left every active asset unchanged while correctly
switching retained -> expired. Evidence: `tools/rfc_ffg_ingest_observation.json`.

`.github/workflows/update_rfc_ffg.yml` runs this ingest on relevant PR changes and
supports manual dispatch once discoverable by GitHub. It restores/saves rehearsal
state through a branch-scoped Actions cache and uploads public/scientific artifacts.
Cache eviction is possible; a cache miss means no last-good state, never permission
to invent one. Durable production state still needs deployment wiring.

The workflow has read-only repository permissions, no cron and no dashboard
publication. Hourly source discovery is implemented; hourly unattended production
execution begins only when this feature is reviewed and integrated. The proposed
cadence remains :50, pending transition/latency observations. The production Git
publisher must commit the versioned assets and pointer together; it must also
persist failure metadata when ingest exits nonzero. Do not gate status publication
solely on a successful ingest exit.

## H5 display review (2026-10-17)

`review/rfc_ffg.html` is a self-contained frozen review of the validated 14Z
snapshot (12Z reference), not a live operational layer. Open it in a browser;
select a duration and a freshness scenario. The default uses the actual clock,
so an expired frozen snapshot is hidden. Simulations are explicitly labeled.
Rebuild with:

```
python tools/build_rfc_ffg_review.py --public-dir PATH_TO_PUBLIC --output review/rfc_ffg.html
node tools/test_rfc_ffg_display.cjs
```

The generator verifies image hashes before embedding. Legends derive directly
from generation metadata: inches, lower-inclusive/upper-exclusive intervals,
with explicit open tails and NoData explanation. The palette is proposed,
not an official RFC color scale and not flood-risk categories. All three
raster previews were visually inspected: broad interior coverage is present;
this does not resolve the independent expected-coverage-mask limitation.

The pure JavaScript freshness contract recomputes expiry from source times
and policy, never from successful polling or encoded duration endpoints.
Ten assertions cover exact expiry, retained-but-fresh guidance, failed refresh
past expiry, missing/invalid timestamps, future times, older reference cycles,
unavailable status, and invalid policy. The review reevaluates every 30 seconds.
It separates snapshot, GRIB reference, source modification, and actual last check.
Individual RFC issue times remain unavailable. Freshness policy still needs
operational acceptance (3-hour snapshot / 9-hour reference maximum ages).

**Map integration gate:** existing PNGs are EPSG:4326. Do not place them directly
in a default EPSG:3857 Leaflet image overlay: latitude stretching would be
incorrect. This review deliberately uses a geographic SVG viewport with
geographically aligned reference cities. Production needs a separately
versioned nearest-neighbor EPSG:3857 derivative or a projection-aware raster
renderer, followed by state/coastline alignment checks on the actual dashboard.
Native scientific values must remain unchanged.

The review page is responsive in CSS, but browser visual QA remains pending:
this environment has no Chromium executable and its attempted browser download
returned an invalid archive. No desktop/mobile screenshot validation is claimed.
Actual raster images were inspected separately. No production app.js/index.html/
style.css changes, publishing, or scheduler changes are included. The manual/PR
rehearsal now builds an offline review artifact after successful ingestion.
Scheduler choice (including the user's cron-job.org option) remains deferred
until display integration and durable publication are validated.

## H5 Mercator and browser validation (2026-10-17 follow-up)

The previous browser-blocker and geographic-only display notes are superseded
by this section. `review/rfc_ffg_leaflet.html` is the new frozen Leaflet review;
the earlier geographic review remains available for comparison.

- Ingest render revision `rfc-ffg-ingest-v0.2-mercator` produces 3000x1650
  EPSG:3857 display PNGs directly from the native numerical arrays with nearest
  neighbor resampling. W/S/E/N bounds remain -126/24/-66/50; projected bounds
  are recorded separately. The new revision prevents reuse of old geographic
  images as Mercator generations. Scientific grids are unchanged.
- The focused Leaflet 1.9.4 review requires the Mercator CRS before creating an
  image overlay. It embeds raster assets, Leaflet, and generalized state
  reference geometry; external map backgrounds require internet connectivity.
  It includes the existing dashboard's 15 background selections (the WPC Dark
  Reference is simplified to country polygons without production place labels).
- CONUS state boundaries use separate vector layers above the raster, with a
  dark halo and a light inner stroke. They stay visible on all backgrounds,
  including No Basemap. They are not burned into the scientific data.
- Browser QA now runs using Chromium 133.0.6943.0, obtained via the packaged
  Chromium distribution after the Playwright download endpoint failed. Actual
  desktop, regional-zoom, and 390px mobile screenshots were visually inspected.
  A conflicting SVG style found on the first render was corrected before
  validation. No JavaScript page errors or mobile horizontal overflow remained.
- All three duration selections, 15 basemap layer transitions, and retained /
  expired / unavailable raster visibility transitions passed browser checks.
  A separate analytical Mercator placement check at five locations and three
  zoom levels had maximum discrepancy 0.90 screen pixels (Leaflet rounding).
  This is a rendering geometry check, not a claim of subpixel source accuracy.
- Two independent numerical tests check projected bounds against the spherical
  Mercator formula, the latitude displacement of a known synthetic boundary,
  preserved color categories and NoData, and unsupported CRS rejection.
  Existing 28 Python tests and 10 JavaScript freshness assertions still pass.
  SHA-256 verification confirms the original native numerical GeoTIFF is unchanged.

Rebuild the review from new ingest output using `tools/build_rfc_ffg_review.py`;
it selects the correct template from the declared CRS. Browser test command:

```
# With playwright available to Node and Chromium installed:
node tools/test_rfc_ffg_leaflet.cjs review/rfc_ffg_leaflet.html
# Optional CHROMIUM_EXECUTABLE_PATH selects an existing Chromium executable.
```

This remains a focused review within draft PR 12. No production dashboard
registration, main-branch publication, durable hosting, or schedule is changed.

External background check: after allowing additional load time through the
execution environment's network proxy, all 28 requested tiles loaded for both
Esri Light Gray and Esri World Imagery. Both complete screenshots were visually
inspected for coastline/state alignment and contrast. OpenStreetMap loaded
partially (9/28 tiles during its shorter observation). Other backgrounds passed
layer-switch checks but were not individually certified for tile availability.

## Dashboard integration and durable review publishing

Andrew approved the 3-hour snapshot / 9-hour reference freshness policy on
2026-10-17. The review branch now registers RFC 1-, 3-, and 6-hour guidance in
Antecedent Hydrologic Conditions, off by default and mutually exclusive.
The existing sidebar handles selection, opacity, solo, and clear controls.
The existing legend dock displays thresholds, source timestamps, and freshness.
State borders remain vectors above the FFG raster even with No Basemap; the
existing remote boundary source has a bundled reference fallback.

`rfc_ffg_layer.js` validates metadata projection, units, policy, legend, and
immutable-generation identity. It downloads, SHA-256 verifies, and decodes
all three images before swapping any layers. Metadata/image/decoding failures
retain the prior complete generation while it remains fresh. The 30-second
clock check hides expired images without waiting for an ingest run. Browser
metadata polling is every five minutes; this is not a server ingestion schedule.

`tools/publish_rfc_ffg.py` restores and publishes the dedicated
`data/rfc-ffg-review` branch. It is a data-only tree with `public`, `science`,
and a branch identity marker; its initial commit has no code-branch parent.
The public manifest, all display assets, original GRIB, native GeoTIFF, and
scientific provenance share one commit. Restore verifies the active hashes.
Publication verifies again and advances the remote ref without force; competing
writers are rejected. Cold runners restore from Git, not Actions cache.
A failed ingest still publishes explicit retained/expired status when the
retained scientific files remain valid. Read or validation failures do not
silently overwrite the durable branch. No main or Pages update is performed.

The workflow is limited to the same-repository H5 review branch PR or manual
runs on that branch. It has no schedule. Its write permission is used solely
by the review publisher. Production activation remains a separate decision.
The dashboard reads the review data branch through raw GitHub URLs. Unique
hashed generation paths prevent mixed-version asset reuse; metadata requests
include a cache-busting query and browser freshness is independently enforced.

Retention is 48 generation directories at the current branch tip. Git retains
historical commits and blobs: this is durable rehearsal storage, not a claim of
bounded historical storage. Before sustained production scheduling, review data
volume and either approve this storage model or move the same immutable-object /
manifest contract to an object store with an explicit lifecycle. No history is
rewritten or deleted by this implementation.

Validation: 36 Python tests (including four durable publisher tests), ten
JavaScript freshness assertions, and a browser rehearsal of the actual
`index.html` / `app.js` passed. The browser isolated unrelated remote products
and used the actual validated Mercator PNGs with controlled metadata and clock.
It checked selection, legend, opacity, exclusivity, partial-image failure,
successful replacement, unchanged-product download avoidance, metadata outage,
and expiry; no JavaScript page errors occurred. A real-GRIB local Git rehearsal
performed update -> publish -> cold restore -> unchanged -> publish -> cold
restore -> retained -> publish -> cold restore -> expired. Evidence is in
`tools/rfc_ffg_durable_observation.json`. Local mock/failure tests are not claims
of continuous operational uptime.

Browser reproduction: `tools/test_rfc_ffg_dashboard.cjs REPO PUBLIC_FIXTURE_DIR`
uses Playwright and optional `CHROMIUM_EXECUTABLE_PATH`. The fixture directory
contains the three Mercator `rfc_ffg_{1,3,6}h.png` files and metadata.json from the
frozen 2026-10-17 14Z review. Cache the existing dashboard's CDN dependencies
iso8601-js-period 0.2.1 as `/tmp/h5_iso.js` and leaflet-timedimension 1.1.1 as
`/tmp/h5_time.js` before running. These files are test dependencies only.


GitHub rehearsal run 39050746511 completed successfully on commit
856b47fa5fe977ba01ea241aa675eaea01e55558. It created durable data commit
2b78c581b68647f32795f3d70ea665a955884de5 with the actual 2026-10-17 16Z
snapshot / 12Z reference. The integrated dashboard loaded and hash-verified
those remote assets in Chromium (controlled review clock 16:45Z). The existing
Validate Dashboard Interface workflow also passed with 148 registry entries.
A final consistency check aligned backend expiry with browser expiry at the
exact cutoff and rejects retained manifests missing any of the three durations.
