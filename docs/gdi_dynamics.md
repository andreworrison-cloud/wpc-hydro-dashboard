# GDI + Dynamics: RAP and CAM companions

This delivery combines the existing José notebook GFS-baseline GDI with separately
calculated meteorological diagnostics. It does not modify, rescale, smooth, or
replace GDI. It implements an ingredients display in the spirit of the WPC
International Desk's [GDI and Dynamics description](https://www.wpc.ncep.noaa.gov/international/wng/CAR/index.shtml).
It is not a reproduction of an undocumented numerical EGDI enhancement.

## Diagnostics

| Overlay | Calculation and displayed units |
| --- | --- |
| Moisture convergence | Pressure-weighted mean of levelwise `-div(r V)` at 950/900/850/700 hPa; g kg⁻¹ h⁻¹. Positive contours green; negative moisture divergence brown and dashed. |
| Upper divergence | Pressure-weighted mean of wind divergence at 400/300/200 hPa; 10⁻⁵ s⁻¹. Positive contours gold; negative convergence blue and dashed. |
| Upper humidity | Mean RH at 400/300 hPa; percent. Pink labeled contours. |
| Precipitable water | Model total-column PWAT, kg m⁻² converted to inches by dividing by 25.4. Cyan labeled contours. |
| Low-level flow | Pressure-weighted mean earth-relative wind at 1000/950/900/850 hPa; knots. White barbs for speeds ≥10 kt. |
| Upper-level flow | Pressure-weighted mean earth-relative wind at 400/300/200 hPa; knots. Blue barbs for speeds ≥10 kt. |

Scalar contour levels and colors are fixed in `dynamics_contract.py` and verified
by both publisher and client. Moisture-convergence magnitudes are 1/2/4/8
g kg⁻¹ h⁻¹; upper-divergence magnitudes are 2/4/8/12 ×10⁻⁵ s⁻¹.
These are display intervals, not thresholds defining a heavy-rain or flood probability.

RH-to-specific-humidity conversion uses the same Bolton liquid-water saturation
expression as the GDI adapter. The moisture flux uses mixing ratio `r=q/(1-q)`.
Direct model RH is preferred for the upper-humidity diagnostic; a provider may
instead supply q with temperature, which is converted using the inverse expression.

## Derivatives, filtering, and terrain

The native RAP latitude/longitude Jacobian determines horizontal derivatives.
GRIB grid-relative winds are rotated into earth-relative east/north components
using the native orthogonal grid axes and scan-direction flags. Spherical
divergence includes the meridional metric term; treating grid-relative winds as
earth-relative or omitting map geometry is not permitted.

Moisture fluxes and winds are filtered before differentiation. RH and PW receive
the same diagnostic filter. Its Gaussian sigma is **20 km in native projected
coordinates**, so its ground footprint varies with the Lambert map scale. It is
not 20 km of exact geodesic radius and not a 20-km neighborhood exceedance product.
Filtering requires 80% finite kernel support and a valid center. This filter is
limited to companion diagnostics; native GDI is unchanged.

Below-ground winds and moisture are masked before filtering and differentiation.
Pressure averages use trapezoidal weights over complete adjacent above-ground
segments; missing levels are never bridged. Moisture convergence requires at
least 100 hPa of supported layer and low-level flow at least 50 hPa. Upper
divergence/flow require the full 200 hPa layer, and upper humidity the full 100 hPa
layer. Limited terrain support can hide a companion overlay without hiding GDI.
The depth supporting moisture convergence is retained in the native intermediate.

Display reprojection uses the established RAP masked bilinear sampler. Scalar
contours never interpolate across missing input cells. Wind barbs use interpolated
earth-relative components; Web Mercator preserves their local direction.

## Sources and scheduling

