// Dynamic MPD Styling Function - Bulletproof search
function getMpdStyle(feature) {
    // Stringify the entire properties object to ignore whatever weird column name WPC used
    const propStr = JSON.stringify(feature.properties).toUpperCase();
    let lineColor = "#ff00ff"; // Fallback Fuchsia
    
    if (propStr.includes("POSSIBLE")) lineColor = "#0000FF"; // Blue
    if (propStr.includes("LIKELY")) lineColor = "#800080";   // Purple
    
    return { color: lineColor, weight: 3, dashArray: "5, 5", fillOpacity: 0.1 };
}

const mpdLayer = L.geoJSON(null, {
    style: getMpdStyle,
    onEachFeature: function (feature, layer) {
        const props = feature.properties;
        const issueRaw = props.ISSUE || "Unknown";
        const expireRaw = props.EXPIRE || "Unknown";
        
        // Bulletproof Tag Extraction
        const propStr = JSON.stringify(props).toUpperCase();
        let displayTag = "See WPC for details";
        
        if (propStr.includes("FLASH FLOODING POSSIBLE")) {
            displayTag = "Flash Flooding Possible";
        } else if (propStr.includes("FLASH FLOODING LIKELY")) {
            displayTag = "Flash Flooding Likely";
        } else if (props.TAG || props.SUBJECT) {
            let rawTag = props.TAG || props.SUBJECT;
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
