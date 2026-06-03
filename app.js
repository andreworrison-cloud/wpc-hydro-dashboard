// Initialize the map, centered roughly over the CONUS
const map = L.map('map', {
    zoomControl: true,
    center: [39.8283, -98.5795], 
    zoom: 5
});

// --- TOP-CENTER DASHBOARD TITLE ---
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

// --- THE AWIPS BORDERS TRICK ---
map.createPane('labels');
map.getPane('labels').style.zIndex = 650;
map.getPane('labels').style.pointerEvents = 'none'; 

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

// The floating borders and labels (Always sits on top of weather data)
const esriDarkLabels = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Reference/MapServer/tile/{z}/{y}/{x}', {
    pane: 'labels',
    maxZoom: 16
});
esriDarkLabels.addTo(map);

// --- BOLDER GEOJSON STATE BORDERS ---
fetch('https://raw.githubusercontent.com/PublicaMundi/MappingAPI/master/data/geojson/us-states.json')
    .then(response => response.json())
    .then(data => {
        L.geoJSON(data, {
            style: {
                color: 'rgba(255, 255, 255, 0.8)', // Bright, crisp white
                weight: 1.5,                       // Thicker, bolder lines
                fillOpacity: 0                     // Completely transparent inside
            },
            pane: 'labels',                        // Forces it into the top pane
            interactive: false                     // Prevents blocking mouse clicks
        }).addTo(map);
    });

// --- TIME LOOP LOGIC (10-Min Intervals, 2-Hour Loop for Speed) ---
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

// --- STATIC SATELLITE LAYERS (GOES-East & GOES-West) ---
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

const commonAlertOptions = {
    style: function (feature) {
        return { color: getAlertColor(feature.properties.prod_type), weight: 2, opacity: 1, fillOpacity: 0.2 };
    },
    onEachFeature: function (feature, layer) {
        const props = feature.properties;
        const eventName = props.prod_type || "Unknown Hydro Alert";
        const wfo = props.wfo ? `WFO ${props.wfo}` : "NWS";
        const expires = props.expiration || "Unknown";
        const link = props.url ? `<br><br><a href="${props.url}" target="_blank">View Alert Text</a>` : "";

        layer.bindPopup(`
            <div style="font-family: sans-serif; text-align: center; min-width: 200px;">
                <strong style="color: ${getAlertColor(eventName)}; font-size: 1.1em;">${eventName}</strong><br>
                <em>Issued by ${wfo}</em><br>
                <hr style="margin: 5px 0;">
                <span style="font-size: 0.9em;">Expires: ${expires}</span>
                ${link}
            </div>
        `);
    }
};

const warningsLayer = L.geoJSON(null, commonAlertOptions);
const watchesLayer = L.geoJSON(null, commonAlertOptions);

warningsLayer.addTo(map);
watchesLayer.addTo(map);

