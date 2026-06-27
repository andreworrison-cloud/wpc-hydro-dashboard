// --- UI CSS FIXES (Scrollable Menu & Popup/Tooltip Priority) ---
const customStyle = document.createElement('style');
customStyle.innerHTML = `
    /* Fix for the double scrollbar: Apply scroll ONLY to the inner list */
    .leaflet-control-layers-expanded {
        overflow: hidden !important; 
    }
    .leaflet-control-layers-list {
        max-height: 60vh !important; 
        overflow-y: auto !important; 
        overflow-x: hidden !important;
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

// Dark Base
const esriDarkBase = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}', {
    maxZoom: 16,
    attribution: '© Esri, HERE, Garmin, © OpenStreetMap'
});
esriDarkBase.addTo(map); 

// Daytime / White Base (OpenStreetMap)
const osmLayer = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '© OpenStreetMap contributors'
});

// The floating borders and labels
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

map.on('baselayerchange', function(e) {
    if (e.name === "OpenStreetMap") {
        if (map.hasLayer(esriDarkLabels)) map.removeLayer(esriDarkLabels); 
        if (map.hasLayer(whiteBorders)) map.removeLayer(whiteBorders);
        blackBorders.addTo(map);
    } else {
        if (!map.hasLayer(esriDarkLabels)) esriDarkLabels.addTo(map); 
        if (map.hasLayer(blackBorders)) map.removeLayer(blackBorders);
        whiteBorders.addTo(map);
    }
});

// --- TIME LOOP LOGIC ---
const endTime = new Date();
endTime.setMinutes(Math.floor(endTime.getMinutes() / 10) * 10);
endTime.setSeconds(0);
endTime.setMilliseconds(0);

const startTime = new Date(endTime.getTime() - 2 * 60 * 60 * 1000);
const timeRange = startTime.toISOString() + "/" + endTime.toISOString();

map.timeDimension = L.timeDimension({
    timeInterval: timeRange,
    period: "PT10M", 
    currentTime: endTime.getTime()
});

L.control.timeDimension({
    position: 'bottomleft',
    autoPlay: true,
    playerOptions: { transitionTime: 500, loop: true }
}).addTo(map);

// --- LOOPING RADAR LAYER ---
const radarWMS = L.tileLayer.wms("https://mesonet.agron.iastate.edu/cgi-bin/wms/nexrad/n0q-t.cgi", {
    format: 'image/png', transparent: true, opacity: 0.6, layers: 'nexrad-n0q-wmst', attribution: "Data © IEM"
});
const radarTimeLayer = L.timeDimension.layer.wms(radarWMS, { updateTimeDimension: false });
radarTimeLayer.addTo(map);

// --- MRMS QPE LAYERS ---
const mrmsOptions = { format: 'image/png', transparent: true, opacity: 0.65, attribution: "Data © IEM / NCEP" };
const mrms1hr = L.tileLayer.wms("https://mesonet.agron.iastate.edu/cgi-bin/wms/us/mrms_nn.cgi", { ...mrmsOptions, layers: 'mrms_p1h' });
const mrms24hr = L.tileLayer.wms("https://mesonet.agron.iastate.edu/cgi-bin/wms/us/mrms_nn.cgi", { ...mrmsOptions, layers: 'mrms_p24h' });
const mrms48hr = L.tileLayer.wms("https://mesonet.agron.iastate.edu/cgi-bin/wms/us/mrms_nn.cgi", { ...mrmsOptions, layers: 'mrms_p48h' });
const mrms72hr = L.tileLayer.wms("https://mesonet.agron.iastate.edu/cgi-bin/wms/us/mrms_nn.cgi", { ...mrmsOptions, layers: 'mrms_p72h' });

// --- STATIC SATELLITE LAYERS ---
const satOptions = { format: 'image/png', transparent: true, opacity: 0.6 };
const goesEastVis = L.tileLayer.wms("https://mesonet.agron.iastate.edu/cgi-bin/wms/goes_east.cgi", { ...satOptions, layers: 'conus_ch02' });
const goesEastWV = L.tileLayer.wms("https://mesonet.agron.iastate.edu/cgi-bin/wms/goes_east.cgi", { ...satOptions, layers: 'conus_ch09' });
const goesEastIR = L.tileLayer.wms("https://mesonet.agron.iastate.edu/cgi-bin/wms/goes_east.cgi", { ...satOptions, layers: 'conus_ch13' });
const goesWestVis = L.tileLayer.wms("https://mesonet.agron.iastate.edu/cgi-bin/wms/goes_west.cgi", { ...satOptions, layers: 'conus_ch02' });
const goesWestWV = L.tileLayer.wms("https://mesonet.agron.iastate.edu/cgi-bin/wms/goes_west.cgi", { ...satOptions, layers: 'conus_ch09' });
const goesWestIR = L.tileLayer.wms("https://mesonet.agron.iastate.edu/cgi-bin/wms/goes_west.cgi", { ...satOptions, layers: 'conus_ch13' });

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
        const url = `https://mapservices.weather.noaa.gov/eventdriven/rest/services/WWA/watch_warn_adv/MapServer/1/query?where=${encodeURIComponent(whereClause)}&outFields=prod_type,wfo,expiration,url&f=geojson`;
        const response = await fetch(url);
        if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
        const data = await response.json();
        
        if (data && data.features) {
            const warningFeatures = data.features.filter(f => f.properties && f.properties.prod_type && !f.properties.prod_type.includes("Watch"));
            const watchFeatures = data.features.filter(f => f.properties && f.properties.prod_type && f.properties.prod_type.includes("Watch"));
            if (warningFeatures.length > 0) warningsLayer.addData(warningFeatures);
            if (watchFeatures.length > 0) watchesLayer.addData(watchFeatures);
        }
    } catch (error) { console.error("Error fetching NWS alerts:", error); }
}
fetchNWSAlerts();