AWS is primary and NOMADS fallback, each using its own inventory, offsets,
decoded identities, units, grid signatures, and checksums. RAP's paired U/V
subfields share one physical GRIB message. The reader uses the next **distinct**
byte offset and explicitly selects the indexed subfield. Decoding stays on the
main thread; only bounded network prefetch runs in workers.

The existing cron-job.org RAP dispatch calls `publish_rap_gdi.yml`. After a
successful GDI publication, its `dynamics` job receives the actual published
cycle as an output. It builds F00 and F03 together and publishes atomically to
`data/rap-dynamics-gdi`, independently of the existing `data/rap-gdi` branch.
A diagnostic failure cannot overwrite or interrupt the already-published GDI.
There is no new scheduler or GitHub timer. Native caches are bounded to eight hours.

The client requires the displayed GDI's exact model, cycle, valid time, and grid.
It clears companion overlays immediately when those change, and rejects unsafe
paths, altered definitions, corrupt checksums, and inconsistent provenance.
Matching previously loaded data may survive a source outage until cycle +6 hours;
expired or mismatched dynamics are hidden. Toggling off GDI clears all companions.

## Delivery sequence

RAP includes analysis/change context and same-cycle F03 context. Forecast
companions use the exact seven hourly valid times and actual HRRR/RRFS cycles
already published by the synchronized GDI forecast producer. They are available
with HRRR, RRFS, and the HRRR/RRFS blend. Day 1 maximum GDI products keep their
existing interpretation; instantaneous companions are not placed over a period
maximum with an ambiguous valid time.

## Native 3-km HRRR/RRFS delivery

The companion science, units and contour levels are the same as RAP. Gaussian
sigma remains **20 km in native projected coordinates**, approximately 6.7 cells
on the 3-km grids (Gaussian full width at half maximum about 47 km). It filters
moisture flux and wind *before* differentiation, reducing small-scale derivative
noise. It is applied once; the blend has no additional filter. GDI itself and its
native shading/contours are unchanged. Barbs retain the same fixed display
spacing (110 by 100 pixels on the 2400 by 1360 CONUS export), regardless of native
grid resolution. Contour labels require long paths and maintain separation.

Each source's decoded Lambert projection defines the display mapping. HRRR/RRFS
use the 38.5° standard parallel and −97.5° central meridian on their present CONUS
grid; the RAP projection is different and is not reused for CAMs. Grid signatures
must match the published GDI inputs. Blends additionally require the native
coordinates to agree. Both models must supply a finite diagnostic value at a cell;
missing/terrain-limited values never turn into a one-model blend. Moisture
convergence, divergence, humidity and PW are averaged after separate per-model
calculation. Winds are blended as earth-relative components, not speed/direction.

RRFS total-column PWAT is read from its `2dfld` product. The pressure-level file's
`30–0 mb above ground` PWAT is explicitly ineligible. Both AWS and NOMADS use their
own inventories and byte ranges. The separate two-model diagnostic decoder runs
at most two processes, one per model, each with bounded network prefetch; ecCodes
remains on the subprocess main thread.

The existing cron-job.org HRRR root triggers `publish_gdi_guidance.yml` and its
focused forecast workflow. GDI publishes first. A dependent job receives the
actual published metadata through a same-run artifact, builds all 126 companion
images (six fields × seven times × three perspectives), and publishes atomically
to `data/forecast-dynamics-gdi`. Decoded caches are bounded to eight hours; raw
GRIB downloads are not persisted between jobs. No scheduler or duplicate timer
is added. The client matches the base selection signature, exact sources, valid
time and grids, and preloads complete selected companion loops before showing
them. Playback changes overlay visibility without refetching hourly images.

A future TLE can summarize joint ingredient persistence within members before
summarizing agreement across runs; the retired GDI-only TLE remains disabled.

Checks cover analytic divergence and moisture-flux sign/units, wind rotation and
reverse scans, pressure weights and terrain, real multi-field GRIB selection,
provider fallback, exact client timing, late responses, toggles, and expiry.
