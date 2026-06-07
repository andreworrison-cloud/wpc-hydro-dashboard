// --- UI CSS FIXES (Scrollable Menu) ---
const customStyle = document.createElement('style');
customStyle.innerHTML = `
    .leaflet-control-layers-expanded {
        max-height: 60vh !important; 
        overflow-y: auto !important; 
    }
`;
document.head.appendChild(customStyle);

// Initialize the map, centered roughly over the CONUS
const map = L.map('map', {
    zoomControl: true,
    center: [39.8283, -98.5795], 
    zoom: 5
});

// --- TOP-CENTER DASHBOARD TITLE ---
const mapTitle = L.DomUtil.create('div', 'map-title');
mapTitle.innerHTML = '<strong>WPC Real-Time Hydrometeorological Dashboard</strong>';
mapTitle.style.position = 'absolute';
mapTitle.style.top = '10px';
mapTitle.style.left = '50%';
mapTitle.style.transform = 'translateX(-50%)';
mapTitle.style.zIndex = '1000';
mapTitle.style.background = 'rgba(0, 0, 0, 0.7)';
mapTitle.style.color = 'white';
mapTitle.style.padding = '12px 24px';
mapTitle.style.borderRadius = '6px';
mapTitle.style.fontFamily = 'sans-serif';
mapTitle.style.fontSize = '24px';
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

// --- AUTO-TOGGLING GEOJSON STATE BORDERS ---
const whiteBorders = L.geoJSON(null, {
    style: { color: 'rgba(255, 255, 255, 0.8)', weight: 1.5, fillOpacity: 0 },
    pane: 'labels', interactive: false
});

const blackBorders = L.geoJSON(null, {
    style: { color: 'rgba(0, 0, 0, 0.8)', weight: 1.5, fillOpacity: 0 },
    pane: 'labels', interactive: false
});

fetch('https://raw.githubusercontent.com/PublicaMundi/MappingAPI/master/data/geojson/us-states.json')
    .then(response => response.json())
    .then(data => {
        whiteBorders.addData(data);
        blackBorders.addData(data);
    });

whiteBorders.addTo(map); // Default to white borders for the dark map

