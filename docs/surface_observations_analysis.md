# Surface observations and hourly analysis

The **Surface Observations & Analysis** section follows Radar and Satellite Data.
It provides nine mutually exclusive filled fields and a separate optional
**METAR Station Values (Zoom In)** checkbox. Temperature and dewpoint use °F;
wind speed and gust use knots; pressure uses hPa. All surface layers start off.

## Filled fields: NOAA RTMA

- Source: CONUS hourly RTMA `rtma2p5.tHHz.2dvaranl_ndfd.grb2_wexp`.
- Native inputs: 2-m temperature (`TMP`) and dewpoint (`DPT`), 10-m sustained wind
  speed (`WIND`), wind direction (`WDIR`), wind gust (`GUST`), and surface pressure
  (`PRES`, surface level). GRIB discipline/category/parameter number, units and
  level are validated. MSLP is not substituted for surface pressure.
- Nominal native spacing: 2.5 km (actual grid increment 2539.703 m); 2345 × 1597
  Lambert conformal grid. This is an observation-assimilating surface analysis
  with a model background, not a measurement at every pixel or a forecast.
- Units convert K → °F, m/s → kt, Pa → hPa. Missing and implausible values remain
  missing. Native gust analyses are not labeled hourly maximum gusts.
- Scalar fields undergo bilinear reprojection to EPSG:3857 before colorization.
  The 3600 × 2024 image covers 24–50°N, 125–66°W. Display pixels do not increase
  scientific resolution; unsupported edges remain transparent. Palettes have
  continuous linear RGB interpolation with clamped endpoint colors. Legend
  gradients use the exact product palette and show the endpoint tails.
- Wind direction uses separately reprojected sine/cosine components and an
  `atan2` reconstruction, rather than scalar averaging of degrees. Directions
  are meteorological **from**, relative to true north. Northerly 359°/1° values
  interpolate through 0°, not 180°. Near-opposite unresolved vectors and winds
  below 1 kt are transparent. The cyclic palette and compass legend meet at north.
- Surface pressure is actual pressure at the model terrain surface. Its strong
  terrain dependence is labeled explicitly; it is not mean-sea-level pressure.
- Newest nonfuture, complete hour is selected from a bounded four-hour search,
  including the previous UTC day. NOAA NODD/AWS is preferred, with NOMADS fallback
  at the same hour before stepping back. Each provider's own `.idx` byte offsets
  are used. HTTP 206/content range, GRIB framing/length, parameter, height, units,
  analysis lead, source/valid time and common native grid are checked.
- All six native inputs and all nine display fields publish together. No valid-time regression is accepted.
  The analysis age warning begins at 150 minutes; images hide at 240 minutes.

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
- Station values are optional and appear at Leaflet zoom 7 and above. The
  default **Follow selected analysis** mode determines the point variable. A
  persistent legend selector can independently choose temperature, dewpoint,
  wind speed/direction/gust, calculated RH/heat index/wind chill, or reported MSLP.
  Direction points show compass names with exact degrees available in titles and
  popups. Calm/variable reports do not invent a direction; absent gusts stay absent.
- Reported MSLP comes only from AWC `sea_level_pressure_mb` (numerically hPa).
  Altimeter settings are not relabeled as MSLP or station pressure. The feed
  does not report actual surface pressure: following that fill shows an explicit
  message and offers **Reported MSLP** as a separate station choice. The fill and
  station headings always identify their quantities separately.
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

## Updating and publication

`update_surface_analysis.yml` is reusable and callable manually. The existing
`update_rap.yml` dispatch calls it as an independent job, so it shares the
existing cron-job.org hourly trigger without a new scheduler or dependency on
RAP success. Source changes also trigger one build on main for initialization.

The parentless `surface-data` branch holds `surface_publish/metadata.json`,
immutable generation images and immutable station JSON packages. The existing
bounded snapshot publisher uses a lease to protect concurrent writes. Main and
Pages hold source code, not operational surface data. Three asset generations
are retained for cached readers. Backend validation checks all referenced asset
checksums and image sizes before atomically replacing metadata. Frontend fetches
and decodes selected images, checks SHA-256 and dimensions, and retains an older
validated image with its own valid time on failure. Images load only on demand.
Each component can retain its previous usable data if its upstream source fails.
The v2 renderer rebuilds a complete nine-product suite even at the same valid hour
as a restored v1 three-product package. Restoring or retaining v1 is supported
when expansion inputs fail. The new browser accepts both formats and identifies
new fields as waiting until a complete expanded generation is available.

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
Expanded checks cover reference formula values and domain boundaries, actual
359°/1° circular reprojection, calm/variable winds, pressure-unit conversion,
reported MSLP versus altimeter settings, legacy retention, post-render report
ages, nine-field switching and the independent station selector.

Sources:

- https://www.emc.ncep.noaa.gov/emc/pages/numerical_forecast_systems/rtma.php
- https://www.nco.ncep.noaa.gov/pmb/products/rtma/
- https://registry.opendata.aws/noaa-rtma/
- https://aviationweather.gov/data/api/
- https://qed.epa.gov/hms/meteorology/humidity/algorithms/
- https://www.wpc.ncep.noaa.gov/html/heatindex_equation.shtml
- https://www.ncl.ucar.edu/Document/Functions/Heat_stress/heat_index_nws.shtml
- https://www.weather.gov/safety/cold-wind-chill-chart
