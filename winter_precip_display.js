/* Optional winter supplement: failures disable this mode, never baseline RALA. */
(function (root) {
    'use strict';
    const expected = ['Rain', 'Mix', 'Snow', 'Ice (sleet/freezing rain)'];
    function available(manifest) {
        const supplement = manifest?.winter_type;
        return ['mrms-hrrr-winter-v1','mrms-hrrr-winter-v2'].includes(supplement?.revision)
            && supplement.experimental === true
            && (supplement.revision === 'mrms-hrrr-winter-v1' || palette(manifest) !== null)
            && Array.isArray(supplement.classes)
            && supplement.classes.length === 4
            && supplement.classes.every((c, i) => c.id === i + 1 && c.label === expected[i] && /^#[0-9a-f]{6}$/i.test(c.color))
            && Array.isArray(manifest.frames) && manifest.frames.length > 0
            && manifest.frames.every(f => /^winter_frames(?:_v2)?\/winter_\d{8}T\d{6}Z\.png$/.test(f.ptype_png || '') && validFrame(f));
    }
    function validFrame(frame) {
        const radar = Date.parse(frame.valid_time_utc), p = frame.ptype;
        const flag = Date.parse(p?.flag_valid_time_utc);
        if (!Number.isFinite(radar) || !Number.isFinite(flag) || Math.abs(radar - flag) > 120000) return false;
        if (p.hrrr) {
            const valid = Date.parse(p.hrrr.valid_time_utc), cycle = Date.parse(p.hrrr.cycle_utc);
            if (!Number.isFinite(valid) || !Number.isFinite(cycle) || valid > radar || radar - valid > 5400000
                || p.hrrr.forecast_hour !== 1 || valid - cycle !== 3600000) return false;
        }
        return true;
    }
    function path(frame, mode) {
        if (mode !== 'ptype') return frame.png;
        if (!validFrame(frame) || !/^winter_frames(?:_v2)?\/winter_\d{8}T\d{6}Z\.png$/.test(frame.ptype_png || '')) throw new Error('Winter type frame unavailable');
        return frame.ptype_png;
    }
    function palette(manifest) {
        const info = manifest?.winter_type?.intensity;
        if (info?.units === 'dBZ' && info.thresholds_dbz?.length === 15
            && info.thresholds_dbz.every((v,i) => v === 5+i*5)
            && [1,2,3,4].every(c => info.colors?.[c]?.length === 15 && info.colors[c].every(v => /^#[0-9a-f]{6}$/i.test(v)))) return info;
        // Previous frames retain their actual original brightness ramp until
        // the first complete v2 archive arrives; never mislabel old colors.
        if (manifest?.winter_type?.revision !== 'mrms-hrrr-winter-v1') return null;
        const colors = {};
        for (const c of manifest.winter_type.classes) {
            const rgb = [1,3,5].map(i => parseInt(c.color.slice(i,i+2),16));
            colors[c.id] = Array.from({length:15},(_,i) => '#'+rgb.map(v => Math.floor(v*(.55+.45*Math.min(i/9,1))).toString(16).padStart(2,'0')).join(''));
        }
        return {units:'dBZ',thresholds_dbz:Array.from({length:15},(_,i)=>5+i*5),colors};
    }
    function legend(manifest) {
        if (!available(manifest)) return '';
        const scale = palette(manifest);
        if (!scale) return '<div>Precipitation-type intensity scale unavailable</div>';
        const rows = manifest.winter_type.classes.map(c => `<div style="margin:7px 0;"><strong>${c.label}</strong><div style="display:grid;grid-template-columns:repeat(15,1fr);height:14px;border:1px solid #888;">${scale.colors[c.id].map((color,i) => `<span style="background:${color};" title="${scale.thresholds_dbz[i]}${i===14?'+':' to <'+scale.thresholds_dbz[i+1]} dBZ"></span>`).join('')}</div></div>`).join('');
        const ticks = [0,3,6,9,12,14].map(i => `<span style="grid-column:${i+1};font-size:9px;">${scale.thresholds_dbz[i]}${i===14?'+':''}</span>`).join('');
        return `<div style="background:white;padding:10px;border-radius:5px;color:#17202a;font:12px/1.4 sans-serif;"><strong>Radar Precipitation Type &amp; Intensity</strong><div>Experimental • MRMS + HRRR</div>${rows}<div style="display:grid;grid-template-columns:repeat(15,1fr);">${ticks}</div><div style="font-size:10px;text-align:center;">Radar reflectivity (dBZ)</div><div style="font-size:10px;margin-top:7px;">Echo strength, not snow/ice accumulation rate.<br>MRMS radar ~1 km; HRRR type ~3 km.<br>MRMS rain/snow fallback where HRRR has no type.</div></div>`;
    }
    root.WinterPrecipDisplay = {available, validFrame, path, palette, legend};
    if (typeof module !== 'undefined') module.exports = root.WinterPrecipDisplay;
})(typeof window !== 'undefined' ? window : globalThis);
