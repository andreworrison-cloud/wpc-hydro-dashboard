// --- POPUP / TOOLTIP PRIORITY ---
// The full dashboard interface is styled in style.css.
const customStyle = document.createElement('style');
customStyle.innerHTML = `
    .leaflet-popup-pane { z-index: 7000 !important; }
    .leaflet-tooltip-pane { z-index: 6500 !important; }
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

map.createPane('warnings');
map.getPane('warnings').style.zIndex = 450;

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

const warningsLayer = L.geoJSON(null, commonAlertOptions('warnings'));
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
        
        warningsLayer.clearLayers();
        watchesLayer.clearLayers();
        
        if (data && data.features) {
            const warningFeatures = data.features.filter(f => f.properties && f.properties.prod_type && !f.properties.prod_type.includes("Watch"));
            const watchFeatures = data.features.filter(f => f.properties && f.properties.prod_type && f.properties.prod_type.includes("Watch"));
            if (warningFeatures.length > 0) warningsLayer.addData(warningFeatures);
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
    if (propStr.includes("LIKELY")) lineColor = "#800080";   
    return { color: lineColor, weight: 3, dashArray: "5, 5", fillOpacity: 0.1 };
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
            const validTime = props.valid_time || "Unknown";
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
        legendCount > 0 || visibleTimeCount > 0
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

    if (eventLayer.name.includes('GOES-')) {
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
    
    if (eventLayer.name.includes('NEXRAD Radar') || eventLayer.name.includes('GOES-')) {
        const hasSatRadar = Array.from(activeLayerNames).some(name => name.includes('NEXRAD Radar') || name.includes('GOES-'));
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
            {id: 'goes-west-ir', label: 'GOES-West: Clean IR (Ch. 13)', layer: goesWestIR, kind: 'raster'}
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

function getAllDashboardLayerEntries() {
    return dashboardSections.flatMap(section => section.layers);
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

    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.className = 'layer-checkbox';
    checkbox.dataset.layerId = entry.id;
    checkbox.checked = map.hasLayer(entry.layer);
    checkbox.addEventListener('change', () => {
        selectDashboardLayer(entry.id);
        setDashboardLayerActive(entry, checkbox.checked);
    });

    const label = document.createElement('span');
    label.className = 'layer-label';
    label.innerHTML = entry.label;

    row.addEventListener('click', () => selectDashboardLayer(entry.id));
    row.append(checkbox, label);
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
            const count = sectionConfig.layers.length;
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
                sectionConfig.layers.forEach(entry => body.append(renderLayerRow(entry)));
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