// --- MRMS DVD FLASH FLOOD DETECTOR (FFD) ---
const ffdLayer = L.layerGroup();

async function fetchFFDData() {
    try {
        const targetUrl = `static/ffd_contours.txt?t=${new Date().getTime()}`;
        const response = await fetch(targetUrl);
        if (!response.ok) throw new Error("Could not fetch local FFD placefile.");
        
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
                    if (parts.length > 0 && /Z$/i.test(parts[0])) {
                        const timeStamp = parts[0];
                        let impactTag = parts.length > 1 ? parts.slice(1).join(' ') : colorInferredImpact;
                        if (impactTag.length > 0) impactTag = impactTag.charAt(0).toUpperCase() + impactTag.slice(1);
                        currentTooltipHTML = `<span style="font-size: 0.9em;">${timeStamp}</span><br><span style="font-size: 1.1em;"><strong>${impactTag}</strong></span>`;
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
        
        if (eroFeatures.length > 0) eroLayer.addData(eroFeatures);
        if (mpdFeatures.length > 0) mpdLayer.addData(mpdFeatures);
    } catch (error) { console.error("Error fetching WPC GeoJSON:", error); }
}
fetchWPCData();

// --- RAP MESOANALYSIS LAYERS ---
const rapBounds = [[16.281, -139.856], [55.481, -57.373]]; 

// Base Layers
const pwatLayer = L.imageOverlay('static/rap_pwat.png', rapBounds, {zIndex: 10});
const sbcapeLayer = L.imageOverlay('static/rap_sbcape.png', rapBounds, {zIndex: 10});
const mlcapeLayer = L.imageOverlay('static/rap_mlcape.png', rapBounds, {zIndex: 10});
const mucapeLayer = L.imageOverlay('static/rap_mucape.png', rapBounds, {zIndex: 10});

// 3-Hour Change Layers
const pwatDiffLayer = L.imageOverlay('static/rap_pwat_diff.png', rapBounds, {zIndex: 10});
const sbcapeDiffLayer = L.imageOverlay('static/rap_sbcape_diff.png', rapBounds, {zIndex: 10});
const mlcapeDiffLayer = L.imageOverlay('static/rap_mlcape_diff.png', rapBounds, {zIndex: 10});
const mucapeDiffLayer = L.imageOverlay('static/rap_mucape_diff.png', rapBounds, {zIndex: 10});

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
const trans850Layer = L.imageOverlay('static/rap_trans850.png', rapBounds, {zIndex: 10});
const trans700Layer = L.imageOverlay('static/rap_trans700.png', rapBounds, {zIndex: 10});
const meanWindLayer = L.imageOverlay('static/rap_mean_wind.png', rapBounds, {zIndex: 10});
const vort500Layer = L.imageOverlay('static/rap_vort500.png', rapBounds, {zIndex: 10});
const diffAdvLayer = L.imageOverlay('static/rap_diff_adv.png', rapBounds, {zIndex: 10});
const div250Layer = L.imageOverlay('static/rap_div250.png', rapBounds, {zIndex: 10});

// --- TIME AND LEGEND UI CONTROLS ---
const timeControl = L.control({position: 'bottomright'});
timeControl.onAdd = function() {
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
timeControl.addTo(map);

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

const legendControl = L.control({position: 'bottomright'});
legendControl.onAdd = function () {
    const div = L.DomUtil.create('div', 'legend-box');
    div.id = 'legend-container';
    div.style.background = 'rgba(0, 0, 0, 0.7)';
    div.style.padding = '10px';
    div.style.borderRadius = '6px';
    div.style.display = 'none'; 
    div.innerHTML = `<img id="legend-img" src="" style="max-width: 300px; display: none;"><div id="legend-html" style="display: none;"></div>`;
    return div;
};
legendControl.addTo(map);

// --- RAP METADATA FETCH ---
fetch('static/rap_metadata.json?t=' + new Date().getTime())
    .then(r => r.json())
    .then(data => {
        const timeBox = document.getElementById('rap-time-box');
        timeBox.innerHTML = `<strong>${data.valid_time}</strong>`;
        timeBox.style.display = 'block';

        if (data.bounds) {
            const exactBounds = L.latLngBounds(data.bounds[0], data.bounds[1]);
            [pwatLayer, pwatDiffLayer, sbcapeLayer, sbcapeDiffLayer, mlcapeLayer, mlcapeDiffLayer, 
             mucapeLayer, mucapeDiffLayer, lrsfc3Layer, lr75Layer, scpLayer, mfcLayer, 
             f925Layer, f850Layer, effShearLayer, corfidiUpLayer, corfidiDownLayer, 
             trans850Layer, trans700Layer, meanWindLayer, vort500Layer, diffAdvLayer, div250Layer].forEach(layer => layer.setBounds(exactBounds));
        }
    })
    .catch(err => console.log("RAP metadata not found yet."));

function formatUTC(date) {
    const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
    const m = months[date.getUTCMonth()];
    const d = String(date.getUTCDate()).padStart(2, '0');
    const h = String(date.getUTCHours()).padStart(2, '0');
    const min = String(date.getUTCMinutes()).padStart(2, '0');
    return `${m} ${d}, ${h}${min}Z`;
}

// --- NEW CLEAN RAP LEGEND MAPPING DICTIONARY ---
const rapLegendMapping = {
    "Precipitable Water (PWAT)": "static/leg_pwat.png",
    "&nbsp;&nbsp;&nbsp;&nbsp;3-Hour PWAT Change": "static/leg_pwat_diff.png",
    "Surface Based CAPE": "static/leg_cape.png",
    "&nbsp;&nbsp;&nbsp;&nbsp;3-Hour SBCAPE Change": "static/leg_cape_diff.png",
    "Mixed Layer CAPE (90mb)": "static/leg_cape.png",
    "&nbsp;&nbsp;&nbsp;&nbsp;3-Hour MLCAPE Change": "static/leg_cape_diff.png",
    "Most Unstable CAPE (255mb)": "static/leg_cape.png",
    "&nbsp;&nbsp;&nbsp;&nbsp;3-Hour MUCAPE Change": "static/leg_cape_diff.png",
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
    "700mb Moisture Transport": "static/leg_trans.png",
    "850-300mb Mean Layer Wind": "static/leg_mean_wind.png",
    "500mb Absolute Vorticity": "static/leg_vort.png",
    "700-400mb Diff Vorticity Advection": "static/leg_diff_adv.png",
    "250mb Divergence": "static/leg_div.png"
};

// Map overlay handling
map.on('overlayadd', function(eventLayer) {
    const legendContainer = document.getElementById('legend-container');
    const legendImg = document.getElementById('legend-img');
    const legendHtml = document.getElementById('legend-html');
    const mrmsTimeBox = document.getElementById('mrms-time-box');
    
    // Check if the toggled layer is exactly in our RAP dictionary
    if (rapLegendMapping[eventLayer.name]) {
        legendContainer.style.display = 'block';
        legendContainer.style.background = 'rgba(0, 0, 0, 0.7)';
        legendHtml.style.display = 'none';
        legendImg.style.display = 'block';
        legendImg.src = rapLegendMapping[eventLayer.name];
    }
    
    // MRMS HTML Legend Handler
    if (eventLayer.name.includes('MRMS') && eventLayer.name.includes('QPE')) {
        legendContainer.style.display = 'block';
        legendContainer.style.background = 'transparent'; 
        legendImg.style.display = 'none';
        legendHtml.style.display = 'block';
        
        let hours = 1;
        if (eventLayer.name.includes('24-Hour')) hours = 24;
        if (eventLayer.name.includes('48-Hour')) hours = 48;
        if (eventLayer.name.includes('72-Hour')) hours = 72;

        legendHtml.innerHTML = `<div style="background: white; padding: 10px; border-radius: 5px; font-weight: bold; color: black; font-family: sans-serif; font-size: 14px; text-align: center;">Precip Scale Active<br>(${hours}-Hour)</div>`;
        
        const now = new Date();
        const start = new Date(now.getTime() - (hours * 60 * 60 * 1000));
        mrmsTimeBox.innerHTML = `<strong>MRMS ${hours}-Hour Accumulation</strong><br>${formatUTC(start)} &mdash; ${formatUTC(now)}`;
        mrmsTimeBox.style.display = 'block';
    }
});

map.on('overlayremove', function(eventLayer) {
    const legendContainer = document.getElementById('legend-container');
    const mrmsTimeBox = document.getElementById('mrms-time-box');
    
    if (rapLegendMapping[eventLayer.name]) {
        legendContainer.style.display = 'none';
    }
    if (eventLayer.name.includes('MRMS') && eventLayer.name.includes('QPE')) {
        legendContainer.style.display = 'none';
        mrmsTimeBox.style.display = 'none';
    }
});

// --- MENU CONTROLS (Updated with indentation and names) ---
const baseMaps = {
    "Esri Dark Gray": esriDarkBase,
    "OpenStreetMap": osmLayer
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
    "RAP Mesoanalysis (Real-Time)": {
        "Precipitable Water (PWAT)": pwatLayer,
        "&nbsp;&nbsp;&nbsp;&nbsp;3-Hour PWAT Change": pwatDiffLayer,
        "Surface Based CAPE": sbcapeLayer,
        "&nbsp;&nbsp;&nbsp;&nbsp;3-Hour SBCAPE Change": sbcapeDiffLayer,
        "Mixed Layer CAPE (90mb)": mlcapeLayer,
        "&nbsp;&nbsp;&nbsp;&nbsp;3-Hour MLCAPE Change": mlcapeDiffLayer,
        "Most Unstable CAPE (255mb)": mucapeLayer,
        "&nbsp;&nbsp;&nbsp;&nbsp;3-Hour MUCAPE Change": mucapeDiffLayer,
        "Sfc-3km Low-Level Lapse Rate": lrsfc3Layer,
        "700-500mb Mid-Level Lapse Rate": lr75Layer,
        "Supercell Composite Parameter": scpLayer,
        "Mean BL Moisture Convergence": mfcLayer,
        "925/850mb Frontogenesis": f925Layer,
        "850/700mb Frontogenesis": f850Layer,
        "Effective Bulk Shear": effShearLayer,
        "Corfidi Upwind (Back-Building) Vectors": corfidiUpLayer,
        "Corfidi Downwind (Forward) Vectors": corfidiDownLayer,
        "850mb Moisture Transport": trans850Layer,
        "700mb Moisture Transport": trans700Layer,
        "850-300mb Mean Layer Wind": meanWindLayer,
        "500mb Absolute Vorticity": vort500Layer,
        "700-400mb Diff Vorticity Advection": diffAdvLayer,
        "250mb Divergence": div250Layer
    }
};

const layerControl = L.control.groupedLayers(baseMaps, groupedOverlays, { 
    collapsed: true 
}).addTo(map);

L.DomEvent.disableClickPropagation(layerControl.getContainer());
L.DomEvent.disableScrollPropagation(layerControl.getContainer());
