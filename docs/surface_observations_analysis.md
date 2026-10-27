# Surface observations and hourly analysis

The **Surface Observations & Analysis** section follows Radar and Satellite Data.
It provides seven mutually exclusive map choices covering eight filled fields.
**Surface Wind** combines sustained-speed/gust shading and observed wind barbs
in one menu item. **METAR Station Values** is an independent optional checkbox
that works at national scale and becomes denser as users zoom. Temperature and dewpoint use °F;
wind speed and gust use knots; pressure uses hPa. All surface layers start off.

## Filled fields: NOAA RTMA

- Source: CONUS hourly RTMA `rtma2p5.tHHz.2dvaranl_ndfd.grb2_wexp`.
- Native inputs: 2-m temperature (`TMP`) and dewpoint (`DPT`), 10-m sustained wind
  speed (`WIND`) and wind gust (`GUST`). GRIB discipline/category/parameter number,
  units and level are validated. RTMA direction and terrain pressure fills have
  been replaced by observed barbs and a separate sea-level-pressure analysis.
- Nominal native spacing: 2.5 km (actual grid increment 2539.703 m); 2345 × 1597
  Lambert conformal grid. This is an observation-assimilating surface analysis
  with a model background, not a measurement at every pixel or a forecast.
- Units convert K → °F and m/s → kt. Missing and implausible values remain
  missing. Native gust analyses are not labeled hourly maximum gusts.
- Scalar fields undergo bilinear reprojection to EPSG:3857 before colorization.
  The 3600 × 2024 image covers 24–50°N, 125–66°W. Display pixels do not increase
  scientific resolution; unsupported edges remain transparent. Palettes have
  continuous linear RGB interpolation with clamped endpoint colors. Legend
  gradients use the exact product palette and show the endpoint tails.
- Saturated, fixed physical color scales replace the pastel palettes. The same
  palette colors the fill, station dots and legend; scales do not normalize to
  the current frame. Default fill opacity is 93%.
- Newest nonfuture, complete hour is selected from a bounded four-hour search,
  including the previous UTC day. NOAA NODD/AWS is preferred, with NOMADS fallback
  at the same hour before stepping back. Each provider's own `.idx` byte offsets
  are used. HTTP 206/content range, GRIB framing/length, parameter, height, units,
  analysis lead, source/valid time and common native grid are checked.
- Four native inputs and seven RTMA display fields publish together. No valid-time regression is accepted.
  The analysis age warning begins at 150 minutes; images hide at 240 minutes.

## Barometric pressure: hourly HRRR + METAR objective analysis

- **Barometric Pressure (MSLP)** uses native HRRR CONUS f00 `MSLMA` (MAPS
  sea-level reduction) as its background. It compares pressure across elevations;
  neither terrain-surface `PRES` nor aviation altimeter setting is substituted.
- Source: `hrrr.YYYYMMDD/conus/hrrr.tHHz.wrfsfcf00.grib2`, nominal 3-km native
  grid (1799 × 1059). GRIB identity, units, zero lead, valid hour and native grid
  are checked. NODD/AWS is preferred; NOMADS is the fallback.
- Only METAR **reported sea-level pressure** contributes corrections. Reports
  must be no more than 90 minutes old at construction and within ±60 minutes of
  the HRRR valid hour. One latest report per station is used. Innovations are
  reported MSLP minus bilinearly sampled HRRR background, in hPa.
- Reject innovations exceeding 12 hPa; with at least three neighbors within
  150 km, reject deviations over 4 hPa from their median innovation. These
  conservative checks may exclude a genuine sharp mesoscale anomaly.
- Smooth increments use Gaussian distance weights (sigma 80 km, continuous
  cutoff at 240 km), Gaussian time weights (sigma 30 minutes), and inverse
  station density within 50 km. Analysis = background + sum(w × innovation) /
  (sum(w) + 0.5), with corrections bounded to ±6 hPa. Thus sparse areas revert
  smoothly to HRRR; there is no fixed nationwide 50/50 blend.
- The final field is smoothed with native-grid Gaussian sigma 18 km. The fill,
  numeric cursor samples and 4-hPa isobars share that field. Missing source cells
  remain missing. HRRR may already assimilate some observations; this dashboard
  adjustment is **not** an independent optimal assimilation or an official WPC
  surface analysis. Sea-level reduction artifacts can remain over high terrain.
