# RRFS and HRRR/RRFS flash-flood suites

4 November 2026. All guidance remains experimental.

The dashboard adds two RRFS diagnostic maps, 18 RRFS-TLE maps, two blended
HRRR/RRFS diagnostic maps and 18 pooled HRRR/RRFS-TLE maps. The original HRRR
sections and every existing integration remain available. The additional menus
inherit the established spacing and the Core FFG Guidance, Heavy Rain /
Persistence and Timing / Evolution submenus.

## Shared scientific calculation

`fetch_hrrr_tle.py` remains the HRRR producer. Its existing aggregation was
extracted into `compute_tle_fields`, used by all three suites. All 18 TLE arrays
match the pre-change V3.3 implementation exactly in a frozen regression with
missing FFG cells, varied rainfall, timing, persistence and run-change signals.
The fixture records source commit `27cb4207fe1692bb7049c07f229482e6c8374acb`.

| Setting | RRFS | HRRR/RRFS |
|---|---|---|
| Common interval | 12 hours | Same 12 hours for both models |
| Lagged runs | Six consecutive hourly RRFS cycles | Six HRRR plus six RRFS hourly cycles |
| Leads | f01–12, f02–13, …, f06–17 | Same ranges for each model |
| Neighborhood | Original V3.3 circular footprint, radius 13 native 3-km cells (nominal 40 km) | Same |
| Diagnostics | Original V3.3 on latest complete RRFS f01–f12 | Original V3.3 on the 50/50 mean of paired hourly rainfall fields |
| TLE frequency | Equal weights across six RRFS runs | Equal weights across 12 runs; each model totals 50% |
| TLE median ratio | Median of six member neighborhood maxima | Median of 12 member neighborhood maxima |
| Evolution minimum display support | 2/6 | 4/12, retaining the original one-third fraction |
| Run-change groups | Latest three / prior three cycles | Latest three / prior three from each model: six members per group |
| Run-change signal | At least 2/3 | At least 4/6, retaining the original two-thirds fraction |

The blend is defined before computing diagnostic thresholds, maxima and
coverage. The pooled TLE retains each individual member rainfall forecast; it
does not average rainfall before member exceedance tests. These are different
products with explicitly different purposes. Neither is a calibrated
flash-flood probability. Six lagged cycles from a model are correlated.

The original QPF/FFG rolling 1/3/6-hour accumulations, 1/2/3-inch hourly
thresholds, repeated 1-inch rainfall in two of three hours, rolling three-hour
2/3-inch thresholds, run-change categories, ratio/coverage palettes and native
unsmoothed rendering are retained. Blended frequencies use 1/12 steps; adjacent
pairs share the established six hues. Legends state actual count ranges.

The original IEM archived numerical 1/3/6-hour FFG at or before the reference
cycle is used, including its original lookback and nearest-neighbor mapping.
The deterministic and TLE selections may have different newest complete cycles;
each receives the FFG selected at its own reference. The blend uses the same
frozen FFG for both families. FFG nominal analysis labels are not presented as
individual RFC issue-time evidence. This extension does not change or claim the
different official-cycle FFG methodology used by the SPC/OMD CAM suites.

## Operational RRFS hourly input

NWS implemented RRFS at 12Z on 3 November 2026. Source policy admits only
operational RRFS cycles at or after that time, and excludes the parallel feed
and REFS ensemble members. Source mirrors are operational NOMADS and NOAA's
`noaa-rrfs-ops-pds` bucket.

RRFS publishes the ordinary hourly 2D files for three-hourly cycles. The other
hourly cycles publish `2dfld.3km.subh` files. Each subh file contains four
quarter-hour samples of cumulative APCP, including its whole-hour endpoint.
Consequently, simply changing the model name in the HRRR downloader cannot
produce a six-consecutive-hour RRFS TLE.

For cycles divisible by three, the adapter reads the directly encoded
incremental one-hour APCP. For other cycles it selects cumulative APCP at
exact whole-hour endpoints, checks its initialization, deterministic RRFS
identifier (134), units, surface level, accumulation interval and native grid,
then subtracts the preceding endpoint. Initial cumulative rainfall is
mathematically zero at initialization; every later endpoint must actually
exist. Quarter-hour records and precipitation rates cannot pass the selector.

Cumulative differencing has GRIB packing precision limits. A live 15Z f12
comparison on 4 November found a 0.125-mm maximum and approximately 0.00346-mm
mean absolute difference from directly encoded one-hour APCP. This is input
encoding precision, not a change to V3.3. The adapter records both endpoint
receipts and packing quantums. Negative increments can become zero only within
the sum of the two endpoint quantization steps; larger decreases, missing
endpoints, missing cells or an unexpected grid reject the member. No missing
hour is represented as dry rainfall.