async function fetchNWSAlerts() {
    try {
        const whereClause = "prod_type IN ('Flash Flood Warning', 'Flood Warning', 'Flood Advisory', 'Flood Watch', 'Flash Flood Watch')";
        const url = `https://mapservices.weather.noaa.gov/eventdriven/rest/services/WWA/watch_warn_adv/MapServer/1/query?where=${encodeURIComponent(whereClause)}&outFields=prod_type,wfo,expiration,url&f=geojson`;
        
        const response = await fetch(url);
        if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
        const data = await response.json();
        
        const warningFeatures = data.features.filter(f => !f.properties.prod_type.includes("Watch"));
        const watchFeatures = data.features.filter(f => f.properties.prod_type.includes("Watch"));
        
        if (warningFeatures.length > 0) warningsLayer.addData(warningFeatures);
        if (watchFeatures.length > 0) watchesLayer.addData(watchFeatures);
        
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

// --- RAP MESOANALYSIS LAYERS & UI ---
const rapBounds = [[16.281, -139.856], [55.481, -57.373]]; 

const pwatLayer = L.imageOverlay('static/rap_pwat.png', rapBounds, {zIndex: 10});
const sbcapeLayer = L.imageOverlay('static/rap_sbcape.png', rapBounds, {zIndex: 10});
const mlcapeLayer = L.imageOverlay('static/rap_mlcape.png', rapBounds, {zIndex: 10});
const mucapeLayer = L.imageOverlay('static/rap_mucape.png', rapBounds, {zIndex: 10});
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

// Valid Time UI Box
const timeControl = L.control({position: 'bottomright'});
timeControl.onAdd = function(map) {
    const div = L.DomUtil.create('div', 'time-box');
    div.id = 'rap-time-box';
    div.style.background = 'rgba(0, 0, 0, 0.7)';
    div.style.color = '#ffffff';
    div.style.padding = '8px 12px';
    div.style.borderRadius = '6px';
    div.style.marginBottom = '5px';
    div.style.textAlign = 'center';
    div.style.display = 'none'; // Hidden until RAP data is fetched
    return div;
};
timeControl.addTo(map);

// Legend UI Box
const legendControl = L.control({position: 'bottomright'});
legendControl.onAdd = function (map) {
    const div = L.DomUtil.create('div', 'legend-box');
    div.id = 'legend-container';
    div.style.background = 'rgba(0, 0, 0, 0.7)';
    div.style.padding = '10px';
    div.style.borderRadius = '6px';
    div.style.display = 'none'; 
    div.innerHTML = '<img id="legend-img" src="" style="max-width: 300px;">';
    return div;
};
legendControl.addTo(map);

// Fetch the valid time from the Python script's JSON output
fetch('static/rap_metadata.json?t=' + new Date().getTime())
    .then(r => r.json())
    .then(data => {
        const timeBox = document.getElementById('rap-time-box');
        timeBox.innerHTML = `<strong>${data.valid_time}</strong>`;
        timeBox.style.display = 'block';
    })
    .catch(err => console.log("RAP metadata not found yet."));

// Dynamically route the legend images on layer add
map.on('overlayadd', function(eventLayer) {
    const legendContainer = document.getElementById('legend-container');
    const legendImg = document.getElementById('legend-img');
    
    if (eventLayer.name.includes('RAP') || eventLayer.name.includes('Lapse Rate')) {
        legendContainer.style.display = 'block';
        
        if (eventLayer.name.includes('PWAT')) legendImg.src = 'static/leg_pwat.png';
        else if (eventLayer.name.includes('CAPE')) legendImg.src = 'static/leg_cape.png';
        else if (eventLayer.name.includes('700-500mb Mid-Level')) legendImg.src = 'static/leg_lr75.png';
        else if (eventLayer.name.includes('Sfc-3km')) legendImg.src = 'static/leg_lrsfc3.png';
        else if (eventLayer.name.includes('Supercell Composite')) legendImg.src = 'static/leg_scp.png';
        else if (eventLayer.name.includes('Convergence')) legendImg.src = 'static/leg_mfc.png';
        else if (eventLayer.name.includes('Frontogenesis')) legendImg.src = 'static/leg_fronto.png';
        else if (eventLayer.name.includes('Wind Shear')) legendImg.src = 'static/leg_eff_shear.png';
        else if (eventLayer.name.includes('Corfidi Upwind')) legendImg.src = 'static/leg_corfidi_up.png';
        else if (eventLayer.name.includes('Corfidi Downwind')) legendImg.src = 'static/leg_corfidi_down.png';
        else if (eventLayer.name.includes('Transport')) legendImg.src = 'static/leg_trans.png';
        else if (eventLayer.name.includes('Mean Layer Wind')) legendImg.src = 'static/leg_mean_wind.png';
        else if (eventLayer.name.includes('Absolute Vorticity')) legendImg.src = 'static/leg_vort.png';
        else if (eventLayer.name.includes('Diff Vorticity')) legendImg.src = 'static/leg_diff_adv.png';
        else if (eventLayer.name.includes('Divergence')) legendImg.src = 'static/leg_div.png';
    }
});

// Hide the legend when a RAP layer is toggled off via checkbox
map.on('overlayremove', function(eventLayer) {
    const legendContainer = document.getElementById('legend-container');
    if (eventLayer.name.includes('RAP') || eventLayer.name.includes('Lapse Rate')) {
        legendContainer.style.display = 'none';
    }
});

// --- GROUPED LAYER CONTROLS ---
const baseMaps = {
    "Esri Dark Gray": esriDarkBase,
    "OpenStreetMap": osmLayer
};

const groupedOverlays = {
    "Active Hazards & Warnings": {
        "NEXRAD Radar (2-Hour Loop)": radarTimeLayer,
        "Active Hydro Warnings & Advisories": warningsLayer,
        "Active Hydro Watches": watchesLayer,
        "WPC Active MPDs": mpdLayer,
        "Day 1 ERO (Real-Time)": eroLayer
    },
    "RAP Mesoanalysis (Real-Time)": {
        "RAP Precipitable Water (PWAT)": pwatLayer,
        "RAP Surface Based CAPE": sbcapeLayer,
        "RAP Mixed Layer CAPE (90mb)": mlcapeLayer,
        "RAP Most Unstable CAPE (255mb)": mucapeLayer,
        "RAP Sfc-3km Low-Level Lapse Rate": lrsfc3Layer,
        "RAP 700-500mb Mid-Level Lapse Rate": lr75Layer,
        "RAP Supercell Composite Parameter": scpLayer,
        "RAP Mean BL Moisture Convergence": mfcLayer,
        "RAP 925/850mb Frontogenesis": f925Layer,
        "RAP 850/700mb Frontogenesis": f850Layer,
        "RAP 0-6km Bulk Wind Shear": effShearLayer,
        "RAP Corfidi Upwind (Back-Building) Vectors": corfidiUpLayer,
        "RAP Corfidi Downwind (Forward) Vectors": corfidiDownLayer,
        "RAP 850mb Moisture Transport": trans850Layer,
        "RAP 700mb Moisture Transport": trans700Layer,
        "RAP 850-300mb Mean Layer Wind": meanWindLayer,
        "RAP 500mb Absolute Vorticity": vort500Layer,
        "RAP 700-400mb Diff Vorticity Advection": diffAdvLayer,
        "RAP 250mb Divergence": div250Layer
    },
    "GOES-East (Latest)": {
        "Visible (Ch. 2)": goesEastVis,
        "Mid-Level WV (Ch. 9)": goesEastWV,
        "Clean IR (Ch. 13)": goesEastIR
    },
    "GOES-West (Latest)": {
        "Visible (Ch. 2)": goesWestVis,
        "Mid-Level WV (Ch. 9)": goesWestWV,
        "Clean IR (Ch. 13)": goesWestIR
    }
};

// Menu without the exclusiveGroups constraint to allow checkboxes
L.control.groupedLayers(baseMaps, groupedOverlays, { 
    collapsed: true 
}).addTo(map);
