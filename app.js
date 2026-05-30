// Initialize the map, centered roughly over the CONUS
const map = L.map('map', {
    zoomControl: true,
    center: [39.8283, -98.5795], 
    zoom: 5
});

// --- 1. TOP-CENTER DASHBOARD TITLE ---
const mapTitle = L.DomUtil.create('div', 'map-title');
mapTitle.innerHTML = '<strong>WPC Real-Time Hydrologic Dashboard</strong>';
mapTitle.style.position = 'absolute';
mapTitle.style.top = '10px';
mapTitle.style.left = '50%';
mapTitle.style.transform = 'translateX(-50%)';
mapTitle.style.zIndex = '1000';
mapTitle.style.background = 'rgba(0, 0, 0, 0.7)';
mapTitle.style.color = 'white';
mapTitle.style.padding = '10px 20px';
mapTitle.style.borderRadius = '6px';
mapTitle.style.fontFamily = 'sans-serif';
mapTitle.style.fontSize = '18px';
mapTitle.style.letterSpacing = '1px';
mapTitle.style.boxShadow = '0 2px 5px rgba(0,0,0,0.5)';
document.getElementById('map').appendChild(mapTitle);

// Define Basemaps
const osmLayer = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '© OpenStreetMap contributors'
});

const esriDarkLayer = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}', {
    maxZoom: 16,
    attribution: '© Esri, HERE, Garmin, © OpenStreetMap'
});

esriDarkLayer.addTo(map);

// --- TIME LOOP LOGIC (15-Min Intervals for Radar & Sat) ---
const endTime = new Date();
endTime.setMinutes(Math.floor(endTime.getMinutes() / 15) * 15);
endTime.setSeconds(0);
endTime.setMilliseconds(0);

const startTime = new Date(endTime.getTime() - 6 * 60 * 60 * 1000);
const timeRange = startTime.toISOString() + "/" + endTime.toISOString();

map.timeDimension = L.timeDimension({
    timeInterval: timeRange,
    period: "PT15M",
    currentTime: endTime.getTime()
});

L.control.timeDimension({
    position: 'bottomleft',
    autoPlay: true,
    playerOptions: { transitionTime: 500, loop: true }
}).addTo(map);

// --- REAL-TIME WMS LOOPING LAYERS (Radar & Satellite) ---
const noaaWmsOptions = { format: 'image/png', transparent: true, opacity: 0.6 };

// Radar
const radarWMS = L.tileLayer.wms("https://mesonet.agron.iastate.edu/cgi-bin/wms/nexrad/n0q-t.cgi", {
    ...noaaWmsOptions, layers: 'nexrad-n0q-wmst', attribution: "Weather data © IEM Nexrad"
});
const radarTimeLayer = L.timeDimension.layer.wms(radarWMS, { updateTimeDimension: false });
radarTimeLayer.addTo(map);

// GOES-East Satellite (Vis, WV, IR)
const goesEastVis = L.timeDimension.layer.wms(L.tileLayer.wms("https://mesonet.agron.iastate.edu/cgi-bin/wms/goes_east.cgi", { ...noaaWmsOptions, layers: 'goes_east_ch02' }), { updateTimeDimension: false });
const goesEastWV = L.timeDimension.layer.wms(L.tileLayer.wms("https://mesonet.agron.iastate.edu/cgi-bin/wms/goes_east.cgi", { ...noaaWmsOptions, layers: 'goes_east_ch09' }), { updateTimeDimension: false });
const goesEastIR = L.timeDimension.layer.wms(L.tileLayer.wms("https://mesonet.agron.iastate.edu/cgi-bin/wms/goes_east.cgi", { ...noaaWmsOptions, layers: 'goes_east_ch13' }), { updateTimeDimension: false });

// GOES-West Satellite (Vis, WV, IR)
const goesWestVis = L.timeDimension.layer.wms(L.tileLayer.wms("https://mesonet.agron.iastate.edu/cgi-bin/wms/goes_west.cgi", { ...noaaWmsOptions, layers: 'goes_west_ch02' }), { updateTimeDimension: false });
const goesWestWV = L.timeDimension.layer.wms(L.tileLayer.wms("https://mesonet.agron.iastate.edu/cgi-bin/wms/goes_west.cgi", { ...noaaWmsOptions, layers: 'goes_west_ch09' }), { updateTimeDimension: false });
const goesWestIR = L.timeDimension.layer.wms(L.tileLayer.wms("https://mesonet.agron.iastate.edu/cgi-bin/wms/goes_west.cgi", { ...noaaWmsOptions, layers: 'goes_west_ch13' }), { updateTimeDimension: false });

// --- STATIC REAL-TIME WMS LAYERS (Surface & METARs) ---
// WPC Surface Analysis
const wpcSurfaceAnalysis = L.tileLayer.wms("https://mesonet.agron.iastate.edu/cgi-bin/wms/wpc/sfc.cgi", {
    format: 'image/png', transparent: true, opacity: 0.8, layers: 'wpc_sfc'
});

