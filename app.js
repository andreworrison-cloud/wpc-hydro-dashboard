// Initialize the map, centered roughly over the CONUS
const map = L.map('map', {
    zoomControl: true,
    center: [39.8283, -98.5795], // Geographic center of contiguous US
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
    playerOptions: {
        transitionTime: 500,
        loop: true
    }
}).addTo(map);

const radarWMS = L.tileLayer.wms("https://mesonet.agron.iastate.edu/cgi-bin/wms/nexrad/n0q-t.cgi", {
    layers: 'nexrad-n0q-wmst',
    format: 'image/png',
    transparent: true,
    opacity: 0.6,
    attribution: "Weather data © IEM Nexrad"
});

const radarTimeLayer = L.timeDimension.layer.wms(radarWMS, {
    updateTimeDimension: false
});

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
        return {
            color: getAlertColor(feature.properties.event),
            weight: 2,
            opacity: 1,
            fillOpacity: 0.2
        };
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

// --- NEW: WPC ERO & MPD Logic ---

// ERO styling based on standard WPC risk colors
function getEroStyle(feature) {
    let riskColor = "green"; // Default
    const cat = feature.properties.OUTLOOK;
    if (cat === "MRGL") riskColor = "#00ff00"; // Green
    if (cat === "SLGT") riskColor = "#ffff00"; // Yellow
    if (cat === "MDT")  riskColor = "#ff0000"; // Red
    if (cat === "HIGH") riskColor = "#ff00ff"; // Magenta
    
    return {
        color: riskColor,
        weight: 2,
        fillOpacity: 0.15
    };
}

const eroLayer = L.geoJSON(null, {
    style: getEroStyle,
    onEachFeature: function (feature, layer) {
        layer.bindPopup(`<strong>WPC Day 1 ERO</strong><br>Category: ${feature.properties.OUTLOOK}`);
    }
});

const mpdLayer = L.geoJSON(null, {
    style: {
        color: "fuchsia",
        weight: 3,
        dashArray: "5, 5",
        fillOpacity: 0.1
    },
    onEachFeature: function (feature, layer) {
        layer.bindPopup(`<strong>Active WPC MPD</strong>`);
    }
});

eroLayer.addTo(map);
mpdLayer.addTo(map);

async function fetchWPCData() {
    try {
        // Cache busting to ensure we always fetch the newest iteration of the file
        const url = 'wpc_data.geojson?t=' + new Date().getTime();
        const response = await fetch(url);
        
        if (!response.ok) {
            console.log("wpc_data.geojson not found yet. The backend action may still be running.");
            return;
        }
        
        const data = await response.json();
        
        const eroFeatures = data.features.filter(f => f.properties.dataType === 'ERO');
        const mpdFeatures = data.features.filter(f => f.properties.dataType === 'MPD');
        
        if (eroFeatures.length > 0) eroLayer.addData(eroFeatures);
        if (mpdFeatures.length > 0) mpdLayer.addData(mpdFeatures);
        
    } catch (error) {
        console.error("Error fetching WPC GeoJSON:", error);
    }
}

fetchWPCData();

// --- Layer Controls ---

const baseMaps = {
    "Esri Dark Gray": esriDarkLayer,
    "OpenStreetMap": osmLayer
};

const overlays = {
    "NEXRAD Radar": radarTimeLayer,
    "Active Hydro Warnings": alertsLayer,
    "WPC Day 1 ERO": eroLayer,
    "WPC Active MPDs": mpdLayer
};

L.control.layers(baseMaps, overlays).addTo(map);
