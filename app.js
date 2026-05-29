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
                'User-Agent': 'WPC-Hydro-Dashboard/1.0 (Contact: wpc.meteorologist@noaa.gov)' 
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

// --- WPC ERO & MPD Logic ---
function getEroStyle(feature) {
    const cat = (feature.properties.OUTLOOK || feature.properties.outlook || feature.properties.Outlook || "").toUpperCase();
    let riskColor = "#00ff00"; 
    
    if (cat.includes("SLGT") || cat.includes("SLIGHT")) riskColor = "#FFA500"; 
    if (cat.includes("MDT") || cat.includes("MODERATE"))  riskColor = "#FF0000"; 
    if (cat.includes("HIGH")) riskColor = "#FF00FF"; 
    
    return { color: riskColor, weight: 2, fillOpacity: 0.15 };
}

// Dynamic MPD Styling Function
function getMpdStyle(feature) {
    const props = feature.properties;
    const tagStr = (props.TAG || props.tag || props.PROB || props.SUBJECT || "").toUpperCase();
    let lineColor = "#ff00ff"; // Fallback Fuchsia
    
    // Using .includes() securely catches the words regardless of the long WPC header
    if (tagStr.includes("POSSIBLE")) lineColor = "#0000FF"; // Blue
    if (tagStr.includes("LIKELY")) lineColor = "#800080";   // Purple
    
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
        
        const issueRaw = props.ISSUE || props.issue || props.Issue || "Unknown";
        const expireRaw = props.EXPIRE || props.expire || props.Expire || "Unknown";
        let rawTag = props.TAG || props.tag || props.PROB || props.SUBJECT || "See WPC for details";
        
        // --- NEW: Clean up the long WPC header for the popup UI ---
        let displayTag = rawTag;
        if (displayTag.includes("...")) {
            let parts = displayTag.split("...");
            // Grab the last part (e.g., "Flash flooding possible") and capitalize the first letter nicely
            let isolatedTag = parts[parts.length - 1].trim();
            displayTag = isolatedTag.charAt(0).toUpperCase() + isolatedTag.slice(1).toLowerCase();
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
            
            map.on('overlayadd', function(e) { if (e.name === "WPC Day 1 ERO") noEroLabel.addTo(map); });
            map.on('overlayremove', function(e) { if (e.name === "WPC Day 1 ERO") noEroLabel.remove(); });
            if (map.hasLayer(eroLayer)) noEroLabel.addTo(map);
        }
        
        if (mpdFeatures.length > 0) mpdLayer.addData(mpdFeatures);
        
    } catch (error) {
        console.error("Error fetching WPC GeoJSON:", error);
    }
}

fetchWPCData();

// --- Layer Controls ---
const baseMaps = { "Esri Dark Gray": esriDarkLayer, "OpenStreetMap": osmLayer };
const overlays = {
    "NEXRAD Radar": radarTimeLayer,
    "Active Hydro Warnings": alertsLayer,
    "WPC Day 1 ERO": eroLayer,
    "WPC Active MPDs": mpdLayer
};

L.control.layers(baseMaps, overlays).addTo(map);