// METAR Surface Observations
const metarLayer = L.tileLayer.wms("https://mapservices.weather.noaa.gov/vector/services/obs/metar/MapServer/WMSServer", {
    format: 'image/png', transparent: true, opacity: 1.0, layers: '0'
});

// --- NWS Active Warnings Logic ---
function getAlertColor(event) {
    if (event === "Flash Flood Warning") return "red";
    if (event === "Flood Warning") return "green";
    if (event === "Flood Advisory") return "lightgreen";
    return "gray"; 
}

const alertsLayer = L.geoJSON(null, {
    style: function (feature) {
        return { color: getAlertColor(feature.properties.event), weight: 2, opacity: 1, fillOpacity: 0.2 };
    },
    onEachFeature: function (feature, layer) {
        layer.bindPopup(`
            <div style="font-family: sans-serif;">
                <strong style="color: ${getAlertColor(feature.properties.event)};">${feature.properties.event}</strong><br>
                <em>${feature.properties.senderName}</em><br>
                <hr style="margin: 5px 0;">
                <span style="font-size: 0.9em;">${feature.properties.headline}</span>
            </div>
        `);
    }
});

alertsLayer.addTo(map);

async function fetchNWSAlerts() {
    try {
        const url = 'https://api.weather.gov/alerts/active?event=Flash%20Flood%20Warning,Flood%20Warning,Flood%20Advisory';
        const response = await fetch(url, { headers: { 'Accept': 'application/geo+json', 'User-Agent': 'WPC-Hydro-Dashboard/1.0' } });
        if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
        const data = await response.json();
        alertsLayer.addData(data);
    } catch (error) { console.error("Error fetching NWS alerts:", error); }
}
fetchNWSAlerts();

// --- LIVE WPC GEOJSON (Day 1 ERO & MPDs) ---
function getEroStyle(feature) {
    const cat = (feature.properties.OUTLOOK || feature.properties.outlook || feature.properties.Outlook || "").toUpperCase();
    let riskColor = "#00ff00"; 
    if (cat.includes("SLGT") || cat.includes("SLIGHT")) riskColor = "#FFA500"; 
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
    style: getEroStyle,
    onEachFeature: function (feature, layer) {
        const cat = feature.properties.OUTLOOK || feature.properties.outlook || feature.properties.Outlook || "Unknown";
        layer.bindPopup(`<strong>WPC Day 1 ERO</strong><br>Category: ${cat}`);
    }
});

const mpdLayer = L.geoJSON(null, {
    style: getMpdStyle,
    onEachFeature: function (feature, layer) {
        const props = feature.properties;
        if (props && props.dataType === "MPD") {
            const mpdNum = props.mpd_number || "Unknown";
            const mpdTag = props.mpd_tag || "See WPC for details";
            const validTime = props.valid_time || "Unknown";
            
            const tooltipHTML = `<div style="text-align: center; font-family: sans-serif; line-height: 1.4;"><strong>MPD ${mpdNum}</strong><br>${mpdTag}<br>Valid: ${validTime}</div>`;
            layer.bindTooltip(tooltipHTML, { sticky: true, direction: "top" });
            
            const popupHTML = `<div style="font-family: sans-serif; font-size: 14px; min-width: 240px; text-align: center;"><strong>MPD ${mpdNum}</strong><br><span style="color: #d84b2a;"><strong>${mpdTag}</strong></span><br><hr style="margin: 5px 0;"><span style="font-size: 0.9em;">Valid: ${validTime}</span></div>`;
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
        
        const eroFeatures = data.features.filter(f => f.properties.dataType === 'ERO');
        const mpdFeatures = data.features.filter(f => f.properties.dataType === 'MPD');
        
        if (eroFeatures.length > 0) eroLayer.addData(eroFeatures);
        if (mpdFeatures.length > 0) mpdLayer.addData(mpdFeatures);
        
    } catch (error) { console.error("Error fetching WPC GeoJSON:", error); }
}
fetchWPCData();

// --- GROUPED LAYER CONTROLS ---
const baseMaps = {
    "Esri Dark Gray": esriDarkLayer,
    "OpenStreetMap": osmLayer
};

const groupedOverlays = {
    "Active Hazards & Warnings": {
        "NEXRAD Radar (6-Hour)": radarTimeLayer,
        "Active Hydro Warnings": alertsLayer,
        "WPC Active MPDs": mpdLayer,
        "Day 1 ERO (Real-Time)": eroLayer
    },
    "Surface & Observations": {
        "WPC Surface Analysis": wpcSurfaceAnalysis,
        "Hourly METARs": metarLayer
    },
    "GOES-East Satellite (Looping)": {
        "Visible (Ch. 2)": goesEastVis,
        "Mid-Level WV (Ch. 9)": goesEastWV,
        "Clean IR (Ch. 13)": goesEastIR
    },
    "GOES-West Satellite (Looping)": {
        "Visible (Ch. 2)": goesWestVis,
        "Mid-Level WV (Ch. 9)": goesWestWV,
        "Clean IR (Ch. 13)": goesWestIR
    }
};

L.control.groupedLayers(baseMaps, groupedOverlays, { collapsed: true }).addTo(map);
