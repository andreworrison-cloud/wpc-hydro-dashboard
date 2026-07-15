// --- UI CSS FIXES (Scrollable Menu, Width & Popup/Tooltip Priority) ---
const customStyle = document.createElement('style');
customStyle.innerHTML = `
    /* Fix for the double scrollbar and widening the menu */
    .leaflet-control-layers-expanded {
        overflow: hidden !important; 
        min-width: 350px !important; 
        padding-right: 10px !important;
    }
    .leaflet-control-layers-list {
        max-height: 60vh !important; 
        overflow-y: auto !important; 
        overflow-x: hidden !important;
        padding-right: 10px !important;
    }
    /* Force popups and tooltips to ALWAYS sit above city labels and map layers */
    .leaflet-popup-pane {
        z-index: 7000 !important;
    }
    .leaflet-tooltip-pane {
        z-index: 6500 !important;
    }
`;
document.head.appendChild(customStyle);

// Initialize the map, centered roughly over the CONUS
const map = L.map('map', {
    zoomControl: true,
    center: [39.8283, -98.5795], 
    zoom: 5
});

// --- TOP-CENTER DASHBOARD TITLE ---
const mapTitle = L.DomUtil.create('div', 'map-title');
mapTitle.innerHTML = '<strong>WPC Real-Time Hydrometeorological Dashboard</strong>';
mapTitle.style.position = 'absolute';
mapTitle.style.top = '10px';
mapTitle.style.left = '50%';
mapTitle.style.transform = 'translateX(-50%)';
mapTitle.style.zIndex = '1000';
mapTitle.style.background = 'rgba(0, 0, 0, 0.7)';
mapTitle.style.color = 'white';
mapTitle.style.padding = '12px 24px';
mapTitle.style.borderRadius = '6px';
mapTitle.style.fontFamily = 'sans-serif';
mapTitle.style.fontSize = '24px';
mapTitle.style.letterSpacing = '1px';
mapTitle.style.boxShadow = '0 2px 5px rgba(0,0,0,0.5)';
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

// NEW: Esri World Imagery (Satellite)
const esriWorldImagery = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
    maxZoom: 19,
    attribution: 'Tiles © Esri — Source: Esri, i-cubed, USDA, USGS, AEX, GeoEye, Getmapping, Aerogrid, IGN, IGP, UPR-EGP, and the GIS User Community'
});

// NEW: Esri World Topographic
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
    // Clear out old boundary/label layers
    if (map.hasLayer(esriDarkLabels)) map.removeLayer(esriDarkLabels); 
    if (map.hasLayer(whiteBorders)) map.removeLayer(whiteBorders);
    if (map.hasLayer(blackBorders)) map.removeLayer(blackBorders);

    // Apply the correct contrast borders based on the selected map
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

// --- MRMS DVD FLASH FLOOD DETECTOR (FFD) ---
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
                    // Build tooltip but do not rely on it for the global timestamp
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

// --- DYNAMIC METADATA FETCHING AND AUTO-UPDATING ---
let rapValidTime = "Unknown";
let rapValidTimeF03 = "Unknown";
let camCycles = { href: "Unknown", refs: "Unknown" };
let eroValidRangeStr = "Unknown";

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

// Initial fetch on load
fetchRAPMetadata();
fetchCAMMetadata();
fetchEROCAMMetadata();

// Auto-Refresh generated PNGs every 15 minutes
setInterval(() => {
    fetchRAPMetadata();
    fetchCAMMetadata();
    fetchEROCAMMetadata();
}, 15 * 60 * 1000); 

// --- STACKABLE LEGENDS & TIME BOX UI ---

const rapTimeControl = L.control({position: 'bottomright'});
rapTimeControl.onAdd = function() {
    const div = L.DomUtil.create('div', 'time-box');
    div.id = 'rap-time-box';
    div.style.background = 'rgba(0, 0, 0, 0.7)';
    div.style.color = '#ffffff';
    div.style.padding = '8px 12px';
    div.style.borderRadius = '6px';
    div.style.marginBottom = '5px';
    div.style.textAlign = 'center';
    div.style.display = 'none'; 
    return div;
};
rapTimeControl.addTo(map);

const mrmsTimeControl = L.control({position: 'bottomright'});
mrmsTimeControl.onAdd = function() {
    const div = L.DomUtil.create('div', 'time-box');
    div.id = 'mrms-time-box';
    div.style.background = 'rgba(0, 0, 0, 0.7)';
    div.style.color = '#ffffff';
    div.style.padding = '8px 12px';
    div.style.borderRadius = '6px';
    div.style.marginBottom = '5px';
    div.style.textAlign = 'center';
    div.style.display = 'none'; 
    return div;
};
mrmsTimeControl.addTo(map);

