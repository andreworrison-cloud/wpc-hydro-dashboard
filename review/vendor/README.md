# Review dependencies

Leaflet 1.9.4 JavaScript and CSS from https://unpkg.com/leaflet@1.9.4/dist/.
License: LEAFLET-LICENSE.txt. Embedded in the generated offline review.

State geometry is the same reference source used by the dashboard:
https://raw.githubusercontent.com/PublicaMundi/MappingAPI/master/data/geojson/us-states.json
Downloaded 2026-10-17. This is generalized reference cartography, not a
survey-grade boundary dataset. Alaska, Hawaii, and Puerto Rico are excluded
from this CONUS display. Boundaries are vectors above the raster, not burned
into the scientific grid or image. Background services retain their attribution.

Basemap configurations mirror app.js at the H5 review branch baseline. WPC
Dark Reference in this focused review uses country polygons without the
production dashboard's additional place-label utilities. No claim of full
production interface parity is made.
