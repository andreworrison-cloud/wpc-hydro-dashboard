// Initialize the map, centered roughly over the CONUS
const map = L.map('map', {
    zoomControl: true,
    center: [39.8283, -98.5795], 
    zoom: 5
});

// Define Basemaps
const osmLayer = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '© OpenStreetMap contributors'
});

const esriDarkLayer = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}', {
    maxZoom: 16,
    attribution: '© Esri, HERE, Garmin, © OpenStreetMap'
});

// Add default basemap to the map
esriDarkLayer.addTo(map);

// --- 6-Hour Loop Logic ---
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

const radarWMS = L.tileLayer.wms("https://mesonet.agron.iastate.edu/cgi-bin/wms/nexrad/n0q-t.cgi", {
    layers: 'nexrad-n0q-wmst',
    format: 'image/png',
    transparent: true,
    opacity: 0.6,
    attribution: "Weather data © IEM Nexrad"
});

const radarTimeLayer = L.timeDimension.layer.wms(radarWMS, { updateTimeDimension: false });
radarTimeLayer.addTo(map);

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
        const response = await fetch(url, {
            headers: {
                'Accept': 'application/geo+json',
                'User-Agent': 'WPC-Hydro-Dashboard/1.0' 
            }
        });
        if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
        const data = await response.json();
        alertsLayer.addData(data);
    } catch (error) {
        console.error("Error fetching NWS alerts:", error);
    }
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

// Dynamic MPD Styling Function - Bulletproof search
function getMpdStyle(feature) {
    const propStr = JSON.stringify(feature.properties).toUpperCase();
    let lineColor = "#ff00ff"; // Fallback Fuchsia
    
    if (propStr.includes("POSSIBLE")) lineColor = "#0000FF"; // Blue
    if (propStr.includes("LIKELY")) lineColor = "#800080";   // Purple
    
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
        const issueRaw = props.ISSUE || props.issue || "Unknown";
        const expireRaw = props.EXPIRE || props.expire || "Unknown";
        
        // Bulletproof Tag Extraction
        const propStr = JSON.stringify(props).toUpperCase();
        let displayTag = "See WPC for details";
        
        if (propStr.includes("FLASH FLOODING POSSIBLE")) {
            displayTag = "Flash Flooding Possible";
        } else if (propStr.includes("FLASH FLOODING LIKELY")) {
            displayTag = "Flash Flooding Likely";
        } else if (props.TAG || props.SUBJECT || props.tag) {
            let rawTag = props.TAG || props.SUBJECT || props.tag;
            if (rawTag.includes("...")) {
                let parts = rawTag.split("...");
                let isolatedTag = parts[parts.length - 1].trim();
                displayTag = isolatedTag.charAt(0).toUpperCase() + isolatedTag.slice(1).toLowerCase();
            } else {
                displayTag = rawTag;
            }
        }
        
        function formatWPCTime(t) {
            let str = String(t).trim().split('.')[0];
            if (str.length === 10 || str.length === 12) {
                let offset = str.length === 10 ? 0 : 2;
                return `${str.substring(2+offset, 4+offset)}/${str.substring(4+offset, 6+offset)} ${str.substring(6+offset, 10+offset)}Z`;
            }
            return str;
        }
        
        const validStr = (issueRaw !== "Unknown" || expireRaw !== "Unknown") 
                       ? `${formatWPCTime(issueRaw)} - ${formatWPCTime(expireRaw)}` 
                       : "Unknown Timeframe";
                       
        const popupContent = `<strong>Active WPC MPD</strong><br>
                              <strong>Tag:</strong> ${displayTag}<br>
                              <strong>Valid:</strong> ${validStr}`;
                              
        layer.bindPopup(popupContent);
        layer.on('mouseover', function () { this.openPopup(); });
        layer.on('mouseout', function () { this.closePopup(); });
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
        
        if (eroFeatures.length > 0) {
            eroLayer.addData(eroFeatures);
        } else {
            const noEroLabel = L.control({position: 'topright'});
            noEroLabel.onAdd = function () {
                const div = L.DomUtil.create('div', 'info legend');
                div.style.backgroundColor = "rgba(0,0,0,0.7)";
                div.style.color = "white";
                div.style.padding = "10px";
                div.style.borderRadius = "5px";
                div.style.fontSize = "0.9em";
                div.style.maxWidth = "250px";
                div.innerHTML = "<strong>WPC Day 1 ERO</strong><br>The probability of rainfall exceeding flash flood guidance is less than 5 percent.";
                return div;
            };
            map.on('overlayadd', function(e) { if (e.name === "Day 1 ERO (Real-Time)") noEroLabel.addTo(map); });
            map.on('overlayremove', function(e) { if (e.name === "Day 1 ERO (Real-Time)") noEroLabel.remove(); });
            if (map.hasLayer(eroLayer)) noEroLabel.addTo(map);
        }
        
        if (mpdFeatures.length > 0) mpdLayer.addData(mpdFeatures);
        
    } catch (error) {
        console.error("Error fetching WPC GeoJSON:", error);
    }
}

