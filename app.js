// --- POPUP / TOOLTIP PRIORITY ---
// The full dashboard interface is styled in style.css.
const customStyle = document.createElement('style');
customStyle.innerHTML = `
    .leaflet-popup-pane { z-index: 7000 !important; }
    .leaflet-tooltip-pane { z-index: 6500 !important; }

    .glm-trend-card {
        margin: 8px 8px 10px;
        overflow: hidden;
        border: 1px solid rgba(79, 195, 247, 0.46);
        border-radius: 9px;
        background:
            linear-gradient(145deg, rgba(18, 47, 68, 0.98), rgba(12, 24, 38, 0.98));
        color: #f5fbff;
        box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.05);
        font-family: Arial, sans-serif;
    }
    .glm-trend-card__header {
        display: grid;
        grid-template-columns: minmax(0, 1fr) minmax(118px, 0.9fr);
        gap: 8px;
        align-items: center;
        padding: 9px 10px 7px;
        border-bottom: 1px solid rgba(255, 255, 255, 0.10);
        background: rgba(22, 61, 84, 0.60);
    }
    .glm-trend-card__kicker {
        margin-bottom: 2px;
        color: #7fd7ff;
        font-size: 8px;
        font-weight: 800;
        letter-spacing: 0.10em;
        text-transform: uppercase;
    }
    .glm-trend-card__title {
        font-size: 13px;
        font-weight: 800;
        line-height: 1.1;
    }
    .glm-trend-card__select {
        width: 100%;
        min-width: 0;
        padding: 5px 24px 5px 7px;
        border: 1px solid rgba(127, 215, 255, 0.42);
        border-radius: 5px;
        background: #101f2e;
        color: #fff;
        font-size: 10px;
        font-weight: 700;
    }
    .glm-trend-card__body { padding: 9px 10px 10px; }
    .glm-trend-card__state-row {
        display: flex;
        justify-content: space-between;
        gap: 8px;
        align-items: center;
        margin-bottom: 7px;
    }
    .glm-trend-card__state {
        display: inline-flex;
        align-items: center;
        gap: 5px;
        padding: 5px 8px;
        border: 1px solid currentColor;
        border-radius: 999px;
        font-size: 11px;
        font-weight: 900;
        line-height: 1;
        letter-spacing: 0.01em;
    }
    .glm-trend-card__change {
        color: #fff;
        font-size: 18px;
        font-weight: 900;
        line-height: 1;
        text-align: right;
    }
    .glm-trend-card__change-label {
        display: block;
        margin-top: 2px;
        color: #a9bac8;
        font-size: 8px;
        font-weight: 700;
        text-transform: uppercase;
    }
    .glm-trend-card__sparkline {
        padding: 4px 5px 1px;
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-radius: 6px;
        background: rgba(0, 0, 0, 0.18);
    }
    .glm-trend-card__axis {
        display: flex;
        justify-content: space-between;
        margin-top: -1px;
        color: #91a6b6;
        font-size: 8px;
        font-weight: 700;
    }
    .glm-trend-card__metrics {
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 5px;
        margin-top: 8px;
    }
    .glm-trend-card__metric {
        min-width: 0;
        padding: 6px 5px;
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-radius: 6px;
        background: rgba(255, 255, 255, 0.035);
        text-align: center;
    }
    .glm-trend-card__metric-value {
        overflow: hidden;
        color: #fff;
        font-size: 12px;
        font-weight: 900;
        line-height: 1.05;
        text-overflow: ellipsis;
        white-space: nowrap;
    }
    .glm-trend-card__metric-label {
        margin-top: 3px;
        color: #9fb1bf;
        font-size: 7px;
        font-weight: 800;
        line-height: 1.1;
        letter-spacing: 0.03em;
        text-transform: uppercase;
    }
    .glm-trend-card__regional {
        margin-top: 7px;
        padding-top: 7px;
        border-top: 1px solid rgba(255, 255, 255, 0.08);
        color: #c8d9e5;
        font-size: 9px;
        line-height: 1.25;
    }
    .glm-trend-card__regional strong { color: #7fd7ff; }
    .glm-trend-card__footnote {
        margin-top: 6px;
        color: #8298a8;
        font-size: 8px;
        line-height: 1.25;
    }
    .utility-toggle-field {
        padding: 7px 8px;
        border: 1px solid rgba(127, 215, 255, 0.18);
        border-radius: 6px;
        background: rgba(255, 255, 255, 0.025);
    }
    .utility-toggle-row {
        display: grid;
        grid-template-columns: auto minmax(0, 1fr);
        gap: 8px;
        align-items: start;
        color: #e8f5ff;
        cursor: pointer;
        font-size: 11px;
        line-height: 1.2;
    }
    .utility-toggle-row input {
        margin: 2px 0 0;
        accent-color: #6fd3ff;
    }
    .utility-toggle-row strong {
        display: block;
        font-size: 11px;
    }
    .utility-toggle-row small {
        display: block;
        margin-top: 3px;
        color: #8ea5b6;
        font-size: 9px;
        line-height: 1.25;
    }
    .ufvs-domain-tooltip {
        padding: 4px 7px;
        border: 1px solid rgba(111, 211, 255, 0.75);
        border-radius: 4px;
        background: rgba(8, 23, 35, 0.94);
        color: #f5fbff;
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.35);
        font-size: 10px;
        font-weight: 800;
        white-space: nowrap;
    }
    @media (max-width: 420px) {
        .glm-trend-card__header {
            grid-template-columns: 1fr;
        }
    }
`;
document.head.appendChild(customStyle);

// --- MOBILE VIEWPORT COMPATIBILITY ---
// Older mobile browsers can report 100vh taller than the actually visible page.
// Keep the dashboard sized to the usable browser viewport instead.
function updateDashboardViewportHeight() {
    const viewportHeight = window.innerHeight;
    if (!Number.isFinite(viewportHeight) || viewportHeight <= 0) return;
    document.documentElement.style.setProperty('--app-height', `${Math.round(viewportHeight)}px`);
}

updateDashboardViewportHeight();

// Initialize the map, centered roughly over the CONUS
const map = L.map('map', {
    zoomControl: true,
    center: [39.8283, -98.5795], 
    zoom: 5
});

let viewportRefreshTimer = null;
function refreshDashboardViewport() {
    window.clearTimeout(viewportRefreshTimer);
    viewportRefreshTimer = window.setTimeout(() => {
        updateDashboardViewportHeight();
        map.invalidateSize({pan: false, animate: false});
        viewportRefreshTimer = null;
    }, 120);
}

window.addEventListener('resize', refreshDashboardViewport, {passive: true});
window.addEventListener('orientationchange', refreshDashboardViewport, {passive: true});

// --- TOP-CENTER DASHBOARD TITLE ---
const mapTitle = L.DomUtil.create('div', 'map-title');
mapTitle.innerHTML = '<strong>WPC Real-Time Hydrometeorological Dashboard</strong>';
document.getElementById('map').appendChild(mapTitle);

// --- GLOBAL UTILITY FUNCTION ---
function formatUTC(date) {
    const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
    const m = months[date.getUTCMonth()];
    const d = String(date.getUTCDate()).padStart(2, '0');
    const h = String(date.getUTCHours()).padStart(2, '0');
    const min = String(date.getUTCMinutes()).padStart(2, '0');
    return `${m} ${d}, ${h}${min}Z`;
}

// --- CUSTOM MAP PANES FOR STRICT Z-INDEX HAZARD PRIORITY ---
map.createPane('labels');
map.getPane('labels').style.zIndex = 600;
map.getPane('labels').style.pointerEvents = 'none'; 

map.createPane('watches');
map.getPane('watches').style.zIndex = 410;

map.createPane('ero');
map.getPane('ero').style.zIndex = 420;

map.createPane('mpd');
map.getPane('mpd').style.zIndex = 430;

map.createPane('ffd');
map.getPane('ffd').style.zIndex = 440;

// Hydro-product click priority is enforced with separate panes:
// Flash Flood Warning > Flood Warning > Flood Advisory > Flood Watch.
map.createPane('warnings');
map.getPane('warnings').style.zIndex = 450; // Flood Advisories

map.createPane('floodWarnings');
map.getPane('floodWarnings').style.zIndex = 451;

map.createPane('flashFloodWarnings');
map.getPane('flashFloodWarnings').style.zIndex = 452;

// Authoritative fixed WPC UFVS geographic domains used for verification.
// Keep these bounds synchronized with UFVS_TREND_DOMAINS in
// fetch_glm_mosaic.py. Boundaries are displayed above raster data but below
// the map-label pane.
map.createPane('ufvsDomains');
map.getPane('ufvsDomains').style.zIndex = 590;

const UFVS_GEOGRAPHIC_DOMAINS = [
    { id: 'west-coast', label: 'West Coast', west: -125.0, east: -117.0, south: 32.0, north: 49.0},
    { id: 'southwest', label: 'Southwest', west: -117.0, east: -104.0, south: 28.0, north: 42.0},
    { id: 'interior-mountain-west', label: 'Interior Mountain West', west: -117.0, east: -104.0, south: 42.0, north: 49.0},
    { id: 'northern-plains', label: 'Northern Plains', west: -104.0, east: -85.0, south: 38.0, north: 49.0},
    { id: 'southern-plains', label: 'Southern Plains', west: -104.0, east: -90.0, south: 24.0, north: 38.0},
    { id: 'southeast', label: 'Southeast', west: -90.0, east: -75.0, south: 24.0, north: 38.0},
    { id: 'northeast', label: 'Northeast', west: -85.0, east: -66.0, south: 38.0, north: 49.0}
];
const UFVS_DOMAINS_SESSION_KEY = 'wpc-ufvs-geographic-domains-v1';
const ufvsGeographicDomainsLayer = L.layerGroup();

UFVS_GEOGRAPHIC_DOMAINS.forEach(domain => {
    const rectangle = L.rectangle(
        [[domain.south, domain.west], [domain.north, domain.east]],
        {
            pane: 'ufvsDomains',
            color: '#6fd3ff',
            weight: 1.5,
            opacity: 0.88,
            dashArray: '7 5',
            fill: false,
            interactive: true,
            bubblingMouseEvents: false
        }
    );
    rectangle.bindTooltip(domain.label, {
        sticky: true,
        direction: 'top',
        className: 'ufvs-domain-tooltip'
    });
    rectangle.addTo(ufvsGeographicDomainsLayer);
});

function readUFVSDomainsVisibility() {
    try {
        return window.sessionStorage.getItem(UFVS_DOMAINS_SESSION_KEY) === '1';
    } catch (error) {
        return false;
    }
}

function writeUFVSDomainsVisibility(isVisible) {
    try {
        window.sessionStorage.setItem(UFVS_DOMAINS_SESSION_KEY, isVisible ? '1' : '0');
    } catch (error) {
        // Session storage is optional; the utility remains functional in-page.
    }
}

function setUFVSGeographicDomainsVisible(isVisible, persist = true) {
    const shouldShow = Boolean(isVisible);
    if (shouldShow && !map.hasLayer(ufvsGeographicDomainsLayer)) {
        map.addLayer(ufvsGeographicDomainsLayer);
    } else if (!shouldShow && map.hasLayer(ufvsGeographicDomainsLayer)) {
        map.removeLayer(ufvsGeographicDomainsLayer);
    }
    if (persist) writeUFVSDomainsVisibility(shouldShow);
    const toggle = document.getElementById('ufvs-geographic-domains-toggle');
    if (toggle) toggle.checked = shouldShow;
}

if (readUFVSDomainsVisibility()) {
    setUFVSGeographicDomainsVisible(true, false);
}

// --- BASEMAPS ---

// Esri Dark Gray
const esriDarkBase = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}', {
    maxZoom: 16,
    attribution: '© Esri, HERE, Garmin, © OpenStreetMap'
});

// OpenStreetMap
const osmLayer = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '© OpenStreetMap contributors'
});

// Esri World Imagery (Satellite)
const esriWorldImagery = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
    maxZoom: 19,
    attribution: 'Tiles © Esri — Source: Esri, i-cubed, USDA, USGS, AEX, GeoEye, Getmapping, Aerogrid, IGN, IGP, UPR-EGP, and the GIS User Community'
});

// Esri World Topographic
const esriWorldTopo = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}', {
    maxZoom: 19,
    attribution: 'Tiles © Esri — Esri, DeLorme, NAVTEQ, TomTom, Intermap, iPC, USGS, FAO, NPS, NRCAN, GeoBase, Kadaster NL, Ordnance Survey, Esri Japan, METI, Esri China (Hong Kong), and the GIS User Community'
});

// Add default basemap
esriDarkBase.addTo(map); 

// The floating text labels for the Dark Base
const esriDarkLabels = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Reference/MapServer/tile/{z}/{y}/{x}', {
    pane: 'labels',
    maxZoom: 16
});
esriDarkLabels.addTo(map);

// --- AUTO-TOGGLING GEOJSON STATE BORDERS ---
const whiteBorders = L.geoJSON(null, {
    style: { color: 'rgba(255, 255, 255, 0.8)', weight: 1.5, fillOpacity: 0 },
    pane: 'labels', interactive: false
});

const blackBorders = L.geoJSON(null, {
    style: { color: 'rgba(0, 0, 0, 0.8)', weight: 1.5, fillOpacity: 0 },
    pane: 'labels', interactive: false
});

fetch('https://raw.githubusercontent.com/PublicaMundi/MappingAPI/master/data/geojson/us-states.json')
    .then(response => response.json())
    .then(data => {
        whiteBorders.addData(data);
        blackBorders.addData(data);
    });

whiteBorders.addTo(map); 

// DYNAMIC BASEMAP TOGGLE LOGIC
map.on('baselayerchange', function(e) {
    if (map.hasLayer(esriDarkLabels)) map.removeLayer(esriDarkLabels); 
    if (map.hasLayer(whiteBorders)) map.removeLayer(whiteBorders);
    if (map.hasLayer(blackBorders)) map.removeLayer(blackBorders);

    if (e.name === "Esri Dark Gray") {
        esriDarkLabels.addTo(map);
        whiteBorders.addTo(map);
    } else if (e.name === "OpenStreetMap" || e.name === "Esri World Topographic") {
        blackBorders.addTo(map);
    } else if (e.name === "Esri World Imagery (Satellite)") {
        whiteBorders.addTo(map);
    }
});

// --- TIME LOOP LOGIC (NOW AUTO-UPDATING) ---
map.timeDimension = L.timeDimension({
    period: "PT10M"
});

L.control.timeDimension({
    position: 'bottomleft',
    autoPlay: true,
    playerOptions: { transitionTime: 500, loop: true }
}).addTo(map);

function updateTimeDimension() {
    const endTime = new Date();
    endTime.setMinutes(Math.floor(endTime.getMinutes() / 10) * 10);
    endTime.setSeconds(0);
    endTime.setMilliseconds(0);

    const startTime = new Date(endTime.getTime() - 2 * 60 * 60 * 1000);
    
    let newTimes = [];
    let curr = new Date(startTime);
    while (curr <= endTime) {
        newTimes.push(curr.getTime());
        curr = new Date(curr.getTime() + 10 * 60 * 1000); 
    }
    
    map.timeDimension.setAvailableTimes(newTimes, 'replace');
}

updateTimeDimension();
setInterval(updateTimeDimension, 10 * 60 * 1000); 

// --- LOOPING RADAR LAYER ---
const radarWMS = L.tileLayer.wms("https://mesonet.agron.iastate.edu/cgi-bin/wms/nexrad/n0q-t.cgi", {
    format: 'image/png', transparent: true, opacity: 0.6, layers: 'nexrad-n0q-wmst', attribution: "Data © IEM"
});
const radarTimeLayer = L.timeDimension.layer.wms(radarWMS, { updateTimeDimension: false });
radarTimeLayer.addTo(map);

// --- MRMS & SATELLITE QPE LAYERS ---
const mrmsOptions = { format: 'image/png', transparent: true, opacity: 0.65, attribution: "Data © IEM / NCEP" };
const mrms1hr = L.tileLayer.wms("https://mesonet.agron.iastate.edu/cgi-bin/wms/us/mrms_nn.cgi", { ...mrmsOptions, layers: 'mrms_p1h' });
const mrms24hr = L.tileLayer.wms("https://mesonet.agron.iastate.edu/cgi-bin/wms/us/mrms_nn.cgi", { ...mrmsOptions, layers: 'mrms_p24h' });
const mrms48hr = L.tileLayer.wms("https://mesonet.agron.iastate.edu/cgi-bin/wms/us/mrms_nn.cgi", { ...mrmsOptions, layers: 'mrms_p48h' });
const mrms72hr = L.tileLayer.wms("https://mesonet.agron.iastate.edu/cgi-bin/wms/us/mrms_nn.cgi", { ...mrmsOptions, layers: 'mrms_p72h' });

// --- OPERATIONAL MRMS FLASH ROLLING 24-HOUR MAXIMA ---
// These transparent PNGs are pre-warped to EPSG:3857. Their exact Leaflet
// bounds and valid windows are read from the synchronized metadata files.
const MRMS_CREST_24H_LAYER_NAME = 'MRMS FLASH CREST Unit Q — Rolling 24-Hour Maximum';
const MRMS_FFD_24H_LAYER_NAME = 'MRMS FLASH FFD — Rolling 24-Hour Maximum Category';
const MRMS_CREST_24H_IMAGE_URL = 'static/mrms_crest_unitq_max24h.png';
const MRMS_CREST_24H_METADATA_URL = 'static/mrms_crest_unitq_max24h_metadata.json';
const MRMS_FFD_24H_IMAGE_URL = 'static/mrms_ffd_max24h.png';
const MRMS_FFD_24H_METADATA_URL = 'static/mrms_ffd_max24h_metadata.json';
const mrmsFlashPlaceholderBounds = [[20.0, -130.0], [55.0, -60.0]];

const mrmsCrest24hLayer = L.imageOverlay(
    MRMS_CREST_24H_IMAGE_URL,
    mrmsFlashPlaceholderBounds,
    {zIndex: 12, opacity: 0, interactive: false}
);

const mrmsFfd24hLayer = L.imageOverlay(
    MRMS_FFD_24H_IMAGE_URL,
    mrmsFlashPlaceholderBounds,
    {zIndex: 12, opacity: 0, interactive: false}
);

let mrmsCrest24hReady = false;
let mrmsFfd24hReady = false;
let mrmsCrest24hMetadata = null;
let mrmsFfd24hMetadata = null;

// --- OPERATIONAL GOES GLM CONTROLLED MOSAIC ---
// The three primary products use an exclusive GOES-18/GOES-19 ownership
// mask. The optional debug layers expose each native satellite contribution
// and the ownership mask without changing the primary dashboard display.
const GLM_MOSAIC_5MIN_LAYER_NAME = 'GOES GLM Controlled Mosaic — Latest 5-Minute FED';
const GLM_MOSAIC_30MIN_LAYER_NAME = 'GOES GLM Controlled Mosaic — Rolling 30-Minute Accumulation';
const GLM_MOSAIC_60MIN_LAYER_NAME = 'GOES GLM Controlled Mosaic — Rolling 60-Minute Accumulation';
const GLM_TREND_MAP_15MIN_LAYER_NAME = 'GOES GLM Controlled Mosaic — Convective Trend (15 min)';
const GLM_TRANSPARENT_PLACEHOLDER = 'data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw==';
const glmPlaceholderBounds = [[20.0, -130.0], [55.0, -60.0]];

function createGLMImageOverlay(imageUrl, zIndex = 13) {
    return L.imageOverlay(imageUrl, glmPlaceholderBounds, {
        zIndex,
        opacity: 0,
        interactive: false
    });
}

const glmMosaic5minLayer = createGLMImageOverlay('static/glm_conus_mosaic_5min.png');
const glmMosaic30minLayer = createGLMImageOverlay('static/glm_conus_mosaic_30min.png');
const glmMosaic60minLayer = createGLMImageOverlay('static/glm_conus_mosaic_60min.png');
const glmTrendMap15minLayer = createGLMImageOverlay(GLM_TRANSPARENT_PLACEHOLDER);


const GLM_LAYER_CONFIGS = [
    {
        id: 'glm-mosaic-5min',
        name: GLM_MOSAIC_5MIN_LAYER_NAME,
        layer: glmMosaic5minLayer,
        imageUrl: 'static/glm_conus_mosaic_5min.png',
        metadataUrl: 'static/glm_conus_mosaic_5min_metadata.json',
        productRole: 'controlled_mosaic',
        windowMinutes: 5,
        legendId: 'five-minute',
        defaultOpacity: 1.0,
        debug: false
    },
    {
        id: 'glm-mosaic-30min',
        name: GLM_MOSAIC_30MIN_LAYER_NAME,
        layer: glmMosaic30minLayer,
        imageUrl: 'static/glm_conus_mosaic_30min.png',
        metadataUrl: 'static/glm_conus_mosaic_30min_metadata.json',
        productRole: 'controlled_mosaic',
        windowMinutes: 30,
        legendId: 'rolling',
        defaultOpacity: 1.0,
        debug: false
    },
    {
        id: 'glm-mosaic-60min',
        name: GLM_MOSAIC_60MIN_LAYER_NAME,
        layer: glmMosaic60minLayer,
        imageUrl: 'static/glm_conus_mosaic_60min.png',
        metadataUrl: 'static/glm_conus_mosaic_60min_metadata.json',
        productRole: 'controlled_mosaic',
        windowMinutes: 60,
        legendId: 'rolling',
        defaultOpacity: 1.0,
        debug: false
    },
    {
        id: 'glm-convective-trend-15min',
        name: GLM_TREND_MAP_15MIN_LAYER_NAME,
        layer: glmTrendMap15minLayer,
        imageUrl: GLM_TRANSPARENT_PLACEHOLDER,
        metadataUrl: 'static/glm_convective_trend_15min_metadata.json',
        productRole: 'convective_trend_map',
        windowMinutes: 15,
        legendId: 'trend-map',
        defaultOpacity: 0.96,
        debug: false,
        embeddedImageField: 'embedded_png_base64'
    }
];

const glmConfigByName = new Map(GLM_LAYER_CONFIGS.map(config => [config.name, config]));
const glmMetadataByName = new Map();
const glmReadyNames = new Set();
const GLM_MANIFEST_URL = 'static/glm_mosaic_manifest.json';
const GLM_MANIFEST_POLL_INTERVAL_MS = 90 * 1000;
const GLM_MANIFEST_RETRY_DELAYS_MS = [0, 3500, 9000];
let glmLastManifestVersion = '';
let glmManifestCheckInFlight = false;
const GLM_TREND_SESSION_KEY = 'wpc-glm-trend-domain-v1';
const GLM_TREND_STATE_PRESENTATION = {
    rapidly_increasing: {
        label: 'Rapidly Increasing', symbol: '▲', color: '#ff4848',
        background: 'rgba(255, 72, 72, 0.15)'
    },
    increasing: {
        label: 'Increasing', symbol: '↗', color: '#ffaa40',
        background: 'rgba(255, 170, 64, 0.14)'
    },
    steady: {
        label: 'Steady', symbol: '→', color: '#ffe878',
        background: 'rgba(255, 232, 120, 0.13)'
    },
    decreasing: {
        label: 'Decreasing', symbol: '↘', color: '#4ceaff',
        background: 'rgba(76, 234, 255, 0.13)'
    },
    rapidly_decreasing: {
        label: 'Rapidly Decreasing', symbol: '▼', color: '#3876ff',
        background: 'rgba(56, 118, 255, 0.14)'
    },
    low_activity: {
        label: 'Low Activity', symbol: '•', color: '#91a6b6',
        background: 'rgba(145, 166, 182, 0.10)'
    },
    insufficient_data: {
        label: 'Insufficient Data', symbol: '—', color: '#b0bec5',
        background: 'rgba(176, 190, 197, 0.10)'
    }
};


// --- CIMSS/SSEC LIGHTNINGCAST ---
// Authorized CIMSS/SSEC real-time CONUS LightningCast contours. The backend
// publishes a transparent EPSG:3857 raster using the standard 10/30/50/70/90%
// probability contours. LightningCast remains independent of the observed GLM
// layers so forecasters may compare prediction and observed lightning together.
const LIGHTNINGCAST_LAYER_NAME = 'CIMSS/SSEC LightningCast — Probability of Lightning in Next 60 Minutes';
const LIGHTNINGCAST_IMAGE_URL = 'static/lightningcast_conus_probability_60min.png';
const LIGHTNINGCAST_METADATA_URL = 'static/lightningcast_conus_probability_60min_metadata.json';
const LIGHTNINGCAST_MANIFEST_URL = 'static/lightningcast_manifest.json';
const LIGHTNINGCAST_MANIFEST_POLL_INTERVAL_MS = 90 * 1000;
const LIGHTNINGCAST_MANIFEST_RETRY_DELAYS_MS = [0, 3500, 9000];
const lightningCastPlaceholderBounds = [[20.0, -130.0], [55.0, -60.0]];
const lightningCastLayer = L.imageOverlay(
    LIGHTNINGCAST_IMAGE_URL,
    lightningCastPlaceholderBounds,
    {zIndex: 14, opacity: 0, interactive: false}
);

let lightningCastMetadata = null;
let lightningCastReady = false;
let lightningCastLastManifestVersion = '';
let lightningCastManifestCheckInFlight = false;


// --- HRRR-TLE FLASH FLOOD GUIDANCE — EXPERIMENTAL ---
// Frozen Version 3.3 science. The production backend publishes 18 transparent
// EPSG:3857 overlays plus synchronized metadata/manifest files.
const HRRR_TLE_SECTION_TITLE = 'HRRR-TLE Flash Flood Guidance - Experimental';
const HRRR_TLE_MANIFEST_URL = 'static/hrrr_tle_manifest.json';
const HRRR_TLE_METADATA_URL = 'static/hrrr_tle_metadata.json';
const HRRR_TLE_MANIFEST_POLL_INTERVAL_MS = 3 * 60 * 1000;
const HRRR_TLE_PLACEHOLDER_BOUNDS = [[23.0, -125.0], [50.5, -66.5]];

const HRRR_DIAGNOSTIC_LAYER_CONFIGS = [
    {id: 'hrrr-diag-max-ratio', key: 'hrrr_max_ratio',
     label: 'Max FFG Exceedance Ratio — Next 12 Hours',
     file: 'hrrr_latest_12h_max_ffg_ratio.png', legendType: 'ratio',
     keywords: 'latest deterministic HRRR maximum FFG exceedance QPF ratio next 12 hours'},
    {id: 'hrrr-diag-ffg-coverage', key: 'hrrr_ffg_coverage',
     label: 'FFG Exceedance Areal Coverage — Next 12 Hours',
     file: 'hrrr_latest_12h_ffg_exceedance_coverage.png', legendType: 'coverage',
     keywords: 'latest deterministic HRRR FFG exceedance areal coverage 40 km next 12 hours'}
];

