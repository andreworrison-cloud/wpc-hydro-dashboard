# Radar precipitation type

The radar menu has adjacent choices for existing RALA reflectivity and
experimental precipitation type & intensity. They are mutually exclusive, also
with the IEM backup radar, and share the existing playback engine. The type
choice is directly below RALA; no display selector is buried in the legend.
The type layer uses official NOAA GRIB2
data, not WeatherFront imagery or endpoints. Hail has no separate display class.

## Sources and interpretation

* MRMS `ReflectivityAtLowestAltitude_00.50`: observed echo coverage/intensity.
* MRMS `PrecipFlag_00.00`: precipitation support and a rain/snow fallback.
  The flag timestamp must be within two minutes of the radar frame. MRMS dry,
  missing, no-coverage and unrecognized flag values remain transparent.
* HRRR `wrfsfcf01`: `CRAIN`, `CSNOW`, `CICEP`, `CFRZR` at the surface. Use the
  one-hour forecast valid at or before the radar frame, no more than 90 minutes
  older. First try the frame's UTC hour, then the previous hour within that limit.
  This is a model estimate of phase, not an observed four-class MRMS product.
  Analysis-hour (`f00`) categorical fields can be all zero and are not used.

The HRRR fields are binary occurrence flags. Rain alone maps to rain; snow
alone to snow; sleet and/or freezing rain alone to ice. Coexisting phase families
(rain, snow, ice) map to mix. All four model fields must have valid binary values
at a pixel. Missing/invalid/all-zero model flags fall back to MRMS rain/snow.
MRMS flag 7 (rain mixed with hail), 91 and 96 (tropical rain combinations) are
rain fallback classes; they never independently imply wintry mix or ice.

The map explicitly identifies MRMS + HRRR, shows the HRRR valid time/one-hour
forecast, and reports a rain/snow fallback when present. Radar is nominally 1 km;
the model phase estimate is nominally 3 km. Categorical fields use nearest-neighbor
reprojection without smoothing or invented transition bands. Reflectivity below
5 dBZ stays transparent, consistent with the existing radar display. Brightness
shows 5-dBZ echo-strength bins and is not a snow/ice accumulation or rate estimate.
Version 2 supplies distinct fifteen-color intensity ramps per precipitation type.
Rain progresses through green/yellow/orange/red; snow, mix and ice retain separate
blue, purple and pink ramps. The legend uses the exact color arrays and thresholds
published by the renderer, from 5 through 75+ dBZ. Previous v1 images retain their
actual legacy brightness legend until a complete v2 archive is available.

## Operation

`fetch_mrms_winter_type.py` reads the newly built RALA manifest and writes one
`winter_frames_v2/` image per retained radar frame. Revision-specific paths prevent
old cached colors from appearing under the new legend. Timestamped NCEP MRMS flag files
and NOAA's public MRMS AWS inventory supply flag candidates. HRRR AWS is preferred,
with NOMADS fallback using that provider's own index/byte offsets. Each GRIB record
is checked for variable, level, grid, cycle, lead and validity time before use.

The existing cron-job.org dispatch of `update_mrms_rala.yml` also builds this
supplement; no additional schedule or credential is required. HRRR native fields
and projected phase are reused within a build. Validated prior winter images are
reused across runs, including checksums, dimensions, paths and source-time checks.

The supplement updates the manifest atomically only when every retained radar
frame has a usable image. The workflow treats supplement failure as optional and
still publishes validated reflectivity; the browser disables the unavailable type
choice. The original 2/4/6-hour windows, 10-minute sampling, speed, opacity and
20-minute freshness policy remain in effect. Images retain the existing
history-free `mrms-rala-data` publication architecture.

## Verification

Playback preloads the selected product/window on every activation, cancels
obsolete product warmers, and waits for image decoding before buffer swaps.
A single timer generation owns playback; speed changes and pause/restart cannot
start overlapping frame advances. Each displayed frame receives the full selected
hold interval, so a slow download does not cause a catch-up burst. Network and
decoding delays can still lengthen an interval before the cache is warm.

`node tools/test_radar_playback.cjs` checks asynchronous speed changes, restart
generations, slow-load frame holds and product-specific cache warming.

Run `python tools/test_winter_precip.py`,
`node tools/test_winter_precip_display.cjs`, the existing RALA selection self-test
and `python tools/validate_dashboard.py`. A live GRIB2 smoke build should additionally
check source-time metadata and visually inspect a native-resolution image.

Official references:

* https://www.nssl.noaa.gov/projects/mrms/operational/tables.php
* https://github.com/NOAA-National-Severe-Storms-Laboratory/mrms-support/blob/main/GRIB2_TABLES/UserTable_MRMS_PrecipFlags.csv
* https://www.nco.ncep.noaa.gov/pmb/products/hrrr/hrrr.t00z.wrfsfcf01.grib2.shtml