Native HRRR/RRFS grids must match. No rainfall interpolation is introduced.
The producer fails if the grid cannot share the existing 3-km neighborhood.
Each source record retains the model cycle, true forecast lead, interval,
encoded model identity, source URL, retrieval time, HTTP modification metadata,
received-byte hash and grid description. Whole-hour conversions retain both
parent endpoint receipts. Metadata includes hashes for every published PNG and
the shared FFG files; the manifest includes a hash for the complete metadata.

Official references:

- [NWS implementation notice](https://www.weather.gov/media/notification/pdf_2026/scn26-048_Updated_RRFS_and_REFS_Implementation.aaf.pdf)
- [NCO RRFS product inventory](https://www.nco.ncep.noaa.gov/pmb/products/rrfs/)
- [NCO subhourly APCP inventory](https://www.nco.ncep.noaa.gov/pmb/products/rrfs/rrfs.t06z.2dfld.3km.subh.f017.conus.grib2.shtml)

## Hourly publication and display

The existing `update_hrrr_tle.yml` workflow name and cron-job.org dispatch
endpoint are preserved. Its established hourly :20 trigger now starts the
HRRR job and independent RRFS and blended jobs. No duplicate GitHub native
schedule or new cron-job.org credential is needed. A push limited to these
producer files performs the initial build. The existing GDI workflow dependency
on the HRRR workflow name remains intact.

The hourly trigger is an availability check, not a promise that upstream f12
will be present at :20. A complete package keeps actual source cycles and
times. A failed new build leaves the live package intact. The display polls
the small manifests every three minutes, updates active layers automatically,
and hides expired packages. Only active new overlays are decoded during refresh
to avoid preloading another 40 high-resolution PNGs into browser memory.

All 20 maps in each suite are staged and verified together. A suite cannot
publish without six complete cycles per family, all source hours, correct
weights, consistent valid intervals, matching native grids, checksums, 6000 ×
3594 RGBA render geometry, 600 DPI and an unexpired 12-hour window.

## Storage and retention

The existing `pages-live` publisher creates a parentless current snapshot with
a force-with-lease against the restored tip, protecting concurrent product
writers. New RRFS products are added to the runtime ownership guard so source
sync cannot overwrite them. The original 512-MiB site safety cap remains; each
new suite also has a 32-MiB package cap. New maps never accumulate on main or
new recurring data branches. Raw/decoded model downloads are temporary runner
files. All flash-flood jobs avoid Actions model-data caches and artifacts.

The read-only 19:31Z audit found these distinct pools:

| Pool | Observed size | Interpretation |
|---|---:|---|
| Live Pages payload | 84.79 MiB | Well below the 512-MiB internal cap and 1-GiB Pages limit |
| GitHub-reported repository disk | 1.127 GiB | Includes server objects/history; not the live site size |
| Actions caches | 5.40 GiB | Separate from artifact storage; largest GDI cache about 4.79 GiB |
| Nonexpired Actions artifacts | 113.88 GiB | Existing uploads; 4,023 records inspected |
| Repeated RFC FFG artifacts | 101.26 GiB | 337 roughly 300-MiB uploads, the dominant growth source |

`review/rrfs-flash-flood/storage_audit_20261104.json` contains the observation.
The observation spans a changing repository; it is not an account billing or
bandwidth measurement. `tools/audit_repository_storage.py` can repeat the
read-only inventory.

The RFC FFG workflow now uploads provenance JSON only, retained two days.
Operational current/prior FFG scientific files remain on their existing data
branch, unchanged. This eliminates future duplicate raster/GRIB artifact
uploads; it does not retroactively delete existing artifacts. Existing older
uploads retain their original expiry. No bulk artifact deletion, branch
deletion or main-history rewrite is performed in this extension. GitHub
controls garbage collection of old unreachable snapshot objects, so bounded
branch ancestry does not guarantee immediate reduction in its reported disk
figure.

GitHub's [Pages limits](https://docs.github.com/en/pages/getting-started-with-github-pages/github-pages-limits)
and [Actions billing/storage documentation](https://docs.github.com/en/billing/concepts/product-billing/github-actions)
describe separate limits. The public API does not expose this account's billing
balance or all account-wide storage. This audit cannot certify zero risk of a
future account quota notice.

## Verification

- `python tools/test_flash_flood.py`: frozen 18-field regression, equal model
  weights, blend-before-threshold ordering, 4/6 run-change support, source
  completeness, subhourly endpoint identity, reset/packing rejection, palettes
  and runtime ownership.
- `node tools/test_flash_flood_display.cjs`: 40 unique new layer IDs/names,
  5/6/7 submenu grouping, count legends, automatic manifest refresh, retention
  after a failed replacement, active-image loading and expired-map hiding.
- `python tools/validate_dashboard.py`: existing menu/integration contract.
- Live 6-member RRFS and 12-member pooled builds plus the package validator.
- Browser review of menu layout, layer activation, valid times and legends.