const HRRR_DIAGNOSTIC_CONFIG_BY_NAME = new Map();
HRRR_DIAGNOSTIC_LAYER_CONFIGS.forEach(config => {
    config.url = `static/${config.file}`;
    config.layer = L.imageOverlay(
        config.url,
        HRRR_TLE_PLACEHOLDER_BOUNDS,
        {zIndex: 13, opacity: 0, interactive: false}
    );
    HRRR_DIAGNOSTIC_CONFIG_BY_NAME.set(config.label, config);
});

const HRRR_TLE_LAYER_CONFIGS = [
    // Core FFG Guidance
    {id: 'hrrr-tle-ffg-consensus', key: 'ffg_consensus', group: 'Core FFG Guidance',
     label: 'FFG Exceedance Consensus', file: 'hrrr_tle_ffg_consensus.png', legendType: 'frequency6',
     keywords: 'HRRR time lagged ensemble FFG exceedance member frequency consensus'},
    {id: 'hrrr-tle-median-ratio', key: 'median_ratio', group: 'Core FFG Guidance',
     label: 'Median Neighborhood-Max QPF / FFG Ratio', file: 'hrrr_tle_median_neighborhood_ratio.png', legendType: 'ratio',
     keywords: 'median neighborhood maximum QPF FFG ratio magnitude'},
    {id: 'hrrr-tle-ffg-1h', key: 'ffg_1h', group: 'Core FFG Guidance',
     label: '1-h FFG Exceedance', file: 'hrrr_tle_ffg_1h.png', legendType: 'frequency6',
     keywords: '1 hour FFG exceedance'},
    {id: 'hrrr-tle-ffg-3h', key: 'ffg_3h', group: 'Core FFG Guidance',
     label: '3-h FFG Exceedance', file: 'hrrr_tle_ffg_3h.png', legendType: 'frequency6',
     keywords: '3 hour FFG exceedance'},
    {id: 'hrrr-tle-ffg-6h', key: 'ffg_6h', group: 'Core FFG Guidance',
     label: '6-h FFG Exceedance', file: 'hrrr_tle_ffg_6h.png', legendType: 'frequency6',
     keywords: '6 hour FFG exceedance'},

    // Heavy Rain / Persistence
    {id: 'hrrr-tle-qpf1h-1in', key: 'qpf1h_1in', group: 'Heavy Rain / Persistence',
     label: '1-h QPF ≥ 1 in', file: 'hrrr_tle_qpf1h_1in.png', legendType: 'frequency6',
     keywords: 'one hour QPF 1 inch rainfall threshold'},
    {id: 'hrrr-tle-qpf1h-2in', key: 'qpf1h_2in', group: 'Heavy Rain / Persistence',
     label: '1-h QPF ≥ 2 in', file: 'hrrr_tle_qpf1h_2in.png', legendType: 'frequency6',
     keywords: 'one hour QPF 2 inch rainfall threshold'},
    {id: 'hrrr-tle-qpf1h-3in', key: 'qpf1h_3in', group: 'Heavy Rain / Persistence',
     label: '1-h QPF ≥ 3 in', file: 'hrrr_tle_qpf1h_3in.png', legendType: 'frequency6',
     keywords: 'one hour QPF 3 inch rainfall threshold'},
    {id: 'hrrr-tle-persist-1in', key: 'persistence_1in_2of3', group: 'Heavy Rain / Persistence',
     label: '≥1 in in 2 of 3 Hours', file: 'hrrr_tle_persistence_1in_2of3.png', legendType: 'frequency6',
     keywords: 'persistence repeated one inch two of three hours'},
    {id: 'hrrr-tle-persist-3h-2in', key: 'persistence_3h_2in', group: 'Heavy Rain / Persistence',
     label: 'Rolling 3-h QPF ≥ 2 in', file: 'hrrr_tle_persistence_3h_2in.png', legendType: 'frequency6',
     keywords: 'rolling three hour QPF 2 inch'},
    {id: 'hrrr-tle-persist-3h-3in', key: 'persistence_3h_3in', group: 'Heavy Rain / Persistence',
     label: 'Rolling 3-h QPF ≥ 3 in', file: 'hrrr_tle_persistence_3h_3in.png', legendType: 'frequency6',
     keywords: 'rolling three hour QPF 3 inch'},

    // Timing / Evolution
    {id: 'hrrr-tle-evol-00-03', key: 'evolution_00_03', group: 'Timing / Evolution',
     label: 'FFG Exceedance +00–03 h', file: 'hrrr_tle_evolution_00_03.png', legendType: 'frequency6Min2',
     evolutionHours: [0, 3], keywords: 'timing evolution first 3 hours'},
    {id: 'hrrr-tle-evol-03-06', key: 'evolution_03_06', group: 'Timing / Evolution',
     label: 'FFG Exceedance +03–06 h', file: 'hrrr_tle_evolution_03_06.png', legendType: 'frequency6Min2',
     evolutionHours: [3, 6], keywords: 'timing evolution 3 to 6 hours'},
    {id: 'hrrr-tle-evol-06-09', key: 'evolution_06_09', group: 'Timing / Evolution',
     label: 'FFG Exceedance +06–09 h', file: 'hrrr_tle_evolution_06_09.png', legendType: 'frequency6Min2',
     evolutionHours: [6, 9], keywords: 'timing evolution 6 to 9 hours'},
    {id: 'hrrr-tle-evol-09-12', key: 'evolution_09_12', group: 'Timing / Evolution',
     label: 'FFG Exceedance +09–12 h', file: 'hrrr_tle_evolution_09_12.png', legendType: 'frequency6Min2',
     evolutionHours: [9, 12], keywords: 'timing evolution 9 to 12 hours'},
    {id: 'hrrr-tle-prior3', key: 'prior3', group: 'Timing / Evolution',
     label: 'Prior 3 HRRR Cycles', file: 'hrrr_tle_prior3_consensus.png', legendType: 'frequency3',
     keywords: 'prior three cycles older runs consensus'},
    {id: 'hrrr-tle-latest3', key: 'latest3', group: 'Timing / Evolution',
     label: 'Latest 3 HRRR Cycles', file: 'hrrr_tle_latest3_consensus.png', legendType: 'frequency3',
     keywords: 'latest three cycles newest runs consensus'},
    {id: 'hrrr-tle-run-change', key: 'run_change', group: 'Timing / Evolution',
     label: 'Run-to-Run Signal Change', file: 'hrrr_tle_run_change.png', legendType: 'runChange',
     keywords: 'fading persistent emerging run to run signal trend'}
];

const HRRR_TLE_CONFIG_BY_NAME = new Map();
const HRRR_TLE_CONFIG_BY_KEY = new Map();
HRRR_TLE_LAYER_CONFIGS.forEach(config => {
    config.url = `static/${config.file}`;
    config.layer = L.imageOverlay(
        config.url,
        HRRR_TLE_PLACEHOLDER_BOUNDS,
        {zIndex: 13, opacity: 0, interactive: false}
    );
    HRRR_TLE_CONFIG_BY_NAME.set(config.label, config);
    HRRR_TLE_CONFIG_BY_KEY.set(config.key, config);
});

const HRRR_ALL_LAYER_CONFIGS = [
    ...HRRR_DIAGNOSTIC_LAYER_CONFIGS,
    ...HRRR_TLE_LAYER_CONFIGS
];

let hrrrTLEMetadata = null;
let hrrrTLEReady = false;
let hrrrTLELastManifestVersion = '';
let hrrrTLEManifestCheckInFlight = false;

const satOptions = { format: 'image/png', transparent: true, opacity: 0.6 };
const goesEastVis = L.tileLayer.wms("https://mesonet.agron.iastate.edu/cgi-bin/wms/goes_east.cgi", { ...satOptions, layers: 'conus_ch02' });
const goesEastWV = L.tileLayer.wms("https://mesonet.agron.iastate.edu/cgi-bin/wms/goes_east.cgi", { ...satOptions, layers: 'conus_ch09' });
const goesEastIR = L.tileLayer.wms("https://mesonet.agron.iastate.edu/cgi-bin/wms/goes_east.cgi", { ...satOptions, layers: 'conus_ch13' });
const goesWestVis = L.tileLayer.wms("https://mesonet.agron.iastate.edu/cgi-bin/wms/goes_west.cgi", { ...satOptions, layers: 'conus_ch02' });
const goesWestWV = L.tileLayer.wms("https://mesonet.agron.iastate.edu/cgi-bin/wms/goes_west.cgi", { ...satOptions, layers: 'conus_ch09' });
const goesWestIR = L.tileLayer.wms("https://mesonet.agron.iastate.edu/cgi-bin/wms/goes_west.cgi", { ...satOptions, layers: 'conus_ch13' });

// --- AUTO-REFRESH WMS LAYERS ---
function refreshWMSLayers() {
    const wmsLayersToUpdate = [radarWMS, mrms1hr, mrms24hr, mrms48hr, mrms72hr, goesEastVis, goesEastWV, goesEastIR, goesWestVis, goesWestWV, goesWestIR];
    wmsLayersToUpdate.forEach(layer => {
        layer.setParams({_t: new Date().getTime()}, false); 
    });
}
setInterval(refreshWMSLayers, 5 * 60 * 1000); 

// --- NWS ACTIVE HYDRO WARNINGS & WATCHES ---
function getAlertColor(event) {
    if (!event) return "gray";
    if (event === "Flash Flood Warning") return "red";
    if (event === "Flood Warning") return "green";
    if (event === "Flood Advisory") return "lightgreen";
    if (event === "Flood Watch" || event === "Flash Flood Watch") return "seagreen"; 
    return "gray"; 
}

window.loadNWSAlertText = async function(event, url, containerId) {
    if (event) {
        event.stopPropagation();
        event.preventDefault();
    }
    const container = document.getElementById(containerId);
    if (!container) return;
    container.innerHTML = "<em>Loading official text...</em>";
    
    try {
        const response = await fetch(url);
        if (!response.ok) throw new Error("API not responding");
        const data = await response.json();
        const desc = data.properties.description ? data.properties.description.replace(/\n/g, '<br>') : "No text description provided by WFO.";
        const inst = data.properties.instruction ? "<br><br><strong>Instructions:</strong><br>" + data.properties.instruction.replace(/\n/g, '<br>') : "";
        container.innerHTML = `<div style="text-align: left; margin-top: 10px; padding: 10px; background: #ffffff; border: 1px solid #ccc; border-radius: 4px; max-height: 250px; overflow-y: auto; font-family: monospace; font-size: 11px; color: #333; z-index: 9999;">${desc}${inst}</div>`;
    } catch (error) {
        container.innerHTML = "<span style='color: red;'>Failed to load alert text from NWS API.</span>";
    }
};

const commonAlertOptions = (paneName) => ({
    pane: paneName,
    style: function (feature) {
        return { color: getAlertColor(feature.properties.prod_type), weight: 2, opacity: 1, fillOpacity: 0.2 };
    },
    onEachFeature: function (feature, layer) {
        const props = feature.properties;
        if (!props) return;
        const eventName = props.prod_type || "Unknown Hydro Alert";
        const wfo = props.wfo ? `WFO ${props.wfo}` : "NWS";
        const expires = props.expiration || "Unknown";
        
        const alertId = "alert-" + Math.random().toString(36).substr(2, 9);
        const linkHTML = props.url ? `<br><div id="${alertId}" style="margin-top: 10px;"><button onclick="loadNWSAlertText(event, '${props.url}', '${alertId}')" style="background: #007bff; color: white; border: none; padding: 6px 12px; border-radius: 4px; cursor: pointer; font-weight: bold; font-size: 12px;">Load Official Alert Text</button></div>` : "";

        layer.bindPopup(`
            <div style="font-family: sans-serif; text-align: center; min-width: 260px; background: white;">
                <strong style="color: ${getAlertColor(eventName)}; font-size: 1.1em;">${eventName}</strong><br>
                <em>Issued by ${wfo}</em><br>
                <hr style="margin: 5px 0;">
                <span style="font-size: 0.9em;">Expires: ${expires}</span>
                ${linkHTML}
            </div>
        `, { maxWidth: 400 });
    }
});

const floodAdvisoryLayer = L.geoJSON(
    null,
    commonAlertOptions('warnings')
);
const floodWarningLayer = L.geoJSON(
    null,
    commonAlertOptions('floodWarnings')
);
const flashFloodWarningLayer = L.geoJSON(
    null,
    commonAlertOptions('flashFloodWarnings')
);

// Preserve the existing single sidebar toggle for all warnings/advisories while
// placing each product type in its own click-priority pane.
const warningsLayer = L.layerGroup([
    floodAdvisoryLayer,
    floodWarningLayer,
    flashFloodWarningLayer
]);
const watchesLayer = L.geoJSON(null, commonAlertOptions('watches'));

warningsLayer.addTo(map);
watchesLayer.addTo(map);

async function fetchNWSAlerts() {
    try {
        const whereClause = "prod_type IN ('Flash Flood Warning', 'Flood Warning', 'Flood Advisory', 'Flood Watch', 'Flash Flood Watch')";
        const url = `https://mapservices.weather.noaa.gov/eventdriven/rest/services/WWA/watch_warn_adv/MapServer/1/query?where=${encodeURIComponent(whereClause)}&outFields=prod_type,wfo,expiration,url&f=geojson&t=${new Date().getTime()}`;
        const response = await fetch(url);
        if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
        const data = await response.json();
        
        flashFloodWarningLayer.clearLayers();
        floodWarningLayer.clearLayers();
        floodAdvisoryLayer.clearLayers();
        watchesLayer.clearLayers();
        
        if (data && data.features) {
            const validFeatures = data.features.filter(
                feature => feature.properties && feature.properties.prod_type
            );
            const flashFloodFeatures = validFeatures.filter(
                feature => feature.properties.prod_type === 'Flash Flood Warning'
            );
            const floodWarningFeatures = validFeatures.filter(
                feature => feature.properties.prod_type === 'Flood Warning'
            );
            const floodAdvisoryFeatures = validFeatures.filter(
                feature => feature.properties.prod_type === 'Flood Advisory'
            );
            const watchFeatures = validFeatures.filter(
                feature => feature.properties.prod_type === 'Flood Watch' ||
                    feature.properties.prod_type === 'Flash Flood Watch'
            );

            if (floodAdvisoryFeatures.length > 0) {
                floodAdvisoryLayer.addData(floodAdvisoryFeatures);
            }
            if (floodWarningFeatures.length > 0) {
                floodWarningLayer.addData(floodWarningFeatures);
            }
            if (flashFloodFeatures.length > 0) {
                flashFloodWarningLayer.addData(flashFloodFeatures);
            }
            if (watchFeatures.length > 0) watchesLayer.addData(watchFeatures);
        }
    } catch (error) { console.error("Error fetching NWS alerts:", error); }
}
fetchNWSAlerts();
setInterval(fetchNWSAlerts, 5 * 60 * 1000); 

// --- BULLETPROOF MRMS DVD FLASH FLOOD DETECTOR (FFD) ---
const ffdLayer = L.layerGroup();

async function fetchFFDData() {
    try {
        const targetUrl = `static/ffd_contours.txt?t=${new Date().getTime()}`;
        const response = await fetch(targetUrl);
        if (!response.ok) throw new Error("Could not fetch local FFD placefile.");
        
        const lastModified = response.headers.get('Last-Modified');
        let latestFFDTime = lastModified ? formatUTC(new Date(lastModified)) : formatUTC(new Date()); 
        
        const text = await response.text();
        ffdLayer.clearLayers(); 
        
        const lines = text.split('\n');
        let currentColor = '#00ff00'; 
        let colorInferredImpact = 'Monitor';
        let currentTooltipHTML = '<strong>Monitor</strong>';
        let isDrawing = false;
        let currentCoords = [];
        
        lines.forEach(line => {
            const cleanLine = line.trim();
            
            if (cleanLine.match(/^Color:\s*(\d+)\s+(\d+)\s+(\d+)/i)) {
                const colorMatch = cleanLine.match(/^Color:\s*(\d+)\s+(\d+)\s+(\d+)/i);
                const r = parseInt(colorMatch[1]);
                const g = parseInt(colorMatch[2]);
                const b = parseInt(colorMatch[3]);
                currentColor = `rgb(${r}, ${g}, ${b})`;
                
                if (r === 0 && g >= 200 && b === 0) colorInferredImpact = "Monitor";
                else if (r === 255 && g === 255 && b === 0) colorInferredImpact = "Advisory";
                else if (r === 255 && (g > 100 && g < 200) && b === 0) colorInferredImpact = "Base FFW";
                else if (r === 255 && g === 0 && b === 0) colorInferredImpact = "Considerable FFW";
                else if (r === 255 && g === 0 && b === 255) colorInferredImpact = "Catastrophic FFW";
                else colorInferredImpact = "Flash Flood Detector";
                return; 
            }
            
            if (cleanLine.match(/^(Line:|Polygon:)/i)) {
                isDrawing = true;
                currentCoords = [];
                const titleMatch = cleanLine.match(/"([^"]+)"/);
                if (titleMatch) {
                    let rawLabel = titleMatch[1];
                    rawLabel = rawLabel.replace(/\\[nN]/g, ' ').replace(/\/[nN]/g, ' ').replace(/boundary/i, '').replace(/\s+/g, ' ').trim();
                    const parts = rawLabel.split(' ');
                    if (parts.length > 0) {
                        let impactTag = parts.length > 1 ? parts.slice(1).join(' ') : colorInferredImpact;
                        if (impactTag.length > 0) impactTag = impactTag.charAt(0).toUpperCase() + impactTag.slice(1);
                        currentTooltipHTML = `<strong>${impactTag}</strong>`;
                    } else {
                        currentTooltipHTML = `<strong>${rawLabel}</strong>`;
                    }
                } else {
                    currentTooltipHTML = `<strong>${colorInferredImpact}</strong>`;
                }
                return;
            }
            
            if (cleanLine.match(/^End:/i) && isDrawing) {
                isDrawing = false;
                if (currentCoords.length > 2) {
                    const polygon = L.polygon(currentCoords, {
                        color: currentColor, weight: 2, fillColor: currentColor, fillOpacity: 0.35, pane: 'ffd'
                    });
                    polygon.bindTooltip(`<div style="text-align: center; line-height: 1.4; font-family: sans-serif;">${currentTooltipHTML}</div>`, { sticky: true, direction: 'top', className: 'ffd-tooltip' });
                    ffdLayer.addLayer(polygon);
                }
                return;
            }
            
            if (isDrawing) {
                const locMatch = cleanLine.match(/^([-+]?\d{1,2}\.\d+)\s*,\s*([-+]?\d{1,3}\.\d+)/);
                if (locMatch) {
                    currentCoords.push([parseFloat(locMatch[1]), parseFloat(locMatch[2])]);
                }
            }
        });

        const ffdTimeBox = document.getElementById('ffd-time-box');
        if (ffdTimeBox) {
            ffdTimeBox.innerHTML = `
                <strong>Flash Flood Detector</strong><br>
                <span style="color: #4fc3f7; font-weight: bold; font-size: 1.05em;">Latest Run: ${latestFFDTime}</span>
            `;
            if (activeLayerNames.has('MRMS DVD Flash Flood Detector')) {
                ffdTimeBox.style.display = 'block';
            }
        }
    } catch (error) { console.log("Waiting for FFD Contours..."); }
}
fetchFFDData();
setInterval(fetchFFDData, 10 * 60 * 1000); 

// --- LIVE WPC GEOJSON (Day 1 ERO & MPDs) ---
function getEroStyle(feature) {
    const cat = (feature.properties.OUTLOOK || feature.properties.outlook || feature.properties.Outlook || "").toUpperCase();
    let riskColor = "#00ff00"; 
    if (cat.includes("SLGT") || cat.includes("SLIGHT")) riskColor = "#FFFF00"; 
    if (cat.includes("MDT") || cat.includes("MODERATE"))  riskColor = "#FF0000"; 
    if (cat.includes("HIGH")) riskColor = "#FF00FF"; 
    return { color: riskColor, weight: 2, fillOpacity: 0.15 };
}

function getMpdStyle(feature) {
    const propStr = JSON.stringify(feature.properties).toUpperCase();
    let lineColor = "#ff00ff"; 
    if (propStr.includes("POSSIBLE")) lineColor = "#0000FF"; 
    if (propStr.includes("LIKELY")) lineColor = "#C77DFF";   
    return { color: lineColor, weight: 3, dashArray: "5, 5", fillOpacity: 0.1 };
}

function formatMpdValidTime(properties) {
    const start = properties && properties.valid_start_utc
        ? new Date(properties.valid_start_utc)
        : null;
    const end = properties && properties.valid_end_utc
        ? new Date(properties.valid_end_utc)
        : null;

    const formatOfficialTime = date => {
        if (!(date instanceof Date) || Number.isNaN(date.getTime())) return null;
        const hours = String(date.getUTCHours()).padStart(2, '0');
        const minutes = String(date.getUTCMinutes()).padStart(2, '0');
        const month = date.toLocaleString('en-US', {
            month: 'short',
            timeZone: 'UTC'
        });
        const day = String(date.getUTCDate()).padStart(2, '0');
        const year = date.getUTCFullYear();
        return `${hours}${minutes}Z ${month} ${day} ${year}`;
    };

    const formattedStart = formatOfficialTime(start);
    const formattedEnd = formatOfficialTime(end);
    if (formattedStart && formattedEnd) {
        return `${formattedStart} - ${formattedEnd}`;
    }

    return properties && properties.valid_time
        ? properties.valid_time
        : 'Unknown';
}

const eroLayer = L.geoJSON(null, {
    pane: 'ero',
    style: getEroStyle,
    onEachFeature: function (feature, layer) {
        const cat = feature.properties.OUTLOOK || feature.properties.outlook || feature.properties.Outlook || "Unknown";
        layer.bindPopup(`
            <div style="text-align: center; font-family: sans-serif; background: white;">
                <strong>WPC Day 1 ERO</strong><br>Category: ${cat}<br><br>
                <a href="https://www.wpc.ncep.noaa.gov/discussions/qpferd.html" target="_blank" rel="noopener noreferrer">Read ERO Discussion</a>
            </div>
        `);
    }
});

const mpdLayer = L.geoJSON(null, {
    pane: 'mpd',
    style: getMpdStyle,
    onEachFeature: function (feature, layer) {
        const props = feature.properties;
        if (props && props.dataType === "MPD") {
            const mpdNum = props.mpd_number || "Unknown";
            const mpdTag = props.mpd_tag || "See WPC for details";
            const validTime = formatMpdValidTime(props);
            const currentYear = new Date().getUTCFullYear();
            
            const tooltipHTML = `<div style="text-align: center; font-family: sans-serif; line-height: 1.4;"><strong>MPD ${mpdNum}</strong><br>${mpdTag}<br>Valid: ${validTime}</div>`;
            layer.bindTooltip(tooltipHTML, { sticky: true, direction: "top" });
            
            const popupHTML = `
                <div style="font-family: sans-serif; font-size: 14px; min-width: 240px; text-align: center; background: white;">
                    <strong>MPD ${mpdNum}</strong><br>
                    <span style="color: #d84b2a;"><strong>${mpdTag}</strong></span><br>
                    <hr style="margin: 5px 0;">
                    <span style="font-size: 0.9em;">Valid: ${validTime}</span><br><br>
                    <a href="https://www.wpc.ncep.noaa.gov/metwatch/metwatch_mpd_multi.php?md=${mpdNum}&yr=${currentYear}" target="_blank" rel="noopener noreferrer">Read MPD Discussion</a>
                </div>
            `;
            layer.bindPopup(popupHTML);
        }
    }
});

eroLayer.addTo(map);
mpdLayer.addTo(map);

async function fetchWPCData() {
    try {
        const url = 'wpc_data.geojson?t=' + new Date().getTime();
        const response = await fetch(url);
        if (!response.ok) return;
        const data = await response.json();
        
        let eroFeatures = data.features.filter(f => f.properties.dataType === 'ERO');
        const mpdFeatures = data.features.filter(f => f.properties.dataType === 'MPD');
        
        eroFeatures.sort((a, b) => {
            const getRank = (feature) => {
                const cat = (feature.properties.OUTLOOK || feature.properties.outlook || feature.properties.Outlook || "").toUpperCase();
                if (cat.includes("HIGH")) return 4;
                if (cat.includes("MDT") || cat.includes("MODERATE")) return 3;
                if (cat.includes("SLGT") || cat.includes("SLIGHT")) return 2;
                return 1; 
            };
            return getRank(a) - getRank(b); 
        });
        
        eroLayer.clearLayers();
        mpdLayer.clearLayers();
        
        if (eroFeatures.length > 0) eroLayer.addData(eroFeatures);
        if (mpdFeatures.length > 0) mpdLayer.addData(mpdFeatures);
    } catch (error) { console.error("Error fetching WPC GeoJSON:", error); }
}

fetchWPCData();
setInterval(fetchWPCData, 5 * 60 * 1000); 

// --- RAP MESOANALYSIS LAYERS ---
const rapBounds = [[16.281, -139.856], [55.481, -57.373]]; 

// Base Fields
const pwatLayer = L.imageOverlay('static/rap_pwat.png', rapBounds, {zIndex: 10});
const sbcapeLayer = L.imageOverlay('static/rap_sbcape.png', rapBounds, {zIndex: 10});
const mlcapeLayer = L.imageOverlay('static/rap_mlcape.png', rapBounds, {zIndex: 10});
const mucapeLayer = L.imageOverlay('static/rap_mucape.png', rapBounds, {zIndex: 10});
const trans850Layer = L.imageOverlay('static/rap_trans850.png', rapBounds, {zIndex: 10});

// 3-Hour Change Fields
const pwatDiffLayer = L.imageOverlay('static/rap_pwat_diff.png', rapBounds, {zIndex: 10});
const sbcapeDiffLayer = L.imageOverlay('static/rap_sbcape_diff.png', rapBounds, {zIndex: 10});
const mlcapeDiffLayer = L.imageOverlay('static/rap_mlcape_diff.png', rapBounds, {zIndex: 10});
const mucapeDiffLayer = L.imageOverlay('static/rap_mucape_diff.png', rapBounds, {zIndex: 10});
const trans850DiffLayer = L.imageOverlay('static/rap_trans850_diff.png', rapBounds, {zIndex: 10});

// +3 Hour Forecast Fields
const pwatF03Layer = L.imageOverlay('static/rap_pwat_f03.png', rapBounds, {zIndex: 10});
const sbcapeF03Layer = L.imageOverlay('static/rap_sbcape_f03.png', rapBounds, {zIndex: 10});
const mlcapeF03Layer = L.imageOverlay('static/rap_mlcape_f03.png', rapBounds, {zIndex: 10});
const mucapeF03Layer = L.imageOverlay('static/rap_mucape_f03.png', rapBounds, {zIndex: 10});
const trans850F03Layer = L.imageOverlay('static/rap_trans850_f03.png', rapBounds, {zIndex: 10});

