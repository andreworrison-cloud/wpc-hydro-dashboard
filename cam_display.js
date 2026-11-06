/* Shared presentation contract for the SPC/OMD CAM transition. */
(function (root) {
    'use strict';
    const SCHEMA = 'wpc-spc-omd-cam-v3';
    const models = ['spc_refs', 'omd_refs', 'super'];
    const labels = {spc_refs: 'SPC REFS (Experimental)', omd_refs: 'OMD REFS', super: 'SuperEnsemble (50/50)'};
    const colors = {
        qpf: ['#ffffcc', '#a1dab4', '#41b6c4', '#2c7fb8', '#253494'],
        ffg: ['#ffffb2', '#fecc5c', '#fd8d3c', '#f03b20', '#bd0026']
    };
    function date(value) {
        const d = new Date(value || '');
        return Number.isFinite(d.getTime()) ? d : null;
    }
    function utc(value) {
        const d = date(value);
        if (!d) return 'Unavailable';
        const month = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'][d.getUTCMonth()];
        return `${String(d.getUTCDate()).padStart(2, '0')} ${month} ${String(d.getUTCHours()).padStart(2, '0')}Z`;
    }
    function modelFromKey(key) {
        return models.find(model => key.endsWith('_' + model)) || null;
    }
    function modelFromName(name) {
        if (name.includes('SuperEnsemble')) return 'super';
        if (name.includes('SPC REFS')) return 'spc_refs';
        if (name.includes('OMD REFS')) return 'omd_refs';
        return null;
    }
    function validate(meta, kind) {
        if (!meta || meta.schema !== SCHEMA) throw new Error('Awaiting verified SPC/OMD CAM package');
        const spc = date(meta.spc_refs_init_utc), omd = date(meta.omd_refs_init_utc);
        if (!spc || !omd || spc.getTime() !== omd.getTime()) throw new Error('SPC/OMD cycles are not aligned');
        if (meta.method?.probability_method !== 'emc-neighborhood-qpf-local-ffg-gaussian-v1') throw new Error('Awaiting producer-consistent SPC probability processing');
        const ffg = meta.ffg || {};
        for (const value of [ffg.snapshot_time_utc, ffg.reference_time_utc, ffg.model_cycle_utc, meta.common_ffg_reference_utc]) {
            const reference = date(value);
            if (!reference || reference.getTime() !== spc.getTime()) throw new Error('Awaiting the same official model-cycle RFC FFG for SPC and OMD');
        }
        if (ffg.ffg_cycle_policy !== 'official_synoptic_model_cycle') throw new Error('Official cycle-matched RFC FFG is required');
        const keys = kind === 'ero' ? ['ero'] : ['3h_to_9h', '9h_to_15h'];
        if (meta.spc_member_count !== 10) throw new Error('SPC member population is incomplete');
        for (const key of keys) {
            const w = meta.window_contract?.[key];
            const a = date(w?.valid_start_utc), b = date(w?.valid_end_utc);
            if (!a || !b || a >= b) throw new Error('CAM valid window is unavailable');
        }
        return meta;
    }
    function state(meta, kind, key, now = new Date()) {
        try { validate(meta, kind); } catch (error) { return {available: false, reason: error.message}; }
        const windowKey = kind === 'ero' ? 'ero' : (key.includes('9h_to_15h') ? '9h_to_15h' : '3h_to_9h');
        const w = meta.window_contract[windowKey];
        if (now >= date(w.valid_end_utc)) return {available: false, reason: 'This forecast window has expired', window: w};
        return {available: true, window: w};
    }
    function timeHTML(meta, kind, key, name, now = new Date()) {
        const model = modelFromKey(key) || modelFromName(name);
        const info = state(meta, kind, key, now);
        const title = (labels[model] || 'CAM guidance') + (kind === 'ero' ? ' · Day 1 ERO' : '');
        if (!info.available) return `<strong>${title}</strong><br><span style="color:#ffeb3b;">${info.reason}</span>`;
        const init = utc(meta.spc_refs_init_utc);
        const field = name.split(':').slice(1).join(':').trim() || 'Probabilistic guidance';
        const ffg = name.includes('FFG')
            ? `<br><span style="font-size:.85em;">Common official RFC FFG: ${utc(meta.common_ffg_reference_utc)}</span>` : '';
        return `<strong>${title}</strong><br><span style="color:#4fc3f7;font-weight:bold;">${field}</span><br>` +
            `<span style="font-size:.9em;">Initialization: ${init}</span><hr style="margin:5px 0;border-color:#555;">` +
            `<span style="color:#ffeb3b;">Valid: ${utc(info.window.valid_start_utc)} – ${utc(info.window.valid_end_utc)}</span>${ffg}`;
    }
    function legend(ffg, activeNames) {
        const names = [...new Set(activeNames.map(modelFromName).filter(Boolean))].map(model => labels[model]);
        const palette = colors[ffg ? 'ffg' : 'qpf'];
        const ticks = ['10', '30', '50', '70', '90+'];
        const boxes = palette.map((color, i) => `<div style="background:${color};flex:1;padding:2px 5px;${i > 2 ? 'color:white;' : ''}">${ticks[i]}</div>`).join('');
        return `<div style="background:white;padding:10px;border-radius:5px;font-family:sans-serif;text-align:center;color:black;font-size:13px;max-width:280px;">` +
            `<strong>${names.join(' / ')}</strong><br>${ffg ? 'Max FFG Exceedance' : 'Max Hourly QPF'} Probability (%)` +
            `<div style="display:flex;margin-top:5px;border:1px solid #333;">${boxes}</div>` +
            `<div style="font-size:11px;margin-top:5px;">Nominal 40-km QPF neighborhood · smoothed probabilities · peak in the stated window${ffg ? '<br>Neighborhood-maximum QPF vs local 1-, 3- and 6-hour FFG<br>Same official model-cycle RFC FFG for SPC and OMD' : ''}<br>Below 10% or unavailable: transparent.</div>` +
            (names.some(n => n.includes('SuperEnsemble')) ? '<div style="font-size:11px;margin-top:4px;">50% SPC maximum + 50% OMD maximum; configurations share members. Suite peaks can occur at different times.</div>' : '') + '</div>';
    }
    root.WPC_CAM = {SCHEMA, models, labels, colors, date, utc, modelFromKey, modelFromName, validate, state, timeHTML, legend};
    if (typeof module !== 'undefined' && module.exports) module.exports = root.WPC_CAM;
})(typeof window === 'undefined' ? globalThis : window);

