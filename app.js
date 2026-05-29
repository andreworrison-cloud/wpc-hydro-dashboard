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

// New Esri Dark Gray Basemap (Better state borders!)
const esriDarkLayer = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}', {
    maxZoom: 16,
    attribution: '© Esri, HERE, Garmin, © OpenStreetMap'
});

// Add default basemap to the map
esriDarkLayer.addTo(map);

// --- 6-Hour Loop Logic ---

// Calculate timestamps for the past 6 hours
const endTime = new Date();
const startTime = new Date(endTime.getTime() - 6 * 60 * 60 * 1000);
const timeRange = startTime.toISOString() + "/" + endTime.toISOString();

// Initialize TimeDimension for the loop
map.timeDimension = L.timeDimension({
    timeInterval: timeRange,
    period: "PT15M", // 15-minute intervals
    currentTime: endTime.getTime()
});

// Add TimeDimension Control UI to the map
L.control.timeDimension({
    position: 'bottomleft',
    autoPlay: true,
    playerOptions: {
        transitionTime: 500, // Speed of animation (ms)
        loop: true
    }
}).addTo(map);

// Define IEM WMS Base Reflectivity Radar Layer (Time-Enabled)
const radarWMS = L.tileLayer.wms("https://mesonet.agron.iastate.edu/cgi-bin/wms/nexrad/n0q-t.cgi", {
    layers: 'nexrad-n0q-wmst',
    format: 'image/png',
    transparent: true,
    opacity: 0.6,
    attribution: "Weather data © IEM Nexrad"
});

// Bind the WMS layer to the TimeDimension controller
const radarTimeLayer = L.timeDimension.layer.wms(radarWMS, {
    updateTimeDimension: false
});

// Add radar to map by default
radarTimeLayer.addTo(map);

// Create layer controls so users can toggle basemaps and overlays
const baseMaps = {
    "Esri Dark Gray": esriDarkLayer,
    "OpenStreetMap": osmLayer
};

const overlays = {
    "NEXRAD Radar": radarTimeLayer
};

L.control.layers(baseMaps, overlays).addTo(map);

console.log("Leaflet map initialized successfully with 6-hour loop and Esri basemap.");