// Remaining Fields
const lrsfc3Layer = L.imageOverlay('static/rap_lr_sfc3.png', rapBounds, {zIndex: 10});
const lr75Layer = L.imageOverlay('static/rap_lr_75.png', rapBounds, {zIndex: 10});
const scpLayer = L.imageOverlay('static/rap_scp.png', rapBounds, {zIndex: 10});
const mfcLayer = L.imageOverlay('static/rap_mfc.png', rapBounds, {zIndex: 10});
const f925Layer = L.imageOverlay('static/rap_f925_850.png', rapBounds, {zIndex: 10});
const f850Layer = L.imageOverlay('static/rap_f850_700.png', rapBounds, {zIndex: 10});
const effShearLayer = L.imageOverlay('static/rap_eff_shear.png', rapBounds, {zIndex: 10});
const corfidiUpLayer = L.imageOverlay('static/rap_corfidi_up.png', rapBounds, {zIndex: 10});
const corfidiDownLayer = L.imageOverlay('static/rap_corfidi_down.png', rapBounds, {zIndex: 10});
const trans700Layer = L.imageOverlay('static/rap_trans700.png', rapBounds, {zIndex: 10});
const meanWindLayer = L.imageOverlay('static/rap_mean_wind.png', rapBounds, {zIndex: 10});
const vort500Layer = L.imageOverlay('static/rap_vort500.png', rapBounds, {zIndex: 10});
const diffAdvLayer = L.imageOverlay('static/rap_diff_adv.png', rapBounds, {zIndex: 10});
const div250Layer = L.imageOverlay('static/rap_div250.png', rapBounds, {zIndex: 10});

const allRapLayers = [
    pwatLayer, sbcapeLayer, mlcapeLayer, mucapeLayer, trans850Layer,
    pwatDiffLayer, sbcapeDiffLayer, mlcapeDiffLayer, mucapeDiffLayer, trans850DiffLayer,
    pwatF03Layer, sbcapeF03Layer, mlcapeF03Layer, mucapeF03Layer, trans850F03Layer,
    lrsfc3Layer, lr75Layer, scpLayer, mfcLayer, f925Layer, f850Layer, effShearLayer,
    corfidiUpLayer, corfidiDownLayer, trans700Layer, meanWindLayer, vort500Layer, diffAdvLayer, div250Layer
];

// --- NEW CAM NOWCAST ENSEMBLE LAYERS ---
const camLayers = {};
const camTempBounds = [[20, -130], [50, -60]]; 

['3h_to_9h', '9h_to_15h'].forEach(w => {
    ['href', 'refs', 'super'].forEach(m => {
        camLayers[`ffg_${w}_${m}`] = L.imageOverlay(`static/cam_ffg_${w}_${m}.png`, camTempBounds, {zIndex: 11});
        ['0.5_inch', '1_inch', '2_inch', '3_inch'].forEach(q => {
            camLayers[`qpf_${w}_${q}_${m}`] = L.imageOverlay(`static/cam_qpf_${w}_${q}_${m}.png`, camTempBounds, {zIndex: 11});
        });
    });
});

// --- NEW DAY 1 ERO CAM LAYERS ---
const eroCamLayers = {};
['href', 'refs', 'super'].forEach(m => {
    eroCamLayers[`ffg_${m}`] = L.imageOverlay(`static/ero_ffg_${m}.png`, camTempBounds, {zIndex: 11});
    ['0.5_inch', '1_inch', '2_inch', '3_inch'].forEach(q => {
        eroCamLayers[`qpf_${q}_${m}`] = L.imageOverlay(`static/ero_qpf_${q}_${m}.png`, camTempBounds, {zIndex: 11});
    });
});

// --- SOIL LAYERS (NWM & SPoRT) ---
// Leaflet's default map CRS is EPSG:3857. The Python scripts therefore
// pre-warp both PNGs to EPSG:3857 and publish WGS84 corner bounds in JSON.
//
// Start these overlays invisible. They are made visible only after valid
// metadata has been loaded, which prevents a stale or hard-coded rectangle
// from appearing before the exact bounds are known.
const NWM_IMAGE_URL = 'static/nwm_soil_saturation.png';
const SPORT_IMAGE_URL = 'static/sport_soil_percentile.png';
const NLDAS_RSM_0_10_IMAGE_URL = 'static/nldas_rsm_0_10cm.png';
const NLDAS_RSM_0_100_IMAGE_URL = 'static/nldas_rsm_0_100cm.png';
const soilPlaceholderBounds = [[24.0, -125.0], [50.0, -66.0]];

const nwmLayer = L.imageOverlay(
    NWM_IMAGE_URL,
    soilPlaceholderBounds,
    {zIndex: 10, opacity: 0, interactive: false}
);

const sportLayer = L.imageOverlay(
    SPORT_IMAGE_URL,
    soilPlaceholderBounds,
    {zIndex: 10, opacity: 0, interactive: false}
);

const nldasRsm010Layer = L.imageOverlay(
    NLDAS_RSM_0_10_IMAGE_URL,
    soilPlaceholderBounds,
    {zIndex: 10, opacity: 0, interactive: false}
);

const nldasRsm0100Layer = L.imageOverlay(
    NLDAS_RSM_0_100_IMAGE_URL,
    soilPlaceholderBounds,
    {zIndex: 10, opacity: 0, interactive: false}
);

let nwmLayerReady = false;
let sportLayerReady = false;
let nldasRsmReady = false;


// --- DYNAMIC METADATA FETCHING AND AUTO-UPDATING ---
let rapValidTime = "Unknown";
let rapValidTimeF03 = "Unknown";
let camCycles = { href: "Unknown", refs: "Unknown" };
let eroValidRangeStr = "Unknown";
let nwmValidTime = "Unknown";
let sportValidTime = "Unknown";
let nldasRsmValidTime = "Unknown";

function fetchRAPMetadata() {
    fetch('static/rap_metadata.json?t=' + new Date().getTime())
        .then(r => r.json())
        .then(data => {
            rapValidTime = data.valid_time || "Unknown";
            rapValidTimeF03 = data.valid_time_f03 || "Unknown"; 

            const timeBox = document.getElementById('rap-time-box');
            if (timeBox && timeBox.style.display === 'block') {
                let isF03 = false;
                [pwatF03Layer, sbcapeF03Layer, mlcapeF03Layer, mucapeF03Layer, trans850F03Layer].forEach(l => {
                    if(map.hasLayer(l)) isF03 = true;
                });
                timeBox.innerHTML = `<strong>${isF03 ? rapValidTimeF03 : rapValidTime}</strong>`;
            }

            if (data.bounds) {
                const exactBounds = L.latLngBounds(data.bounds[0], data.bounds[1]);
                allRapLayers.forEach(layer => {
                    layer.setBounds(exactBounds);
                    const base = layer._url.split('?')[0]; 
                    layer.setUrl(base + '?t=' + new Date().getTime()); 
                });
            }
        })
        .catch(err => console.log("RAP metadata not found yet."));
}

function fetchCAMMetadata() {
    fetch('static/cam_metadata.json?t=' + new Date().getTime())
        .then(r => r.json())
        .then(data => {
            if (data.valid_time) {
                const match = data.valid_time.match(/HREF (\d{2})Z \| REFS (\d{2})Z/);
                if (match) {
                    camCycles.href = match[1]; 
                    camCycles.refs = match[2];
                }
            }
            if (data.bounds) {
                const exactBounds = L.latLngBounds(data.bounds[0], data.bounds[1]);
                Object.values(camLayers).forEach(layer => {
                    layer.setBounds(exactBounds);
                    const base = layer._url.split('?')[0];
                    layer.setUrl(base + '?t=' + new Date().getTime());
                });
            }
        })
        .catch(err => console.log("CAM metadata not found yet."));
}

function fetchEROCAMMetadata() {
    fetch('static/ero_cam_metadata.json?t=' + new Date().getTime())
        .then(r => r.json())
        .then(data => {
            if (data.ero_window_str) eroValidRangeStr = data.ero_window_str;
            if (data.bounds) {
                const exactBounds = L.latLngBounds(data.bounds[0], data.bounds[1]);
                Object.values(eroCamLayers).forEach(layer => {
                    layer.setBounds(exactBounds);
                    const base = layer._url.split('?')[0];
                    layer.setUrl(base + '?t=' + new Date().getTime());
                });
            }
        })
        .catch(err => console.log("ERO CAM metadata not found yet."));
}

function validateRasterBounds(bounds, productName) {
    if (
        !Array.isArray(bounds) ||
        bounds.length !== 2 ||
        !Array.isArray(bounds[0]) ||
        !Array.isArray(bounds[1]) ||
        bounds[0].length !== 2 ||
        bounds[1].length !== 2
    ) {
        throw new Error(`${productName}: invalid bounds structure`);
    }

    const south = Number(bounds[0][0]);
    const west = Number(bounds[0][1]);
    const north = Number(bounds[1][0]);
    const east = Number(bounds[1][1]);

    if (![south, west, north, east].every(Number.isFinite)) {
        throw new Error(`${productName}: non-numeric bounds`);
    }

    if (south >= north || west >= east) {
        throw new Error(`${productName}: reversed or zero-area bounds`);
    }

    if (
        south < -85.0512 ||
        north > 85.0512 ||
        west < -180 ||
        east > 180
    ) {
        throw new Error(`${productName}: bounds outside Web Mercator limits`);
    }

    return L.latLngBounds(
        [south, west],
        [north, east]
    );
}

function cacheBustedRasterUrl(baseUrl, metadata) {
    // Prefer retrieval time rather than valid time. SPoRT has the same 00Z
    // valid time all day, so using valid_time_iso can leave an older PNG in
    // browser/CDN cache after a corrected workflow rerun.
    const versionParts = [
        metadata.retrieved_time,
        metadata.generated_time_utc,
        metadata.render_revision,
        metadata.valid_time_iso,
        metadata.window_end_utc,
        Date.now()
    ].filter(Boolean);

    return `${baseUrl}?v=${encodeURIComponent(versionParts.join('-'))}`;
}

function applySoilRasterMetadata({
    metadata,
    layer,
    baseUrl,
    productName,
    opacity = 1.0
}) {
    // ImageOverlay linearly places the image in the map's projected
    // coordinate space. The PNG itself must therefore be EPSG:3857.
    const imageCrs = String(
        metadata.image_crs ||
        metadata.crs ||
        ""
    ).toUpperCase();

    if (imageCrs !== "EPSG:3857") {
        throw new Error(
            `${productName}: expected an EPSG:3857 PNG, found ` +
            `${imageCrs || "no image CRS"}`
        );
    }

    const exactBounds = validateRasterBounds(
        metadata.bounds,
        productName
    );

    layer.setBounds(exactBounds);
    layer.setUrl(
        cacheBustedRasterUrl(baseUrl, metadata)
    );
    layer.setOpacity(opacity);

    console.info(
        `${productName} raster updated`,
        {
            bounds: metadata.bounds,
            validTime: metadata.valid_time_iso,
            imageCrs
        }
    );
}


function formatMetadataUTC(value) {
    if (!value) return "Unknown";
    const parsed = new Date(value);
    return Number.isNaN(parsed.getTime()) ? "Unknown" : formatUTC(parsed);
}

function formatMRMSFlashTimeBox(title, metadata) {
    if (!metadata) {
        return `
            <strong>${title}</strong><br>
            <span style="color: #ffeb3b;">Loading latest synchronized raster...</span>
        `;
    }

    const windowHours = Number(metadata.window_hours);
    const start = formatMetadataUTC(metadata.window_start_utc);
    const end = formatMetadataUTC(metadata.window_end_utc);
    const generated = formatMetadataUTC(metadata.generated_time_utc);
    const processed = Number(metadata.processed_cycles);
    const expected = Number(metadata.expected_cycles);
    const completeness = Number(metadata.completeness_fraction);
    const completenessText = (
        Number.isFinite(processed) &&
        Number.isFinite(expected) &&
        expected > 0
    )
        ? `${processed}/${expected} cycles` +
          (Number.isFinite(completeness)
              ? ` (${Math.round(completeness * 100)}%)`
              : "")
        : "Completeness unavailable";

    return `
        <strong>${title}</strong><br>
        <span style="color: #4fc3f7; font-weight: bold;">
            Rolling ${Number.isFinite(windowHours) ? windowHours : 24}-Hour Maximum
        </span><br>
        <span style="color: #ffeb3b;">${start} &mdash; ${end}</span><br>
        <span style="font-size: 0.86em;">${completenessText}</span><br>
        <span style="font-size: 0.82em; color: #d0d0d0;">Generated: ${generated}</span>
    `;
}

function updateMRMSFlashTimeBoxes() {
    const crestTimeBox = document.getElementById('mrms-crest-24h-time-box');
    if (crestTimeBox && crestTimeBox.style.display === 'block') {
        crestTimeBox.innerHTML = formatMRMSFlashTimeBox(
            'MRMS FLASH CREST Unit Q',
            mrmsCrest24hMetadata
        );
    }

    const ffdTimeBox = document.getElementById('mrms-ffd-24h-time-box');
    if (ffdTimeBox && ffdTimeBox.style.display === 'block') {
        ffdTimeBox.innerHTML = formatMRMSFlashTimeBox(
            'MRMS FLASH Flood Detector',
            mrmsFfd24hMetadata
        );
    }
}

function applyMRMSFlashRasterMetadata({
    metadata,
    layer,
    baseUrl,
    productName,
    defaultOpacity
}) {
    const grid = metadata && metadata.grid ? metadata.grid : {};
    const imageCrs = String(grid.image_crs || "").toUpperCase();

    if (metadata.metadata_mode !== "dashboard_compact") {
        throw new Error(`${productName}: metadata is not dashboard_compact`);
    }
    if (imageCrs !== "EPSG:3857") {
        throw new Error(
            `${productName}: expected an EPSG:3857 PNG, found ` +
            `${imageCrs || "no image CRS"}`
        );
    }

    const exactBounds = validateRasterBounds(
        grid.leaflet_bounds,
        productName
    );

    const normalizedMetadata = {
        generated_time_utc: metadata.generated_time_utc,
        window_end_utc: metadata.window_end_utc,
        valid_time_iso: metadata.window_end_utc
    };

    layer.setBounds(exactBounds);
    layer.setUrl(cacheBustedRasterUrl(baseUrl, normalizedMetadata));
    layer.setOpacity(defaultOpacity);

    console.info(
        `${productName} raster updated`,
        {
            bounds: grid.leaflet_bounds,
            windowStart: metadata.window_start_utc,
            windowEnd: metadata.window_end_utc,
            processedCycles: metadata.processed_cycles,
            expectedCycles: metadata.expected_cycles,
            imageCrs
        }
    );
}

async function fetchMRMSFlash24hMetadata() {
    try {
        const cacheToken = Date.now();
        const [crestResponse, ffdResponse] = await Promise.all([
            fetch(
                `${MRMS_CREST_24H_METADATA_URL}?t=${cacheToken}`,
                {cache: 'no-store'}
            ),
            fetch(
                `${MRMS_FFD_24H_METADATA_URL}?t=${cacheToken}`,
                {cache: 'no-store'}
            )
        ]);

        if (!crestResponse.ok) {
            throw new Error(`CREST metadata HTTP ${crestResponse.status}`);
        }
        if (!ffdResponse.ok) {
            throw new Error(`FFD metadata HTTP ${ffdResponse.status}`);
        }

        const [crestData, ffdData] = await Promise.all([
            crestResponse.json(),
            ffdResponse.json()
        ]);

        if (
            crestData.window_start_utc !== ffdData.window_start_utc ||
            crestData.window_end_utc !== ffdData.window_end_utc
        ) {
            throw new Error(
                'MRMS FLASH CREST and FFD rolling windows are not synchronized'
            );
        }

        const crestOpacity = mrmsCrest24hReady
            ? Number(mrmsCrest24hLayer.options.opacity ?? 0.88)
            : 0.88;
        const ffdOpacity = mrmsFfd24hReady
            ? Number(mrmsFfd24hLayer.options.opacity ?? 0.88)
            : 0.88;

        applyMRMSFlashRasterMetadata({
            metadata: crestData,
            layer: mrmsCrest24hLayer,
            baseUrl: MRMS_CREST_24H_IMAGE_URL,
            productName: 'MRMS FLASH CREST Unit Q 24-hour maximum',
            defaultOpacity: crestOpacity
        });

        applyMRMSFlashRasterMetadata({
            metadata: ffdData,
            layer: mrmsFfd24hLayer,
            baseUrl: MRMS_FFD_24H_IMAGE_URL,
            productName: 'MRMS FLASH FFD 24-hour maximum',
            defaultOpacity: ffdOpacity
        });

        mrmsCrest24hMetadata = crestData;
        mrmsFfd24hMetadata = ffdData;
        mrmsCrest24hReady = true;
        mrmsFfd24hReady = true;
        updateMRMSFlashTimeBoxes();
    } catch (error) {
        if (!mrmsCrest24hReady) mrmsCrest24hLayer.setOpacity(0);
        if (!mrmsFfd24hReady) mrmsFfd24hLayer.setOpacity(0);
        console.error('MRMS FLASH rolling 24-hour raster update failed:', error);

        const crestTimeBox = document.getElementById('mrms-crest-24h-time-box');
        if (
            crestTimeBox &&
            crestTimeBox.style.display === 'block' &&
            !mrmsCrest24hReady
        ) {
            crestTimeBox.innerHTML = `
                <strong>MRMS FLASH CREST Unit Q</strong><br>
                <span style="color: #ff8080;">Latest raster unavailable</span>
            `;
        }

        const ffdTimeBox = document.getElementById('mrms-ffd-24h-time-box');
        if (
            ffdTimeBox &&
            ffdTimeBox.style.display === 'block' &&
            !mrmsFfd24hReady
        ) {
            ffdTimeBox.innerHTML = `
                <strong>MRMS FLASH Flood Detector</strong><br>
                <span style="color: #ff8080;">Latest raster unavailable</span>
            `;
        }
    }
}


function glmCompletenessText(metadata) {
    if (!metadata) return 'Completeness unavailable';
    if (metadata.product_role === 'controlled_mosaic') {
        const inputs = metadata.satellite_inputs || {};
        return ['G18', 'G19'].map(satellite => {
            const stats = inputs[satellite] || {};
            const processed = Number(stats.processed_files);
            const expected = Number(stats.expected_files);
            const fraction = Number(stats.completeness_fraction);
            if (!Number.isFinite(processed) || !Number.isFinite(expected) || expected <= 0) {
                return `${satellite}: unavailable`;
            }
            return `${satellite}: ${processed}/${expected}` +
                (Number.isFinite(fraction) ? ` (${Math.round(fraction * 100)}%)` : '');
        }).join(' &nbsp;|&nbsp; ');
    }
    if (metadata.product_role === 'convective_trend_map') {
        const summary = metadata.input_slot_summary || {};
        const recent = `${Number(summary.recent_available_slots) || 0}/${Number(summary.recent_required_slots) || 0}`;
        const prior = `${Number(summary.prior_available_slots) || 0}/${Number(summary.prior_required_slots) || 0}`;
        const hour = Number(summary.hour_available_slots);
        return `Recent slots: ${recent} &nbsp;|&nbsp; Prior slots: ${prior}` + (Number.isFinite(hour) ? ` &nbsp;|&nbsp; Hour slots: ${hour}/12` : '');
    }
    const processed = Number(metadata.processed_files);
    const expected = Number(metadata.expected_files);
    const fraction = Number(metadata.completeness_fraction);
    if (!Number.isFinite(processed) || !Number.isFinite(expected) || expected <= 0) {
        return 'Completeness unavailable';
    }
    return `${processed}/${expected} files` +
        (Number.isFinite(fraction) ? ` (${Math.round(fraction * 100)}%)` : '');
}

function formatGLMTimeBox(config, metadata) {
    if (!metadata) {
        return `
            <strong>${config.name}</strong><br>
            <span style="color: #ffeb3b;">Loading latest GLM raster...</span>
        `;
    }
    if (config.productRole === 'source_ownership_debug') {
        const geometry = metadata.satellite_geometry || {};
        const seam = Number(geometry.nominal_equal_angle_seam_longitude);
        return `
            <strong>${config.name}</strong><br>
            <span style="color: #4fc3f7; font-weight: bold;">Exclusive source assignment</span><br>
            <span style="color: #ffeb3b;">Nominal seam: ${Number.isFinite(seam) ? `${Math.abs(seam).toFixed(1)}°W` : 'Unknown'}</span><br>
            <span style="font-size: 0.82em; color: #d0d0d0;">Generated: ${formatMetadataUTC(metadata.generated_time_utc)}</span>
        `;
    }
    const start = formatMetadataUTC(metadata.window_start_utc);
    const end = formatMetadataUTC(metadata.window_end_utc);
    const maximum = Number(metadata.maximum_value);
    return `
        <strong>${config.name}</strong><br>
        <span style="color: #ffeb3b;">${start} &mdash; ${end}</span><br>
        <span style="font-size: 0.86em;">${glmCompletenessText(metadata)}</span><br>
        <span style="font-size: 0.86em; color: #4fc3f7;">Maximum: ${Number.isFinite(maximum) ? maximum : 'Unknown'}</span><br>
        <span style="font-size: 0.82em; color: #d0d0d0;">Generated: ${formatMetadataUTC(metadata.generated_time_utc)}</span>
    `;
}

function prepareGLMRasterMetadata(config, metadata) {
    if (!metadata || metadata.metadata_mode !== 'glm_dashboard_v1') {
        throw new Error(`${config.name}: invalid GLM metadata mode`);
    }
    if (metadata.product_role !== config.productRole) {
        throw new Error(`${config.name}: unexpected product role ${metadata.product_role}`);
    }
    if (config.productRole === 'controlled_mosaic') {
        const method = metadata.mosaic_method || {};
        if (
            method.summation !== false ||
            method.averaging !== false ||
            method.blending !== false ||
            method.secondary_source_gap_fill !== false
        ) {
            throw new Error(`${config.name}: controlled-mosaic safeguards failed`);
        }
    }
    metadata.rendering = validateGLMRenderingMetadata(metadata, config.name);
    const grid = metadata.grid || {};
    const imageCrs = String(grid.image_crs || '').toUpperCase();
    if (imageCrs !== 'EPSG:3857') {
        throw new Error(`${config.name}: expected EPSG:3857 PNG, found ${imageCrs || 'none'}`);
    }
    const bounds = validateRasterBounds(grid.leaflet_bounds, config.name);
    const currentOpacity = glmReadyNames.has(config.name)
        ? Number(config.layer.options.opacity ?? config.defaultOpacity)
        : Number(metadata.default_opacity ?? config.defaultOpacity);
    let rasterUrl = cacheBustedRasterUrl(config.imageUrl, {
        generated_time_utc: metadata.generated_time_utc,
        valid_time_iso: metadata.window_end_utc || metadata.generated_time_utc
    });
    if (config.embeddedImageField) {
        const encoded = metadata?.[config.embeddedImageField];
        if (typeof encoded !== 'string' || encoded.length < 100) {
            throw new Error(`${config.name}: embedded trend PNG missing from metadata`);
        }
        rasterUrl = `data:image/png;base64,${encoded}`;
    }
    return {
        config,
        metadata,
        bounds,
        rasterUrl,
        opacity: Number.isFinite(currentOpacity) ? currentOpacity : config.defaultOpacity
    };
}

function commitGLMRasterMetadata(prepared) {
    const {config, metadata, bounds, rasterUrl, opacity} = prepared;
    config.layer.setBounds(bounds);
    config.layer.setUrl(rasterUrl);
    config.layer.setOpacity(opacity);
    glmMetadataByName.set(config.name, metadata);
    glmReadyNames.add(config.name);
}

function applyGLMRasterMetadata(config, metadata) {
    commitGLMRasterMetadata(prepareGLMRasterMetadata(config, metadata));
}

function updateGLMTimeBox(preferredName = null) {
    const timeBox = document.getElementById('glm-time-box');
    if (!timeBox) return;
    let config = preferredName ? glmConfigByName.get(preferredName) : null;
    if (!config || !map.hasLayer(config.layer)) {
        config = GLM_LAYER_CONFIGS.find(item => map.hasLayer(item.layer)) || null;
    }
    if (!config) {
        timeBox.style.display = 'none';
        refreshLegendDockSummary();
        return;
    }
    timeBox.innerHTML = formatGLMTimeBox(config, glmMetadataByName.get(config.name));
    timeBox.style.display = 'block';
    refreshLegendDockSummary();
}


function getGLMTrendPayload() {
    for (const config of GLM_LAYER_CONFIGS) {
        const trend = glmMetadataByName.get(config.name)?.convective_trend;
        if (trend && trend.metadata_mode === 'glm_convective_trend_v1') return trend;
    }
    return null;
}

function readGLMTrendDomain(payload) {
    let stored = '';
    try {
        stored = window.sessionStorage.getItem(GLM_TREND_SESSION_KEY) || '';
    } catch (error) {
        stored = '';
    }
    if (stored && payload?.domains?.[stored]) return stored;
    const fallback = payload?.default_domain_id || 'conus';
    return payload?.domains?.[fallback] ? fallback : Object.keys(payload?.domains || {})[0];
}

function writeGLMTrendDomain(domainId) {
    try {
        window.sessionStorage.setItem(GLM_TREND_SESSION_KEY, domainId);
    } catch (error) {
        // Session storage is optional; the selected domain still works in-page.
    }
}

function formatGLMTrendInteger(value) {
    const number = Number(value);
    return Number.isFinite(number) ? Math.round(number).toLocaleString() : '—';
}

function formatGLMTrendPercent(value) {
    const number = Number(value);
    if (!Number.isFinite(number)) return '—';
    const rounded = Math.round(number);
    return `${rounded > 0 ? '+' : ''}${rounded}%`;
}

function buildGLMTrendSparkline(series, color) {
    const width = 280;
    const height = 68;
    const paddingX = 4;
    const paddingY = 7;
    const values = (series || []).map(item => {
        const value = Number(item?.flash_extent_contributions);
        return item?.available && Number.isFinite(value) ? value : null;
    });
    const finite = values.filter(value => value !== null);
    if (!finite.length) {
        return '<div style="padding:22px 0;color:#91a6b6;font-size:9px;text-align:center;">Trend history unavailable</div>';
    }

    const minimum = Math.min(...finite);
    const maximum = Math.max(...finite);
    const span = Math.max(1, maximum - minimum);
    const xFor = index => paddingX + (
        (width - (2 * paddingX)) * index / Math.max(1, values.length - 1)
    );
    const yFor = value => paddingY + (
        (height - (2 * paddingY)) * (1 - ((value - minimum) / span))
    );

    const segments = [];
    let current = [];
    values.forEach((value, index) => {
        if (value === null) {
            if (current.length) segments.push(current);
            current = [];
            return;
        }
        current.push(`${xFor(index).toFixed(1)},${yFor(value).toFixed(1)}`);
    });
    if (current.length) segments.push(current);

    const lines = segments.map(points => (
        `<polyline points="${points.join(' ')}" fill="none" stroke="${color}" ` +
        'stroke-width="3" stroke-linecap="round" stroke-linejoin="round" />'
    )).join('');
    const points = values.map((value, index) => value === null ? '' : (
        `<circle cx="${xFor(index).toFixed(1)}" cy="${yFor(value).toFixed(1)}" ` +
        `r="${index === values.length - 1 ? 3.1 : 1.7}" fill="${color}" />`
    )).join('');

    return `
        <svg viewBox="0 0 ${width} ${height}" width="100%" height="68" role="img" aria-label="Sixty-minute GLM convective trend history">
            <line x1="4" y1="34" x2="276" y2="34" stroke="rgba(255,255,255,0.09)" stroke-width="1" />
            ${lines}${points}
        </svg>
    `;
}

