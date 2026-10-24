# Surface observations and hourly analysis

The **Surface Observations & Analysis** section follows Radar and Satellite Data.
It provides three mutually exclusive filled fields and a separate optional
**METAR Station Values (Zoom In)** checkbox. Temperature and dewpoint use °F;
wind speed uses knots. All surface layers start off.

## Filled fields: NOAA RTMA

- Source: CONUS hourly RTMA `rtma2p5.tHHz.2dvaranl_ndfd.grb2_wexp`.
- 2-m temperature (`TMP`) and dewpoint (`DPT`); 10-m sustained wind speed (`WIND`).
- Nominal native spacing: 2.5 km (actual grid increment 2539.703 m); 2345 × 1597
  Lambert conformal grid. This is an observation-assimilating surface analysis
  with a model background, not a measurement at every pixel or a forecast.
- Units convert K → °F and m/s → kt. Missing and implausible source values remain
  missing; wind speeds are not wind gusts.
- Scalar fields undergo bilinear reprojection to EPSG:3857 before colorization.
  The 3600 × 2024 image covers 24–50°N, 125–66°W. Display pixels do not increase
  scientific resolution; unsupported edges remain transparent. Palettes have
  continuous linear RGB interpolation with clamped endpoint colors. Legend
  gradients use the exact product palette and show the endpoint tails.
- Newest nonfuture, complete hour is selected from a bounded four-hour search,
  including the previous UTC day. NOAA NODD/AWS is preferred, with NOMADS fallback
  at the same hour before stepping back. Each provider's own `.idx` byte offsets
  are used. HTTP 206/content range, GRIB framing/length, parameter, height, units,
  analysis lead, source/valid time and common native grid are checked.
- All three fields publish together. No valid-time regression is accepted.
  The analysis age warning begins at 150 minutes; images hide at 240 minutes.

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
  currently selected fill determines the point variable; when viewing only
  stations, a legend selector chooses temperature, dewpoint or wind speed.
- Points carry their actual report times, independent of RTMA time. Popups show
  ID, observation UTC time, age, temperature, dewpoint, wind/gust, wind direction
  when reported, and the escaped raw report. Screen-space collision checks choose
  newer reports first to limit label overlap; more sites appear as users zoom.
  Markers and open popups survive map auto-pan and periodic age updates while
  their reports remain fresh; stale reports still disappear at the age limit.
- Every 30 seconds the browser reevaluates source and individual station ages,
  even if no newer package has arrived. It never keeps old points visible just
  because the package was recently retrieved.

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

Sources:

- https://www.emc.ncep.noaa.gov/emc/pages/numerical_forecast_systems/rtma.php
- https://www.nco.ncep.noaa.gov/pmb/products/rtma/
- https://registry.opendata.aws/noaa-rtma/
- https://aviationweather.gov/data/api/
