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

// Create a layer control so the user can toggle basemaps
const baseMaps = {
    "Dark Mode": darkMatterLayer,
    "OpenStreetMap": osmLayer
};

L.control.layers(baseMaps).addTo(map);

console.log("Leaflet map initialized successfully.");