function updateGLMTrendCard() {
    const card = document.getElementById('glm-trend-card');
    if (!card) return;
    const hasActiveGLM = GLM_LAYER_CONFIGS.some(config => map.hasLayer(config.layer));
    if (!hasActiveGLM) {
        card.style.display = 'none';
        card.innerHTML = '';
        refreshLegendDockSummary();
        return;
    }

    card.style.display = 'block';
    const payload = getGLMTrendPayload();
    if (!payload) {
        card.innerHTML = `
            <div class="glm-trend-card__header">
                <div>
                    <div class="glm-trend-card__kicker">Real-Time Diagnostic</div>
                    <div class="glm-trend-card__title">GLM Convective Trend</div>
                </div>
            </div>
            <div class="glm-trend-card__body" style="color:#ffdf7e;font-size:10px;line-height:1.35;">
                Trend metadata will populate after the next GLM generator update.
            </div>
        `;
        refreshLegendDockSummary();
        return;
    }

    const selectedId = readGLMTrendDomain(payload);
    const selected = payload.domains?.[selectedId];
    if (!selected) {
        card.innerHTML = '<div class="glm-trend-card__body">GLM trend domain unavailable.</div>';
        refreshLegendDockSummary();
        return;
    }

    const presentation = GLM_TREND_STATE_PRESENTATION[selected.classification]
        || GLM_TREND_STATE_PRESENTATION.insufficient_data;
    const options = (payload.domain_order || Object.keys(payload.domains)).map(domainId => {
        const domain = payload.domains[domainId];
        return `<option value="${escapeGLMLegendText(domainId)}"${domainId === selectedId ? ' selected' : ''}>${escapeGLMLegendText(domain.label)}</option>`;
    }).join('');

    const leaderId = payload.leading_increase_domain_id;
    const leader = leaderId ? payload.domains?.[leaderId] : null;
    const highestId = payload.highest_activity_domain_id;
    const highest = highestId ? payload.domains?.[highestId] : null;
    let regionalLine = '<strong>Regional signal:</strong> No UFVS domain is currently classified as increasing.';
    if (leader) {
        regionalLine = `<strong>Strongest acceleration:</strong> ${escapeGLMLegendText(leader.label)} (${formatGLMTrendPercent(leader.symmetric_change_percent)}).`;
    } else if (highest) {
        regionalLine = `<strong>Highest recent activity:</strong> ${escapeGLMLegendText(highest.label)}.`;
    }

    card.innerHTML = `
        <div class="glm-trend-card__header">
            <div>
                <div class="glm-trend-card__kicker">Real-Time Diagnostic</div>
                <div class="glm-trend-card__title">GLM Convective Trend</div>
            </div>
            <select id="glm-trend-domain-select" class="glm-trend-card__select" aria-label="Select GLM trend domain">
                ${options}
            </select>
        </div>
        <div class="glm-trend-card__body">
            <div class="glm-trend-card__state-row">
                <span class="glm-trend-card__state" style="color:${presentation.color};background:${presentation.background};">
                    <span aria-hidden="true">${presentation.symbol}</span>
                    ${escapeGLMLegendText(presentation.label)}
                </span>
                <div class="glm-trend-card__change">
                    ${formatGLMTrendPercent(selected.symmetric_change_percent)}
                    <span class="glm-trend-card__change-label">15-min change</span>
                </div>
            </div>
            <div class="glm-trend-card__sparkline">
                ${buildGLMTrendSparkline(selected.series, presentation.color)}
                <div class="glm-trend-card__axis"><span>−60 min</span><span>Latest 5 min</span></div>
            </div>
            <div class="glm-trend-card__metrics">
                <div class="glm-trend-card__metric">
                    <div class="glm-trend-card__metric-value">${formatGLMTrendInteger(selected.latest_value)}</div>
                    <div class="glm-trend-card__metric-label">Current 5-min contributions</div>
                </div>
                <div class="glm-trend-card__metric">
                    <div class="glm-trend-card__metric-value">${formatGLMTrendInteger(selected.latest_active_grid_cells)}</div>
                    <div class="glm-trend-card__metric-label">Active grid cells</div>
                </div>
                <div class="glm-trend-card__metric">
                    <div class="glm-trend-card__metric-value">${formatGLMTrendInteger(selected.peak_value_last_60min)}</div>
                    <div class="glm-trend-card__metric-label">60-min peak</div>
                </div>
            </div>
            <div class="glm-trend-card__regional">${regionalLine}</div>
            <div class="glm-trend-card__footnote">
                Controlled-mosaic five-minute flash-extent contributions. The map layer shows local gridcell trend classifications plus muted gray past-hour lightning context, while this card summarizes the selected domain. Classification compares the newest 15-minute neighborhood sum with the preceding 15-minute neighborhood sum. Valid through ${formatMetadataUTC(payload.window_end_utc)}.
            </div>
        </div>
    `;

    const selector = card.querySelector('#glm-trend-domain-select');
    if (selector) {
        selector.addEventListener('change', event => {
            writeGLMTrendDomain(event.target.value);
            updateGLMTrendCard();
        });
    }
    refreshLegendDockSummary();
}

async function fetchGLMMetadata(configs = GLM_LAYER_CONFIGS, options = {}) {
    const expectedWindowEnd = options?.expectedWindowEnd || null;
    const requireComplete = Boolean(options?.requireComplete);
    const cacheToken = Date.now();
    const results = await Promise.allSettled(configs.map(async config => {
        const response = await fetch(`${config.metadataUrl}?t=${cacheToken}`, {cache: 'no-store'});
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const metadata = await response.json();
        return prepareGLMRasterMetadata(config, metadata);
    }));

    const preparedRecords = [];
    results.forEach((result, index) => {
        const config = configs[index];
        if (result.status === 'fulfilled') {
            preparedRecords.push(result.value);
            return;
        }
        if (!glmReadyNames.has(config.name)) config.layer.setOpacity(0);
        console.error(`GLM raster update failed for ${config.name}:`, result.reason);
    });

    if (requireComplete && preparedRecords.length !== configs.length) {
        return false;
    }

    const operationalRequested = configs.filter(config => !config.debug);
    const operationalPrepared = preparedRecords.filter(item => !item.config.debug);
    const operationalEnds = operationalPrepared
        .map(item => item.metadata.window_end_utc)
        .filter(Boolean);

    if (
        expectedWindowEnd &&
        operationalPrepared.some(item => item.metadata.window_end_utc !== expectedWindowEnd)
    ) {
        console.warn('GOES GLM files are still propagating through GitHub Pages; retaining the previous package.');
        return false;
    }

    if (
        operationalPrepared.length === operationalRequested.length &&
        operationalEnds.length === operationalRequested.length &&
        new Set(operationalEnds).size !== 1
    ) {
        console.error('GOES GLM operational products are not synchronized:', operationalEnds);
        return false;
    }

    preparedRecords.forEach(commitGLMRasterMetadata);
    updateGLMTimeBox();
    updateGLMTrendCard();
    if (typeof updateLegends === 'function') updateLegends();
    return preparedRecords.length > 0 && (!requireComplete || preparedRecords.length === configs.length);
}

function glmManifestVersion(manifest) {
    return [manifest?.window_end_utc || '', manifest?.generated_time_utc || ''].join('|');
}

function waitForGLMRefresh(milliseconds) {
    return new Promise(resolve => window.setTimeout(resolve, milliseconds));
}

async function fetchGLMManifest() {
    const response = await fetch(`${GLM_MANIFEST_URL}?t=${Date.now()}`, {cache: 'no-store'});
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const manifest = await response.json();
    if (!manifest || manifest.metadata_mode !== 'glm_dashboard_v1' || !manifest.window_end_utc) {
        throw new Error('Invalid GLM manifest');
    }
    return manifest;
}

async function refreshGLMFromManifest({forceMetadata = false} = {}) {
    if (glmManifestCheckInFlight) return false;
    glmManifestCheckInFlight = true;
    try {
        const manifest = await fetchGLMManifest();
        const version = glmManifestVersion(manifest);
        if (!forceMetadata && version && version === glmLastManifestVersion) {
            return false;
        }

        for (const delay of GLM_MANIFEST_RETRY_DELAYS_MS) {
            if (delay > 0) await waitForGLMRefresh(delay);
            const refreshed = await fetchGLMMetadata(GLM_LAYER_CONFIGS, {
                expectedWindowEnd: manifest.window_end_utc,
                requireComplete: true
            });
            if (refreshed) {
                glmLastManifestVersion = version;
                return true;
            }
        }
        console.warn('GOES GLM manifest changed, but the complete synchronized package is not available yet.');
        return false;
    } catch (error) {
        console.error('GOES GLM manifest check failed:', error);
        if (forceMetadata && glmReadyNames.size === 0) {
            return fetchGLMMetadata(GLM_LAYER_CONFIGS, {requireComplete: true});
        }
        return false;
    } finally {
        glmManifestCheckInFlight = false;
    }
}

function checkGLMUpdatesNow() {
    refreshGLMFromManifest();
}

window.setInterval(() => {
    if (!document.hidden) checkGLMUpdatesNow();
}, GLM_MANIFEST_POLL_INTERVAL_MS);

document.addEventListener('visibilitychange', () => {
    if (!document.hidden) checkGLMUpdatesNow();
});
window.addEventListener('focus', checkGLMUpdatesNow);
window.addEventListener('online', checkGLMUpdatesNow);


function validateLightningCastBounds(bounds) {
    if (!Array.isArray(bounds) || bounds.length !== 2) {
        throw new Error('LightningCast metadata has invalid Leaflet bounds');
    }
    const south = Number(bounds[0]?.[0]);
    const west = Number(bounds[0]?.[1]);
    const north = Number(bounds[1]?.[0]);
    const east = Number(bounds[1]?.[1]);
    if (![south, west, north, east].every(Number.isFinite) || south >= north || west >= east) {
        throw new Error('LightningCast metadata has malformed geographic bounds');
    }
    return [[south, west], [north, east]];
}

function validateLightningCastMetadata(metadata, expectedScanTime = null) {
    if (!metadata || metadata.metadata_mode !== 'lightningcast_dashboard_v1e') {
        throw new Error('Invalid LightningCast metadata mode');
    }
    if (metadata.product_role !== 'probability_of_lightning_next_60_minutes') {
        throw new Error(`Unexpected LightningCast product role: ${metadata.product_role}`);
    }
    const thresholds = metadata.probability_thresholds_percent || [];
    if (JSON.stringify(thresholds) !== JSON.stringify([10, 30, 50, 70, 90])) {
        throw new Error('LightningCast probability threshold contract failed');
    }
    if (expectedScanTime && metadata.scan_time_utc !== expectedScanTime) {
        throw new Error(`LightningCast scan mismatch: expected ${expectedScanTime}, found ${metadata.scan_time_utc}`);
    }
    const rendering = metadata.rendering || {};
    if (String(rendering.image_crs || '').toUpperCase() !== 'EPSG:3857') {
        throw new Error(`LightningCast expected EPSG:3857 image, found ${rendering.image_crs || 'none'}`);
    }
    if (rendering.contour_lines_only !== true || rendering.polygon_fill_inference !== false) {
        throw new Error('LightningCast contour-only rendering contract failed');
    }
    const rgb = rendering.source_threshold_rgb || [];
    if (!Array.isArray(rgb) || rgb.length !== 5) {
        throw new Error('LightningCast source-color contract failed');
    }
    const ownership = metadata.satellite_ownership || {};
    if (
        ownership.summation !== false ||
        ownership.averaging !== false ||
        ownership.blending !== false ||
        ownership.gap_fill !== false ||
        ownership.cross_boundary_geometry_clipping !== false ||
        ownership.cross_threshold_family_splitting !== false ||
        ownership.cross_satellite_family_splitting !== false
    ) {
        throw new Error('LightningCast source-ownership safeguards failed');
    }
    return {
        metadata,
        bounds: validateLightningCastBounds(rendering.leaflet_bounds)
    };
}

function lightningCastRasterUrl(metadata) {
    const version = encodeURIComponent(metadata.generated_time_utc || metadata.scan_time_utc || Date.now());
    return `${LIGHTNINGCAST_IMAGE_URL}?v=${version}`;
}

function preloadLightningCastImage(url) {
    return new Promise((resolve, reject) => {
        const image = new Image();
        image.onload = () => resolve(url);
        image.onerror = () => reject(new Error('LightningCast raster failed to preload'));
        image.src = url;
    });
}

async function fetchLightningCastMetadata({expectedScanTime = null} = {}) {
    const response = await fetch(`${LIGHTNINGCAST_METADATA_URL}?t=${Date.now()}`, {cache: 'no-store'});
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const metadata = await response.json();
    const validated = validateLightningCastMetadata(metadata, expectedScanTime);
    const rasterUrl = lightningCastRasterUrl(metadata);
    await preloadLightningCastImage(rasterUrl);

    const currentOpacity = Number(lightningCastLayer.options?.opacity);
    lightningCastLayer.setBounds(validated.bounds);
    lightningCastLayer.setUrl(rasterUrl);
    lightningCastLayer.setOpacity(
        lightningCastReady && Number.isFinite(currentOpacity) ? currentOpacity : 1.0
    );
    lightningCastMetadata = metadata;
    lightningCastReady = true;
    updateLightningCastTimeBox();
    if (typeof updateLegends === 'function') updateLegends();
    return true;
}

function formatLightningCastTimeBox(metadata) {
    if (!metadata) {
        return `
            <strong>${LIGHTNINGCAST_LAYER_NAME}</strong><br>
            <span style="color:#ffeb3b;">Loading latest LightningCast contours...</span>
        `;
    }
    return `
        <strong>${LIGHTNINGCAST_LAYER_NAME}</strong><br>
        <span style="color:#4fc3f7;font-weight:bold;">Scan: ${formatMetadataUTC(metadata.scan_time_utc)}</span><br>
        <span style="color:#ffeb3b;">Probability window: ${formatMetadataUTC(metadata.forecast_window_start_utc)} &mdash; ${formatMetadataUTC(metadata.forecast_window_end_utc)}</span><br>
        <span style="font-size:0.82em;color:#d0d0d0;">LightningCast data courtesy CIMSS/SSEC</span>
    `;
}

function updateLightningCastTimeBox() {
    const box = document.getElementById('lightningcast-time-box');
    if (!box) return;
    if (!map.hasLayer(lightningCastLayer)) {
        box.style.display = 'none';
        refreshLegendDockSummary();
        return;
    }
    box.innerHTML = formatLightningCastTimeBox(lightningCastMetadata);
    box.style.display = 'block';
    refreshLegendDockSummary();
}

function buildLightningCastLegendHTML() {
    const thresholds = lightningCastMetadata?.probability_thresholds_percent || [10, 30, 50, 70, 90];
    const colors = lightningCastMetadata?.rendering?.source_threshold_rgb || [
        [80, 201, 134], [255, 255, 81], [255, 192, 108], [255, 80, 80], [255, 80, 255]
    ];
    const rows = thresholds.map((threshold, index) => {
        const rgb = colors[index] || [255, 255, 255];
        return `
            <div style="display:grid;grid-template-columns:28px minmax(0,1fr);align-items:center;gap:7px;">
                <span style="display:block;width:26px;height:0;border-top:3px solid rgb(${rgb[0]},${rgb[1]},${rgb[2]});"></span>
                <span style="font-size:10px;font-weight:700;line-height:1.15;">${threshold}%</span>
            </div>
        `;
    }).join('');
    return `
        <div style="box-sizing:border-box;width:100%;background:white;padding:9px;border-radius:5px;color:black;font-family:sans-serif;">
            <strong style="display:block;font-size:13px;line-height:1.2;text-align:center;">CIMSS/SSEC LightningCast</strong>
            <span style="display:block;margin-top:2px;font-size:9px;line-height:1.2;text-align:center;">Probability of lightning in the next 60 minutes</span>
            <div style="display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:7px 14px;margin-top:8px;">${rows}</div>
            <span style="display:block;margin-top:7px;font-size:8px;line-height:1.2;text-align:center;color:#333;">LightningCast data courtesy CIMSS/SSEC</span>
        </div>
    `;
}

function lightningCastManifestVersion(manifest) {
    return [manifest?.scan_time_utc || '', manifest?.generated_time_utc || ''].join('|');
}

function waitForLightningCastRefresh(milliseconds) {
    return new Promise(resolve => window.setTimeout(resolve, milliseconds));
}

async function fetchLightningCastManifest() {
    const response = await fetch(`${LIGHTNINGCAST_MANIFEST_URL}?t=${Date.now()}`, {cache: 'no-store'});
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const manifest = await response.json();
    if (
        !manifest ||
        manifest.manifest_mode !== 'lightningcast_dashboard_manifest_v1' ||
        !manifest.scan_time_utc
    ) {
        throw new Error('Invalid LightningCast manifest');
    }
    return manifest;
}

async function refreshLightningCastFromManifest({forceMetadata = false} = {}) {
    if (lightningCastManifestCheckInFlight) return false;
    lightningCastManifestCheckInFlight = true;
    try {
        const manifest = await fetchLightningCastManifest();
        const version = lightningCastManifestVersion(manifest);
        if (!forceMetadata && version && version === lightningCastLastManifestVersion) return false;

        for (const delay of LIGHTNINGCAST_MANIFEST_RETRY_DELAYS_MS) {
            if (delay > 0) await waitForLightningCastRefresh(delay);
            try {
                await fetchLightningCastMetadata({expectedScanTime: manifest.scan_time_utc});
                lightningCastLastManifestVersion = version;
                return true;
            } catch (error) {
                console.warn('LightningCast package not synchronized yet:', error);
            }
        }
        console.warn('LightningCast manifest changed, but the synchronized raster package is not available yet.');
        return false;
    } catch (error) {
        console.error('LightningCast manifest check failed:', error);
        if (forceMetadata && !lightningCastReady) {
            try {
                return await fetchLightningCastMetadata();
            } catch (fallbackError) {
                console.error('Initial LightningCast metadata fetch failed:', fallbackError);
            }
        }
        return false;
    } finally {
        lightningCastManifestCheckInFlight = false;
    }
}

function checkLightningCastUpdatesNow() {
    refreshLightningCastFromManifest();
}

window.setInterval(() => {
    if (!document.hidden) checkLightningCastUpdatesNow();
}, LIGHTNINGCAST_MANIFEST_POLL_INTERVAL_MS);

document.addEventListener('visibilitychange', () => {
    if (!document.hidden) checkLightningCastUpdatesNow();
});
window.addEventListener('focus', checkLightningCastUpdatesNow);
window.addEventListener('online', checkLightningCastUpdatesNow);


function validateHRRRTLEMetadata(metadata, expectedCycle = null, expectedHRRRCycle = null) {
    if (!metadata || metadata.metadata_mode !== 'hrrr_tle_dashboard_v3_3') {
        throw new Error('Invalid HRRR-TLE metadata contract');
    }
    if (String(metadata.algorithm_version) !== '3.3') {
        throw new Error('Unexpected HRRR-TLE algorithm version');
    }
    if (Number(metadata.members_available) !== 6) {
        throw new Error(`HRRR-TLE dashboard requires 6/6 members; got ${metadata.members_available}`);
    }
    if (expectedCycle && metadata.latest_cycle_utc !== expectedCycle) {
        throw new Error(
            `HRRR-TLE package not synchronized: expected ${expectedCycle}, got ${metadata.latest_cycle_utc}`
        );
    }
    if (
        expectedHRRRCycle &&
        metadata.latest_hrrr_diagnostic_cycle_utc !== expectedHRRRCycle
    ) {
        throw new Error(
            `Latest-HRRR diagnostics not synchronized: expected ${expectedHRRRCycle}, got ${metadata.latest_hrrr_diagnostic_cycle_utc}`
        );
    }
    const bounds = metadata.bounds;
    if (
        !Array.isArray(bounds) || bounds.length !== 2 ||
        !Array.isArray(bounds[0]) || !Array.isArray(bounds[1]) ||
        bounds[0].length !== 2 || bounds[1].length !== 2
    ) {
        throw new Error('HRRR-TLE metadata contains invalid Leaflet bounds');
    }
    if (!metadata.layers || Object.keys(metadata.layers).length !== HRRR_ALL_LAYER_CONFIGS.length) {
        throw new Error('HRRR-TLE metadata layer inventory is incomplete');
    }
    return metadata;
}

function hrrrTLERasterUrl(config, metadata) {
    const version = encodeURIComponent(metadata.generated_utc || metadata.latest_cycle_utc || Date.now());
    const published = metadata.layers?.[config.key]?.file || config.file;
    return `static/${published}?v=${version}`;
}

function preloadDashboardRaster(url) {
    return new Promise((resolve, reject) => {
        const image = new Image();
        image.onload = () => resolve(url);
        image.onerror = () => reject(new Error(`Dashboard raster failed to preload: ${url}`));
        image.src = url;
    });
}

async function fetchHRRRTLEMetadata({expectedCycle = null, expectedHRRRCycle = null} = {}) {
    const response = await fetch(`${HRRR_TLE_METADATA_URL}?t=${Date.now()}`, {cache: 'no-store'});
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const metadata = validateHRRRTLEMetadata(await response.json(), expectedCycle, expectedHRRRCycle);
    const urls = HRRR_ALL_LAYER_CONFIGS.map(config => hrrrTLERasterUrl(config, metadata));

    // Preload the entire synchronized package before swapping any layer URL.
    await Promise.all(urls.map(preloadDashboardRaster));

    HRRR_ALL_LAYER_CONFIGS.forEach((config, index) => {
        const currentOpacity = Number(config.layer.options?.opacity);
        config.layer.setBounds(metadata.bounds);
        config.layer.setUrl(urls[index]);
        config.layer.setOpacity(
            hrrrTLEReady && Number.isFinite(currentOpacity) ? currentOpacity : 1.0
        );
    });

    hrrrTLEMetadata = metadata;
    hrrrTLEReady = true;
    updateHRRRDiagnosticTimeBox();
    updateHRRRTLETimeBox();
    if (typeof updateLegends === 'function') updateLegends();
    return true;
}

function hrrrTLEManifestVersion(manifest) {
    return [
        manifest?.latest_hrrr_diagnostic_cycle_utc || '',
        manifest?.hrrr_diagnostic_valid_end_utc || '',
        manifest?.latest_cycle_utc || '',
        manifest?.common_valid_end_utc || '',
        manifest?.generated_utc || ''
    ].join('|');
}

async function fetchHRRRTLEManifest() {
    const response = await fetch(`${HRRR_TLE_MANIFEST_URL}?t=${Date.now()}`, {cache: 'no-store'});
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const manifest = await response.json();
    if (
        !manifest ||
        manifest.metadata_mode !== 'hrrr_tle_dashboard_manifest_v1' ||
        String(manifest.algorithm_version) !== '3.3' ||
        !manifest.latest_cycle_utc
    ) {
        throw new Error('Invalid HRRR-TLE manifest');
    }
    return manifest;
}

async function refreshHRRRTLEFromManifest({forceMetadata = false} = {}) {
    if (hrrrTLEManifestCheckInFlight) return false;
    hrrrTLEManifestCheckInFlight = true;
    try {
        const manifest = await fetchHRRRTLEManifest();
        const version = hrrrTLEManifestVersion(manifest);
        if (!forceMetadata && version === hrrrTLELastManifestVersion) return false;
        await fetchHRRRTLEMetadata({
            expectedCycle: manifest.latest_cycle_utc,
            expectedHRRRCycle: manifest.latest_hrrr_diagnostic_cycle_utc
        });
        hrrrTLELastManifestVersion = version;
        return true;
    } catch (error) {
        console.error('HRRR-TLE package refresh failed:', error);
        if (!hrrrTLEReady) {
            HRRR_TLE_LAYER_CONFIGS.forEach(config => config.layer.setOpacity(0));
        }
        return false;
    } finally {
        hrrrTLEManifestCheckInFlight = false;
    }
}

function formatHRRRTLEUTC(value) {
    if (!value) return 'Unknown';
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? value : formatUTC(date);
}

function activeHRRRDiagnosticConfigs() {
    return HRRR_DIAGNOSTIC_LAYER_CONFIGS.filter(
        config => activeLayerNames.has(config.label)
    );
}

function formatHRRRDiagnosticTimeBox(config, metadata) {
    if (!config) return '';
    if (!metadata) {
        return `
            <strong>${config.label}</strong><br>
            <span style="color:#ffeb3b;">Loading latest complete HRRR f01–f12 package...</span>
        `;
    }

    return `
        <strong>${config.label}</strong><br>
        <span style="color:#4fc3f7;font-weight:bold;">Latest HRRR: ${formatHRRRTLEUTC(metadata.latest_hrrr_diagnostic_cycle_utc)}</span><br>
        <span style="color:#ffeb3b;">Valid: ${formatHRRRTLEUTC(metadata.hrrr_diagnostic_valid_start_utc)} — ${formatHRRRTLEUTC(metadata.hrrr_diagnostic_valid_end_utc)}</span><br>
        <span style="font-size:0.82em;color:#d0d0d0;">f${String(metadata.hrrr_diagnostic_fxx_start || 1).padStart(2,'0')}–f${String(metadata.hrrr_diagnostic_fxx_end || 12).padStart(2,'0')} | FFG: ${formatHRRRTLEUTC(metadata.hrrr_diagnostic_ffg_analysis_utc)} (age ${Number(metadata.hrrr_diagnostic_ffg_age_hours).toFixed(1)} h) | ${metadata.neighborhood_km} km neighborhood</span>
    `;
}

function updateHRRRDiagnosticTimeBox() {
    const box = document.getElementById('hrrr-diagnostics-time-box');
    if (!box) return;
    const active = activeHRRRDiagnosticConfigs();
    if (active.length === 0) {
        box.style.display = 'none';
        refreshLegendDockSummary();
        return;
    }
    box.innerHTML = formatHRRRDiagnosticTimeBox(
        active[active.length - 1],
        hrrrTLEMetadata
    );
    box.style.display = 'block';
    refreshLegendDockSummary();
}

function activeHRRRTLEConfigs() {
    return HRRR_TLE_LAYER_CONFIGS.filter(config => activeLayerNames.has(config.label));
}

