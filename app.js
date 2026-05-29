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

// --- NEW: NWS Active Warnings Logic ---

// Determine color based on hazard type
function getAlertColor(event) {
    if (event === "Flash Flood Warning") return "red";
    if (event === "Flood Warning") return "green";
    if (event === "Flood Advisory") return "lightgreen";
    return "gray"; // Fallback color
}

// Create an empty GeoJSON layer with custom styling and popups
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

// Add the alerts layer to the map by default
alertsLayer.addTo(map);

// Fetch the data from the NWS API
async function fetchNWSAlerts() {
    try {
        // We filter directly in the URL to save bandwidth (only asking for the 3 we want)
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
        console.log(`Successfully loaded ${data.features.length} hydrologic alerts.`);
        
    } catch (error) {
        console.error("Error fetching NWS alerts:", error);
    }
}

// Execute the fetch function
fetchNWSAlerts();

// --- Layer Controls ---

const baseMaps = {
    "Esri Dark Gray": esriDarkLayer,
    "OpenStreetMap": osmLayer
};

const overlays = {
    "NEXRAD Radar": radarTimeLayer,
    "Active Hydro Warnings": alertsLayer
};

L.control.layers(baseMaps, overlays).addTo(map);

console.log("Phase 1 Frontend completed!");