- A completed observation-adjusted hour is immutable. A background-only hour
  can be rebuilt when observations become available. Metadata records accepted
  station IDs/times, input checksums, method and maximum correction. The legend
  explicitly distinguishes observation-adjusted and HRRR-only fallback fields.
- H/L symbols come from the **same closed 4-hPa contours** used for display.
  Innermost closed loops locate the enclosed maximum/minimum; nested isobars
  share a center. Distinct nearby systems are not removed by a 300-km ring test
  or 500-km suppression. Open lines, flat fields and loops containing missing
  grid data cannot certify a center. Symbol central values use the contour
  sampling grid (every fourth display pixel) and are rounded to whole hPa.
- Pressure retains independent valid time, failure status and 150/240-minute
  aging/hiding. Source failure retains the previous validated field. METAR
  point labels remain actual reports with their own timestamps.

## Derived analysis fields

Calculations use the same-hour temperature/dewpoint/wind fields after scalar
reprojection, so the displayed applicability mask is evaluated at the display
pixel. This is display processing of the native 2.5-km analysis, not added
scientific resolution. The same formulas calculate station-derived values from
each individual report's inputs before rounding for presentation.

- **Relative humidity:** August-Roche-Magnus liquid-water RH,
  `100 exp(17.625 Td/(243.04+Td) - 17.625 T/(243.04+T))`, with Celsius T/Td.
  Reject invalid inputs and dewpoints >T+0.5°C; small accepted supersaturation is
  bounded at 100%. The source and legend state RH relative to liquid water.
- **Heat index:** NWS/WPC preliminary Steadman estimate
  `0.5 [T+61+1.2(T-68)+0.094 RH]`, averaged with T. Only when that average is
  ≥80°F is the full Rothfusz regression displayed, including the documented
  low-humidity subtraction and high-humidity addition. Cooler conditions are
  transparent, not replaced with air temperature. This is the shade/light-wind
  heat index, not a solar-radiation exposure index.
- **Wind chill:** NWS `35.74+0.6215 T-35.75 V^0.16+0.4275 T V^0.16`, with Fahrenheit
  T and sustained wind V in mph. Show only for T≤50°F and V>3 mph. Gusts are not
  used, and there is no second height adjustment to the standard 10-m wind input.
- All-missing heat-index or wind-chill images are valid when no locations meet
  their domain criteria. Product-specific applicability counts and legend notes
  distinguish those transparent areas from loading failures.

## Points: actual METAR/SPECI observations

The backend downloads AWC's recommended bulk cache once per update. Browsers
read the published package, avoiding AWC's cross-origin API restriction.
These points do not interpolate the fill or supply artificial additional sites.

- Retain the newest real METAR/SPECI report per station in the displayed CONUS
  bounds. Exclude invalid coordinates, future reports, reports over 90 minutes
  old and stations with no usable temperature, dewpoint or wind speed.
- Independent field sanity checks preserve valid zero values and exclude
  impossible fields. Dewpoint exceeding temperature by more than 0.5°C is
  excluded; missing fields remain missing. This is basic ingest checking,
  not a claim that the dashboard independently performs full observing-system QC.
- Station values are optional and appear at every zoom. The
  default **Follow selected analysis** mode determines the point variable. A
  persistent legend selector can independently choose temperature, dewpoint,
  a combined wind value, calculated RH/heat index/wind chill, or reported MSLP.
  Wind values combine compass direction, sustained knots and reported gusts
  (for example `NE 12 G20`). Exact degrees are available in
  popups. Calm/variable reports do not invent a direction; absent gusts stay absent.
- Reported MSLP comes only from AWC `sea_level_pressure_mb` (numerically hPa).
  Altimeter settings are not relabeled as MSLP or station pressure. The fill and
  station headings identify the gridded analysis and actual reported quantity.
- Points carry their actual report times, independent of RTMA time. Popups show
  ID, observation UTC time, age, temperature, dewpoint, wind/gust, direction and
  MSLP when reported, calculated humidity/heat index/wind chill, and the escaped
  raw report. Calculated values are labeled separately. Screen-space collision checks choose
  newer reports first to limit label overlap; more sites appear as users zoom.
  Markers and open popups survive map auto-pan and periodic age updates while
  their reports remain fresh; stale reports still disappear at the age limit.
- Every 30 seconds the browser reevaluates source and individual station ages,
  even if no newer package has arrived. It never keeps old points visible just
  because the package was recently retrieved.