const camTimeControl = L.control({position: 'bottomright'});
camTimeControl.onAdd = function() {
    const div = L.DomUtil.create('div', 'time-box');
    div.id = 'cam-time-box';
    div.style.background = 'rgba(0, 0, 0, 0.7)';
    div.style.color = '#ffffff';
    div.style.padding = '8px 12px';
    div.style.borderRadius = '6px';
    div.style.marginBottom = '5px';
    div.style.textAlign = 'center';
    div.style.display = 'none'; 
    return div;
};
camTimeControl.addTo(map);

const radarTimeControl = L.control({position: 'bottomright'});
radarTimeControl.onAdd = function() {
    const div = L.DomUtil.create('div', 'time-box');
    div.id = 'radar-time-box';
    div.style.background = 'rgba(0, 0, 0, 0.7)';
    div.style.color = '#ffffff';
    div.style.padding = '8px 12px';
    div.style.borderRadius = '6px';
    div.style.marginBottom = '5px';
    div.style.textAlign = 'center';
    div.style.display = 'none'; 
    return div;
};
radarTimeControl.addTo(map);

const ffdTimeControl = L.control({position: 'bottomright'});
ffdTimeControl.onAdd = function() {
    const div = L.DomUtil.create('div', 'time-box');
    div.id = 'ffd-time-box';
    div.style.background = 'rgba(0, 0, 0, 0.7)';
    div.style.color = '#ffffff';
    div.style.padding = '8px 12px';
    div.style.borderRadius = '6px';
    div.style.marginBottom = '5px';
    div.style.textAlign = 'center';
    div.style.display = 'none'; 
    return div;
};
ffdTimeControl.addTo(map);

const legendControl = L.control({position: 'bottomright'});
legendControl.onAdd = function () {
    const div = L.DomUtil.create('div', 'legend-container');
    div.id = 'legend-container';
    div.style.background = 'transparent';
    div.style.padding = '0px';
    div.style.boxShadow = 'none';
    div.style.display = 'none'; 
    return div;
};
legendControl.addTo(map);

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
    "&nbsp;&nbsp;&nbsp;&nbsp;▶ <b>+3h Forecast:</b> 850mb Moisture Trans": "static/leg_trans.png",
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

// Global tracker for currently active layers
let activeLayerNames = new Set();

function updateLegends() {
    const legendContainer = document.getElementById('legend-container');
    legendContainer.innerHTML = '';
    let hasLegend = false;

    const addLegendBlock = (htmlContent) => {
        const div = document.createElement('div');
        div.style.marginBottom = '5px'; 
        div.innerHTML = htmlContent;
        legendContainer.appendChild(div);
        hasLegend = true;
    };

    if (activeLayerNames.has('Active Hydro Warnings & Advisories')) addLegendBlock(hazardLegendHTML);
    if (activeLayerNames.has('Active Hydro Watches')) addLegendBlock(watchLegendHTML);
    if (activeLayerNames.has('WPC Active MPDs')) addLegendBlock(mpdLegendHTML);
    if (activeLayerNames.has('Day 1 ERO (Real-Time)')) addLegendBlock(eroLegendHTML);
    if (activeLayerNames.has('MRMS DVD Flash Flood Detector')) addLegendBlock(ffdLegendHTML);
    
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

    if (rapLegendMapping[eventLayer.name]) {
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
});

map.on('overlayremove', function(eventLayer) {
    activeLayerNames.delete(eventLayer.name);
    updateLegends();

    const rapTimeBox = document.getElementById('rap-time-box');
    const mrmsTimeBox = document.getElementById('mrms-time-box');
    const camTimeBox = document.getElementById('cam-time-box');
    const radarTimeBox = document.getElementById('radar-time-box');
    const ffdTimeBox = document.getElementById('ffd-time-box');
    
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
    
    if (eventLayer.name.includes('SuperEnsemble') || eventLayer.name.includes('HREF') || eventLayer.name.includes('REFS') || eventLayer.name.includes('[ERO]')) {
        const hasCAM = Array.from(activeLayerNames).some(name => name.includes('SuperEnsemble') || name.includes('HREF') || name.includes('REFS'));
        if (!hasCAM) camTimeBox.style.display = 'none';
    }
    
    if (eventLayer.name.includes('NEXRAD Radar') || eventLayer.name.includes('GOES-')) {
        const hasSatRadar = Array.from(activeLayerNames).some(name => name.includes('NEXRAD Radar') || name.includes('GOES-'));
        if (!hasSatRadar) radarTimeBox.style.display = 'none';
    }
});

