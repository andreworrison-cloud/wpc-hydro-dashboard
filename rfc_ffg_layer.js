/* RFC guidance adapter: immutable, hash-verified images; all durations swap together. */
window.createRFCFFGLayers = function ({map, metadataURL, onChange = () => {}, now = () => Date.now()}) {
    const hours = [1, 3, 6], layers = {}, images = {};
    let metadata = null, loadedGeneration = null, busy = false, failed = false, objectURLs = [], borders = null;
    map.createPane('rfcFFG'); map.getPane('rfcFFG').style.zIndex = 340;
    hours.forEach(h => {
        const group = L.layerGroup(); group.options.opacity = 1;
        group.setOpacity = value => {group.options.opacity = value; group.eachLayer(l => l.setOpacity(value));};
        layers[h] = group;
    });
    const utc = value => Number.isFinite(Date.parse(value)) ? new Date(value).toISOString().replace('T', ' ').replace(/\.\d{3}Z$/, 'Z') : 'Unavailable';
    const esc = value => String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    function state() {
        const m = failed && metadata ? {...metadata, stale:true, last_attempt:{...metadata.last_attempt,ok:false}} : metadata;
        return ffgDisplayState(m, now());
    }
    function selected() { return hours.filter(h => map.hasLayer(layers[h])); }
    function sync() {
        const s = state();
        hours.forEach(h => {
            if (s.visible && images[h] && !layers[h].hasLayer(images[h])) layers[h].addLayer(images[h]);
            if (!s.visible) layers[h].clearLayers();
        });
        if (borders) {
            if (selected().length && !map.hasLayer(borders)) borders.addTo(map);
            if (!selected().length && map.hasLayer(borders)) map.removeLayer(borders);
        }
        onChange();
    }
    function validate(m) {
        if (m?.schema_version !== 1 || !m.policy) throw Error('Invalid FFG metadata');
        // Accepted application policy cannot be silently relaxed by a producer.
        if (m.policy.max_snapshot_age_hours !== 3 || m.policy.max_reference_age_hours !== 9) throw Error('FFG freshness policy mismatch');
        if (!m.active) return;
        const a=m.active, l=a.legend;
        if (ffgDisplayState(m,now()).state === 'unavailable' || Date.parse(a.reference_time)>Date.parse(a.snapshot_time)) throw Error('Invalid FFG time contract');
        if (l?.crs !== 'EPSG:3857' || JSON.stringify(l.bounds_wsen)!=='[-126,24,-66,50]' || l.units!=='inches' || l.resampling!=='nearest') throw Error('Invalid FFG projection');
        if (!Array.isArray(l.class_upper_edges) || !Array.isArray(l.colors_rgb) || l.colors_rgb.length!==l.class_upper_edges.length+1 || !l.class_upper_edges.every((v,i,x)=>Number.isFinite(v)&&v>0&&(!i||v>x[i-1])) || !l.colors_rgb.every(c=>Array.isArray(c)&&c.length===3&&c.every(v=>Number.isInteger(v)&&v>=0&&v<=255))) throw Error('Invalid FFG legend');
        if (!a.generation || !hours.every(h => a.assets?.[h]?.duration_hours===h && /^[a-f0-9]{64}$/.test(a.assets[h].sha256) && a.assets[h].path.startsWith(`generations/${a.generation}/`) && !a.assets[h].path.includes('..'))) throw Error('Invalid FFG asset contract');
        if (metadata?.active?.generation === a.generation && ['assets','legend','snapshot_time','reference_time','source_sha256'].some(key=>JSON.stringify(metadata.active[key])!==JSON.stringify(a[key]))) throw Error('Immutable FFG generation changed');
        if (metadata?.active && (Date.parse(a.snapshot_time)<Date.parse(metadata.active.snapshot_time) || Date.parse(a.reference_time)<Date.parse(metadata.active.reference_time))) throw Error('Regressing FFG product');
    }
    async function refresh() {
        if (busy) return; busy=true;
        const controller=new AbortController(), timeout=setTimeout(()=>controller.abort(),30000), staged=[];
        try {
            const url=new URL(metadataURL,document.baseURI); url.searchParams.set('_check',String(now()));
            const response=await fetch(url,{cache:'no-store',signal:controller.signal});
            if (!response.ok) throw Error('FFG metadata unavailable');
            const next=await response.json();validate(next);
            if (next.active && ffgDisplayState(next,now()).visible && next.active.generation!==loadedGeneration) {
                // Wait for every download, hash, and decode before changing anything on the map.
                const results=await Promise.allSettled(hours.map(async h => {
                    const asset=next.active.assets[h], assetURL=new URL(asset.path,new URL('.',url));
                    const r=await fetch(assetURL,{signal:controller.signal});if(!r.ok)throw Error('FFG image unavailable');
                    const data=await r.arrayBuffer(), hash=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',data)),v=>v.toString(16).padStart(2,'0')).join('');
                    if(hash!==asset.sha256)throw Error('FFG image checksum mismatch');
                    const blobURL=URL.createObjectURL(new Blob([data],{type:'image/png'}));staged.push(blobURL);
                    const decoded=new Image();decoded.src=blobURL;await decoded.decode();
                    if(decoded.naturalWidth!==3000||decoded.naturalHeight!==1650)throw Error('Invalid FFG image dimensions');
                    return [h,L.imageOverlay(blobURL,[[24,-126],[50,-66]],{pane:'rfcFFG',opacity:layers[h].options.opacity,interactive:false,className:'rfc-ffg-raster'})];
                }));
                const error=results.find(r=>r.status==='rejected');if(error)throw error.reason;
                hours.forEach(h=>layers[h].clearLayers());
                results.forEach(r=>{images[r.value[0]]=r.value[1];});
                loadedGeneration=next.active.generation;
                const old=objectURLs;objectURLs=staged.splice(0);old.forEach(u=>URL.revokeObjectURL(u));
            }
            // An unavailable upstream pointer must not discard a still-valid local generation.
            if (!next.active && metadata?.active) {failed=true;} else {metadata=next;failed=false;}
        } catch(error) {failed=true;console.warn('RFC FFG refresh retained prior validated product:',error.message);}
        finally {staged.forEach(u=>URL.revokeObjectURL(u));clearTimeout(timeout);busy=false;sync();}
    }
    function legendHTML() {
        const active=selected();if(!active.length)return '';
        const s=state(),a=metadata?.active;
        let html=`<div class="rfc-ffg-card"><strong>RFC ${active.join(' / ')}-hour Flash Flood Guidance</strong><div class="rfc-ffg-status ${s.state}">${esc(s.label)}</div>`;
        if(a){const l=a.legend,e=l.class_upper_edges;
            html+='<strong>Rainfall threshold · inches</strong>';
            l.colors_rgb.forEach((c,i)=>{const label=i===0?`< ${e[0]}`:i===e.length?`≥ ${e[i-1]}`:`${e[i-1]} to < ${e[i]}`;html+=`<div><i class="rfc-ffg-swatch" style="background:rgb(${c.join(',')})"></i>${esc(label)}</div>`;});
            html+=`<p>NoData is transparent; it does not mean no flood threat. Colors represent rainfall thresholds, not risk categories.</p><div>Snapshot: ${esc(utc(a.snapshot_time))}<br>Reference cycle: ${esc(utc(a.reference_time))}<br>File modified: ${esc(utc(a.http_modified_time))}<br>Last source check: ${esc(utc(metadata.last_attempt?.at))}<br>Freshness cutoff: ${esc(s.expires ? utc(new Date(s.expires).toISOString()) : 'Unavailable')}</div><p>Individual RFC issue times unavailable. Nominal 5-km source; display resampling adds no detail.</p>`;
        }
        return html+'</div>';
    }
    function setBorders(geojson) {
        if(borders&&map.hasLayer(borders))map.removeLayer(borders);
        borders=L.layerGroup([
            L.geoJSON(geojson,{pane:'mapReference',interactive:false,style:{color:'#101820',weight:2.6,opacity:.85,fill:false}}),
            L.geoJSON(geojson,{pane:'mapReference',interactive:false,style:{color:'#fff',weight:1,opacity:.9,fill:false}})
        ]);sync();
    }
    map.on('layeradd layerremove',e=>{if(hours.some(h=>layers[h]===e.layer))sync();});
    const timer=setInterval(sync,30000),poll=setInterval(refresh,300000);
    // Initial refresh runs after the dashboard's synchronous initialization.
    setTimeout(refresh,0);
    return {layers,refresh,legendHTML,setBorders,getState:state,getMetadata:()=>metadata,sync,stop:()=>{clearInterval(timer);clearInterval(poll);}};
};
