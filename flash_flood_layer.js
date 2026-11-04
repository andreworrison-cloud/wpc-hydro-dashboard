/* RRFS and HRRR/RRFS V3.3 suites; existing HRRR definitions supply the menu. */
(function (root) {
    'use strict';
    const SCHEMA = 'wpc-flash-flood-suite-v1';
    const EMPTY = 'data:image/gif;base64,R0lGODlhAQABAAD/ACwAAAAAAQABAAACADs=';
    const COLORS = ['#fff59d', '#ffcc80', '#ff8a65', '#ef5350', '#ab47bc', '#5e35b1'];
    const GROUP_COLORS = ['#ffcc80', '#ef5350', '#5e35b1'];

    function create(options) {
        const {L, suite, label, diagnosticConfigs, tleConfigs, isActive,
            formatTime, legacyLegend, legendShell, legendRows, preload, changed} = options;
        const count = suite === 'rrfs' ? 6 : 12;
        const prefix = suite.replace(/_/g, '-');
        const diagnostic = diagnosticConfigs.map(c => makeConfig(c, true));
        const tle = tleConfigs.map(c => makeConfig(c, false));
        const configs = [...diagnostic, ...tle];
        const byName = new Map(configs.map(c => [c.label, c]));
        const timeBoxIds = [`${prefix}-diagnostics-time-box`, `${prefix}-tle-time-box`];
        let metadata = null, version = '', inFlight = false, error = '';

        function makeConfig(base, diag) {
            let text = base.label.replace(/HRRR/g, label);
            if (count === 12 && ['prior3', 'latest3'].includes(base.key)) {
                text = `${base.key === 'prior3' ? 'Prior' : 'Latest'} 3 Cycles per Model`;
            } else if (['prior3', 'latest3'].includes(base.key)) {
                text = `${base.key === 'prior3' ? 'Prior' : 'Latest'} 3 Cycles`;
            }
            return {...base, diagnostic: diag, id: base.id.replace(/^hrrr/, prefix),
                label: `${label} · ${text}`, keywords: `${label} ${base.keywords}`,
                file: base.file.replace(/^hrrr_/, `${suite}_`),
                layer: L.imageOverlay(EMPTY, [[23, -125], [50.5, -66.5]],
                    {zIndex: 13, opacity: 0, interactive: false})};
        }

        function validate(manifest, meta) {
            if (manifest?.schema !== SCHEMA || meta?.schema !== SCHEMA ||
                manifest.suite !== suite || meta.suite !== suite || meta.complete !== true ||
                meta.algorithm_version !== '3.3' || meta.members_available !== count ||
                meta.generated_utc !== manifest.generated_utc ||
                meta.latest_cycle_utc !== manifest.latest_cycle_utc ||
                meta.diagnostic_cycle_utc !== manifest.diagnostic_cycle_utc ||
                !Array.isArray(meta.bounds) || meta.bounds.length !== 2 ||
                !meta.bounds.every(p => Array.isArray(p) && p.length === 2 && p.every(Number.isFinite)) ||
                !meta.layers || Object.keys(meta.layers).length !== 20 ||
                !configs.every(c => meta.layers[c.key]?.file === c.file && /^[a-f0-9]{64}$/.test(meta.layers[c.key]?.sha256))) {
                throw new Error('Incomplete or mixed flash-flood package');
            }
            for (const key of ['common_valid_start_utc', 'common_valid_end_utc', 'diagnostic_valid_start_utc', 'diagnostic_valid_end_utc']) {
                if (!Number.isFinite(Date.parse(meta[key])) || meta[key] !== manifest[key]) throw new Error('Invalid flash-flood valid interval');
            }
            if (Date.parse(meta.common_valid_end_utc)-Date.parse(meta.common_valid_start_utc) !== 12*3600000 ||
                Date.parse(meta.diagnostic_valid_end_utc)-Date.parse(meta.diagnostic_valid_start_utc) !== 12*3600000) throw new Error('Expected 12-hour windows');
            return meta;
        }

        function expired(c, now = Date.now()) {
            return !metadata || now >= Date.parse(c.diagnostic ? metadata.diagnostic_valid_end_utc : metadata.common_valid_end_utc);
        }

        function activeConfigs() { return configs.filter(c => isActive(c.label)); }

        function syncTimeBoxes() {
            configs.forEach(c => {
                if (expired(c)) {
                    const requestedOpacity=Number(c.layer.options.opacity);
                    if (!metadata && requestedOpacity>0) c.retainedOpacity=requestedOpacity;
                    else if (!c.hiddenForExpiry) c.retainedOpacity = metadata ? requestedOpacity : 1;
                    c.hiddenForExpiry = true;
                    c.layer.setOpacity(0);
                }
            });
            [diagnostic, tle].forEach((group, i) => {
                const box = document.getElementById(timeBoxIds[i]);
                if (!box) return;
                const active = group.filter(c => isActive(c.label));
                box.style.display = active.length ? 'block' : 'none';
                if (!active.length) return;
                const c = active[active.length-1];
                if (!metadata) {
                    box.innerHTML = `<strong>${label} ${i ? 'TLE Guidance' : 'Diagnostics'}</strong><br><span style="color:#ffeb3b">${error ? 'Complete package unavailable; awaiting the next hourly update.' : 'Loading newest complete package…'}</span>`;
                    return;
                }
                const start = new Date(c.diagnostic ? metadata.diagnostic_valid_start_utc : metadata.common_valid_start_utc);
                const end = new Date(c.diagnostic ? metadata.diagnostic_valid_end_utc : metadata.common_valid_end_utc);
                if (c.evolutionHours) {
                    end.setTime(start.getTime()+c.evolutionHours[1]*3600000);
                    start.setTime(start.getTime()+c.evolutionHours[0]*3600000);
                }
                const ffg = c.diagnostic ? metadata.diagnostic_ffg_analysis_utc : metadata.ffg_analysis_utc;
                const support = c.diagnostic ? (count === 12 ? '50% HRRR + 50% RRFS hourly QPF' : 'Latest RRFS f01–f12') :
                    (count === 12 ? '12/12 members · 6 HRRR + 6 RRFS cycles' : '6/6 RRFS cycles');
                const age = (Date.now()-Date.parse(c.diagnostic ? metadata.diagnostic_cycle_utc : metadata.latest_cycle_utc))/3600000;
                box.innerHTML = `<strong>${c.label}</strong><br>
                    <span style="color:#4fc3f7;font-weight:bold">Anchor: ${formatTime(c.diagnostic ? metadata.diagnostic_cycle_utc : metadata.latest_cycle_utc)}</span><br>
                    <span style="color:#ffeb3b">Valid: ${formatTime(start.toISOString())} — ${formatTime(end.toISOString())}</span><br>
                    <span style="font-size:.82em;color:#d0d0d0">${support} | FFG: ${formatTime(ffg)} | 40 km neighborhood</span>
                    ${expired(c) ? '<br><span style="color:#ffb74d">Expired package hidden; awaiting complete guidance.</span>' : age > 4 ? '<br><span style="color:#ffb74d">Retaining latest complete guidance; newer cycle pending.</span>' : ''}`;
            });
        }

        async function refresh({force = false} = {}) {
            syncTimeBoxes();
            if (inFlight) return false;
            inFlight = true;
            try {
                const response = await fetch(`static/${suite}_tle_manifest.json?t=${Date.now()}`, {cache: 'no-store'});
                if (!response.ok) throw new Error(`HTTP ${response.status}`);
                const manifest = await response.json();
                if (!force && version === manifest.generated_utc) return false;
                const data = await fetch(`static/${suite}_tle_metadata.json?t=${Date.now()}`, {cache: 'no-store'});
                if (!data.ok) throw new Error(`HTTP ${data.status}`);
                const meta = validate(manifest, await data.json());
                const url = c => `static/${c.file}?v=${encodeURIComponent(meta.generated_utc)}`;
                // Only active overlays need decoding in the browser. All 20 were
                // verified together by the producer before snapshot publication.
                await Promise.all(activeConfigs().map(c => preload(url(c))));
                const previouslyReady = !!metadata;
                const opacities = configs.map(c => !previouslyReady && Number(c.layer.options.opacity)>0 ? Number(c.layer.options.opacity) : c.hiddenForExpiry ? c.retainedOpacity : previouslyReady ? Number(c.layer.options.opacity) : 1);
                metadata = meta;
                configs.forEach((c, i) => {
                    c.layer.setBounds(meta.bounds);
                    c.layer.setUrl(url(c));
                    const opacity = Number.isFinite(opacities[i]) ? opacities[i] : 1;
                    c.retainedOpacity = opacity;
                    c.hiddenForExpiry = expired(c);
                    c.layer.setOpacity(c.hiddenForExpiry ? 0 : opacity);
                });
                version = meta.generated_utc;
                error = '';
                syncTimeBoxes();
                changed();
                return true;
            } catch (e) {
                error = String(e);
                syncTimeBoxes();
                return false;
            } finally { inFlight = false; }
        }

        function legend(c) {
            if (c.diagnostic || c.legendType === 'ratio' || count === 6) {
                const sentinel = '__SUITE_TITLE__';
                let html = legacyLegend({...c, label: sentinel}).replace(/HRRR/g, label).replace(sentinel, c.label);
                if (c.diagnostic && c.legendType === 'ratio') html = html.replace('Median of member 40-km neighborhood-maximum QPF / FFG ratios', 'Maximum 40-km neighborhood QPF / FFG ratio; 1/3/6-h durations');
                if (c.diagnostic && count === 12) html = html.replace('Latest deterministic HRRR/RRFS, next 12 hours', '50/50 HRRR/RRFS hourly rainfall blend, next 12 hours');
                return html;
            }
            if (c.legendType === 'runChange') {
                return legendShell(c.label, 'Latest 3 cycles per model versus prior 3 per model; signal ≥4/6 members',
                    legendRows([{label:'Fading',color:'#4575b4'}, {label:'Persistent',color:'#7b3294'}, {label:'Emerging',color:'#fdae61'}],3),
                    'Each group contains 3 HRRR and 3 RRFS cycles.');
            }
            const n = c.legendType === 'frequency3' ? 6 : 12;
            const colors = n === 6 ? GROUP_COLORS : COLORS;
            const minimum = c.legendType === 'frequency6Min2' ? 4 : 1;
            const rows = colors.map((color, i) => ({color, low: 2*i+1, high: 2*i+2})).filter(r => r.high >= minimum).map(r => {
                const low = Math.max(r.low, minimum), high = r.high;
                const percent = low === high ? Math.round(100*low/n) : `${Math.round(100*low/n)}–${Math.round(100*high/n)}`;
                return {color:r.color, label:`${low === high ? low : `${low}–${high}`}/${n} (${percent}%)`};
            });
            return legendShell(c.label, n === 12 ? 'Equal model weight · 6 HRRR + 6 RRFS aligned hourly cycles' : '3 HRRR + 3 RRFS cycles in this group',
                legendRows(rows, 3), 'Member frequency / consensus; NOT calibrated probability.' + (minimum === 4 ? ' Evolution display requires ≥4/12 support.' : ''));
        }

        function entries(items) {
            return items.map(c => ({id:c.id, label:c.label, layer:c.layer, kind:'raster', keywords:c.keywords}));
        }
        const sections = [
            {id:`${prefix}-diagnostics`, title:`${label} Flash Flood Diagnostics - Experimental`, layers:entries(diagnostic)},
            {id:`${prefix}-tle`, title:`${label}-TLE Flash Flood Guidance - Experimental`, layers:[],
                groups:['Core FFG Guidance','Heavy Rain / Persistence','Timing / Evolution'].map((title, i) => ({
                    id:`${prefix}-tle-group-${i}`, title, openByDefault:i === 0,
                    layers:entries(tle.filter(c => c.group === title))}))}
        ];
        return {configs, sections, timeBoxIds, activeConfigs, refresh, syncTimeBoxes, legend, validate,
            getMetadata: () => metadata,
            onLayerChange(name, added) {
                if (!byName.has(name)) return;
                syncTimeBoxes();
                if (added) refresh({force:!metadata});
            }};
    }
    root.WPCFlashFlood = {create};
    if (typeof module !== 'undefined') module.exports = root.WPCFlashFlood;
})(typeof window !== 'undefined' ? window : globalThis);