function hrrrTLELayerValidText(config, metadata) {
    if (!metadata) return 'Loading synchronized 6-cycle package...';
    if (Array.isArray(config.evolutionHours)) {
        const start = new Date(metadata.common_valid_start_utc);
        const end = new Date(metadata.common_valid_start_utc);
        start.setUTCHours(start.getUTCHours() + config.evolutionHours[0]);
        end.setUTCHours(end.getUTCHours() + config.evolutionHours[1]);
        return `${formatUTC(start)} — ${formatUTC(end)}`;
    }
    return `${formatHRRRTLEUTC(metadata.common_valid_start_utc)} — ${formatHRRRTLEUTC(metadata.common_valid_end_utc)}`;
}

function formatHRRRTLETimeBox(config, metadata) {
    if (!config) return '';
    if (!metadata) {
        return `
            <strong>${config.label}</strong><br>
            <span style="color:#ffeb3b;">Loading newest complete HRRR-TLE package...</span>
        `;
    }

    let cycleDetail = '';
    if (config.key === 'latest3') {
        cycleDetail = `<br><span style="font-size:0.82em;color:#d0d0d0;">Cycles: ${(metadata.latest_three_cycles || []).join(', ')}</span>`;
    } else if (config.key === 'prior3') {
        cycleDetail = `<br><span style="font-size:0.82em;color:#d0d0d0;">Cycles: ${(metadata.prior_three_cycles || []).join(', ')}</span>`;
    } else if (config.key === 'run_change') {
        cycleDetail = `<br><span style="font-size:0.82em;color:#d0d0d0;">Signal threshold: ${metadata.run_change_signal_threshold || '2/3 members'}</span>`;
    }

    return `
        <strong>${config.label}</strong><br>
        <span style="color:#4fc3f7;font-weight:bold;">HRRR anchor: ${formatHRRRTLEUTC(metadata.latest_cycle_utc)} | ${metadata.members_available}/6 cycles</span><br>
        <span style="color:#ffeb3b;">Valid: ${hrrrTLELayerValidText(config, metadata)}</span><br>
        <span style="font-size:0.82em;color:#d0d0d0;">FFG: ${formatHRRRTLEUTC(metadata.ffg_analysis_utc)} (age ${Number(metadata.ffg_age_hours).toFixed(1)} h) | ${metadata.neighborhood_km} km neighborhood</span>
        ${cycleDetail}
    `;
}

function updateHRRRTLETimeBox() {
    const box = document.getElementById('hrrr-tle-time-box');
    if (!box) return;
    const active = activeHRRRTLEConfigs();
    if (active.length === 0) {
        box.style.display = 'none';
        refreshLegendDockSummary();
        return;
    }
    // If several HRRR-TLE layers are active, show the most recently found
    // active layer's shared metadata; each layer retains its own legend.
    box.innerHTML = formatHRRRTLETimeBox(active[active.length - 1], hrrrTLEMetadata);
    box.style.display = 'block';
    refreshLegendDockSummary();
}

function hrrrTLELegendShell(title, subtitle, body, footer = '') {
    return `
        <div style="box-sizing:border-box;width:100%;background:white;padding:9px;border-radius:5px;color:black;font-family:sans-serif;">
            <strong style="display:block;font-size:13px;line-height:1.2;text-align:center;">${title}</strong>
            <span style="display:block;margin-top:2px;font-size:9px;line-height:1.25;text-align:center;">${subtitle}</span>
            <div style="margin-top:8px;">${body}</div>
            ${footer ? `<span style="display:block;margin-top:7px;font-size:8px;line-height:1.2;text-align:center;color:#333;">${footer}</span>` : ''}
        </div>
    `;
}

function hrrrTLEDiscreteRows(items, columns = 2) {
    return `
        <div style="display:grid;grid-template-columns:repeat(${columns},minmax(0,1fr));gap:7px 12px;">
            ${items.map(item => `
                <div style="display:grid;grid-template-columns:28px minmax(0,1fr);align-items:center;gap:7px;">
                    <span style="display:block;width:26px;height:11px;border:1px solid rgba(0,0,0,0.28);background:${item.color};"></span>
                    <span style="font-size:9px;font-weight:700;line-height:1.15;">${item.label}</span>
                </div>
            `).join('')}
        </div>
    `;
}

function buildHRRRTLELegendHTML(config) {
    const note = 'HRRR time-lagged member frequency / consensus; NOT calibrated probability.';
    if (config.legendType === 'coverage') {
        return hrrrTLELegendShell(
            config.label,
            'Percent of the 40-km neighborhood containing an FFG exceedance',
            hrrrTLEDiscreteRows([
                {label: '1–5%', color: '#e0f7fa'},
                {label: '5–10%', color: '#c8e6c9'},
                {label: '10–25%', color: '#fff59d'},
                {label: '25–50%', color: '#ffb74d'},
                {label: '50–75%', color: '#f44336'},
                {label: '75–100%', color: '#9c27b0'}
            ], 3),
            'Latest deterministic HRRR, next 12 hours; values <1% are transparent.'
        );
    }

    if (config.legendType === 'ratio') {
        const bins = [
            ['0.75–1.00', '#ffff00'], ['1.00–1.25', '#ffa500'],
            ['1.25–1.50', '#ff0000'], ['1.50–2.00', '#8b0000'],
            ['2.00–2.50', '#ff00ff'], ['2.50–3.00', '#800080'],
            ['3.00–4.00', '#0000ff'], ['4.00–5.00', '#00ffff'],
            ['≥5.00', '#00ffff']
        ].map(([label, color]) => ({label, color}));
        return hrrrTLELegendShell(
            config.label,
            'Median of member 40-km neighborhood-maximum QPF / FFG ratios',
            hrrrTLEDiscreteRows(bins, 3),
            'Values <0.75 are transparent.'
        );
    }

    if (config.legendType === 'runChange') {
        return hrrrTLELegendShell(
            config.label,
            'Latest 3 cycles versus prior 3 cycles; signal threshold ≥2/3 members',
            hrrrTLEDiscreteRows([
                {label: 'Fading', color: '#4575b4'},
                {label: 'Persistent', color: '#7b3294'},
                {label: 'Emerging', color: '#fdae61'}
            ], 3),
            'Categorical run-to-run signal evolution.'
        );
    }

    if (config.legendType === 'frequency3') {
        return hrrrTLELegendShell(
            config.label,
            'Three-cycle FFG-exceedance consensus',
            hrrrTLEDiscreteRows([
                {label: '1/3 (33%)', color: '#ffcc80'},
                {label: '2/3 (67%)', color: '#ef5350'},
                {label: '3/3 (100%)', color: '#5e35b1'}
            ], 3),
            note
        );
    }

    const allSix = [
        {label: '1/6 (17%)', color: '#fff59d'},
        {label: '2/6 (33%)', color: '#ffcc80'},
        {label: '3/6 (50%)', color: '#ff8a65'},
        {label: '4/6 (67%)', color: '#ef5350'},
        {label: '5/6 (83%)', color: '#ab47bc'},
        {label: '6/6 (100%)', color: '#5e35b1'}
    ];
    const items = config.legendType === 'frequency6Min2' ? allSix.slice(1) : allSix;
    const subtitle = config.legendType === 'frequency6Min2'
        ? 'FFG-exceedance member consensus; 1/6 support intentionally suppressed on display'
        : 'HRRR-TLE member frequency / consensus';
    return hrrrTLELegendShell(
        config.label,
        subtitle,
        hrrrTLEDiscreteRows(items, 3),
        note
    );
}

function checkHRRRTLEUpdatesNow() {
    refreshHRRRTLEFromManifest();
}

window.setInterval(() => {
    if (!document.hidden) checkHRRRTLEUpdatesNow();
}, HRRR_TLE_MANIFEST_POLL_INTERVAL_MS);

document.addEventListener('visibilitychange', () => {
    if (!document.hidden) checkHRRRTLEUpdatesNow();
});
window.addEventListener('focus', checkHRRRTLEUpdatesNow);
window.addEventListener('online', checkHRRRTLEUpdatesNow);


async function fetchNWMMetadata() {
    try {
        const response = await fetch(
            'static/nwm_metadata.json?t=' + Date.now(),
            {cache: 'no-store'}
        );

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }

        const data = await response.json();

        applySoilRasterMetadata({
            metadata: data,
            layer: nwmLayer,
            baseUrl: NWM_IMAGE_URL,
            productName: "NWM soil saturation",
            opacity: 1.0
        });

        nwmLayerReady = true;
        nwmValidTime = data.valid_time || "Unknown";

        const timeBox = document.getElementById('nwm-time-box');
        if (timeBox && timeBox.style.display === 'block') {
            timeBox.innerHTML = `
                <strong>NWM 0-40cm Soil Saturation</strong><br>
                <span style="color: #ffeb3b;">${nwmValidTime}</span>
            `;
        }
    } catch (error) {
        nwmLayerReady = false;
        nwmLayer.setOpacity(0);
        console.error("NWM raster metadata update failed:", error);
    }
}

async function fetchSPoRTMetadata() {
    try {
        const response = await fetch(
            'static/sport_metadata.json?t=' + Date.now(),
            {cache: 'no-store'}
        );

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }

        const data = await response.json();

        applySoilRasterMetadata({
            metadata: data,
            layer: sportLayer,
            baseUrl: SPORT_IMAGE_URL,
            productName: "NASA SPoRT-LIS VSM percentile",
            opacity: 1.0
        });

        sportLayerReady = true;
        sportValidTime = data.valid_time || "Unknown";

        const timeBox = document.getElementById('sport-time-box');
        if (timeBox && timeBox.style.display === 'block') {
            timeBox.innerHTML = `
                <strong>NASA SPoRT-LIS VSM Percentile (0–100 cm)</strong><br>
                <span style="color: #ffeb3b;">${sportValidTime}</span>
            `;
        }
    } catch (error) {
        sportLayerReady = false;
        sportLayer.setOpacity(0);
        console.error("SPoRT raster metadata update failed:", error);
    }
}

async function fetchNLDASRSMMetadata() {
    try {
        const response = await fetch(
            'static/nldas_rsm_metadata.json?t=' + Date.now(),
            {cache: 'no-store'}
        );

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }

        const data = await response.json();
        const product010 = data.products && data.products['0_10cm'];
        const product0100 = data.products && data.products['0_100cm'];

        if (!product010 || !product0100) {
            throw new Error('NLDAS RSM metadata missing required products');
        }

        const sharedMetadata = {
            bounds: data.bounds,
            image_crs: data.image_crs || data.crs,
            render_revision: data.render_revision,
            retrieved_time: data.retrieved_time,
            valid_time_iso: data.valid_time_iso,
            valid_time: data.valid_time
        };

        applySoilRasterMetadata({
            metadata: sharedMetadata,
            layer: nldasRsm010Layer,
            baseUrl: product010.image || NLDAS_RSM_0_10_IMAGE_URL,
            productName: 'NLDAS-2 Noah RSM (0-10 cm)',
            opacity: 1.0
        });

        applySoilRasterMetadata({
            metadata: sharedMetadata,
            layer: nldasRsm0100Layer,
            baseUrl: product0100.image || NLDAS_RSM_0_100_IMAGE_URL,
            productName: 'NLDAS-2 Noah RSM (0-100 cm)',
            opacity: 1.0
        });

        nldasRsmReady = true;
        nldasRsmValidTime = data.valid_time || 'Unknown';

        const timeBox010 = document.getElementById('nldas-rsm-010-time-box');
        if (timeBox010 && timeBox010.style.display === 'block') {
            timeBox010.innerHTML = `
                <strong>NLDAS-2 Noah RSM (0-10 cm)</strong><br>
                <span style="color: #ffeb3b;">${nldasRsmValidTime}</span>
            `;
        }

        const timeBox0100 = document.getElementById('nldas-rsm-0100-time-box');
        if (timeBox0100 && timeBox0100.style.display === 'block') {
            timeBox0100.innerHTML = `
                <strong>NLDAS-2 Noah RSM (0-100 cm)</strong><br>
                <span style="color: #ffeb3b;">${nldasRsmValidTime}</span>
            `;
        }
    } catch (error) {
        nldasRsmReady = false;
        nldasRsm010Layer.setOpacity(0);
        nldasRsm0100Layer.setOpacity(0);
        console.error('NLDAS RSM raster metadata update failed:', error);
    }
}

// Initial fetch on load
fetchRAPMetadata();
fetchCAMMetadata();
fetchEROCAMMetadata();
fetchMRMSFlash24hMetadata();
refreshGLMFromManifest({forceMetadata: true});
refreshLightningCastFromManifest({forceMetadata: true});
refreshHRRRTLEFromManifest({forceMetadata: true});
fetchNWMMetadata();
fetchSPoRTMetadata();
fetchNLDASRSMMetadata();

// Auto-Refresh generated PNGs every 15 minutes
setInterval(() => {
    fetchRAPMetadata();
    fetchCAMMetadata();
    fetchEROCAMMetadata();
    fetchMRMSFlash24hMetadata();
    fetchNWMMetadata();
    fetchSPoRTMetadata();
    fetchNLDASRSMMetadata();
}, 15 * 60 * 1000); 

// GLM and LightningCast products are refreshed by their manifest watchers above.

function getValidTimeRange(cycleStr, windowStr) {
    if (!cycleStr || cycleStr === "Unknown") return "Valid Time Unknown";
    
    let cycleHour = parseInt(cycleStr);
    let now = new Date();
    
    let baseDate = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate(), cycleHour, 0, 0));
    
    if (now.getUTCHours() < cycleHour) {
        baseDate.setUTCDate(baseDate.getUTCDate() - 1);
    }
    
    let startOffset = windowStr === '+3h to +9h' ? 3 : 9;
    let endOffset = windowStr === '+3h to +9h' ? 9 : 15;
    
    let startDate = new Date(baseDate.getTime() + (startOffset * 60 * 60 * 1000));
    let endDate = new Date(baseDate.getTime() + (endOffset * 60 * 60 * 1000));
    
    return `${formatUTC(startDate)} &mdash; ${formatUTC(endDate)}`;
}

// --- RESPONSIVE LEGEND & VALID-TIME DOCK ---

const LEGEND_DOCK_SESSION_KEY = 'wpcLegendDockExpanded';
const legendDockCompactMedia = window.matchMedia('(max-width: 900px), (pointer: coarse)');
let legendDockExpanded = true;
let legendDockPreferenceExplicit = false;

function readLegendDockPreference() {
    try {
        return window.sessionStorage.getItem(LEGEND_DOCK_SESSION_KEY);
    } catch (error) {
        return null;
    }
}

function writeLegendDockPreference(isExpanded) {
    try {
        window.sessionStorage.setItem(
            LEGEND_DOCK_SESSION_KEY,
            isExpanded ? 'true' : 'false'
        );
    } catch (error) {
        // The dock still works when browser privacy settings block storage.
    }
}

function applyLegendDockState(dock, isExpanded) {
    if (!dock) return;

    legendDockExpanded = Boolean(isExpanded);
    dock.classList.toggle('is-collapsed', !legendDockExpanded);

    const toggle = dock.querySelector('#legend-dock-toggle');
    const title = dock.querySelector('#legend-dock-title');
    const icon = dock.querySelector('#legend-dock-icon');

    if (toggle) {
        toggle.setAttribute('aria-expanded', String(legendDockExpanded));
        toggle.setAttribute(
            'aria-label',
            legendDockExpanded
                ? 'Collapse legends and valid times'
                : 'Expand legends and valid times'
        );
    }
    if (title) {
        title.textContent = legendDockExpanded
            ? 'Legends & Valid Times'
            : 'Legends';
    }
    if (icon) icon.textContent = legendDockExpanded ? '−' : '+';
}

function setLegendDockExpanded(isExpanded, persist = true) {
    const dock = document.getElementById('legend-dock');
    applyLegendDockState(dock, isExpanded);

    if (persist) {
        legendDockPreferenceExplicit = true;
        writeLegendDockPreference(Boolean(isExpanded));
    }
}

function initializeLegendDockState() {
    const storedPreference = readLegendDockPreference();
    if (storedPreference === 'true' || storedPreference === 'false') {
        legendDockPreferenceExplicit = true;
        setLegendDockExpanded(storedPreference === 'true', false);
        return;
    }

    legendDockPreferenceExplicit = false;
    setLegendDockExpanded(!legendDockCompactMedia.matches, false);
}

function refreshLegendDockSummary() {
    const dock = document.getElementById('legend-dock');
    if (!dock) return;

    const legendContainer = document.getElementById('legend-container');
    const legendCount = legendContainer
        ? legendContainer.querySelectorAll('.legend-block').length
        : 0;
    const visibleTimeCount = Array.from(
        dock.querySelectorAll('.legend-dock-time-box')
    ).filter(box => window.getComputedStyle(box).display !== 'none').length;
    const trendCard = document.getElementById('glm-trend-card');
    const visibleTrendCount = trendCard && window.getComputedStyle(trendCard).display !== 'none'
        ? 1
        : 0;

    const count = document.getElementById('legend-dock-count');
    if (count) {
        count.textContent = String(legendCount);
        count.setAttribute(
            'aria-label',
            `${legendCount} active legend${legendCount === 1 ? '' : 's'}`
        );
    }

    dock.classList.toggle(
        'has-content',
        legendCount > 0 || visibleTimeCount > 0 || visibleTrendCount > 0
    );
}

function createLegendDockTimeBox(parent, id) {
    const div = L.DomUtil.create(
        'div',
        'time-box legend-dock-time-box',
        parent
    );
    div.id = id;
    div.style.display = 'none';
    return div;
}

const legendDockControl = L.control({position: 'bottomright'});
legendDockControl.onAdd = function () {
    const dock = L.DomUtil.create('section', 'legend-dock');
    dock.id = 'legend-dock';
    dock.setAttribute('aria-label', 'Active legends and valid times');

    dock.innerHTML = `
        <button
            id="legend-dock-toggle"
            class="legend-dock-toggle"
            type="button"
            aria-controls="legend-dock-body"
            aria-expanded="true"
        >
            <span id="legend-dock-title" class="legend-dock-title">Legends & Valid Times</span>
            <span id="legend-dock-count" class="legend-dock-count" aria-label="0 active legends">0</span>
            <span id="legend-dock-icon" class="legend-dock-icon" aria-hidden="true">−</span>
        </button>
        <div id="legend-dock-body" class="legend-dock-body">
            <div id="legend-time-stack" class="legend-time-stack"></div>
            <div id="glm-trend-card" class="glm-trend-card" style="display:none;" aria-live="polite"></div>
            <div id="legend-container" class="legend-container"></div>
        </div>
    `;

    const timeStack = dock.querySelector('#legend-time-stack');
    [
        'rap-time-box',
        'mrms-time-box',
        'cam-time-box',
        'radar-time-box',
        'ffd-time-box',
        'mrms-crest-24h-time-box',
        'mrms-ffd-24h-time-box',
        'glm-time-box',
        'lightningcast-time-box',
        'hrrr-diagnostics-time-box',
        'hrrr-tle-time-box',
        'nwm-time-box',
        'sport-time-box',
        'nldas-rsm-010-time-box',
        'nldas-rsm-0100-time-box'
    ].forEach(id => createLegendDockTimeBox(timeStack, id));

    const toggle = dock.querySelector('#legend-dock-toggle');
    toggle.addEventListener('click', () => {
        setLegendDockExpanded(!legendDockExpanded);
    });

    L.DomEvent.disableClickPropagation(dock);
    L.DomEvent.disableScrollPropagation(dock);

    return dock;
};
legendDockControl.addTo(map);
initializeLegendDockState();
updateGLMTrendCard();

if (typeof legendDockCompactMedia.addEventListener === 'function') {
    legendDockCompactMedia.addEventListener('change', () => {
        if (!legendDockPreferenceExplicit) {
            setLegendDockExpanded(!legendDockCompactMedia.matches, false);
        }
    });
}

// Update radar loop timestamps dynamically as player plays
map.timeDimension.on('timeload', function() {
    const radarTimeBox = document.getElementById('radar-time-box');
    if (radarTimeBox && radarTimeBox.style.display === 'block') {
        const hasRadar = Array.from(activeLayerNames).some(name => name.includes('NEXRAD Radar'));
        if (hasRadar) {
            const currentFrameTime = new Date(map.timeDimension.getCurrentTime());
            radarTimeBox.innerHTML = `
                <strong>NEXRAD Radar Loop</strong><br>
                <span style="color: #ffeb3b; font-weight: bold; font-size: 1.05em;">Frame: ${formatUTC(currentFrameTime)}</span>
            `;
        }
    }
});

// --- LEGEND DICTIONARIES AND HTML BLOCKS ---
const rapLegendMapping = {
    "Precipitable Water (PWAT)": "static/leg_pwat.png",
    "&nbsp;&nbsp;&nbsp;&nbsp;3-Hour PWAT Change": "static/leg_pwat_diff.png",
    "&nbsp;&nbsp;&nbsp;&nbsp;▶ <b>+3h Forecast:</b> PWAT": "static/leg_pwat.png",
    "Surface Based CAPE": "static/leg_cape.png",
    "&nbsp;&nbsp;&nbsp;&nbsp;3-Hour SBCAPE Change": "static/leg_cape_diff.png",
    "&nbsp;&nbsp;&nbsp;&nbsp;▶ <b>+3h Forecast:</b> SBCAPE": "static/leg_cape.png",
    "Mixed Layer CAPE (90mb)": "static/leg_cape.png",
    "&nbsp;&nbsp;&nbsp;&nbsp;3-Hour MLCAPE Change": "static/leg_cape_diff.png",
    "&nbsp;&nbsp;&nbsp;&nbsp;▶ <b>+3h Forecast:</b> MLCAPE": "static/leg_cape.png",
    "Most Unstable CAPE (255mb)": "static/leg_cape.png",
    "&nbsp;&nbsp;&nbsp;&nbsp;3-Hour MUCAPE Change": "static/leg_cape_diff.png",
    "&nbsp;&nbsp;&nbsp;&nbsp;▶ <b>+3h Forecast:</b> MUCAPE": "static/leg_cape.png",
    "Sfc-3km Low-Level Lapse Rate": "static/leg_lrsfc3.png",
    "700-500mb Mid-Level Lapse Rate": "static/leg_lr75.png",
    "Supercell Composite Parameter": "static/leg_scp.png",
    "Mean BL Moisture Convergence": "static/leg_mfc.png",
    "925/850mb Frontogenesis": "static/leg_fronto.png",
    "850/700mb Frontogenesis": "static/leg_fronto.png",
    "Effective Bulk Shear": "static/leg_eff_shear.png",
    "Corfidi Upwind (Back-Building) Vectors": "static/leg_corfidi_up.png",
    "Corfidi Downwind (Forward) Vectors": "static/leg_corfidi_down.png",
    "850mb Moisture Transport": "static/leg_trans.png",
    "&nbsp;&nbsp;&nbsp;&nbsp;3-Hour 850mb Moisture Transport Change": "static/leg_trans_diff.png",
    "&nbsp;&nbsp;&nbsp;&nbsp;▶ <b>+3h Forecast:</b> 850mb Moisture Transport": "static/leg_trans.png",
    "700mb Moisture Transport": "static/leg_trans.png",
    "850-300mb Mean Layer Wind": "static/leg_mean_wind.png",
    "500mb Absolute Vorticity": "static/leg_vort.png",
    "700-400mb Diff Vorticity Advection": "static/leg_diff_adv.png",
    "250mb Divergence": "static/leg_div.png"
};

const camLegendQPF = `
    <div style="background: white; padding: 10px; border-radius: 5px; font-family: sans-serif; text-align: center; color: black; font-size: 13px; max-width: 250px;">
        <strong>Max Hourly QPF Probability (%)</strong><br>
        <div style="display: flex; margin-top: 5px; border: 1px solid #333;">
            <div style="background: #ffffcc; flex: 1; padding: 2px 5px;">10</div>
            <div style="background: #a1dab4; flex: 1; padding: 2px 5px;">30</div>
            <div style="background: #41b6c4; flex: 1; padding: 2px 5px;">50</div>
            <div style="background: #2c7fb8; flex: 1; padding: 2px 5px; color: white;">70</div>
            <div style="background: #253494; flex: 1; padding: 2px 5px; color: white;">90+</div>
        </div>
    </div>
`;

const camLegendFFG = `
    <div style="background: white; padding: 10px; border-radius: 5px; font-family: sans-serif; text-align: center; color: black; font-size: 13px; max-width: 250px;">
        <strong>Max FFG Exceedance Probability (%)</strong><br>
        <div style="display: flex; margin-top: 5px; border: 1px solid #333;">
            <div style="background: #ffffb2; flex: 1; padding: 2px 5px;">10</div>
            <div style="background: #fecc5c; flex: 1; padding: 2px 5px;">30</div>
            <div style="background: #fd8d3c; flex: 1; padding: 2px 5px;">50</div>
            <div style="background: #f03b20; flex: 1; padding: 2px 5px; color: white;">70</div>
            <div style="background: #bd0026; flex: 1; padding: 2px 5px; color: white;">90+</div>
        </div>
    </div>
`;

const hazardLegendHTML = `
    <div style="background: white; padding: 10px; border-radius: 5px; font-family: sans-serif; color: black; font-size: 12px; min-width: 200px; text-align: left;">
        <strong style="display: block; text-align: center; margin-bottom: 5px; font-size: 13px;">Hydro Warnings & Advisories</strong>
        <div style="display: flex; align-items: center; margin-bottom: 3px;">
            <div style="width: 15px; height: 15px; background: red; margin-right: 8px; border: 1px solid #333; opacity: 0.6;"></div>
            <span>Flash Flood Warning</span>
        </div>
        <div style="display: flex; align-items: center; margin-bottom: 3px;">
            <div style="width: 15px; height: 15px; background: green; margin-right: 8px; border: 1px solid #333; opacity: 0.6;"></div>
            <span>Flood Warning</span>
        </div>
        <div style="display: flex; align-items: center;">
            <div style="width: 15px; height: 15px; background: lightgreen; margin-right: 8px; border: 1px solid #333; opacity: 0.6;"></div>
            <span>Flood Advisory</span>
        </div>
    </div>
`;

const watchLegendHTML = `
    <div style="background: white; padding: 10px; border-radius: 5px; font-family: sans-serif; color: black; font-size: 12px; min-width: 200px; text-align: left;">
        <strong style="display: block; text-align: center; margin-bottom: 5px; font-size: 13px;">Hydro Watches</strong>
        <div style="display: flex; align-items: center;">
            <div style="width: 15px; height: 15px; background: seagreen; margin-right: 8px; border: 1px solid #333; opacity: 0.6;"></div>
            <span>Flood / Flash Flood Watch</span>
        </div>
    </div>
`;

