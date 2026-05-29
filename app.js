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

const darkMatterLayer = L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
    maxZoom: 19,
    attribution: '© OpenStreetMap contributors, © CARTO'
});

// Add default basemap to the map
darkMatterLayer.addTo(map);

// --- NEW: 6-Hour Loop Logic ---

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

// Define IEM WMS Base Reflectivity Radar Layer
const radarWMS = L.tileLayer.wms("https://mesonet.agron.iastate.edu/cgi-bin/wms/nexrad/n0q.cgi", {
    layers: 'nexrad-n0q-900913',
    format: 'image/png',
    transparent: true,
    opacity: 0.6, // Slight transparency so basemap features are visible
    attribution: "Weather data © IEM Nexrad"
});

// Bind the WMS layer to the TimeDimension controller
const radarTimeLayer = L.timeDimension.layer.wms(radarWMS, {
    updateTimeDimension: false
});

// Add radar to map by default
radarTimeLayer.addTo(map);

// --- END NEW ---

// Create layer controls so users can toggle basemaps and overlays
const baseMaps = {
    "Dark Mode": darkMatterLayer,
    "OpenStreetMap": osmLayer
};

const overlays = {
    "NEXRAD Radar": radarTimeLayer
};

L.control.layers(baseMaps, overlays).addTo(map);

console.log("Leaflet map initialized with 6-Hour IEM Radar Loop.");
