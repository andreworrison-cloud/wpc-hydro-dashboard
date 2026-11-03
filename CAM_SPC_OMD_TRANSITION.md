# SPC / OMD REFS dashboard transition — 3 November 2026

The CAM Nowcasts and Day 1 ERO CAMs replace retired HREF guidance with WPC
experimental probabilities calculated from the ten-member SPC REFS
configuration. The existing native REFS producer probability products remain
available as **OMD REFS**. **SuperEnsemble** assigns 50% to each suite's maximum.

## Fields and windows

Each of the three perspectives has five fields: maximum hourly neighborhood
probability of QPF **>0.5, >1, >2, and >3 inches**, and maximum neighborhood
probability of exceeding matching **1-, 3-, or 6-hour FFG**.

| Reference cycle | Day 1 period | Hourly QPF endpoints |
|---|---|---|
| 00Z | 12Z–12Z next day | f13–f36 |
| 06Z | 12Z–12Z next day | f07–f30 |
| 12Z | 12Z–12Z next day | f01–f24 |
| 18Z | 18Z–12Z next day | f01–f18 |

The nowcasts retain initialization-relative +3–9 h and +9–15 h periods, using
hourly endpoints f04–f09 and f10–f15. Every accumulation must fit completely
inside its stated period. No preceding rainfall is imported across a boundary.

Both suites use the dashboard's existing product cadence: 1-hour FFG hourly,
and 3-/6-hour FFG at forecast hours divisible by three. Thus a full Day 1 has
24 one-hour, 8 three-hour and 7 six-hour comparisons; the 18Z update has 18, 6
and 5. Each six-hour nowcast has 6, 2 and 1. This differs deliberately from the
standalone notebook's additional hourly sliding 3-/6-hour windows.

These maps show a **peak rolling probability**, computed by taking maxima of
the duration-specific member frequencies over eligible times. They do not
combine the identities of different members into an event-anytime probability.
The standalone notebook offers that different event-union diagnostic separately.

## SPC calculation and data sources

The roster is HRRR current/−6/−12 hours; RRFS control current/−6/−12 hours;
and current REFS M01/M02/M03/M05. All ten members have equal weights. Each
physical forecast's initialization and native lead are checked against its
required valid hour. Missing members are never dropped from the denominator.

Only exact one-hour APCP GRIB records are retrieved. Native 3-km grids must
match; rainfall is not interpolated. For FFG, each member's 1/3/6-hour rainfall
sum is compared with the corresponding **local** numerical FFG first. A single
nominal 40-km circular neighborhood ANY operation follows that comparison, then
members are counted. No second neighborhood or additional smoothing is applied.

The native hourly reader and neighborhood operator derive from the verified
SPC Day 1 v0.2 notebook. The dashboard's explicit peak/cadence rules are shared
between both entry points in `cam_ensemble.py` and `cam_probability.py`.

AWS is primary: `noaa-hrrr-bdp-pds` for HRRR, `noaa-rrfs-ops-pds` for RRFS
members and OMD products. NOMADS production and parallel paths are backups;
the former REFS AWS v1 path remains a final producer-product fallback.
OMD products use indexed byte ranges when possible and bounded full GRIB
downloads otherwise. Quick discovery probes are separate from retried data
transfers, so an unfinished new cycle does not cause lengthy repeated downloads.

## FFG timing and native OMD qualification

SPC uses one official WPC numerical FFG mosaic **demonstrably published by
the model initialization**, frozen for that cycle and shared between the two
scripts. Filename timestamps alone are insufficient. Publication must not be
later than initialization; at initialization, snapshot age must be <3 h and
encoded reference age <9 h. Durations, units, depths, masks and projection are
checked. FFG is sampled onto the native member grid by nearest neighbor.

For example, the 3 November 12Z snapshot was posted at 12:38Z. It is ineligible
for an as-of-12Z calculation; the 11Z snapshot posted at 11:38Z is eligible.
Re-running the same cycle does not replace that baseline with newer FFG.

OMD retains **native producer** probabilities. The reader verifies the cycle,
time interval, threshold, neighborhood-process identifier 194, REFS model
identifier 136, and 14-member probability metadata. It applies no additional
neighborhood. Negative native PPFFG values, including the producer's −10
no-coverage sentinel and intermediate negative values, remain missing rather
than becoming zero. Tiny GRIB packing errors around 0/100 are bounded separately.

The native OMD GRIB does **not** identify the exact source FFG mosaic. Its
internal producer postprocessing is retained. Therefore the two displayed
FFG perspectives share window, threshold-duration and maximum definitions,
but they are **not a controlled roster-only experiment with a certified
identical FFG snapshot and postprocessing kernel**. The metadata and FFG legend
state the distinction. No claim of identical internal SPC/NCEP processing is made.

## SuperEnsemble and presentation

The blend is `0.5 * SPC maximum + 0.5 * OMD maximum` on identical native grids,
with matching initializations and absolute valid periods. Both finite values
are required at a cell. It is the same average-of-suite-maxima definition used
previously, not the maximum of hourly blended fields or a pooled 24-member
ensemble. The configurations share members and are not independent samples.

The original legend colors and boundaries (10/30/50/70/90/100%) are retained.
The PNG renderer now uses those exact five legend colors. Ten-member SPC
frequencies occur in 10-point increments; OMD and blended fields can have
intermediate values. Values below 10% and unavailable cells are transparent.
Output resolution remains 6000×3600 pixels in Web Mercator for Leaflet.

Menus, legend titles and time boxes identify SPC REFS (experimental), OMD REFS,
and the 50/50 SuperEnsemble. New image filenames prevent archived HREF images
from being relabeled as SPC. New metadata is required before images become
visible. Each nowcast expires independently, and valid times update with the
metadata rather than using only the hour-of-day from an old cycle.

## Publication and bounded storage

Existing workflow filenames and cron-job.org dispatch targets are preserved.
Source changes also trigger a refresh; no duplicate periodic schedules were
added. Both scripts use the same checked engine and publication validator.

The workflows retain a usable verified package after a transient upstream
failure, subject to independent completeness and expiry checks. All required
member-hours and producer slots must exist for a new package. Every PNG and
source manifest has a content hash to reject mixed or changed generations.

Generated products use the existing history-free `pages-live` snapshot
publisher. Raw grids remain in Actions caches, bounded to the current verified
suite before saving, with at most one immutable cache key per product/cycle.
They are not committed to the durable source branch. Metadata records exact
source URLs, native forecast hours, hashes, cache use, and the FFG snapshot.

## Validation

- Live 3 November 12Z run: 120/120 distinct physical member-hours for CAM;
  240/240 for the full Day 1. Every raw GRIB-message hash was unique.
- 30 CAM and 15 ERO overlays passed the new publication checks at 6000×3600.
- 20 scientific/decoder regression tests and 10 presentation checks passed.
- Independent reconstruction from native hourly rainfall at four locations
  across all three periods matched all 12 location/window comparisons.
- Whole-field probability bounds, SPC 10-point quantization and equal-weight
  blend identities passed. The full 181-layer dashboard validator passed.
- Existing standalone v0.2 notebooks were not changed by this integration.