- The retrieval clock is captured after analysis rendering. A new report arriving
  while maps are rendering is not rejected against an obsolete processing-start
  clock. Truly future reports remain rejected.

## Wind barbs: observed, independent of shading

- **Surface Wind** is one map checkbox. Its legend selects sustained-speed or
  gust shading, with an independent **Wind barbs** checkbox in that same control.
  Barbs default on and stay on when switching shading. Removing Surface Wind
  removes its fill and barbs together. Numeric station values remain optional.
  Barbs use each station's reported sustained speed and true-north
  **from** direction, not the gust value or a model wind interpolated to a station.
- The shaft points toward the direction wind comes from. A half feather is 5 kt,
  full feather 10 kt, triangle 50 kt; speed rounds to the nearest 5 kt. Explicit
  calm reports use a circle; light nonzero reports retain their direction even
  if rounding leaves a bare shaft. Missing/variable directions are not invented.
- Barbs appear at national scale, with screen-space thinning in both dimensions.
  More stations appear naturally as users zoom. White halos and dark strokes
  preserve contrast over either fill and the map. Numeric station labels move
  below the station anchor while barbs are enabled.
- The same 90-minute report-age limit applies to barbs. Clicking opens the actual
  report's time, wind, gust and raw METAR. Open barb popups and marker identities
  survive map movement and routine refresh while fresh.

## Vector contours and labels

- Every new filled product publishes a checksum-verified GeoJSON sidecar tied to
  that exact generation, field, unit and valid time. Isobars are always 4 hPa
  apart, anchored at 1000 hPa. Temperature/dewpoint/wind chill use 10°F intervals;
  temperature also includes the 32°F isotherm. Wind speed/gust use 10 kt, RH 10%,
  and heat index 5°F. At national scale, alternate nonpressure contours are
  omitted to reduce clutter; zooming reveals all intervals.
- Other than the already smoothed pressure field, contour computation lightly
  smooths a sampled display grid (sigma 1.25 cells at a four-display-pixel stride).
  RTMA fills and station values keep their source detail. Contours stop at missing
  support, including heat-index/wind-chill applicability masks; no bridging of
  missing corridors. Display-space line simplification uses 1.1-km Mercator
  tolerance and does not change contour values.
- Contours have a white halo and dark stroke. Labels follow visible line segments,
  align to their local direction, and use screen-space collision checks against
  other labels and station values. Pressure labels are available nationally;
  other labels appear from zoom 5. More labels become available in a smaller
  geographic region as users zoom. H/L symbols take priority over numeric points.
- The legend's **Contours** checkbox (pressure: **Isobars & H/L**) hides vectors
  independently of the fill and METAR values. Sidecar loading/failure does not
  delay or hide a verified fill, and contours from another time are never paired
  with it. Failed sidecars retry independently.

## Updating and publication

`update_surface_analysis.yml` is reusable and callable manually. The existing
`update_rap.yml` dispatch calls it as an independent job, so it shares the
existing cron-job.org hourly trigger without a new scheduler or dependency on
RAP success. Source changes also trigger one build on main for initialization.

The parentless `surface-data` branch holds `surface_publish/metadata.json`,
immutable RTMA `generations/`, HRRR `pressure/` images and immutable station JSON packages. The existing
bounded snapshot publisher uses a lease to protect concurrent writes. Main and
Pages hold source code, not operational surface data. Three asset generations
per component are retained for cached readers. Backend validation checks all referenced asset
checksums and image sizes before atomically replacing metadata. Frontend fetches
and decodes selected images, checks SHA-256 and dimensions, and retains an older
validated image with its own valid time on failure. Images load only on demand.
Each component can retain its previous usable data if its upstream source fails.
The v4 RTMA renderer rebuilds the seven retained fields even at the same valid
hour as a restored v1/v2 package. Backend and browser accept legacy packages
during migration. Legacy terrain pressure is never used as the new MSLP fill,
and the direction raster is no longer exposed as a layer. Pressure initializes
independently as its own `hrrr-mslp-v2` component. The new revisions require
their contour sidecars. Restored v1/v2/v3 RTMA and v1 pressure packages remain
readable during migration, with a clear updating message for absent vectors.

Browser metadata checks run every five minutes while a surface layer is selected.
The UI is a latest-hour view; there is no surface animation or historical station
matching to the radar loop in this first implementation.