const mpdLegendHTML = `
    <div style="background: white; padding: 10px; border-radius: 5px; font-family: sans-serif; color: black; font-size: 12px; min-width: 200px; text-align: left;">
        <strong style="display: block; text-align: center; margin-bottom: 5px; font-size: 13px;">WPC Active MPDs</strong>
        <div style="display: flex; align-items: center; margin-bottom: 3px;">
            <div style="width: 20px; height: 3px; background: transparent; border-top: 3px dashed #800080; margin-right: 8px;"></div>
            <span>Flash Flood Likely</span>
        </div>
        <div style="display: flex; align-items: center;">
            <div style="width: 20px; height: 3px; background: transparent; border-top: 3px dashed #0000FF; margin-right: 8px;"></div>
            <span>Flash Flood Possible</span>
        </div>
    </div>
`;

const eroLegendHTML = `
    <div style="background: white; padding: 10px; border-radius: 5px; font-family: sans-serif; color: black; font-size: 12px; min-width: 200px; text-align: left;">
        <strong style="display: block; text-align: center; margin-bottom: 5px; font-size: 13px;">Day 1 ERO Risks</strong>
        <div style="display: flex; align-items: center; margin-bottom: 3px;">
            <div style="width: 15px; height: 15px; background: #00ff00; margin-right: 8px; border: 1px solid #333; opacity: 0.6;"></div>
            <span>Marginal Risk (MRGL)</span>
        </div>
        <div style="display: flex; align-items: center; margin-bottom: 3px;">
            <div style="width: 15px; height: 15px; background: #ffff00; margin-right: 8px; border: 1px solid #333; opacity: 0.6;"></div>
            <span>Slight Risk (SLGT)</span>
        </div>
        <div style="display: flex; align-items: center; margin-bottom: 3px;">
            <div style="width: 15px; height: 15px; background: #ff0000; margin-right: 8px; border: 1px solid #333; opacity: 0.6;"></div>
            <span>Moderate Risk (MDT)</span>
        </div>
        <div style="display: flex; align-items: center;">
            <div style="width: 15px; height: 15px; background: #ff00ff; margin-right: 8px; border: 1px solid #333; opacity: 0.6;"></div>
            <span>High Risk (HIGH)</span>
        </div>
    </div>
`;

const ffdLegendHTML = `
    <div style="background: white; padding: 10px; border-radius: 5px; font-family: sans-serif; color: black; font-size: 12px; min-width: 200px; text-align: left;">
        <strong style="display: block; text-align: center; margin-bottom: 5px; font-size: 13px;">FFD Inferred Impacts</strong>
        <div style="display: flex; align-items: center; margin-bottom: 3px;">
            <div style="width: 15px; height: 15px; background: #00ff00; margin-right: 8px; border: 1px solid #333; opacity: 0.6;"></div>
            <span>Monitor</span>
        </div>
        <div style="display: flex; align-items: center; margin-bottom: 3px;">
            <div style="width: 15px; height: 15px; background: #ffff00; margin-right: 8px; border: 1px solid #333; opacity: 0.6;"></div>
            <span>Advisory</span>
        </div>
        <div style="display: flex; align-items: center; margin-bottom: 3px;">
            <div style="width: 15px; height: 15px; background: #ffaa00; margin-right: 8px; border: 1px solid #333; opacity: 0.6;"></div>
            <span>Base FFW</span>
        </div>
        <div style="display: flex; align-items: center; margin-bottom: 3px;">
            <div style="width: 15px; height: 15px; background: #ff0000; margin-right: 8px; border: 1px solid #333; opacity: 0.6;"></div>
            <span>Considerable FFW</span>
        </div>
        <div style="display: flex; align-items: center;">
            <div style="width: 15px; height: 15px; background: #ff00ff; margin-right: 8px; border: 1px solid #333; opacity: 0.6;"></div>
            <span>Catastrophic FFW</span>
        </div>
    </div>
`;

const mrmsLegendQPE1hr = `
    <div style="background: white; padding: 10px; border-radius: 5px; text-align: center; color: black; font-family: sans-serif; min-width: 280px; max-width: 320px;">
        <strong style="font-size: 13px;">MRMS 1-Hour QPE (inches)</strong><br>
        <div style="display: flex; margin-top: 5px; border: 1px solid #333; height: 16px;">
            <div style="background: #000080; flex: 1;" title="0.01 - 0.1"></div>
            <div style="background: #0000FF; flex: 1;" title="0.1 - 0.25"></div>
            <div style="background: #0080FF; flex: 1;" title="0.25 - 0.5"></div>
            <div style="background: #00FFFF; flex: 1;" title="0.5 - 1.0"></div>
            <div style="background: #00FF00; flex: 1;" title="1.0 - 1.5"></div>
            <div style="background: #00C800; flex: 1;" title="1.5 - 2.0"></div>
            <div style="background: #008000; flex: 1;" title="2.0 - 3.0"></div>
            <div style="background: #FFFF00; flex: 1;" title="3.0 - 4.0"></div>
            <div style="background: #FFC800; flex: 1;" title="4.0 - 5.0"></div>
            <div style="background: #FF9000; flex: 1;" title="5.0 - 6.0"></div>
            <div style="background: #FF0000; flex: 1;" title="6.0 - 8.0"></div>
            <div style="background: #C00000; flex: 1;" title="8.0+"></div>
        </div>
        <div style="display: flex; justify-content: space-between; font-size: 9px; margin-top: 2px;">
            <span>.01</span><span>.1</span><span>.25</span><span>.5</span><span>1</span><span>1.5</span><span>2</span><span>3</span><span>4</span><span>5</span><span>6</span><span>8+</span>
        </div>
    </div>
`;

const mrmsLegendQPEMulti = `
    <div style="background: white; padding: 10px; border-radius: 5px; text-align: center; color: black; font-family: sans-serif; min-width: 280px; max-width: 320px;">
        <strong style="font-size: 13px;">MRMS Multi-Hour QPE (inches)</strong><br>
        <div style="display: flex; margin-top: 5px; border: 1px solid #333; height: 16px;">
            <div style="background: #000080; flex: 1;" title="0.01 - 0.1"></div>
            <div style="background: #0000FF; flex: 1;" title="0.1 - 0.25"></div>
            <div style="background: #0080FF; flex: 1;" title="0.25 - 0.5"></div>
            <div style="background: #00FFFF; flex: 1;" title="0.5 - 1.0"></div>
            <div style="background: #00FF00; flex: 1;" title="1.0 - 1.5"></div>
            <div style="background: #00C800; flex: 1;" title="1.5 - 2.0"></div>
            <div style="background: #008000; flex: 1;" title="2.0 - 3.0"></div>
            <div style="background: #FFFF00; flex: 1;" title="3.0 - 4.0"></div>
            <div style="background: #FFC800; flex: 1;" title="4.0 - 5.0"></div>
            <div style="background: #FF9000; flex: 1;" title="5.0 - 6.0"></div>
            <div style="background: #FF0000; flex: 1;" title="6.0 - 8.0"></div>
            <div style="background: #C00000; flex: 1;" title="8.0 - 10.0"></div>
            <div style="background: #FF00FF; flex: 1;" title="10.0 - 15.0"></div>
            <div style="background: #800080; flex: 1;" title="15.0 - 20.0"></div>
            <div style="background: #FFFFFF; flex: 1;" title="20.0+"></div>
        </div>
        <div style="display: flex; justify-content: space-between; font-size: 9px; margin-top: 2px;">
            <span>.01</span><span>.1</span><span>.25</span><span>.5</span><span>1</span><span>1.5</span><span>2</span><span>3</span><span>4</span><span>5</span><span>6</span><span>8</span><span>10</span><span>15</span><span>20+</span>
        </div>
    </div>
`;

const mrmsCrest24hLegendHTML = `
    <div style="background: white; padding: 10px; border-radius: 5px; text-align: center; color: black; font-family: sans-serif; min-width: 300px; max-width: 330px;">
        <strong style="font-size: 13px;">MRMS FLASH CREST Unit Q — 24-Hour Maximum</strong><br>
        <span style="font-size: 10px;">m³ s⁻¹ km⁻²</span>
        <div style="display: flex; margin-top: 6px; border: 1px solid #333; height: 17px;">
            <div style="background: #00ff00; flex: 1;" title="1.0–1.5"></div>
            <div style="background: #ffff00; flex: 1;" title="1.5–2.0"></div>
            <div style="background: #ffc800; flex: 1;" title="2.0–3.0"></div>
            <div style="background: #ff8c00; flex: 1;" title="3.0–4.0"></div>
            <div style="background: #ff4600; flex: 1;" title="4.0–5.0"></div>
            <div style="background: #ff0000; flex: 1;" title="5.0–6.0"></div>
            <div style="background: #be00be; flex: 1;" title="6.0–8.5"></div>
            <div style="background: #6400be; flex: 1;" title="8.5–10.0"></div>
            <div style="background: #0050ff; flex: 1;" title="10.0–15.0"></div>
            <div style="background: #0000b4; flex: 1;" title="15.0–20.0"></div>
            <div style="background: #000064; flex: 1;" title="20.0+"></div>
        </div>
        <div style="display: flex; justify-content: space-between; font-size: 8px; margin-top: 2px;">
            <span>1</span><span>1.5</span><span>2</span><span>3</span><span>4</span><span>5</span><span>6</span><span>8.5</span><span>10</span><span>15</span><span>20+</span>
        </div>
        <div style="font-size: 9px; margin-top: 4px; text-align: left;">
            Transparent where Unit Q is below 1.0 or unavailable.
        </div>
    </div>
`;

const mrmsFfd24hLegendHTML = `
    <div style="background: white; padding: 10px; border-radius: 5px; font-family: sans-serif; color: black; font-size: 12px; min-width: 240px; text-align: left;">
        <strong style="display: block; text-align: center; margin-bottom: 6px; font-size: 13px;">MRMS FLASH FFD — Highest 24-Hour Category</strong>
        <div style="display: flex; align-items: center; margin-bottom: 3px;">
            <div style="width: 15px; height: 15px; background: transparent; margin-right: 8px; border: 1px dashed #555;"></div>
            <span><strong>0</strong> — None / transparent</span>
        </div>
        <div style="display: flex; align-items: center; margin-bottom: 3px;">
            <div style="width: 15px; height: 15px; background: #00ff00; margin-right: 8px; border: 1px solid #333;"></div>
            <span><strong>1</strong> — Monitor</span>
        </div>
        <div style="display: flex; align-items: center; margin-bottom: 3px;">
            <div style="width: 15px; height: 15px; background: #ffff00; margin-right: 8px; border: 1px solid #333;"></div>
            <span><strong>2</strong> — Flood Advisory</span>
        </div>
        <div style="display: flex; align-items: center; margin-bottom: 3px;">
            <div style="width: 15px; height: 15px; background: #ffaa00; margin-right: 8px; border: 1px solid #333;"></div>
            <span><strong>3</strong> — FFW Base</span>
        </div>
        <div style="display: flex; align-items: center; margin-bottom: 3px;">
            <div style="width: 15px; height: 15px; background: #ff0000; margin-right: 8px; border: 1px solid #333;"></div>
            <span><strong>4</strong> — FFW Considerable</span>
        </div>
        <div style="display: flex; align-items: center;">
            <div style="width: 15px; height: 15px; background: #ff00ff; margin-right: 8px; border: 1px solid #333;"></div>
            <span><strong>5</strong> — FFW Catastrophic</span>
        </div>
    </div>
`;

const nwmLegendHTML = `
    <div style="background: white; padding: 10px; border-radius: 5px; text-align: center; color: black; font-family: sans-serif; min-width: 250px;">
        <strong style="font-size: 13px;">NWM 0-40cm Soil Saturation (%)</strong><br>
        <div style="display: flex; margin-top: 5px; border: 1px solid #333; height: 16px;">
            <div style="background: #d2b48c; flex: 2;" title="0-40%"></div>
            <div style="background: #e0eee0; flex: 1;" title="40-60%"></div>
            <div style="background: #90ee90; flex: 0.5;" title="60-70%"></div>
            <div style="background: #3cb371; flex: 0.5;" title="70-80%"></div>
            <div style="background: #00ced1; flex: 0.5;" title="80-90%"></div>
            <div style="background: #1e90ff; flex: 0.25;" title="90-95%"></div>
            <div style="background: #00008b; flex: 0.25;" title="95-100%"></div>
        </div>
        <div style="display: flex; justify-content: space-between; font-size: 9px; margin-top: 2px;">
            <span>0</span><span>40</span><span>60</span><span>70</span><span>80</span><span>90</span><span>100</span>
        </div>
    </div>
`;

const sportLegendHTML = `
    <div style="background: white; padding: 10px; border-radius: 5px; text-align: center; color: black; font-family: sans-serif; min-width: 250px;">
        <strong style="font-size: 13px;">NASA SPoRT-LIS Volumetric Soil Moisture Percentile (0–100 cm)</strong><br>
        <div style="display: flex; margin-top: 5px; border: 1px solid #333; height: 16px;">
            <div style="background: rgb(170,220,255); flex: 1;" title="70-80"></div>
            <div style="background: rgb(80,170,255); flex: 1;" title="80-90"></div>
            <div style="background: rgb(20,110,235); flex: 0.5;" title="90-95"></div>
            <div style="background: rgb(0,45,180); flex: 0.3;" title="95-98"></div>
            <div style="background: rgb(120,0,180); flex: 0.2;" title="98-100"></div>
        </div>
        <div style="display: flex; justify-content: space-between; font-size: 9px; margin-top: 2px;">
            <span>70</span><span>80</span><span>90</span><span>95</span><span>98</span><span>100</span>
        </div>
    </div>
`;

function buildNLDASRSMHTML(title) {
    return `
        <div style="background: white; padding: 10px; border-radius: 5px; text-align: center; color: black; font-family: sans-serif; min-width: 250px;">
            <strong style="font-size: 13px;">${title}</strong><br>
            <div style="display: flex; margin-top: 5px; border: 1px solid #333; height: 16px;">
                <div style="background: rgba(150,110,70,0.88); flex: 4;" title="0-40"></div>
                <div style="background: rgba(210,190,120,0.88); flex: 1;" title="40-50"></div>
                <div style="background: rgba(170,215,130,0.88); flex: 1;" title="50-60"></div>
                <div style="background: rgba(90,190,120,0.88); flex: 1;" title="60-70"></div>
                <div style="background: rgba(35,185,190,0.88); flex: 1;" title="70-80"></div>
                <div style="background: rgba(45,125,230,0.88); flex: 1;" title="80-90"></div>
                <div style="background: rgba(20,50,170,0.96); flex: 0.5;" title="90-95"></div>
                <div style="background: rgba(125,0,175,1); flex: 0.5;" title="95-100"></div>
            </div>
            <div style="display: flex; justify-content: space-between; font-size: 9px; margin-top: 2px;">
                <span>0</span><span>40</span><span>50</span><span>60</span><span>70</span><span>80</span><span>90</span><span>95</span><span>100</span>
            </div>
        </div>
    `;
}

const nldasRsm010LegendHTML = buildNLDASRSMHTML('NLDAS-2 Noah Relative Soil Moisture (0-10 cm)');
const nldasRsm0100LegendHTML = buildNLDASRSMHTML('NLDAS-2 Noah Relative Soil Moisture (0-100 cm)');

const GLM_FALLBACK_RENDERING = {
    5: {
        labels: ['1', '2–3', '4–7', '8–15', '16–31', '32–63', '64–127', '128–255', '≥256'],
        rgba: [
            [0, 255, 255, 255], [0, 255, 0, 255], [255, 255, 0, 255],
            [255, 153, 0, 255], [255, 0, 0, 255], [255, 0, 255, 255],
            [199, 125, 255, 255], [0, 102, 255, 255], [255, 255, 255, 255]
        ],
        units: 'flashes per 0.02-degree grid cell per five minutes'
    },
    rolling: {
        labels: ['1', '2–3', '4–7', '8–15', '16–31', '32–63', '64–127', '128–255', '256–511', '≥512'],
        rgba: [
            [0, 255, 255, 255], [0, 255, 0, 255], [255, 255, 0, 255],
            [255, 153, 0, 255], [255, 0, 0, 255], [255, 0, 255, 255],
            [199, 125, 255, 255], [0, 102, 255, 255], [102, 204, 255, 255],
            [255, 255, 255, 255]
        ],
        units: 'flash extent contributions per 0.02-degree grid cell'
    },
    trendMap: {
        labels: ['Past-Hour Lightning Context', 'Rapidly Decreasing', 'Decreasing', 'Steady', 'Increasing', 'Rapidly Increasing'],
        rgba: [
            [142, 146, 158, 156], [56, 118, 255, 224], [76, 234, 255, 220],
            [255, 232, 120, 214], [255, 170, 64, 224], [255, 72, 72, 232]
        ],
        units: 'categorical 15-minute convective trend class'
    }
};

