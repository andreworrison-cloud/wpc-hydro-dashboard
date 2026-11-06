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
sum is first replaced by its neighborhood maximum using EMC's native 13-grid-cell
circle (39 km on the 3-km grid, conventionally labeled 40 km). That rainfall
maximum is compared with FFG **at the output center**. The fixed-member
probability is then smoothed using EMC's Gaussian settings: sigma 5 cells
(15 km), truncated to a square half-width of 8 cells (24 km). Smoothing occurs
at each eligible time/duration **before** taking the period maximum. Constant
hourly QPF thresholds use the same neighborhood and probability smoothing.

The initial SPC implementation instead compared local rainfall/FFG first,
then expanded those exceedances through 40 km without producer smoothing.
That is a different, valid experimental event-ANY statistic, but it was an
incorrect match to native OMD processing and exaggerated the footprint of
isolated low-FFG pockets in this dashboard comparison. It has been replaced
in schema v3. Standalone notebooks retain their separately defined statistics.

The implementation follows the published EMC source at commit
[081f905354e5](https://github.com/NOAA-EMC/HREF/tree/081f905354e512b854f9505f49938991658475fc/sorc/refs_ensprod.fd):
`sref_ens_gen.f` applies `neighborhood_max` to rainfall before the FFG
comparison and calls `Gsmoothing` before publication; `util.f` defines the
13-cell circle and Gaussian kernel. An exact row-filter decomposition avoids
a slow per-cell circular scan. Missing rainfall invalidates the affected
neighborhood/smoothing footprint. FFG no-data uses the producer's -10
smoothing sentinel, with negative outputs and missing FFG centers masked.

The native hourly reader and neighborhood operator derive from the verified
SPC Day 1 v0.2 notebook. The dashboard's explicit peak/cadence rules are shared
between both entry points in `cam_ensemble.py` and `cam_probability.py`.

AWS is primary: `noaa-hrrr-bdp-pds` for HRRR, `noaa-rrfs-ops-pds` for RRFS
members and OMD products. NOMADS production and parallel paths are backups;
the former REFS AWS v1 path remains a final producer-product fallback.
OMD products use indexed byte ranges when possible and bounded full GRIB
downloads otherwise. Quick discovery probes are separate from retried data
transfers, so an unfinished new cycle does not cause lengthy repeated downloads.

## Common official FFG cycle

**SPC REFS and OMD REFS must use the same official synoptic-cycle RFC FFG.**
For an 18Z ensemble cycle, SPC uses the official 18Z national 1-/3-/6-hour FFG
mosaic corresponding to the OMD 18Z producer cycle. The same rule applies at
00Z, 06Z and 12Z. The reference is the current suite cycle, including for the
older physical forecasts that constitute its time-lagged members.

Publication after model initialization is allowed: an official 18Z file posted
at 18:38Z is eligible for the 18Z suite. A 17Z file is not eligible. Requiring
publication before initialization was an error in the first dashboard
integration and has been removed.

Both the official archive filename timestamp and the encoded FFG reference
must equal the model cycle. A file labeled 18Z but encoded with an older
reference is rejected. Missing, mixed-cycle or unqualified official FFG
withholds the new package; there is no previous-hour, latest-available or
previous-cycle FFG substitution. An independently verified earlier *complete
suite* may remain visible until its own window expires, with its actual
initialization and matching official FFG cycle clearly displayed.

The exact official national mosaic is frozen per cycle and shared by both
dashboard scripts. Encoded 1-/3-/6-hour durations, units, positive depths, masks
and projection are checked. Spatial gaps stay missing. FFG is sampled onto the
native member grid by nearest neighbor. Individual RFC input issuance times
are not separately encoded in this national mosaic.

OMD retains its native producer probabilities under the official synoptic-cycle
FFG contract. The reader verifies the model initialization, time interval,
threshold, neighborhood-process identifier 194, REFS model identifier 136,
and 14-member probability metadata. OMD records state the required common FFG
cycle and explicitly identify it as the operational producer contract; the
native probability GRIB does not repeat the raw FFG input-file hash. SPC input
provenance records the downloaded official mosaic URL, encoded reference and
SHA256. We do not infer a different FFG baseline from that metadata limitation.

No extra neighborhood or Gaussian filter is applied to native OMD probabilities;
they already contain the producer processing described above. Negative PPFFG
values, including the producer's −10 no-coverage sentinel and intermediate
negative values, remain missing rather than becoming zero. Tiny GRIB packing
errors around 0/100 are bounded separately.

Schema v2 fixed the FFG timing rule; schema `wpc-spc-omd-cam-v3` additionally
requires the corrected producer probability method. The qualified FFG cache
`cycle-ffg-v2` and Actions cache keys `cam-native-v2-*` remain reusable because
the raw rainfall and correct cycle-matched FFG inputs are unchanged. Old FFG
arrays and v1/v2 output packages cannot pass v3 publication qualification.
Publication and frontend checks require both model cycles, the official FFG
snapshot, encoded reference, FFG model-cycle binding and common FFG reference
to agree. FFG legends identify the shared baseline, and every FFG time box
(including OMD and SuperEnsemble) displays the official common FFG cycle.

## SuperEnsemble and presentation

The blend is `0.5 * SPC maximum + 0.5 * OMD maximum` on identical native grids,
with matching initializations and absolute valid periods. Both finite values
are required at a cell. It is the same average-of-suite-maxima definition used
previously, not the maximum of hourly blended fields or a pooled 24-member
ensemble. The configurations share members and are not independent samples.

The original legend colors and boundaries (10/30/50/70/90/100%) are retained.
The PNG renderer now uses those exact five legend colors. Raw ten-member SPC
frequencies occur in 10-point increments. The published SPC probabilities,
OMD probabilities and blends can have intermediate values because probability
smoothing is part of the product calculation. Values below 10% and unavailable cells are transparent.
Output resolution remains 6000×3600 pixels in Web Mercator for Leaflet.

Menus, legend titles and time boxes identify SPC REFS (experimental), OMD REFS,
and the 50/50 SuperEnsemble. New image filenames prevent archived HREF images
from being relabeled as SPC. New metadata is required before images become
visible. Each nowcast expires independently, and valid times update with the
metadata rather than using only the hour-of-day from an old cycle.

Only one CAM probability raster is displayed at a time across the two nowcast
sections and Day 1 ERO CAMs. Selecting a new CAM field switches off the previous
CAM raster while preserving radar, hazard and other context layers. Stacking
the partly transparent SPC, OMD and SuperEnsemble images is not a numerical
blend: colors overlap and lower layers show through wherever the top image is
transparent. The legend explicitly identifies the below-10% transparency rule
and that the two suite maxima can occur at different times.

### 6 November 2026 12Z initial replay check and subsequent correction

The published 12Z packages were replayed from the exact archived source data:
120 member-hours and 24 OMD files for the nowcasts; 240 member-hours and 48 OMD
files for Day 1. Every input hash matched the published provenance. The common
official 12Z FFG file matched SHA256
`5cb6bfe457c3c9d45784b1ec0b1c8e396ecc9fc2eab5d02c087ba26d883b4690`.
At every grid cell and for all five fields in all three valid periods, the
SuperEnsemble was the exact arithmetic midpoint of its two finite inputs;
missing either suite left the blend unavailable. All 45 regenerated 6000×3600
PNGs were pixel-identical to the published files, with matching map bounds.
An independent literal disk-maximum and two-dimensional Gaussian calculation
at the two nowcast blend-peak locations also matched all five SPC fields in
all three periods within 0.00001 percentage point (30 point/field checks).
Those checks established reproducibility and arithmetic consistency with the
existing implementation, **not correctness of its FFG period masking**. The
initial conclusion was incomplete. The forecaster's three single-layer
screenshots subsequently identified a separate aggregation defect in southeast
Virginia/northeast North Carolina. Reproducing the same incorrect masks in a
second run did not validate those masks. The single-CAM selection rule prevents
overlay ambiguity but does not correct the defect described below.

### Schema v4: retain valid FFG peaks across unavailable slots

The v3 OMD reduction tracked whether **every** smoothed hour/duration field was
finite at each cell. A negative native PPFFG value is unavailable for that slot,
but the old final mask erased a valid positive peak from another slot. Near
36.6N, 76.6W in the 6 November 12Z +3–9-hour window, early 1-hour values were
about -1.5%, while f09 3-hour/6-hour values were 25.5%/19.0%. The old mask
discarded the valid 25.5% maximum and consequently withheld the blend.

Schema `wpc-spc-omd-cam-v4` and policy `maximum-of-finite-ffg-slots-v1` reduce
the FFG product over the finite, valid probabilities in the stated period.
Negative native values remain unavailable, **never zero**. A cell with no valid
slot remains missing. All required source files and every configured member/hour
are still mandatory; missing hourly rainfall continues to invalidate affected
SPC neighborhood/smoothing footprints. SPC now tracks that true missing-input
condition separately from a negative smoothed FFG no-data-edge value, allowing
a valid later SPC peak to survive the same situation. The common cycle-matched
FFG, fixed population, neighborhood, Gaussian, cadence, palettes and 50/50
arithmetic remain unchanged. The shared engine applies this correction to both
CAM Nowcasts and Day 1 ERO CAMs. Publication and presentation reject v3 packages
and packages without the corrected peak policy.

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

## Minnesota processing audit — 3 November 2026

The initial 18Z SPC Day 1/+9–15-hour fields reached 90% near 47.885N, 93.301W.
Independent reconstruction of all 180 member-hours identified the 03–09Z
4 November six-hour period. Nine of ten members exceeded isolated official
six-hour FFG values of 7–8 mm (about 0.28–0.31 inches) somewhere in the 40-km
circle, while no member exceeded the 2.72-inch FFG at the output center.
The raw 7-mm source value was confirmed with both GDAL and ecCodes.

Applying EMC's ordering and Gaussian kernel to the same ten members reduced
that cell to about 0.612%; the native 14-member OMD value for the same slot
was about 0.5%. The northern Minnesota envelope maximum for that six-hour
slot was about 12.56% for the corrected ten-member calculation versus about
13% in native OMD. These comparisons expose a processing mismatch, not stale
FFG, incorrect units, a changed denominator, or excessive six-hour rainfall.

## Validation

The original integration checks below established the precipitation and
rendering behavior. The FFG timing correction requires regenerated v2 packages;
a v1 run does not certify a corrected FFG baseline.

- Live 3 November 12Z run: 120/120 distinct physical member-hours for CAM;
  240/240 for the full Day 1. Every raw GRIB-message hash was unique.
- 30 CAM and 15 ERO overlays passed the new publication checks at 6000×3600.
- Regression checks cover the precipitation operators, native OMD decoder,
  exact official FFG cycle, publication after initialization, rejection of
  prior-hour/older-reference FFG, cache invalidation and all three time boxes.
  GitHub Actions runs these checks for the corrected source.
- Independent reconstruction from native hourly rainfall at four locations
  across all three periods matched all 12 location/window comparisons.
- Whole-field probability bounds, SPC 10-point quantization and equal-weight
  blend identities passed. The full 181-layer dashboard validator passed.
- Existing standalone v0.2 notebooks were not changed by this integration.

