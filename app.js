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

const esriDarkBase = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}', {
    maxZoom: 16,
    attribution: '© Esri, HERE, Garmin, © OpenStreetMap'
});
esriDarkBase.addTo(map);

const esriDarkLabels = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Reference/MapServer/tile/{z}/{y}/{x}', {
    pane: 'labels',
    maxZoom: 16
});
esriDarkLabels.addTo(map);


// --- TIME LOOP LOGIC (10-Min Intervals for Radar & Sat) ---
const endTime = new Date();
// Snap to the nearest 10-minute block (e.g., :00, :10, :20)
endTime.setMinutes(Math.floor(endTime.getMinutes() / 10) * 10);
endTime.setSeconds(0);
endTime.setMilliseconds(0);

const startTime = new Date(endTime.getTime() - 6 * 60 * 60 * 1000);
const timeRange = startTime.toISOString() + "/" + endTime.toISOString();

map.timeDimension = L.timeDimension({
    timeInterval: timeRange,
    period: "PT10M", // 10-minute steps
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


// --- LOOPING SATELLITE LAYERS (GOES-East & GOES-West) ---
const satOptions = { format: 'image/png', transparent: true, opacity: 0.6 };

// GOES-East
const goesEastVisWMS = L.tileLayer.wms("https://mesonet.agron.iastate.edu/cgi-bin/wms/goes_east.cgi", { ...satOptions, layers: 'conus_ch02' });
const goesEastVis = L.timeDimension.layer.wms(goesEastVisWMS, { updateTimeDimension: false });

const goesEastWVWMS = L.tileLayer.wms("https://mesonet.agron.iastate.edu/cgi-bin/wms/goes_east.cgi", { ...satOptions, layers: 'conus_ch09' });
const goesEastWV = L.timeDimension.layer.wms(goesEastWVWMS, { updateTimeDimension: false });

const goesEastIRWMS = L.tileLayer.wms("https://mesonet.agron.iastate.edu/cgi-bin/wms/goes_east.cgi", { ...satOptions, layers: 'conus_ch13' });
const goesEastIR = L.timeDimension.layer.wms(goesEastIRWMS, { updateTimeDimension: false });

// GOES-West
const goesWestVisWMS = L.tileLayer.wms("https://mesonet.agron.iastate.edu/cgi-bin/wms/goes_west.cgi", { ...satOptions, layers: 'conus_ch02' });
const goesWestVis = L.timeDimension.layer.wms(goesWestVisWMS, { updateTimeDimension: false });

const goesWestWVWMS = L.tileLayer.wms("https://mesonet.agron.iastate.edu/cgi-bin/wms/goes_west.cgi", { ...satOptions, layers: 'conus_ch09' });
const goesWestWV = L.timeDimension.layer.wms(goesWestWVWMS, { updateTimeDimension: false });

const goesWestIRWMS = L.tileLayer.wms("https://mesonet.agron.iastate.edu/cgi-bin/wms/goes_west.cgi", { ...satOptions, layers: 'conus_ch13' });
const goesWestIR = L.timeDimension.layer.wms(goesWestIRWMS, { updateTimeDimension: false });


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


// --- GROUPED LAYER CONTROLS ---
const baseMaps = {
    "Esri Dark Gray": esriDarkBase
};

const groupedOverlays = {
    "Active Hazards & Warnings": {
        "NEXRAD Radar (6-Hour Loop)": radarTimeLayer,
        "Active Hydro Warnings & Advisories": warningsLayer,
        "Active Hydro Watches": watchesLayer,
        "WPC Active MPDs": mpdLayer,
        "Day 1 ERO (Real-Time)": eroLayer
    },
    "GOES-East (Looping)": {
        "Visible (Ch. 2)": goesEastVis,
        "Mid-Level WV (Ch. 9)": goesEastWV,
        "Clean IR (Ch. 13)": goesEastIR
    },
    "GOES-West (Looping)": {
        "Visible (Ch. 2)": goesWestVis,
        "Mid-Level WV (Ch. 9)": goesWestWV,
        "Clean IR (Ch. 13)": goesWestIR
    }
};

L.control.groupedLayers(baseMaps, groupedOverlays, { collapsed: true }).addTo(map);