function escapeGLMLegendText(value) {
    return String(value ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}

function validateGLMRenderingMetadata(metadata, layerName = 'GOES GLM') {
    const rendering = metadata?.rendering || {};
    const bins = rendering.bins;
    const labels = rendering.labels;
    const rgba = rendering.rgba;

    if (!Array.isArray(bins) || !Array.isArray(labels) || !Array.isArray(rgba)) {
        throw new Error(`${layerName}: rendering bins, labels, and rgba arrays are required`);
    }
    if (bins.length === 0 || bins.length !== labels.length || bins.length !== rgba.length) {
        throw new Error(`${layerName}: rendering bins, labels, and rgba lengths do not match`);
    }

    const normalizedBins = bins.map(Number);
    normalizedBins.forEach((value, index) => {
        if (!Number.isFinite(value) || value < 0) {
            throw new Error(`${layerName}: invalid rendering bin at index ${index}`);
        }
        if (index > 0 && value <= normalizedBins[index - 1]) {
            throw new Error(`${layerName}: rendering bins must be strictly increasing`);
        }
    });

    const normalizedColors = rgba.map((color, index) => {
        if (!Array.isArray(color) || color.length !== 4) {
            throw new Error(`${layerName}: RGBA entry ${index} must contain four channels`);
        }
        return color.map(channel => {
            const value = Number(channel);
            if (!Number.isFinite(value) || value < 0 || value > 255) {
                throw new Error(`${layerName}: invalid RGBA channel in entry ${index}`);
            }
            return Math.round(value);
        });
    });

    return {
        bins: normalizedBins,
        labels: labels.map(label => String(label)),
        rgba: normalizedColors
    };
}

function glmRGBAtoCSS(color) {
    const alpha = Math.max(0, Math.min(255, Number(color[3]))) / 255;
    return `rgba(${color[0]}, ${color[1]}, ${color[2]}, ${alpha.toFixed(3)})`;
}

function buildGLMLegendHTML(title, labels, rgba, subtitle) {
    const bins = labels.map((label, index) => `
        <div style="display: grid; grid-template-columns: 18px minmax(0, 1fr); align-items: center; gap: 6px; min-width: 0;">
            <span style="display: block; width: 18px; height: 12px; border: 1px solid rgba(0, 0, 0, 0.55); border-radius: 2px; background: ${glmRGBAtoCSS(rgba[index])};"></span>
            <span style="min-width: 0; font-size: 10px; font-weight: 700; line-height: 1.15; text-align: left; white-space: nowrap;">${escapeGLMLegendText(label)}</span>
        </div>
    `).join('');
    return `
        <div style="box-sizing: border-box; width: 100%; max-width: 100%; overflow: hidden; background: white; padding: 9px; border-radius: 5px; color: black; font-family: sans-serif;">
            <strong style="display: block; font-size: 13px; line-height: 1.2; text-align: center;">${escapeGLMLegendText(title)}</strong>
            <span style="display: block; margin-top: 2px; font-size: 9px; line-height: 1.2; text-align: center;">${escapeGLMLegendText(subtitle)}</span>
            <div style="display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 6px 12px; margin-top: 8px;">${bins}</div>
        </div>
    `;
}

function glmLegendHTMLFromMetadata(config, metadata) {
    const fallback = config.legendId === 'trend-map'
        ? GLM_FALLBACK_RENDERING.trendMap
        : (config.windowMinutes === 5 ? GLM_FALLBACK_RENDERING[5] : GLM_FALLBACK_RENDERING.rolling);

    let rendering = fallback;
    if (metadata) {
        try {
            rendering = validateGLMRenderingMetadata(metadata, config.name);
        } catch (error) {
            console.error(`GLM legend metadata rejected for ${config.name}:`, error);
        }
    }

    const title = metadata?.display_label || config.name;
    const subtitle = metadata?.units || fallback.units;
    return buildGLMLegendHTML(title, rendering.labels, rendering.rgba, subtitle);
}

function glmLegendHTMLForConfig(config) {
    return glmLegendHTMLFromMetadata(config, glmMetadataByName.get(config.name));
}

// Global tracker for currently active layers
let activeLayerNames = new Set();

function updateLegends() {
    const legendContainer = document.getElementById('legend-container');
    if (!legendContainer) return;

    legendContainer.innerHTML = '';
    let hasLegend = false;

    const addLegendBlock = (htmlContent) => {
        const div = document.createElement('div');
        div.className = 'legend-block';
        div.innerHTML = htmlContent;
        legendContainer.appendChild(div);
        hasLegend = true;
    };

    if (activeLayerNames.has('Active Hydro Warnings & Advisories')) addLegendBlock(hazardLegendHTML);
    if (activeLayerNames.has('Active Hydro Watches')) addLegendBlock(watchLegendHTML);
    if (activeLayerNames.has('WPC Active MPDs')) addLegendBlock(mpdLegendHTML);
    if (activeLayerNames.has('Day 1 ERO (Real-Time)')) addLegendBlock(eroLegendHTML);
    if (activeLayerNames.has('MRMS DVD Flash Flood Detector')) addLegendBlock(ffdLegendHTML);
    if (activeLayerNames.has(MRMS_CREST_24H_LAYER_NAME)) addLegendBlock(mrmsCrest24hLegendHTML);
    if (activeLayerNames.has(MRMS_FFD_24H_LAYER_NAME)) addLegendBlock(mrmsFfd24hLegendHTML);
    if (activeLayerNames.has('NWM Soil Saturation (0-40cm)')) addLegendBlock(nwmLegendHTML);
    if (activeLayerNames.has('NASA SPoRT-LIS VSM Percentile (0–100 cm)')) addLegendBlock(sportLegendHTML);
    if (activeLayerNames.has('NLDAS-2 Noah Relative Soil Moisture (0-10 cm)')) addLegendBlock(nldasRsm010LegendHTML);
    if (activeLayerNames.has('NLDAS-2 Noah Relative Soil Moisture (0-100 cm)')) addLegendBlock(nldasRsm0100LegendHTML);
    GLM_LAYER_CONFIGS
        .filter(config => activeLayerNames.has(config.name))
        .forEach(config => addLegendBlock(glmLegendHTMLForConfig(config)));
    if (activeLayerNames.has(LIGHTNINGCAST_LAYER_NAME)) addLegendBlock(buildLightningCastLegendHTML());
    HRRR_DIAGNOSTIC_LAYER_CONFIGS
        .filter(config => activeLayerNames.has(config.label))
        .forEach(config => addLegendBlock(buildHRRRTLELegendHTML(config)));
    HRRR_TLE_LAYER_CONFIGS
        .filter(config => activeLayerNames.has(config.label))
        .forEach(config => addLegendBlock(buildHRRRTLELegendHTML(config)));
    
    const hasMRMS1hr = Array.from(activeLayerNames).some(name => name === 'MRMS 1-Hour QPE');
    const hasMRMSMulti = Array.from(activeLayerNames).some(name => name.includes('MRMS') && name.includes('QPE') && !name.includes('1-Hour'));
    
    if (hasMRMS1hr) {
        addLegendBlock(mrmsLegendQPE1hr);
    } else if (hasMRMSMulti) {
        addLegendBlock(mrmsLegendQPEMulti);
    }

    const activeCAM = Array.from(activeLayerNames).find(name => name.includes('SuperEnsemble') || name.includes('HREF') || name.includes('REFS'));
    if (activeCAM) {
        if (activeCAM.includes('Max FFG Exceedance')) {
            addLegendBlock(camLegendFFG);
        } else {
            addLegendBlock(camLegendQPF);
        }
    }

    const activeRAP = Array.from(activeLayerNames).find(name => rapLegendMapping[name]);
    if (activeRAP) {
        addLegendBlock(`
            <div style="background: rgba(0, 0, 0, 0.7); padding: 10px; border-radius: 5px;">
                <img src="${rapLegendMapping[activeRAP]}" style="max-width: 300px; display: block;">
            </div>
        `);
    }

    legendContainer.style.display = hasLegend ? 'block' : 'none';
    refreshLegendDockSummary();
}

// Map overlay handling dynamically updates Sets and GUI
map.on('overlayadd', function(eventLayer) {
    activeLayerNames.add(eventLayer.name);
    updateLegends();

    const rapTimeBox = document.getElementById('rap-time-box');
    const mrmsTimeBox = document.getElementById('mrms-time-box');
    const camTimeBox = document.getElementById('cam-time-box');
    const radarTimeBox = document.getElementById('radar-time-box');
    const ffdTimeBox = document.getElementById('ffd-time-box');
    const mrmsCrest24hTimeBox = document.getElementById('mrms-crest-24h-time-box');
    const mrmsFfd24hTimeBox = document.getElementById('mrms-ffd-24h-time-box');
    const glmTimeBox = document.getElementById('glm-time-box');
    const lightningCastTimeBox = document.getElementById('lightningcast-time-box');
    const hrrrDiagnosticsTimeBox = document.getElementById('hrrr-diagnostics-time-box');
    const hrrrTLETimeBox = document.getElementById('hrrr-tle-time-box');
    const nwmTimeBox = document.getElementById('nwm-time-box');
    const sportTimeBox = document.getElementById('sport-time-box');
    const nldasRsm010TimeBox = document.getElementById('nldas-rsm-010-time-box');
    const nldasRsm0100TimeBox = document.getElementById('nldas-rsm-0100-time-box');

    if (rapLegendMapping[eventLayer.name]) {
        // Refresh bounds, valid times, and cache-busted RAP image URLs
        // immediately when a RAP layer is selected.
        fetchRAPMetadata();

        if (eventLayer.name.includes('+3h Forecast')) {
            rapTimeBox.innerHTML = `<strong>${rapValidTimeF03}</strong>`;
        } else {
            rapTimeBox.innerHTML = `<strong>${rapValidTime}</strong>`;
        }
        rapTimeBox.style.display = 'block';
    }
    
    if (eventLayer.name.includes('MRMS') && eventLayer.name.includes('QPE')) {
        let hours = 1;
        if (eventLayer.name.includes('24-Hour')) hours = 24;
        if (eventLayer.name.includes('48-Hour')) hours = 48;
        if (eventLayer.name.includes('72-Hour')) hours = 72;
        
        const now = new Date();
        const start = new Date(now.getTime() - (hours * 60 * 60 * 1000));
        mrmsTimeBox.innerHTML = `<strong>MRMS ${hours}-Hour Accumulation</strong><br>${formatUTC(start)} &mdash; ${formatUTC(now)}`;
        mrmsTimeBox.style.display = 'block';
    }

    if (eventLayer.name.includes('MRMS DVD Flash Flood Detector')) {
        if (ffdTimeBox) ffdTimeBox.style.display = 'block';
    }

    if (eventLayer.name === MRMS_CREST_24H_LAYER_NAME) {
        if (mrmsCrest24hTimeBox) {
            mrmsCrest24hTimeBox.innerHTML = formatMRMSFlashTimeBox(
                'MRMS FLASH CREST Unit Q',
                mrmsCrest24hMetadata
            );
            mrmsCrest24hTimeBox.style.display = 'block';
        }
        fetchMRMSFlash24hMetadata();
    }

    if (eventLayer.name === MRMS_FFD_24H_LAYER_NAME) {
        if (mrmsFfd24hTimeBox) {
            mrmsFfd24hTimeBox.innerHTML = formatMRMSFlashTimeBox(
                'MRMS FLASH Flood Detector',
                mrmsFfd24hMetadata
            );
            mrmsFfd24hTimeBox.style.display = 'block';
        }
        fetchMRMSFlash24hMetadata();
    }

    if (eventLayer.name === LIGHTNINGCAST_LAYER_NAME) {
        if (lightningCastTimeBox) {
            lightningCastTimeBox.innerHTML = formatLightningCastTimeBox(lightningCastMetadata);
            lightningCastTimeBox.style.display = 'block';
        }
        refreshLightningCastFromManifest({forceMetadata: !lightningCastReady});
    }

    if (HRRR_DIAGNOSTIC_CONFIG_BY_NAME.has(eventLayer.name)) {
        if (hrrrDiagnosticsTimeBox) {
            hrrrDiagnosticsTimeBox.innerHTML = formatHRRRDiagnosticTimeBox(
                HRRR_DIAGNOSTIC_CONFIG_BY_NAME.get(eventLayer.name),
                hrrrTLEMetadata
            );
            hrrrDiagnosticsTimeBox.style.display = 'block';
        }
        refreshHRRRTLEFromManifest({forceMetadata: !hrrrTLEReady});
    }

    if (HRRR_TLE_CONFIG_BY_NAME.has(eventLayer.name)) {
        if (hrrrTLETimeBox) {
            hrrrTLETimeBox.innerHTML = formatHRRRTLETimeBox(
                HRRR_TLE_CONFIG_BY_NAME.get(eventLayer.name),
                hrrrTLEMetadata
            );
            hrrrTLETimeBox.style.display = 'block';
        }
        refreshHRRRTLEFromManifest({forceMetadata: !hrrrTLEReady});
    }

    const glmConfig = glmConfigByName.get(eventLayer.name);
    if (glmConfig) {
        if (glmTimeBox) {
            glmTimeBox.innerHTML = formatGLMTimeBox(
                glmConfig,
                glmMetadataByName.get(glmConfig.name)
            );
            glmTimeBox.style.display = 'block';
        }
        updateGLMTrendCard();
        fetchGLMMetadata([glmConfig]);
    }

    if (eventLayer.name === 'NWM Soil Saturation (0-40cm)') {
        fetchNWMMetadata();

        if (nwmTimeBox) {
            nwmTimeBox.innerHTML = nwmLayerReady
                ? `<strong>NWM 0-40cm Soil Saturation</strong><br><span style="color: #ffeb3b;">${nwmValidTime}</span>`
                : `<strong>NWM 0-40cm Soil Saturation</strong><br><span style="color: #ffeb3b;">Loading latest raster...</span>`;
            nwmTimeBox.style.display = 'block';
        }
    }

    if (eventLayer.name === 'NASA SPoRT-LIS VSM Percentile (0–100 cm)') {
        fetchSPoRTMetadata();

        if (sportTimeBox) {
            sportTimeBox.innerHTML = sportLayerReady
                ? `<strong>NASA SPoRT-LIS VSM Percentile (0–100 cm)</strong><br><span style="color: #ffeb3b;">${sportValidTime}</span>`
                : `<strong>NASA SPoRT-LIS VSM Percentile (0–100 cm)</strong><br><span style="color: #ffeb3b;">Loading latest raster...</span>`;
            sportTimeBox.style.display = 'block';
        }
    }

    if (eventLayer.name === 'NLDAS-2 Noah Relative Soil Moisture (0-10 cm)') {
        fetchNLDASRSMMetadata();

        if (nldasRsm010TimeBox) {
            nldasRsm010TimeBox.innerHTML = nldasRsmReady
                ? `<strong>NLDAS-2 Noah RSM (0-10 cm)</strong><br><span style="color: #ffeb3b;">${nldasRsmValidTime}</span>`
                : `<strong>NLDAS-2 Noah RSM (0-10 cm)</strong><br><span style="color: #ffeb3b;">Loading latest raster...</span>`;
            nldasRsm010TimeBox.style.display = 'block';
        }
    }

    if (eventLayer.name === 'NLDAS-2 Noah Relative Soil Moisture (0-100 cm)') {
        fetchNLDASRSMMetadata();

        if (nldasRsm0100TimeBox) {
            nldasRsm0100TimeBox.innerHTML = nldasRsmReady
                ? `<strong>NLDAS-2 Noah RSM (0-100 cm)</strong><br><span style="color: #ffeb3b;">${nldasRsmValidTime}</span>`
                : `<strong>NLDAS-2 Noah RSM (0-100 cm)</strong><br><span style="color: #ffeb3b;">Loading latest raster...</span>`;
            nldasRsm0100TimeBox.style.display = 'block';
        }
    }

    if (eventLayer.name.includes('SuperEnsemble') || eventLayer.name.includes('HREF') || eventLayer.name.includes('REFS')) {
        let titleText = "";
        let cycleText = `HREF: ${camCycles.href}Z &nbsp;|&nbsp; REFS: ${camCycles.refs}Z`;
        let targetCycleForMath = camCycles.href; 
        
        if (eventLayer.name.includes('SuperEnsemble')) {
            titleText = "SuperEnsemble Blend";
        } else if (eventLayer.name.includes('HREF')) {
            titleText = "HREF Only";
            cycleText = `Latest Run: ${camCycles.href}Z`;
            targetCycleForMath = camCycles.href;
        } else if (eventLayer.name.includes('REFS')) {
            titleText = "REFS Only";
            cycleText = `Latest Run: ${camCycles.refs}Z`;
            targetCycleForMath = camCycles.refs;
        }

        let validRangeStr = "Valid Time Unknown";
        if (eventLayer.name.includes('[ERO]')) {
            titleText = titleText + " (Day 1 ERO)";
            validRangeStr = eroValidRangeStr;
        } else {
            let currentWindow = "+3h to +9h";
            let matchedKey = Object.keys(camLayers).find(key => camLayers[key] === eventLayer.layer);
            if (matchedKey && matchedKey.includes('9h_to_15h')) {
                currentWindow = "+9h to +15h";
            }
            validRangeStr = getValidTimeRange(targetCycleForMath, currentWindow);
        }

        let productName = "Probabilistic Guidance";
        if (eventLayer.name.includes(':')) {
            productName = eventLayer.name.split(':')[1].trim(); 
        }

        camTimeBox.innerHTML = `
            <strong>${titleText}</strong><br>
            <span style="color: #4fc3f7; font-weight: bold; font-size: 0.95em;">${productName}</span><br>
            <span style="font-size: 0.9em;">${cycleText}</span>
            <hr style="margin: 5px 0; border-color: #555;">
            <span style="font-size: 0.95em; color: #ffeb3b;">Valid: ${validRangeStr}</span>
        `;
        camTimeBox.style.display = 'block';
    }

    if (eventLayer.name.includes('NEXRAD Radar')) {
        radarTimeBox.style.display = 'block';
        const currentFrameTime = new Date(map.timeDimension.getCurrentTime());
        radarTimeBox.innerHTML = `
            <strong>NEXRAD Radar Loop</strong><br>
            <span style="color: #ffeb3b; font-weight: bold; font-size: 1.05em;">Frame: ${formatUTC(currentFrameTime)}</span>
        `;
    }

    if (eventLayer.name.includes('GOES-') && !glmConfigByName.has(eventLayer.name)) {
        radarTimeBox.style.display = 'block';
        radarTimeBox.innerHTML = `
            <strong>${eventLayer.name}</strong><br>
            <span style="color: #4fc3f7; font-weight: bold; font-size: 0.95em;">Real-Time Feed</span><br>
            <span style="font-size: 0.85em; color: #ffeb3b;">Last Checked: ${formatUTC(new Date())}</span>
        `;
    }


    refreshLegendDockSummary();
});

map.on('overlayremove', function(eventLayer) {
    activeLayerNames.delete(eventLayer.name);
    updateLegends();

    const rapTimeBox = document.getElementById('rap-time-box');
    const mrmsTimeBox = document.getElementById('mrms-time-box');
    const camTimeBox = document.getElementById('cam-time-box');
    const radarTimeBox = document.getElementById('radar-time-box');
    const ffdTimeBox = document.getElementById('ffd-time-box');
    const mrmsCrest24hTimeBox = document.getElementById('mrms-crest-24h-time-box');
    const mrmsFfd24hTimeBox = document.getElementById('mrms-ffd-24h-time-box');
    const glmTimeBox = document.getElementById('glm-time-box');
    const lightningCastTimeBox = document.getElementById('lightningcast-time-box');
    const hrrrDiagnosticsTimeBox = document.getElementById('hrrr-diagnostics-time-box');
    const hrrrTLETimeBox = document.getElementById('hrrr-tle-time-box');
    const nwmTimeBox = document.getElementById('nwm-time-box');
    const sportTimeBox = document.getElementById('sport-time-box');
    const nldasRsm010TimeBox = document.getElementById('nldas-rsm-010-time-box');
    const nldasRsm0100TimeBox = document.getElementById('nldas-rsm-0100-time-box');
    
    if (rapLegendMapping[eventLayer.name]) {
        const hasRAP = Array.from(activeLayerNames).some(name => rapLegendMapping[name]);
        if (!hasRAP) rapTimeBox.style.display = 'none';
    }
    
    if (eventLayer.name.includes('MRMS') && eventLayer.name.includes('QPE')) {
        const hasMRMS = Array.from(activeLayerNames).some(name => name.includes('MRMS') && name.includes('QPE'));
        if (!hasMRMS) mrmsTimeBox.style.display = 'none';
    }
    
    if (eventLayer.name.includes('MRMS DVD Flash Flood Detector')) {
        if (ffdTimeBox) ffdTimeBox.style.display = 'none';
    }

    if (eventLayer.name === MRMS_CREST_24H_LAYER_NAME) {
        if (mrmsCrest24hTimeBox) mrmsCrest24hTimeBox.style.display = 'none';
    }

    if (eventLayer.name === MRMS_FFD_24H_LAYER_NAME) {
        if (mrmsFfd24hTimeBox) mrmsFfd24hTimeBox.style.display = 'none';
    }

    if (eventLayer.name === LIGHTNINGCAST_LAYER_NAME) {
        if (lightningCastTimeBox) lightningCastTimeBox.style.display = 'none';
    }

    if (HRRR_DIAGNOSTIC_CONFIG_BY_NAME.has(eventLayer.name)) {
        window.setTimeout(updateHRRRDiagnosticTimeBox, 0);
    }

    if (HRRR_TLE_CONFIG_BY_NAME.has(eventLayer.name)) {
        window.setTimeout(updateHRRRTLETimeBox, 0);
    }

    if (glmConfigByName.has(eventLayer.name)) {
        window.setTimeout(() => {
            updateGLMTimeBox();
            updateGLMTrendCard();
        }, 0);
    }

    if (eventLayer.name === 'NWM Soil Saturation (0-40cm)') {
        if (nwmTimeBox) nwmTimeBox.style.display = 'none';
    }

    if (eventLayer.name === 'NASA SPoRT-LIS VSM Percentile (0–100 cm)') {
        if (sportTimeBox) sportTimeBox.style.display = 'none';
    }

    if (eventLayer.name === 'NLDAS-2 Noah Relative Soil Moisture (0-10 cm)') {
        if (nldasRsm010TimeBox) nldasRsm010TimeBox.style.display = 'none';
    }

    if (eventLayer.name === 'NLDAS-2 Noah Relative Soil Moisture (0-100 cm)') {
        if (nldasRsm0100TimeBox) nldasRsm0100TimeBox.style.display = 'none';
    }
    
    if (eventLayer.name.includes('SuperEnsemble') || eventLayer.name.includes('HREF') || eventLayer.name.includes('REFS') || eventLayer.name.includes('[ERO]')) {
        const hasCAM = Array.from(activeLayerNames).some(name => name.includes('SuperEnsemble') || name.includes('HREF') || name.includes('REFS'));
        if (!hasCAM) camTimeBox.style.display = 'none';
    }
    
    if (eventLayer.name.includes('NEXRAD Radar') || (eventLayer.name.includes('GOES-') && !glmConfigByName.has(eventLayer.name))) {
        const hasSatRadar = Array.from(activeLayerNames).some(name => name.includes('NEXRAD Radar') || (name.includes('GOES-') && !glmConfigByName.has(name)));
        if (!hasSatRadar) radarTimeBox.style.display = 'none';
    }


    refreshLegendDockSummary();
});

// --- SIDEBAR LAYER REGISTRY & CONTROLS ---
// This registry is the single source of truth for layer order, labels, search,
// sidebar selection, opacity utilities, and future experimental additions.
const baseMapRegistry = [
    {id: 'esri-dark', label: 'Esri Dark Gray', layer: esriDarkBase},
    {id: 'osm', label: 'OpenStreetMap', layer: osmLayer},
    {id: 'esri-imagery', label: 'Esri World Imagery (Satellite)', layer: esriWorldImagery},
    {id: 'esri-topo', label: 'Esri World Topographic', layer: esriWorldTopo}
];

function enforceExclusiveGLMSelection(activeEntry) {
    getAllDashboardLayerEntries().forEach(entry => {
        if (entry !== activeEntry && entry.id && entry.id.startsWith('glm-') && map.hasLayer(entry.layer)) {
            setDashboardLayerActive(entry, false);
        }
    });
}

const dashboardSections = [
    {
        id: 'hazards',
        title: 'Active Hazards & Warnings',
        openByDefault: true,
        layers: [
            {id: 'hydro-warnings', label: 'Active Hydro Warnings & Advisories', layer: warningsLayer, kind: 'vector', defaultActive: true},
            {id: 'hydro-watches', label: 'Active Hydro Watches', layer: watchesLayer, kind: 'vector', defaultActive: true},
            {id: 'wpc-mpds', label: 'WPC Active MPDs', layer: mpdLayer, kind: 'vector', defaultActive: true},
            {id: 'day1-ero', label: 'Day 1 ERO (Real-Time)', layer: eroLayer, kind: 'vector', defaultActive: true}
        ]
    },
    {
        id: 'radar-satellite',
        title: 'Radar and Satellite Data (Real-Time)',
        layers: [
            {id: 'nexrad-loop', label: 'NEXRAD Radar (2-Hour Loop)', layer: radarTimeLayer, kind: 'raster', opacityTarget: radarWMS, defaultActive: true},
            {id: 'mrms-ffd', label: 'MRMS DVD Flash Flood Detector', layer: ffdLayer, kind: 'vector'},
            {id: 'mrms-qpe-1h', label: 'MRMS 1-Hour QPE', layer: mrms1hr, kind: 'raster'},
            {id: 'mrms-qpe-24h', label: 'MRMS 24-Hour QPE', layer: mrms24hr, kind: 'raster'},
            {id: 'mrms-flash-crest-24h', label: MRMS_CREST_24H_LAYER_NAME, layer: mrmsCrest24hLayer, kind: 'raster'},
            {id: 'mrms-flash-ffd-24h', label: MRMS_FFD_24H_LAYER_NAME, layer: mrmsFfd24hLayer, kind: 'raster'},
            {id: 'mrms-qpe-48h', label: 'MRMS 48-Hour QPE', layer: mrms48hr, kind: 'raster'},
            {id: 'mrms-qpe-72h', label: 'MRMS 72-Hour QPE', layer: mrms72hr, kind: 'raster'},
            {id: 'goes-east-vis', label: 'GOES-East: Visible (Ch. 2)', layer: goesEastVis, kind: 'raster'},
            {id: 'goes-east-wv', label: 'GOES-East: Mid-Level WV (Ch. 9)', layer: goesEastWV, kind: 'raster'},
            {id: 'goes-east-ir', label: 'GOES-East: Clean IR (Ch. 13)', layer: goesEastIR, kind: 'raster'},
            {id: 'goes-west-vis', label: 'GOES-West: Visible (Ch. 2)', layer: goesWestVis, kind: 'raster'},
            {id: 'goes-west-wv', label: 'GOES-West: Mid-Level WV (Ch. 9)', layer: goesWestWV, kind: 'raster'},
            {id: 'goes-west-ir', label: 'GOES-West: Clean IR (Ch. 13)', layer: goesWestIR, kind: 'raster'},
            {id: 'glm-mosaic-5min', label: GLM_MOSAIC_5MIN_LAYER_NAME, layer: glmMosaic5minLayer, kind: 'raster', exclusiveGroup: 'glm-primary', onActivate: enforceExclusiveGLMSelection},
            {id: 'glm-mosaic-30min', label: GLM_MOSAIC_30MIN_LAYER_NAME, layer: glmMosaic30minLayer, kind: 'raster', exclusiveGroup: 'glm-primary', onActivate: enforceExclusiveGLMSelection},
            {id: 'glm-mosaic-60min', label: GLM_MOSAIC_60MIN_LAYER_NAME, layer: glmMosaic60minLayer, kind: 'raster', exclusiveGroup: 'glm-primary', onActivate: enforceExclusiveGLMSelection},
            {id: 'glm-convective-trend-15min', label: GLM_TREND_MAP_15MIN_LAYER_NAME, layer: glmTrendMap15minLayer, kind: 'raster', exclusiveGroup: 'glm-primary', onActivate: enforceExclusiveGLMSelection},
            {id: 'lightningcast-probability-60min', label: LIGHTNINGCAST_LAYER_NAME, layer: lightningCastLayer, kind: 'raster', keywords: 'lightning forecast probability CIMSS SSEC next 60 minutes'}
        ]
    },
    {
        id: 'antecedent',
        title: 'Antecedent Hydrologic Conditions',
        layers: [
            {id: 'nwm-soilsat', label: 'NWM Soil Saturation (0-40cm)', layer: nwmLayer, kind: 'raster'},
            {id: 'nldas-rsm-010', label: 'NLDAS-2 Noah Relative Soil Moisture (0-10 cm)', layer: nldasRsm010Layer, kind: 'raster'},
            {id: 'nldas-rsm-0100', label: 'NLDAS-2 Noah Relative Soil Moisture (0-100 cm)', layer: nldasRsm0100Layer, kind: 'raster'},
            {id: 'sport-percentile', label: 'NASA SPoRT-LIS VSM Percentile (0–100 cm)', layer: sportLayer, kind: 'raster'}
        ]
    },
    {
        id: 'rap',
        title: 'RAP Mesoanalysis Data',
        layers: [
            {id: 'rap-pwat', label: 'Precipitable Water (PWAT)', layer: pwatLayer, kind: 'raster'},
            {id: 'rap-pwat-diff', label: '&nbsp;&nbsp;&nbsp;&nbsp;3-Hour PWAT Change', layer: pwatDiffLayer, kind: 'raster', nested: true},
            {id: 'rap-pwat-f03', label: '&nbsp;&nbsp;&nbsp;&nbsp;▶ <b>+3h Forecast:</b> PWAT', layer: pwatF03Layer, kind: 'raster', nested: true},

            {id: 'rap-sbcape', label: 'Surface Based CAPE', layer: sbcapeLayer, kind: 'raster'},
            {id: 'rap-sbcape-diff', label: '&nbsp;&nbsp;&nbsp;&nbsp;3-Hour SBCAPE Change', layer: sbcapeDiffLayer, kind: 'raster', nested: true},
            {id: 'rap-sbcape-f03', label: '&nbsp;&nbsp;&nbsp;&nbsp;▶ <b>+3h Forecast:</b> SBCAPE', layer: sbcapeF03Layer, kind: 'raster', nested: true},

            {id: 'rap-mlcape', label: 'Mixed Layer CAPE (90mb)', layer: mlcapeLayer, kind: 'raster'},
            {id: 'rap-mlcape-diff', label: '&nbsp;&nbsp;&nbsp;&nbsp;3-Hour MLCAPE Change', layer: mlcapeDiffLayer, kind: 'raster', nested: true},
            {id: 'rap-mlcape-f03', label: '&nbsp;&nbsp;&nbsp;&nbsp;▶ <b>+3h Forecast:</b> MLCAPE', layer: mlcapeF03Layer, kind: 'raster', nested: true},

            {id: 'rap-mucape', label: 'Most Unstable CAPE (255mb)', layer: mucapeLayer, kind: 'raster'},
            {id: 'rap-mucape-diff', label: '&nbsp;&nbsp;&nbsp;&nbsp;3-Hour MUCAPE Change', layer: mucapeDiffLayer, kind: 'raster', nested: true},
            {id: 'rap-mucape-f03', label: '&nbsp;&nbsp;&nbsp;&nbsp;▶ <b>+3h Forecast:</b> MUCAPE', layer: mucapeF03Layer, kind: 'raster', nested: true},

            {id: 'rap-lr-sfc3', label: 'Sfc-3km Low-Level Lapse Rate', layer: lrsfc3Layer, kind: 'raster'},
            {id: 'rap-lr-75', label: '700-500mb Mid-Level Lapse Rate', layer: lr75Layer, kind: 'raster'},
            {id: 'rap-scp', label: 'Supercell Composite Parameter', layer: scpLayer, kind: 'raster'},
            {id: 'rap-mfc', label: 'Mean BL Moisture Convergence', layer: mfcLayer, kind: 'raster'},
            {id: 'rap-f925', label: '925/850mb Frontogenesis', layer: f925Layer, kind: 'raster'},
            {id: 'rap-f850', label: '850/700mb Frontogenesis', layer: f850Layer, kind: 'raster'},
            {id: 'rap-eff-shear', label: 'Effective Bulk Shear', layer: effShearLayer, kind: 'raster'},
            {id: 'rap-corfidi-up', label: 'Corfidi Upwind (Back-Building) Vectors', layer: corfidiUpLayer, kind: 'raster'},
            {id: 'rap-corfidi-down', label: 'Corfidi Downwind (Forward) Vectors', layer: corfidiDownLayer, kind: 'raster'},

            {id: 'rap-trans850', label: '850mb Moisture Transport', layer: trans850Layer, kind: 'raster'},
            {id: 'rap-trans850-diff', label: '&nbsp;&nbsp;&nbsp;&nbsp;3-Hour 850mb Moisture Transport Change', layer: trans850DiffLayer, kind: 'raster', nested: true},
            {id: 'rap-trans850-f03', label: '&nbsp;&nbsp;&nbsp;&nbsp;▶ <b>+3h Forecast:</b> 850mb Moisture Transport', layer: trans850F03Layer, kind: 'raster', nested: true},

            {id: 'rap-trans700', label: '700mb Moisture Transport', layer: trans700Layer, kind: 'raster'},
            {id: 'rap-mean-wind', label: '850-300mb Mean Layer Wind', layer: meanWindLayer, kind: 'raster'},
            {id: 'rap-vort500', label: '500mb Absolute Vorticity', layer: vort500Layer, kind: 'raster'},
            {id: 'rap-diff-adv', label: '700-400mb Diff Vorticity Advection', layer: diffAdvLayer, kind: 'raster'},
            {id: 'rap-div250', label: '250mb Divergence', layer: div250Layer, kind: 'raster'}
        ]
    },
    {
        id: 'hrrr-diagnostics',
        title: 'HRRR Flash Flood Diagnostics - Experimental',
        layers: HRRR_DIAGNOSTIC_LAYER_CONFIGS.map(config => ({
            id: config.id,
            label: config.label,
            layer: config.layer,
            kind: 'raster',
            keywords: config.keywords
        }))
    },
    {
        id: 'hrrr-tle',
        title: 'HRRR-TLE Flash Flood Guidance - Experimental',
        layers: [],
        groups: [
            {
                id: 'hrrr-tle-core',
                title: 'Core FFG Guidance',
                openByDefault: true,
                layers: HRRR_TLE_LAYER_CONFIGS
                    .filter(config => config.group === 'Core FFG Guidance')
                    .map(config => ({
                        id: config.id, label: config.label, layer: config.layer,
                        kind: 'raster', keywords: config.keywords
                    }))
            },
            {
                id: 'hrrr-tle-heavy-rain',
                title: 'Heavy Rain / Persistence',
                layers: HRRR_TLE_LAYER_CONFIGS
                    .filter(config => config.group === 'Heavy Rain / Persistence')
                    .map(config => ({
                        id: config.id, label: config.label, layer: config.layer,
                        kind: 'raster', keywords: config.keywords
                    }))
            },
            {
                id: 'hrrr-tle-timing',
                title: 'Timing / Evolution',
                layers: HRRR_TLE_LAYER_CONFIGS
                    .filter(config => config.group === 'Timing / Evolution')
                    .map(config => ({
                        id: config.id, label: config.label, layer: config.layer,
                        kind: 'raster', keywords: config.keywords
                    }))
            }
        ]
    },
    {
        id: 'cam-3-9',
        title: 'CAM Nowcasts (+3h to +9h)',
        layers: [
            {id: 'cam-3-9-ffg-super', label: '<b>SuperEnsemble</b>: Max FFG Exceedance', layer: camLayers['ffg_3h_to_9h_super'], kind: 'raster'},
            {id: 'cam-3-9-ffg-href', label: '&nbsp;&nbsp;&nbsp;&nbsp;HREF: Max FFG Exceedance', layer: camLayers['ffg_3h_to_9h_href'], kind: 'raster', nested: true},
            {id: 'cam-3-9-ffg-refs', label: '&nbsp;&nbsp;&nbsp;&nbsp;REFS: Max FFG Exceedance', layer: camLayers['ffg_3h_to_9h_refs'], kind: 'raster', nested: true},
            {id: 'cam-3-9-q05-super', label: '<b>SuperEnsemble</b>: Max Prob > 0.5"/hr', layer: camLayers['qpf_3h_to_9h_0.5_inch_super'], kind: 'raster'},
            {id: 'cam-3-9-q05-href', label: '&nbsp;&nbsp;&nbsp;&nbsp;HREF: Max Prob > 0.5"/hr', layer: camLayers['qpf_3h_to_9h_0.5_inch_href'], kind: 'raster', nested: true},
            {id: 'cam-3-9-q05-refs', label: '&nbsp;&nbsp;&nbsp;&nbsp;REFS: Max Prob > 0.5"/hr', layer: camLayers['qpf_3h_to_9h_0.5_inch_refs'], kind: 'raster', nested: true},
            {id: 'cam-3-9-q1-super', label: '<b>SuperEnsemble</b>: Max Prob > 1.0"/hr', layer: camLayers['qpf_3h_to_9h_1_inch_super'], kind: 'raster'},
            {id: 'cam-3-9-q1-href', label: '&nbsp;&nbsp;&nbsp;&nbsp;HREF: Max Prob > 1.0"/hr', layer: camLayers['qpf_3h_to_9h_1_inch_href'], kind: 'raster', nested: true},
            {id: 'cam-3-9-q1-refs', label: '&nbsp;&nbsp;&nbsp;&nbsp;REFS: Max Prob > 1.0"/hr', layer: camLayers['qpf_3h_to_9h_1_inch_refs'], kind: 'raster', nested: true},
            {id: 'cam-3-9-q2-super', label: '<b>SuperEnsemble</b>: Max Prob > 2.0"/hr', layer: camLayers['qpf_3h_to_9h_2_inch_super'], kind: 'raster'},
            {id: 'cam-3-9-q2-href', label: '&nbsp;&nbsp;&nbsp;&nbsp;HREF: Max Prob > 2.0"/hr', layer: camLayers['qpf_3h_to_9h_2_inch_href'], kind: 'raster', nested: true},
            {id: 'cam-3-9-q2-refs', label: '&nbsp;&nbsp;&nbsp;&nbsp;REFS: Max Prob > 2.0"/hr', layer: camLayers['qpf_3h_to_9h_2_inch_refs'], kind: 'raster', nested: true},
            {id: 'cam-3-9-q3-super', label: '<b>SuperEnsemble</b>: Max Prob > 3.0"/hr', layer: camLayers['qpf_3h_to_9h_3_inch_super'], kind: 'raster'},
            {id: 'cam-3-9-q3-href', label: '&nbsp;&nbsp;&nbsp;&nbsp;HREF: Max Prob > 3.0"/hr', layer: camLayers['qpf_3h_to_9h_3_inch_href'], kind: 'raster', nested: true},
            {id: 'cam-3-9-q3-refs', label: '&nbsp;&nbsp;&nbsp;&nbsp;REFS: Max Prob > 3.0"/hr', layer: camLayers['qpf_3h_to_9h_3_inch_refs'], kind: 'raster', nested: true}
        ]
    },
    {
        id: 'cam-9-15',
        title: 'CAM Nowcasts (+9h to +15h)',
        layers: [
            {id: 'cam-9-15-ffg-super', label: '<b>SuperEnsemble</b>: Max FFG Exceedance', layer: camLayers['ffg_9h_to_15h_super'], kind: 'raster'},
            {id: 'cam-9-15-ffg-href', label: '&nbsp;&nbsp;&nbsp;&nbsp;HREF: Max FFG Exceedance', layer: camLayers['ffg_9h_to_15h_href'], kind: 'raster', nested: true},
            {id: 'cam-9-15-ffg-refs', label: '&nbsp;&nbsp;&nbsp;&nbsp;REFS: Max FFG Exceedance', layer: camLayers['ffg_9h_to_15h_refs'], kind: 'raster', nested: true},
            {id: 'cam-9-15-q05-super', label: '<b>SuperEnsemble</b>: Max Prob > 0.5"/hr', layer: camLayers['qpf_9h_to_15h_0.5_inch_super'], kind: 'raster'},
            {id: 'cam-9-15-q05-href', label: '&nbsp;&nbsp;&nbsp;&nbsp;HREF: Max Prob > 0.5"/hr', layer: camLayers['qpf_9h_to_15h_0.5_inch_href'], kind: 'raster', nested: true},
            {id: 'cam-9-15-q05-refs', label: '&nbsp;&nbsp;&nbsp;&nbsp;REFS: Max Prob > 0.5"/hr', layer: camLayers['qpf_9h_to_15h_0.5_inch_refs'], kind: 'raster', nested: true},
            {id: 'cam-9-15-q1-super', label: '<b>SuperEnsemble</b>: Max Prob > 1.0"/hr', layer: camLayers['qpf_9h_to_15h_1_inch_super'], kind: 'raster'},
            {id: 'cam-9-15-q1-href', label: '&nbsp;&nbsp;&nbsp;&nbsp;HREF: Max Prob > 1.0"/hr', layer: camLayers['qpf_9h_to_15h_1_inch_href'], kind: 'raster', nested: true},
            {id: 'cam-9-15-q1-refs', label: '&nbsp;&nbsp;&nbsp;&nbsp;REFS: Max Prob > 1.0"/hr', layer: camLayers['qpf_9h_to_15h_1_inch_refs'], kind: 'raster', nested: true},
            {id: 'cam-9-15-q2-super', label: '<b>SuperEnsemble</b>: Max Prob > 2.0"/hr', layer: camLayers['qpf_9h_to_15h_2_inch_super'], kind: 'raster'},
            {id: 'cam-9-15-q2-href', label: '&nbsp;&nbsp;&nbsp;&nbsp;HREF: Max Prob > 2.0"/hr', layer: camLayers['qpf_9h_to_15h_2_inch_href'], kind: 'raster', nested: true},
            {id: 'cam-9-15-q2-refs', label: '&nbsp;&nbsp;&nbsp;&nbsp;REFS: Max Prob > 2.0"/hr', layer: camLayers['qpf_9h_to_15h_2_inch_refs'], kind: 'raster', nested: true},
            {id: 'cam-9-15-q3-super', label: '<b>SuperEnsemble</b>: Max Prob > 3.0"/hr', layer: camLayers['qpf_9h_to_15h_3_inch_super'], kind: 'raster'},
            {id: 'cam-9-15-q3-href', label: '&nbsp;&nbsp;&nbsp;&nbsp;HREF: Max Prob > 3.0"/hr', layer: camLayers['qpf_9h_to_15h_3_inch_href'], kind: 'raster', nested: true},
            {id: 'cam-9-15-q3-refs', label: '&nbsp;&nbsp;&nbsp;&nbsp;REFS: Max Prob > 3.0"/hr', layer: camLayers['qpf_9h_to_15h_3_inch_refs'], kind: 'raster', nested: true}
        ]
    },
    {
        id: 'ero-cams',
        title: 'Day 1 ERO CAMs (12Z-12Z)',
        layers: [
            {id: 'ero-ffg-super', label: '<b>SuperEnsemble [ERO]</b>: Max FFG Exceedance', layer: eroCamLayers['ffg_super'], kind: 'raster'},
            {id: 'ero-ffg-href', label: '&nbsp;&nbsp;&nbsp;&nbsp;HREF [ERO]: Max FFG Exceedance', layer: eroCamLayers['ffg_href'], kind: 'raster', nested: true},
            {id: 'ero-ffg-refs', label: '&nbsp;&nbsp;&nbsp;&nbsp;REFS [ERO]: Max FFG Exceedance', layer: eroCamLayers['ffg_refs'], kind: 'raster', nested: true},
            {id: 'ero-q05-super', label: '<b>SuperEnsemble [ERO]</b>: Max Prob > 0.5"/hr', layer: eroCamLayers['qpf_0.5_inch_super'], kind: 'raster'},
            {id: 'ero-q05-href', label: '&nbsp;&nbsp;&nbsp;&nbsp;HREF [ERO]: Max Prob > 0.5"/hr', layer: eroCamLayers['qpf_0.5_inch_href'], kind: 'raster', nested: true},
            {id: 'ero-q05-refs', label: '&nbsp;&nbsp;&nbsp;&nbsp;REFS [ERO]: Max Prob > 0.5"/hr', layer: eroCamLayers['qpf_0.5_inch_refs'], kind: 'raster', nested: true},
            {id: 'ero-q1-super', label: '<b>SuperEnsemble [ERO]</b>: Max Prob > 1.0"/hr', layer: eroCamLayers['qpf_1_inch_super'], kind: 'raster'},
            {id: 'ero-q1-href', label: '&nbsp;&nbsp;&nbsp;&nbsp;HREF [ERO]: Max Prob > 1.0"/hr', layer: eroCamLayers['qpf_1_inch_href'], kind: 'raster', nested: true},
            {id: 'ero-q1-refs', label: '&nbsp;&nbsp;&nbsp;&nbsp;REFS [ERO]: Max Prob > 1.0"/hr', layer: eroCamLayers['qpf_1_inch_refs'], kind: 'raster', nested: true},
            {id: 'ero-q2-super', label: '<b>SuperEnsemble [ERO]</b>: Max Prob > 2.0"/hr', layer: eroCamLayers['qpf_2_inch_super'], kind: 'raster'},
            {id: 'ero-q2-href', label: '&nbsp;&nbsp;&nbsp;&nbsp;HREF [ERO]: Max Prob > 2.0"/hr', layer: eroCamLayers['qpf_2_inch_href'], kind: 'raster', nested: true},
            {id: 'ero-q2-refs', label: '&nbsp;&nbsp;&nbsp;&nbsp;REFS [ERO]: Max Prob > 2.0"/hr', layer: eroCamLayers['qpf_2_inch_refs'], kind: 'raster', nested: true},
            {id: 'ero-q3-super', label: '<b>SuperEnsemble [ERO]</b>: Max Prob > 3.0"/hr', layer: eroCamLayers['qpf_3_inch_super'], kind: 'raster'},
            {id: 'ero-q3-href', label: '&nbsp;&nbsp;&nbsp;&nbsp;HREF [ERO]: Max Prob > 3.0"/hr', layer: eroCamLayers['qpf_3_inch_href'], kind: 'raster', nested: true},
            {id: 'ero-q3-refs', label: '&nbsp;&nbsp;&nbsp;&nbsp;REFS [ERO]: Max Prob > 3.0"/hr', layer: eroCamLayers['qpf_3_inch_refs'], kind: 'raster', nested: true}
        ]
    },
    {
        id: 'experimental',
        title: 'Experimental Models',
        layers: [],
        emptyMessage: 'Ready for NLDAS-3 and other experimental products. New layers can be registered without rebuilding the sidebar.'
    }
];


const dashboardUtilityLayers = [];

const layerEntriesById = new Map();
let selectedDashboardLayerId = null;
let sidebarRenderQueued = false;

function cleanLayerLabel(label) {
    const node = document.createElement('div');
    node.innerHTML = label;
    return (node.textContent || node.innerText || '')
        .replace(/\u00a0/g, ' ')
        .replace(/\s+/g, ' ')
        .trim();
}

function getSectionLayerEntries(section) {
    return [
        ...(section.layers || []),
        ...((section.groups || []).flatMap(group => group.layers || []))
    ];
}

function getAllDashboardLayerEntries() {
    return [
        ...dashboardSections.flatMap(getSectionLayerEntries),
        ...dashboardUtilityLayers
    ];
}

function rebuildLayerEntryIndex() {
    layerEntriesById.clear();
    getAllDashboardLayerEntries().forEach(entry => {
        if (!entry.id || !entry.label || !entry.layer) {
            throw new Error('Every dashboard layer requires id, label, and layer.');
        }
        if (layerEntriesById.has(entry.id)) {
            throw new Error(`Duplicate dashboard layer id: ${entry.id}`);
        }
        entry.searchText = cleanLayerLabel(
            `${entry.label} ${entry.keywords || ''}`
        ).toLowerCase();
        layerEntriesById.set(entry.id, entry);
    });
}

function dispatchOverlayEvent(eventName, entry) {
    map.fire(eventName, {
        name: entry.label,
        layer: entry.layer
    });
}

function setDashboardLayerActive(entry, shouldBeActive) {
    const isActive = map.hasLayer(entry.layer);

    if (shouldBeActive && !isActive) {
        map.addLayer(entry.layer);
        dispatchOverlayEvent('overlayadd', entry);
        if (typeof entry.onActivate === 'function') entry.onActivate(entry);
    } else if (!shouldBeActive && isActive) {
        map.removeLayer(entry.layer);
        dispatchOverlayEvent('overlayremove', entry);
        if (typeof entry.onDeactivate === 'function') entry.onDeactivate(entry);
    }

    syncSidebarWithMap();
}

function selectDashboardLayer(entryId) {
    selectedDashboardLayerId = entryId;
    const selected = layerEntriesById.get(entryId) || null;
    const selectedName = document.getElementById('selected-layer-name');
    const opacitySlider = document.getElementById('layer-opacity');
    const opacityValue = document.getElementById('opacity-value');
    const soloButton = document.getElementById('solo-selected-layer');

    document.querySelectorAll('.layer-row').forEach(row => {
        row.classList.toggle('is-selected', row.dataset.layerId === entryId);
    });

    if (selectedName) {
        selectedName.textContent = selected
            ? cleanLayerLabel(selected.label)
            : 'No layer selected';
    }

    const opacityTarget = selected
        ? (selected.opacityTarget || selected.layer)
        : null;
    const canSetOpacity = Boolean(
        selected &&
        selected.kind === 'raster' &&
        opacityTarget &&
        typeof opacityTarget.setOpacity === 'function'
    );

    if (opacitySlider) {
        opacitySlider.disabled = !canSetOpacity;
        const currentOpacity = canSetOpacity
            ? Number(opacityTarget.options?.opacity ?? 1)
            : 1;
        opacitySlider.value = String(Math.round(currentOpacity * 100));
    }
    if (opacityValue) {
        opacityValue.textContent = canSetOpacity
            ? `${opacitySlider.value}%`
            : '—';
    }
    if (soloButton) {
        soloButton.disabled = !(selected && selected.kind === 'raster');
    }
}

function updateActiveLayerCount() {
    const activeCount = getAllDashboardLayerEntries()
        .filter(entry => map.hasLayer(entry.layer))
        .length;
    const target = document.getElementById('active-layer-count');
    if (target) {
        target.textContent = `${activeCount} active layer${activeCount === 1 ? '' : 's'}`;
    }
}

function syncSidebarWithMap() {
    document.querySelectorAll('.layer-checkbox[data-layer-id]').forEach(input => {
        const entry = layerEntriesById.get(input.dataset.layerId);
        if (entry) input.checked = map.hasLayer(entry.layer);
    });
    updateActiveLayerCount();
    if (selectedDashboardLayerId) selectDashboardLayer(selectedDashboardLayerId);
}

function renderLayerRow(entry) {
    const row = document.createElement('label');
    row.className = `layer-row${entry.nested ? ' is-nested' : ''}`;
    row.dataset.layerId = entry.id;
    row.dataset.searchText = entry.searchText;

    const control = document.createElement('input');
    const isExclusive = Boolean(entry.exclusiveGroup);
    control.type = isExclusive ? 'radio' : 'checkbox';
    control.className = 'layer-checkbox';
    control.dataset.layerId = entry.id;
    if (isExclusive) control.name = `layer-group-${entry.exclusiveGroup}`;
    control.checked = map.hasLayer(entry.layer);

    control.addEventListener('click', event => {
        selectDashboardLayer(entry.id);
        if (isExclusive && map.hasLayer(entry.layer)) {
            event.preventDefault();
            setDashboardLayerActive(entry, false);
            return;
        }
        setDashboardLayerActive(entry, isExclusive ? true : control.checked);
    });

    const label = document.createElement('span');
    label.className = 'layer-label';
    label.innerHTML = entry.label;

    row.addEventListener('click', () => selectDashboardLayer(entry.id));
    row.append(control, label);
    return row;
}

function renderUtilitySection(container) {
    const section = document.createElement('details');
    section.className = 'dashboard-section utility-section';
    section.dataset.sectionId = 'utilities';

    const summary = document.createElement('summary');
    summary.innerHTML = '<span class="section-title">Dashboard Utilities</span>';

    const body = document.createElement('div');
    body.className = 'section-body utility-grid';
    body.innerHTML = `
        <div class="utility-field">
            <label for="basemap-select">Basemap</label>
            <select id="basemap-select" aria-label="Select basemap"></select>
        </div>
        <div class="utility-toggle-field">
            <label class="utility-toggle-row" for="ufvs-geographic-domains-toggle">
                <input id="ufvs-geographic-domains-toggle" type="checkbox">
                <span>
                    <strong>UFVS Geographic Domains</strong>
                    <small>Overlay the seven WPC verification domains. Hover over a boundary for its domain name.</small>
                </span>
            </label>
        </div>
        <div class="opacity-control">
            <label for="layer-opacity">Selected raster opacity</label>
            <div class="opacity-row">
                <input id="layer-opacity" type="range" min="10" max="100" step="5" value="100" disabled>
                <span id="opacity-value">—</span>
            </div>
        </div>
        <div class="utility-button-grid">
            <button id="solo-selected-layer" class="sidebar-tool-button" type="button" disabled>Solo selected raster</button>
            <button id="clear-raster-layers" class="sidebar-tool-button" type="button">Clear raster layers</button>
            <button id="reset-map-view" class="sidebar-tool-button" type="button">Reset map extent</button>
            <button id="restore-dashboard-defaults" class="sidebar-tool-button" type="button">Restore defaults</button>
        </div>
    `;


    section.append(summary, body);
    container.append(section);

    const basemapSelect = body.querySelector('#basemap-select');
    baseMapRegistry.forEach(base => {
        const option = document.createElement('option');
        option.value = base.id;
        option.textContent = base.label;
        option.selected = map.hasLayer(base.layer);
        basemapSelect.append(option);
    });

    basemapSelect.addEventListener('change', () => {
        const next = baseMapRegistry.find(base => base.id === basemapSelect.value);
        if (!next) return;
        baseMapRegistry.forEach(base => {
            if (base !== next && map.hasLayer(base.layer)) map.removeLayer(base.layer);
        });
        if (!map.hasLayer(next.layer)) map.addLayer(next.layer);
        map.fire('baselayerchange', {name: next.label, layer: next.layer});
    });

    const ufvsDomainsToggle = body.querySelector('#ufvs-geographic-domains-toggle');
    ufvsDomainsToggle.checked = map.hasLayer(ufvsGeographicDomainsLayer);
    ufvsDomainsToggle.addEventListener('change', event => {
        setUFVSGeographicDomainsVisible(event.target.checked);
    });

    body.querySelector('#layer-opacity').addEventListener('input', event => {
        const selected = layerEntriesById.get(selectedDashboardLayerId);
        if (!selected) return;
        const target = selected.opacityTarget || selected.layer;
        if (typeof target.setOpacity !== 'function') return;
        const opacity = Number(event.target.value) / 100;
        target.setOpacity(opacity);
        body.querySelector('#opacity-value').textContent = `${event.target.value}%`;
    });

    body.querySelector('#solo-selected-layer').addEventListener('click', () => {
        const selected = layerEntriesById.get(selectedDashboardLayerId);
        if (!selected || selected.kind !== 'raster') return;
        getAllDashboardLayerEntries().forEach(entry => {
            if (entry.kind === 'raster' && entry !== selected) {
                setDashboardLayerActive(entry, false);
            }
        });
        setDashboardLayerActive(selected, true);
    });

    body.querySelector('#clear-raster-layers').addEventListener('click', () => {
        getAllDashboardLayerEntries().forEach(entry => {
            if (entry.kind === 'raster') setDashboardLayerActive(entry, false);
        });
    });

    body.querySelector('#reset-map-view').addEventListener('click', () => {
        map.setView([39.8283, -98.5795], 5);
    });

    body.querySelector('#restore-dashboard-defaults').addEventListener('click', () => {
        getAllDashboardLayerEntries().forEach(entry => {
            setDashboardLayerActive(entry, Boolean(entry.defaultActive));
        });
        const defaultBase = baseMapRegistry[0];
        baseMapRegistry.forEach(base => {
            if (base !== defaultBase && map.hasLayer(base.layer)) map.removeLayer(base.layer);
        });
        if (!map.hasLayer(defaultBase.layer)) map.addLayer(defaultBase.layer);
        map.fire('baselayerchange', {name: defaultBase.label, layer: defaultBase.layer});
        basemapSelect.value = defaultBase.id;
        setUFVSGeographicDomainsVisible(false);
        map.setView([39.8283, -98.5795], 5);
    });
}

function applyLayerSearch() {
    const searchInput = document.getElementById('layer-search');
    const query = (searchInput?.value || '').trim().toLowerCase();

    document.querySelectorAll('.dashboard-section[data-section-id]').forEach(sectionEl => {
        if (sectionEl.dataset.sectionId === 'utilities') return;
        const rows = Array.from(sectionEl.querySelectorAll('.layer-row'));
        let visibleRows = 0;
        rows.forEach(row => {
            const visible = !query || row.dataset.searchText.includes(query);
            row.hidden = !visible;
            if (visible) visibleRows += 1;
        });

        sectionEl.querySelectorAll('.dashboard-layer-group').forEach(groupEl => {
            const groupRows = Array.from(groupEl.querySelectorAll('.layer-row'));
            const groupVisible = groupRows.some(row => !row.hidden);
            groupEl.hidden = query ? !groupVisible : false;
            if (query && groupVisible) groupEl.open = true;
        });

        const isExperimentalEmpty = sectionEl.dataset.sectionId === 'experimental' && rows.length === 0;
        const emptyNote = sectionEl.querySelector('.empty-section-note');
        const noteMatches = isExperimentalEmpty && (!query || 'experimental nldas-3 model research'.includes(query));
        if (emptyNote) emptyNote.hidden = !noteMatches;

        sectionEl.hidden = query
            ? (visibleRows === 0 && !noteMatches)
            : false;
        if (query && !sectionEl.hidden) sectionEl.open = true;
    });
}

function renderDashboardSidebar() {
    if (sidebarRenderQueued) return;
    sidebarRenderQueued = true;
    requestAnimationFrame(() => {
        sidebarRenderQueued = false;
        rebuildLayerEntryIndex();
        const container = document.getElementById('sidebar-sections');
        if (!container) return;
        container.innerHTML = '';

        dashboardSections.forEach(sectionConfig => {
            const section = document.createElement('details');
            section.className = 'dashboard-section';
            section.dataset.sectionId = sectionConfig.id;
            section.open = Boolean(sectionConfig.openByDefault);

            const summary = document.createElement('summary');
            const count = getSectionLayerEntries(sectionConfig).length;
            summary.innerHTML = `
                <span class="section-title">${sectionConfig.title}</span>
                <span class="section-count">${count}</span>
            `;

            const body = document.createElement('div');
            body.className = 'section-body';

            if (count === 0) {
                const note = document.createElement('div');
                note.className = 'empty-section-note';
                note.textContent = sectionConfig.emptyMessage || 'No layers registered.';
                body.append(note);
            } else {
                (sectionConfig.layers || []).forEach(entry => body.append(renderLayerRow(entry)));

                (sectionConfig.groups || []).forEach(groupConfig => {
                    const group = document.createElement('details');
                    group.className = 'dashboard-layer-group';
                    group.dataset.groupId = groupConfig.id;
                    group.open = Boolean(groupConfig.openByDefault);

                    const groupSummary = document.createElement('summary');
                    groupSummary.innerHTML = `
                        <span>${groupConfig.title}</span>
                        <span class="section-count">${(groupConfig.layers || []).length}</span>
                    `;

                    const groupBody = document.createElement('div');
                    groupBody.className = 'dashboard-layer-group-body';
                    (groupConfig.layers || []).forEach(entry => groupBody.append(renderLayerRow(entry)));

                    group.append(groupSummary, groupBody);
                    body.append(group);
                });
            }

            section.append(summary, body);
            container.append(section);
        });

        renderUtilitySection(container);
        syncSidebarWithMap();
        applyLayerSearch();
    });
}

function setSidebarOpen(isOpen, persist = true) {
    document.body.classList.toggle('sidebar-open', isOpen);
    const toggle = document.getElementById('sidebar-toggle');
    if (toggle) toggle.setAttribute('aria-expanded', String(isOpen));
    if (persist) localStorage.setItem('wpcSidebarOpen', isOpen ? '1' : '0');
    window.setTimeout(() => map.invalidateSize(), 240);
}

function initializeSidebarControls() {
    const savedState = localStorage.getItem('wpcSidebarOpen');
    const defaultOpen = window.innerWidth > 900;
    setSidebarOpen(savedState === null ? defaultOpen : savedState === '1', false);

    document.getElementById('sidebar-toggle')?.addEventListener('click', () => setSidebarOpen(true));
    document.getElementById('sidebar-close')?.addEventListener('click', () => setSidebarOpen(false));
    document.getElementById('layer-search')?.addEventListener('input', applyLayerSearch);
    document.getElementById('clear-layer-search')?.addEventListener('click', () => {
        const input = document.getElementById('layer-search');
        if (input) input.value = '';
        applyLayerSearch();
        input?.focus();
    });
    document.addEventListener('keydown', event => {
        if (event.key === 'Escape' && document.body.classList.contains('sidebar-open')) {
            setSidebarOpen(false);
        }
    });
}

function registerDashboardLayer(sectionId, config) {
    const section = dashboardSections.find(item => item.id === sectionId);
    if (!section) throw new Error(`Unknown dashboard section: ${sectionId}`);
    if (!config || !config.id || !config.label || !config.layer) {
        throw new Error('registerDashboardLayer requires id, label, and layer.');
    }
    section.layers.push({kind: 'raster', ...config});
    renderDashboardSidebar();
    return config.layer;
}

window.WPCDashboard = Object.freeze({
    registerLayer: registerDashboardLayer,
    refreshSidebar: renderDashboardSidebar,
    sections: dashboardSections,
    getActiveLayers: () => getAllDashboardLayerEntries()
        .filter(entry => map.hasLayer(entry.layer))
        .map(entry => ({id: entry.id, label: cleanLayerLabel(entry.label)}))
});

initializeSidebarControls();
renderDashboardSidebar();
map.on('layeradd layerremove', () => window.setTimeout(syncSidebarWithMap, 0));

// --- INITIALIZE DEFAULT DASHBOARD STATE ---
setTimeout(() => {
    if (map.hasLayer(warningsLayer)) activeLayerNames.add("Active Hydro Warnings & Advisories");
    if (map.hasLayer(watchesLayer)) activeLayerNames.add("Active Hydro Watches");
    if (map.hasLayer(mpdLayer)) activeLayerNames.add("WPC Active MPDs");
    if (map.hasLayer(eroLayer)) activeLayerNames.add("Day 1 ERO (Real-Time)");
    if (map.hasLayer(radarTimeLayer)) activeLayerNames.add("NEXRAD Radar (2-Hour Loop)");
    
    if (map.hasLayer(ffdLayer)) activeLayerNames.add("MRMS DVD Flash Flood Detector");
    if (map.hasLayer(mrms1hr)) activeLayerNames.add("MRMS 1-Hour QPE");

    updateLegends();
    
    const radarTimeBox = document.getElementById('radar-time-box');
    if (radarTimeBox && map.hasLayer(radarTimeLayer)) {
        radarTimeBox.style.display = 'block';
        const currentFrameTime = new Date(map.timeDimension.getCurrentTime());
        radarTimeBox.innerHTML = `
            <strong>NEXRAD Radar Loop</strong><br>
            <span style="color: #ffeb3b; font-weight: bold; font-size: 1.05em;">Frame: ${formatUTC(currentFrameTime)}</span>
        `;
    }
    
    const ffdTimeBox = document.getElementById('ffd-time-box');
    if (ffdTimeBox && map.hasLayer(ffdLayer)) {
        ffdTimeBox.style.display = 'block';
    }

    refreshLegendDockSummary();
}, 1500);