## Verification

`python tools/test_surface_analysis.py` checks physical units, palettes and
missing values, METAR report selection/QC, provider-specific inventory offsets,
UTC midnight fallback, non-regression, retention and corruption detection.
`node tools/test_surface_layer.cjs` checks both time cutoffs, palette agreement,
point thinning, safe paths, popup escaping and the actual adapter's decoded
image/station lifecycle. Dashboard and radar regression checks remain in CI.
Expanded checks cover reference formula values and domain boundaries, scalar
pressure reprojection, calm/variable winds, pressure-unit conversion,
reported MSLP versus altimeter settings, legacy retention, post-render report
ages, eight-field switching, pressure-source rejection and independent retention,
barb geometry/orientation and 5/10/50-kt symbols, overlay independence and the station selector.
`python tools/test_surface_contours.py` uses analytic gradients, closed highs/lows,
open ridges, missing rings and corridors to check 4-mb contours, masking, center
selection and field/time/coordinate validation. `node tools/test_surface_cartography.cjs`
checks viewport clipping, labels, zoom intervals, collisions and sidecar identity.
Adapter checks cover consolidated wind controls, national station visibility,
contour failure/recovery and source-independent expiry.

Sources:

- https://www.emc.ncep.noaa.gov/emc/pages/numerical_forecast_systems/rtma.php
- https://www.nco.ncep.noaa.gov/pmb/products/rtma/
- https://registry.opendata.aws/noaa-rtma/
- https://www.nco.ncep.noaa.gov/pmb/products/hrrr/hrrr.t00z.wrfsfcf00.grib2.shtml
- https://registry.opendata.aws/noaa-hrrr-pds/
- https://www.weather.gov/bou/pressure_definitions
- https://www.noaa.gov/jetstream/analyze-appair-pressure-map
- https://contourpy.readthedocs.io/en/v1.3.3/api/contourpy/contour_generator.html
- https://aviationweather.gov/data/api/
- https://qed.epa.gov/hms/meteorology/humidity/algorithms/
- https://www.wpc.ncep.noaa.gov/html/heatindex_equation.shtml
- https://www.ncl.ucar.edu/Document/Functions/Heat_stress/heat_index_nws.shtml
- https://www.weather.gov/safety/cold-wind-chill-chart


## Optional numeric analysis sampling

The surface legend's **Sample analysis** checkbox enables hover readouts and click-to-pin sampling. Click elsewhere to move the pin; **Clear pin** or Escape releases it. METAR values and observed wind barbs remain independent. A pinned location follows field changes and refreshed analyses, with its displayed field and valid time updated together. Deselected or expired fills hide the readout.

RTMA v5 and HRRR MSLP v3 publish immutable, checksum-verified `*_samples.bin.gz` files alongside each image and contour sidecar. They contain the exact scalar display grid before colorization (including the pressure smoothing), quantized to 0.1 of the displayed unit using signed little-endian 16-bit integers, with a reserved missing value. Maximum quantization error is 0.05 unit. A length-prefixed JSON header binds field, units, time, dimensions, bounds and EPSG:3857 projection to the displayed analysis. Browser decompression is size-limited, and every identity is checked before use. Sampling is bilinear in projected pixel-center coordinates; contributing missing cells produce an unavailable readout, rather than interpolation across a hole. Requests use the loaded fill's generation, including when the previous image is retained. Sampling failures do not hide the fill.

Only the selected field is downloaded on opt-in; decoding and values are cached with the existing bounded image cache. Legacy packages show that numeric grids are updating. Browsers without gzip decompression show sampling unavailable while retaining the map. Sampling does not add spatial resolution beyond RTMA's 2.5 km or HRRR's 3 km source analysis.

Heat index remains limited to the NWS preliminary averaged Steadman screen of at least 80°F. Wind chill requires temperature at or below 50°F and sustained wind above 3 mph; gusts are not used. Neither uses a terrain mask. Transparent cells expose the dark basemap and can mean either nonapplicable conditions or missing source inputs. The readout and legend explain this distinction without replacing these cells with air temperature or zero.

### Pressure objective-analysis revision

`hrrr-metar-mslp-v4` adds observation diagnostics and requires both numeric and
contour sidecars. Earlier HRRR-only generations remain readable during rollout.
The hourly publisher retrieves METARs before constructing the pressure field;
station display freshness remains independent.