fetchWPCData();

// --- NEW: WMS LAYERS FOR EXTENDED ERO & QPF ---
const noaaWmsOptions = { format: 'image/png', transparent: true, opacity: 0.6, attribution: 'NOAA/NWS/WPC' };

const eroWmsUrl = "https://mapservices.weather.noaa.gov/vector/services/hazards/wpc_precip_hazards/MapServer/WMSServer";
const eroDay2 = L.tileLayer.wms(eroWmsUrl, { ...noaaWmsOptions, layers: '1' });
const eroDay3 = L.tileLayer.wms(eroWmsUrl, { ...noaaWmsOptions, layers: '2' });
const eroDay4 = L.tileLayer.wms(eroWmsUrl, { ...noaaWmsOptions, layers: '3' });
const eroDay5 = L.tileLayer.wms(eroWmsUrl, { ...noaaWmsOptions, layers: '4' });

const qpfWmsUrl = "https://mapservices.weather.noaa.gov/vector/services/precip/wpc_qpf/MapServer/WMSServer";
const qpfDay1 = L.tileLayer.wms(qpfWmsUrl, { ...noaaWmsOptions, layers: '1' });
const qpfDay2 = L.tileLayer.wms(qpfWmsUrl, { ...noaaWmsOptions, layers: '2' });
const qpfDay3 = L.tileLayer.wms(qpfWmsUrl, { ...noaaWmsOptions, layers: '3' });
const qpfDay4_5 = L.tileLayer.wms(qpfWmsUrl, { ...noaaWmsOptions, layers: '4' });
const qpfDay6_7 = L.tileLayer.wms(qpfWmsUrl, { ...noaaWmsOptions, layers: '5' });

const qpfDay1_2 = L.tileLayer.wms(qpfWmsUrl, { ...noaaWmsOptions, layers: '7' });
const qpfDay1_3 = L.tileLayer.wms(qpfWmsUrl, { ...noaaWmsOptions, layers: '8' });
const qpfDay1_5 = L.tileLayer.wms(qpfWmsUrl, { ...noaaWmsOptions, layers: '9' });
const qpfDay1_7 = L.tileLayer.wms(qpfWmsUrl, { ...noaaWmsOptions, layers: '10' });

// --- GROUPED LAYER CONTROLS ---
const baseMaps = {
    "Esri Dark Gray": esriDarkLayer,
    "OpenStreetMap": osmLayer
};

const groupedOverlays = {
    "Active Hazards & Warnings": {
        "NEXRAD Radar (6-Hour)": radarTimeLayer,
        "Active Hydro Warnings": alertsLayer,
        "WPC Active MPDs": mpdLayer
    },
    "WPC Excessive Rainfall Outlooks": {
        "Day 1 ERO (Real-Time)": eroLayer,
        "Day 2 ERO": eroDay2,
        "Day 3 ERO": eroDay3,
        "Day 4 ERO": eroDay4,
        "Day 5 ERO": eroDay5
    },
    "WPC QPF (Individual Periods)": {
        "Day 1 QPF": qpfDay1,
        "Day 2 QPF": qpfDay2,
        "Day 3 QPF": qpfDay3,
        "Days 4-5 QPF": qpfDay4_5,
        "Days 6-7 QPF": qpfDay6_7
    },
    "WPC QPF (Cumulative Totals)": {
        "Day 1-2 Total": qpfDay1_2,
        "Day 1-3 Total": qpfDay1_3,
        "Day 1-5 Total": qpfDay1_5,
        "Day 1-7 Total": qpfDay1_7
    }
};

L.control.groupedLayers(baseMaps, groupedOverlays, {
    collapsed: true
}).addTo(map);