// Listen for basemap changes and automatically swap border colors!
map.on('baselayerchange', function(e) {
    if (e.name === "OpenStreetMap") {
        if (map.hasLayer(whiteBorders)) map.removeLayer(whiteBorders);
        blackBorders.addTo(map);
    } else {
        if (map.hasLayer(blackBorders)) map.removeLayer(blackBorders);
        whiteBorders.addTo(map);
    }
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

// --- MRMS QPE LAYERS (Via IEM WMS) ---
const mrmsOptions = { format: 'image/png', transparent: true, opacity: 0.65, attribution: "Data © IEM / NCEP" };

const mrms1hr = L.tileLayer.wms("https://mesonet.agron.iastate.edu/cgi-bin/wms/us/mrms_nn.cgi", { ...mrmsOptions, layers: 'mrms_p1h' });
const mrms24hr = L.tileLayer.wms("https://mesonet.agron.iastate.edu/cgi-bin/wms/us/mrms_nn.cgi", { ...mrmsOptions, layers: 'mrms_p24h' });
const mrms48hr = L.tileLayer.wms("https://mesonet.agron.iastate.edu/cgi-bin/wms/us/mrms_nn.cgi", { ...mrmsOptions, layers: 'mrms_p48h' });
const mrms72hr = L.tileLayer.wms("https://mesonet.agron.iastate.edu/cgi-bin/wms/us/mrms_nn.cgi", { ...mrmsOptions, layers: 'mrms_p72h' });

// --- STATIC SATELLITE LAYERS (GOES-East & GOES-West) ---
const satOptions = { format: 'image/png', transparent: true, opacity: 0.6 };

const goesEastVis = L.tileLayer.wms("https://mesonet.agron.iastate.edu/cgi-bin/wms/goes_east.cgi", { ...satOptions, layers: 'conus_ch02' });
const goesEastWV = L.tileLayer.wms("https://mesonet.agron.iastate.edu/cgi-bin/wms/goes_east.cgi", { ...satOptions, layers: 'conus_ch09' });
const goesEastIR = L.tileLayer.wms("https://mesonet.agron.iastate.edu/cgi-bin/wms/goes_east.cgi", { ...satOptions, layers: 'conus_ch13' });

const goesWestVis = L.tileLayer.wms("https://mesonet.agron.iastate.edu/cgi-bin/wms/goes_west.cgi", { ...satOptions, layers: 'conus_ch02' });
const goesWestWV = L.tileLayer.wms("https://mesonet.agron.iastate.edu/cgi-bin/wms/goes_west.cgi", { ...satOptions, layers: 'conus_ch09' });
const goesWestIR = L.tileLayer.wms("https://mesonet.agron.iastate.edu/cgi-bin/wms/goes_west.cgi", { ...satOptions, layers: 'conus_ch13' });

// --- RESTORED & CLEANED NWS ACTIVE HYDRO WARNINGS & WATCHES ---
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
        if (!props) return;
        const eventName = props.prod_type || "Unknown Hydro Alert";
        const wfo = props.wfo ? `WFO ${props.wfo}` : "NWS";
        const expires = props.expiration || "Unknown";
        
        // Fail-safe text link
        const linkHTML = props.url ? `<br><br><a href="${props.url}" target="_blank" rel="noopener noreferrer">View Official NWS Bulletin</a>` : "";

        layer.bindPopup(`
            <div style="font-family: sans-serif; text-align: center; min-width: 200px;">
                <strong style="color: ${getAlertColor(eventName)}; font-size: 1.1em;">${eventName}</strong><br>
                <em>Issued by ${wfo}</em><br>
                <hr style="margin: 5px 0;">
                <span style="font-size: 0.9em;">Expires: ${expires}</span>
                ${linkHTML}
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
        
        // Added fail-safe in case the payload is empty
        if (data && data.features) {
            const warningFeatures = data.features.filter(f => !f.properties.prod_type.includes("Watch"));
            const watchFeatures = data.features.filter(f => f.properties.prod_type.includes("Watch"));
            
            if (warningFeatures.length > 0) warningsLayer.addData(warningFeatures);
            if (watchFeatures.length > 0) watchesLayer.addData(watchFeatures);
        }
    } catch (error) { console.error("Error fetching NWS alerts:", error); }
}
fetchNWSAlerts();

// --- LIVE WPC GEOJSON (Day 1 ERO & MPDs) WITH DISCUSSION LINKS ---
function getEroStyle(feature) {
    const cat = (feature.properties.OUTLOOK || feature.properties.outlook || feature.properties.Outlook || "").toUpperCase();
    let riskColor = "#00ff00"; 
    if (cat.includes("SLGT") || cat.includes("SLIGHT")) riskColor = "#FFFF00"; 
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
        layer.bindPopup(`
            <div style="text-align: center; font-family: sans-serif;">
                <strong>WPC Day 1 ERO</strong><br>Category: ${cat}<br><br>
                <a href="https://www.wpc.ncep.noaa.gov/discussions/qpferd.html" target="_blank" rel="noopener noreferrer">Read ERO Discussion</a>
            </div>
        `);
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
            const currentYear = new Date().getUTCFullYear();
            
            const tooltipHTML = `<div style="text-align: center; font-family: sans-serif; line-height: 1.4;"><strong>MPD ${mpdNum}</strong><br>${mpdTag}<br>Valid: ${validTime}</div>`;
            layer.bindTooltip(tooltipHTML, { sticky: true, direction: "top" });
            
            const popupHTML = `
                <div style="font-family: sans-serif; font-size: 14px; min-width: 240px; text-align: center;">
                    <strong>MPD ${mpdNum}</strong><br>
                    <span style="color: #d84b2a;"><strong>${mpdTag}</strong></span><br>
                    <hr style="margin: 5px 0;">
                    <span style="font-size: 0.9em;">Valid: ${validTime}</span><br><br>
                    <a href="https://www.wpc.ncep.noaa.gov/metwatch/metwatch_mpd_multi.php?md=${mpdNum}&yr=${currentYear}" target="_blank" rel="noopener noreferrer">Read MPD Discussion</a>
                </div>
            `;
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
        
        let eroFeatures = data.features.filter(f => f.properties.dataType === 'ERO');
        const mpdFeatures = data.features.filter(f => f.properties.dataType === 'MPD');
        
        eroFeatures.sort((a, b) => {
            const getRank = (feature) => {
                const cat = (feature.properties.OUTLOOK || feature.properties.outlook || feature.properties.Outlook || "").toUpperCase();
                if (cat.includes("HIGH")) return 4;
                if (cat.includes("MDT") || cat.includes("MODERATE")) return 3;
                if (cat.includes("SLGT") || cat.includes("SLIGHT")) return 2;
                return 1; 
            };
            return getRank(a) - getRank(b); 
        });
        
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

// RAP Valid Time UI Box
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
    div.style.display = 'none'; 
    return div;
};
timeControl.addTo(map);

// MRMS Valid Time UI Box
const mrmsTimeControl = L.control({position: 'bottomright'});
mrmsTimeControl.onAdd = function(map) {
    const div = L.DomUtil.create('div', 'time-box');
    div.id = 'mrms-time-box';
    div.style.background = 'rgba(0, 0, 0, 0.7)';
    div.style.color = '#ffffff';
    div.style.padding = '8px 12px';
    div.style.borderRadius = '6px';
    div.style.marginBottom = '5px';
    div.style.textAlign = 'center';
    div.style.display = 'none'; 
    return div;
};
mrmsTimeControl.addTo(map);

// Legend UI Box (Handles both Images and Dynamic HTML)
const legendControl = L.control({position: 'bottomright'});
legendControl.onAdd = function (map) {
    const div = L.DomUtil.create('div', 'legend-box');
    div.id = 'legend-container';
    div.style.background = 'rgba(0, 0, 0, 0.7)';
    div.style.padding = '10px';
    div.style.borderRadius = '6px';
    div.style.display = 'none'; 
    div.innerHTML = `
        <img id="legend-img" src="" style="max-width: 300px; display: none;">
        <div id="legend-html" style="display: none;"></div>
    `;
    return div;
};
legendControl.addTo(map);

// Programmatic HTML Generator for the MRMS Color Bar
function getMRMSLegendHTML() {
    const levels = [
        {v: '8.0+', c: '#FFFFCC'}, {v: '7.0', c: '#9966CC'}, {v: '6.5', c: '#CC00FF'}, {v: '6.0', c: '#FF00FF'},
        {v: '5.5', c: '#990000'}, {v: '5.0', c: '#CC0000'}, {v: '4.5', c: '#FF0000'}, {v: '4.0', c: '#FF3300'},
        {v: '3.0', c: '#FF6600'}, {v: '2.0', c: '#FF9900'}, {v: '1.75', c: '#FFCC00'}, {v: '1.25', c: '#FFFF00'},
        {v: '1.00', c: '#CCFF33'}, {v: '0.80', c: '#66FF33'}, {v: '0.60', c: '#33CC33'}, {v: '0.40', c: '#009900'},
        {v: '0.20', c: '#0000FF'}, {v: '0.10', c: '#3366FF'}, {v: '0.05', c: '#33CCFF'}, {v: '0.01', c: '#66FFFF'}
    ];
    
    let html = `
        <div style="background: #f4f4f4; padding: 12px 16px; border-radius: 8px; color: #2c3e50; font-family: sans-serif; font-size: 12px; border: 1px solid #ccc; width: max-content;">
            <div style="font-weight: bold; text-align: center; margin-bottom: 8px; font-size: 16px; color: #1a252f;">inches</div>
    `;
    
    levels.forEach(lvl => {
        html += `
            <div style="display: flex; align-items: center; margin-bottom: 2px;">
                <div style="width: 24px; height: 14px; background: ${lvl.c}; border: 1px solid #999; margin-right: 10px;"></div>
                <div style="font-family: monospace; font-size: 13px;">${lvl.v}</div>
            </div>
        `;
    });
    
    html += `</div>`;
    return html;
}

// Fetch the RAP bounds and time
fetch('static/rap_metadata.json?t=' + new Date().getTime())
    .then(r => r.json())
    .then(data => {
        const timeBox = document.getElementById('rap-time-box');
        timeBox.innerHTML = `<strong>${data.valid_time}</strong>`;
        timeBox.style.display = 'block';

        if (data.bounds) {
            const exactBounds = L.latLngBounds(data.bounds[0], data.bounds[1]);
            pwatLayer.setBounds(exactBounds);
            sbcapeLayer.setBounds(exactBounds);
            mlcapeLayer.setBounds(exactBounds);
            mucapeLayer.setBounds(exactBounds);
            lrsfc3Layer.setBounds(exactBounds);
            lr75Layer.setBounds(exactBounds);
            scpLayer.setBounds(exactBounds);
            mfcLayer.setBounds(exactBounds);
            f925Layer.setBounds(exactBounds);
            f850Layer.setBounds(exactBounds);
            effShearLayer.setBounds(exactBounds);
            corfidiUpLayer.setBounds(exactBounds);
            corfidiDownLayer.setBounds(exactBounds);
            trans850Layer.setBounds(exactBounds);
            trans700Layer.setBounds(exactBounds);
            meanWindLayer.setBounds(exactBounds);
            vort500Layer.setBounds(exactBounds);
            diffAdvLayer.setBounds(exactBounds);
            div250Layer.setBounds(exactBounds);
        }
    })
    .catch(err => console.log("RAP metadata not found yet."));

// Helper function to calculate rolling MRMS UTC time strings
function formatUTC(date) {
    const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
    const m = months[date.getUTCMonth()];
    const d = String(date.getUTCDate()).padStart(2, '0');
    const h = String(date.getUTCHours()).padStart(2, '0');
    const min = String(date.getUTCMinutes()).padStart(2, '0');
    return `${m} ${d}, ${h}${min}Z`;
}

// Dynamically route the legend images and time boxes
map.on('overlayadd', function(eventLayer) {
    const legendContainer = document.getElementById('legend-container');
    const legendImg = document.getElementById('legend-img');
    const legendHtml = document.getElementById('legend-html');
    const mrmsTimeBox = document.getElementById('mrms-time-box');
    
    // RAP Legends (Uses static PNG files)
    if (eventLayer.name.includes('RAP') || eventLayer.name.includes('Lapse Rate')) {
        legendContainer.style.display = 'block';
        legendContainer.style.background = 'rgba(0, 0, 0, 0.7)';
        legendHtml.style.display = 'none';
        legendImg.style.display = 'block';
        
        if (eventLayer.name.includes('PWAT')) legendImg.src = 'static/leg_pwat.png';
        else if (eventLayer.name.includes('CAPE')) legendImg.src = 'static/leg_cape.png';
        else if (eventLayer.name.includes('700-500mb Mid-Level')) legendImg.src = 'static/leg_lr75.png';
        else if (eventLayer.name.includes('Sfc-3km')) legendImg.src = 'static/leg_lrsfc3.png';
        else if (eventLayer.name.includes('Supercell Composite')) legendImg.src = 'static/leg_scp.png';
        else if (eventLayer.name.includes('Convergence')) legendImg.src = 'static/leg_mfc.png';
        else if (eventLayer.name.includes('Frontogenesis')) legendImg.src = 'static/leg_fronto.png';
        else if (eventLayer.name.includes('Bulk Shear')) legendImg.src = 'static/leg_eff_shear.png';
        else if (eventLayer.name.includes('Corfidi Upwind')) legendImg.src = 'static/leg_corfidi_up.png';
        else if (eventLayer.name.includes('Corfidi Downwind')) legendImg.src = 'static/leg_corfidi_down.png';
        else if (eventLayer.name.includes('Transport')) legendImg.src = 'static/leg_trans.png';
        else if (eventLayer.name.includes('Mean Layer Wind')) legendImg.src = 'static/leg_mean_wind.png';
        else if (eventLayer.name.includes('Absolute Vorticity')) legendImg.src = 'static/leg_vort.png';
        else if (eventLayer.name.includes('Diff Vorticity')) legendImg.src = 'static/leg_diff_adv.png';
        else if (eventLayer.name.includes('Divergence')) legendImg.src = 'static/leg_div.png';
    }
    
    // MRMS Legends (Uses dynamically generated HTML color bar)
    if (eventLayer.name.includes('MRMS')) {
        legendContainer.style.display = 'block';
        legendContainer.style.background = 'transparent'; // Let the HTML box background show cleanly
        legendImg.style.display = 'none';
        legendHtml.style.display = 'block';
        
        legendHtml.innerHTML = getMRMSLegendHTML();
        
        let hours = 1;
        if (eventLayer.name.includes('24-Hour')) { hours = 24; }
        if (eventLayer.name.includes('48-Hour')) { hours = 48; }
        if (eventLayer.name.includes('72-Hour')) { hours = 72; }

        const now = new Date();
        const start = new Date(now.getTime() - (hours * 60 * 60 * 1000));
        
        mrmsTimeBox.innerHTML = `<strong>MRMS ${hours}-Hour Accumulation</strong><br>${formatUTC(start)} &mdash; ${formatUTC(now)}`;
        mrmsTimeBox.style.display = 'block';
    }
});

// Hide the legend/time when a layer is toggled off
map.on('overlayremove', function(eventLayer) {
    const legendContainer = document.getElementById('legend-container');
    const mrmsTimeBox = document.getElementById('mrms-time-box');
    
    if (eventLayer.name.includes('RAP') || eventLayer.name.includes('Lapse Rate')) {
        legendContainer.style.display = 'none';
    }
    if (eventLayer.name.includes('MRMS')) {
        legendContainer.style.display = 'none';
        mrmsTimeBox.style.display = 'none';
    }
});

// --- GROUPED LAYER CONTROLS ---
const baseMaps = {
    "Esri Dark Gray": esriDarkBase,
    "OpenStreetMap": osmLayer
};

const groupedOverlays = {
    "Active Hazards & Warnings": {
        "Active Hydro Warnings & Advisories": warningsLayer,
        "Active Hydro Watches": watchesLayer,
        "WPC Active MPDs": mpdLayer,
        "Day 1 ERO (Real-Time)": eroLayer
    },
    "Radar and Satellite Data (Real-Time)": {
        "NEXRAD Radar (2-Hour Loop)": radarTimeLayer,
        "MRMS 1-Hour QPE": mrms1hr,
        "MRMS 24-Hour QPE": mrms24hr,
        "MRMS 48-Hour QPE": mrms48hr,
        "MRMS 72-Hour QPE": mrms72hr,
        "GOES-East: Visible (Ch. 2)": goesEastVis,
        "GOES-East: Mid-Level WV (Ch. 9)": goesEastWV,
        "GOES-East: Clean IR (Ch. 13)": goesEastIR,
        "GOES-West: Visible (Ch. 2)": goesWestVis,
        "GOES-West: Mid-Level WV (Ch. 9)": goesWestWV,
        "GOES-West: Clean IR (Ch. 13)": goesWestIR
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
        "RAP Effective Bulk Shear": effShearLayer,
        "RAP Corfidi Upwind (Back-Building) Vectors": corfidiUpLayer,
        "RAP Corfidi Downwind (Forward) Vectors": corfidiDownLayer,
        "RAP 850mb Moisture Transport": trans850Layer,
        "RAP 700mb Moisture Transport": trans700Layer,
        "RAP 850-300mb Mean Layer Wind": meanWindLayer,
        "RAP 500mb Absolute Vorticity": vort500Layer,
        "RAP 700-400mb Diff Vorticity Advection": diffAdvLayer,
        "RAP 250mb Divergence": div250Layer
    }
};

const layerControl = L.control.groupedLayers(baseMaps, groupedOverlays, { 
    collapsed: true 
}).addTo(map);

// --- STOP MENU DOUBLE CLICKS FROM ZOOMING THE MAP ---
L.DomEvent.disableClickPropagation(layerControl.getContainer());
L.DomEvent.disableScrollPropagation(layerControl.getContainer());
