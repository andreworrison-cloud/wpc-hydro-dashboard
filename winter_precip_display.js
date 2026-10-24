/* Optional winter supplement: failures disable this mode, never baseline RALA. */
(function (root) {
    'use strict';
    const expected = ['Rain', 'Mix', 'Snow', 'Ice (sleet/freezing rain)'];
    function available(manifest) {
        const supplement = manifest?.winter_type;
        return supplement?.revision === 'mrms-hrrr-winter-v1'
            && supplement.experimental === true
            && Array.isArray(supplement.classes)
            && supplement.classes.length === 4
            && supplement.classes.every((c, i) => c.id === i + 1 && c.label === expected[i] && /^#[0-9a-f]{6}$/i.test(c.color))
            && Array.isArray(manifest.frames) && manifest.frames.length > 0
            && manifest.frames.every(f => /^winter_frames\/winter_\d{8}T\d{6}Z\.png$/.test(f.ptype_png || '') && validFrame(f));
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
        if (!validFrame(frame) || !/^winter_frames\/winter_\d{8}T\d{6}Z\.png$/.test(frame.ptype_png || '')) throw new Error('Winter type frame unavailable');
        return frame.ptype_png;
    }
    function legend(manifest) {
        if (!available(manifest)) return '';
        const rows = manifest.winter_type.classes.map(c => `<div style="display:flex;align-items:center;gap:7px;margin:5px 0;"><span style="width:24px;height:12px;background:${c.color};border:1px solid #888;"></span><span>${c.label}</span></div>`).join('');
        return `<div style="background:white;padding:10px;border-radius:5px;color:#17202a;font:12px/1.4 sans-serif;"><strong>Radar Precipitation Type</strong><div>Experimental • MRMS + HRRR</div>${rows}<div style="font-size:10px;margin-top:7px;">Shading indicates echo strength.<br>MRMS radar ~1 km; HRRR type ~3 km.<br>MRMS rain/snow fallback where HRRR has no type.</div></div>`;
    }
    root.WinterPrecipDisplay = {available, validFrame, path, legend};
    if (typeof module !== 'undefined') module.exports = root.WinterPrecipDisplay;
})(typeof window !== 'undefined' ? window : globalThis);