// --- MENU CONTROLS ---
const baseMaps = {
    "Esri Dark Gray": esriDarkBase,
    "OpenStreetMap": osmLayer,
    "Esri World Imagery (Satellite)": esriWorldImagery,
    "Esri World Topographic": esriWorldTopo
};

const groupedOverlays = {
    "Active Hazards & Warnings": {
        "Active Hydro Warnings & Advisories": warningsLayer,
        "Active Hydro Watches": watchesLayer,
        "WPC Active MPDs": mpdLayer,
        "Day 1 ERO (Real-Time)": eroLayer
    },
    "Radar and Satellite Data (Real-Time)": {
        "NEXRAD Radar (2-Hour Loop)": radarTimeLayer,
        "MRMS DVD Flash Flood Detector": ffdLayer,
        "MRMS 1-Hour QPE": mrms1hr,
        "MRMS 24-Hour QPE": mrms24hr,
        "MRMS 48-Hour QPE": mrms48hr,
        "MRMS 72-Hour QPE": mrms72hr,
        "GOES-East: Visible (Ch. 2)": goesEastVis,
        "GOES-East: Mid-Level WV (Ch. 9)": goesEastWV,
        "GOES-East: Clean IR (Ch. 13)": goesEastIR,
        "GOES-West: Visible (Ch. 2)": goesWestVis,
        "GOES-West: Mid-Level WV (Ch. 9)": goesWestWV,
        "GOES-West: Clean IR (Ch. 13)": goesWestIR
    },
    "CAM Nowcasts (+3h to +9h)": {
        "<b>SuperEnsemble</b>: Max FFG Exceedance": camLayers['ffg_3h_to_9h_super'],
        "&nbsp;&nbsp;&nbsp;&nbsp;HREF: Max FFG Exceedance": camLayers['ffg_3h_to_9h_href'],
        "&nbsp;&nbsp;&nbsp;&nbsp;REFS: Max FFG Exceedance": camLayers['ffg_3h_to_9h_refs'],
        "<b>SuperEnsemble</b>: Max Prob > 0.5\"/hr": camLayers['qpf_3h_to_9h_0.5_inch_super'],
        "&nbsp;&nbsp;&nbsp;&nbsp;HREF: Max Prob > 0.5\"/hr": camLayers['qpf_3h_to_9h_0.5_inch_href'],
        "&nbsp;&nbsp;&nbsp;&nbsp;REFS: Max Prob > 0.5\"/hr": camLayers['qpf_3h_to_9h_0.5_inch_refs'],
        "<b>SuperEnsemble</b>: Max Prob > 1.0\"/hr": camLayers['qpf_3h_to_9h_1_inch_super'],
        "&nbsp;&nbsp;&nbsp;&nbsp;HREF: Max Prob > 1.0\"/hr": camLayers['qpf_3h_to_9h_1_inch_href'],
        "&nbsp;&nbsp;&nbsp;&nbsp;REFS: Max Prob > 1.0\"/hr": camLayers['qpf_3h_to_9h_1_inch_refs'],
        "<b>SuperEnsemble</b>: Max Prob > 2.0\"/hr": camLayers['qpf_3h_to_9h_2_inch_super'],
        "&nbsp;&nbsp;&nbsp;&nbsp;HREF: Max Prob > 2.0\"/hr": camLayers['qpf_3h_to_9h_2_inch_href'],
        "&nbsp;&nbsp;&nbsp;&nbsp;REFS: Max Prob > 2.0\"/hr": camLayers['qpf_3h_to_9h_2_inch_refs'],
        "<b>SuperEnsemble</b>: Max Prob > 3.0\"/hr": camLayers['qpf_3h_to_9h_3_inch_super'],
        "&nbsp;&nbsp;&nbsp;&nbsp;HREF: Max Prob > 3.0\"/hr": camLayers['qpf_3h_to_9h_3_inch_href'],
        "&nbsp;&nbsp;&nbsp;&nbsp;REFS: Max Prob > 3.0\"/hr": camLayers['qpf_3h_to_9h_3_inch_refs']
    },
    "CAM Nowcasts (+9h to +15h)": {
        "<b>SuperEnsemble</b>: Max FFG Exceedance": camLayers['ffg_9h_to_15h_super'],
        "&nbsp;&nbsp;&nbsp;&nbsp;HREF: Max FFG Exceedance": camLayers['ffg_9h_to_15h_href'],
        "&nbsp;&nbsp;&nbsp;&nbsp;REFS: Max FFG Exceedance": camLayers['ffg_9h_to_15h_refs'],
        "<b>SuperEnsemble</b>: Max Prob > 0.5\"/hr": camLayers['qpf_9h_to_15h_0.5_inch_super'],
        "&nbsp;&nbsp;&nbsp;&nbsp;HREF: Max Prob > 0.5\"/hr": camLayers['qpf_9h_to_15h_0.5_inch_href'],
        "&nbsp;&nbsp;&nbsp;&nbsp;REFS: Max Prob > 0.5\"/hr": camLayers['qpf_9h_to_15h_0.5_inch_refs'],
        "<b>SuperEnsemble</b>: Max Prob > 1.0\"/hr": camLayers['qpf_9h_to_15h_1_inch_super'],
        "&nbsp;&nbsp;&nbsp;&nbsp;HREF: Max Prob > 1.0\"/hr": camLayers['qpf_9h_to_15h_1_inch_href'],
        "&nbsp;&nbsp;&nbsp;&nbsp;REFS: Max Prob > 1.0\"/hr": camLayers['qpf_9h_to_15h_1_inch_refs'],
        "<b>SuperEnsemble</b>: Max Prob > 2.0\"/hr": camLayers['qpf_9h_to_15h_2_inch_super'],
        "&nbsp;&nbsp;&nbsp;&nbsp;HREF: Max Prob > 2.0\"/hr": camLayers['qpf_9h_to_15h_2_inch_href'],
        "&nbsp;&nbsp;&nbsp;&nbsp;REFS: Max Prob > 2.0\"/hr": camLayers['qpf_9h_to_15h_2_inch_refs'],
        "<b>SuperEnsemble</b>: Max Prob > 3.0\"/hr": camLayers['qpf_9h_to_15h_3_inch_super'],
        "&nbsp;&nbsp;&nbsp;&nbsp;HREF: Max Prob > 3.0\"/hr": camLayers['qpf_9h_to_15h_3_inch_href'],
        "&nbsp;&nbsp;&nbsp;&nbsp;REFS: Max Prob > 3.0\"/hr": camLayers['qpf_9h_to_15h_3_inch_refs']
    },
    "Day 1 ERO CAMs (12Z-12Z)": {
        "<b>SuperEnsemble [ERO]</b>: Max FFG Exceedance": eroCamLayers['ffg_super'],
        "&nbsp;&nbsp;&nbsp;&nbsp;HREF [ERO]: Max FFG Exceedance": eroCamLayers['ffg_href'],
        "&nbsp;&nbsp;&nbsp;&nbsp;REFS [ERO]: Max FFG Exceedance": eroCamLayers['ffg_refs'],
        "<b>SuperEnsemble [ERO]</b>: Max Prob > 0.5\"/hr": eroCamLayers['qpf_0.5_inch_super'],
        "&nbsp;&nbsp;&nbsp;&nbsp;HREF [ERO]: Max Prob > 0.5\"/hr": eroCamLayers['qpf_0.5_inch_href'],
        "&nbsp;&nbsp;&nbsp;&nbsp;REFS [ERO]: Max Prob > 0.5\"/hr": eroCamLayers['qpf_0.5_inch_refs'],
        "<b>SuperEnsemble [ERO]</b>: Max Prob > 1.0\"/hr": eroCamLayers['qpf_1_inch_super'],
        "&nbsp;&nbsp;&nbsp;&nbsp;HREF [ERO]: Max Prob > 1.0\"/hr": eroCamLayers['qpf_1_inch_href'],
        "&nbsp;&nbsp;&nbsp;&nbsp;REFS [ERO]: Max Prob > 1.0\"/hr": eroCamLayers['qpf_1_inch_refs'],
        "<b>SuperEnsemble [ERO]</b>: Max Prob > 2.0\"/hr": eroCamLayers['qpf_2_inch_super'],
        "&nbsp;&nbsp;&nbsp;&nbsp;HREF [ERO]: Max Prob > 2.0\"/hr": eroCamLayers['qpf_2_inch_href'],
        "&nbsp;&nbsp;&nbsp;&nbsp;REFS [ERO]: Max Prob > 2.0\"/hr": eroCamLayers['qpf_2_inch_refs'],
        "<b>SuperEnsemble [ERO]</b>: Max Prob > 3.0\"/hr": eroCamLayers['qpf_3_inch_super'],
        "&nbsp;&nbsp;&nbsp;&nbsp;HREF [ERO]: Max Prob > 3.0\"/hr": eroCamLayers['qpf_3_inch_href'],
        "&nbsp;&nbsp;&nbsp;&nbsp;REFS [ERO]: Max Prob > 3.0\"/hr": eroCamLayers['qpf_3_inch_refs']
    }
};

const layerControl = L.control.groupedLayers(baseMaps, groupedOverlays, { 
    collapsed: true 
}).addTo(map);

L.DomEvent.disableClickPropagation(layerControl.getContainer());
L.DomEvent.disableScrollPropagation(layerControl.getContainer());

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
}, 1500);
