/* Hourly RTMA scalar fills and actual, independently timed METAR point values. */
(function (root) {
    'use strict';
    const keys = ['temperature', 'dewpoint', 'wind_speed'];
    const bounds = [[24, -125], [50, -66]];
    const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[c]));
    const utc = value => Number.isFinite(Date.parse(value)) ? new Date(value).toISOString().replace('T', ' ').replace(/\.\d{3}Z$/, 'Z') : 'Unavailable';
    const names = {temperature:'Temperature', dewpoint:'Dewpoint', wind_speed:'Wind speed'};
    function state(analysis, now = Date.now(), failed = false) {
        const age = (now - Date.parse(analysis?.valid_time)) / 60000;
        if (!Number.isFinite(age)) return {visible:false, label:'Waiting for a validated hourly analysis'};
        if (age < 0) return {visible:false, label:'Hidden — future analysis time'};
        if (age >= 240) return {visible:false, label:'Expired — analysis hidden at 4 hours'};
        return {visible:true, age, label:`${failed?'Retained previous analysis · ':''}${age >= 150?'Aging analysis · ':''}${Math.round(age)} min old`};
    }
    function validate(m, previous) {
        if (m?.schema !== 'surface-suite-v1' || m.policy?.analysis_warn_minutes !== 150 || m.policy?.analysis_hide_minutes !== 240 || m.policy?.station_hide_minutes !== 90) throw Error('Invalid surface suite policy');
        const a = m.analysis;
        if (a) {
            if (a.revision !== 'rtma-surface-v1' || a.crs !== 'EPSG:3857' || a.width !== 3600 || a.height !== 2024 || a.native_spacing_km !== 2.5 || JSON.stringify(a.bounds) !== JSON.stringify(bounds) || !Number.isFinite(Date.parse(a.valid_time)) || !/^\d{10}-[a-f0-9]{16}$/.test(a.generation)) throw Error('Invalid RTMA display grid/time');
            if (Object.keys(a.products || {}).sort().join() !== [...keys].sort().join()) throw Error('Incomplete RTMA surface suite');
            keys.forEach(key => {
                const p = a.products[key];
                if (p.path !== `generations/${a.generation}/${key}.png` || !/^[a-f0-9]{64}$/.test(p.sha256) || p.unit !== (key === 'wind_speed' ? 'kt' : '°F')) throw Error('Invalid RTMA asset');
                if (!Array.isArray(p.stops) || p.stops.length !== p.colors?.length || p.stops.length < 3 || !p.stops.every((v,i)=>Number.isFinite(v) && (!i || v > p.stops[i-1])) || !p.colors.every(c=>/^#[a-f0-9]{6}$/i.test(c)) || !p.ticks?.every(Number.isFinite)) throw Error('Invalid surface palette');
            });
            if (previous?.analysis && Date.parse(a.valid_time) < Date.parse(previous.analysis.valid_time)) throw Error('Regressing RTMA time');
            if (previous?.analysis?.generation === a.generation && JSON.stringify(previous.analysis) !== JSON.stringify(a)) throw Error('Immutable RTMA generation changed');
        }
        const o = m.observations;
        if (o && (!/^stations\/\d{14}-[a-f0-9]{16}\.json$/.test(o.path) || !/^[a-f0-9]{64}$/.test(o.sha256) || !Number.isInteger(o.count) || o.count < 500 || !Number.isFinite(Date.parse(o.fetched_at)))) throw Error('Invalid METAR asset');
        if (previous?.observations && o && Date.parse(o.fetched_at) < Date.parse(previous.observations.fetched_at)) throw Error('Regressing METAR retrieval time');
        if (!a && !o) throw Error('Empty surface suite');
    }
    function freshPoint(p, key, now = Date.now()) {
        const age = now - Date.parse(p?.time);
        return p && Number.isFinite(p[key]) && Number.isFinite(age) && age >= 0 && age <= 90*60000 && Number.isFinite(p.lat) && Number.isFinite(p.lon) && p.lat >= 24 && p.lat <= 50 && p.lon >= -125 && p.lon <= -66;
    }
    function thinPoints(points, key, now, project, contains) {
        const occupied = new Set(), result = [];
        points.filter(p=>freshPoint(p,key,now) && contains(p)).sort((a,b)=>Date.parse(b.time)-Date.parse(a.time) || a.id.localeCompare(b.id)).forEach(p=>{
            const pt=project(p), cell=`${Math.floor(pt.x/48)},${Math.floor(pt.y/30)}`;
            if (!occupied.has(cell) && result.length < 800) {occupied.add(cell);result.push(p);}
        });
        return result;
    }
    function color(p, value) {
        if (!p) return '#d9e2e7';
        let i = p.stops.findIndex(x=>x>=value);if(i<0)i=p.stops.length-1;if(!i)return p.colors[0];
        const f=Math.max(0,Math.min(1,(value-p.stops[i-1])/(p.stops[i]-p.stops[i-1])));
        const c=n=>[1,3,5].map(j=>parseInt(p.colors[n].slice(j,j+2),16));
        const lo=c(i-1),hi=c(i);return '#'+lo.map((v,j)=>Math.round(v+(hi[j]-v)*f).toString(16).padStart(2,'0')).join('');
    }
    function scale(p) {
        const lo=p.stops[0],hi=p.stops.at(-1),pos=v=>100*(v-lo)/(hi-lo);
        return `<div class="surface-scale" style="background:linear-gradient(to right,${p.colors.map((c,i)=>`${c} ${pos(p.stops[i])}%`).join(',')})"></div><div class="surface-scale-ticks">${p.ticks.map((v,i)=>`<span style="left:${pos(v)}%;transform:translateX(${i===0?'0':i===p.ticks.length-1?'-100':'-50'}%)">${i===0?'≤':i===p.ticks.length-1?'≥':''}${v}</span>`).join('')}</div>`;
    }
    function popup(p, now) {
        const fmt=(v,u)=>Number.isFinite(v)?`${Math.round(v)} ${u}`:'Unavailable';
        const direction=p.wind_speed===0?'Calm':Number.isFinite(p.wind_direction)?`${p.wind_direction}°`:'Variable / unavailable';
        return `<div class="surface-popup"><strong>${esc(p.id)} · METAR observation</strong><br>${esc(utc(p.time))} · ${Math.floor((now-Date.parse(p.time))/60000)} min old<br>Temperature: ${fmt(p.temperature,'°F')}<br>Dewpoint: ${fmt(p.dewpoint,'°F')}<br>Wind: ${fmt(p.wind_speed,'kt')} · ${direction}<br>Gust: ${fmt(p.wind_gust,'kt')}<p>${esc(p.raw)}</p></div>`;
    }
    function create({map, metadataURL, onChange=()=>{}, now=()=>Date.now()}) {
        const layers={}, cache=new Map(), urls=new Set();
        let metadata=null, points=[], pointHash=null, busy=false, serial=0, stationField='temperature', failed=false, stationFailed=false, border=null;
        map.createPane('surfaceAnalysis');map.getPane('surfaceAnalysis').style.zIndex=338;map.getPane('surfaceAnalysis').style.pointerEvents='none';
        map.createPane('surfaceStations');map.getPane('surfaceStations').style.zIndex=588;
        keys.forEach(key=>{const group=L.layerGroup();group.options.opacity=.85;group.setOpacity=value=>{group.options.opacity=value;group.eachLayer(layer=>layer.setOpacity(value));};layers[key]=group;});
        const stations=L.layerGroup();
        const selected=()=>keys.find(key=>map.hasLayer(layers[key]));
        const stationKey=()=>selected() || stationField;
        const active=()=>selected() || map.hasLayer(stations);
        const item=key=>cache.get(`${metadata?.analysis?.generation}/${key}`);
        const current=key=>Array.from(cache.values()).filter(v=>v.key===key).at(-1);
        function renderStations() {
            stations.clearLayers();
            if (!map.hasLayer(stations) || map.getZoom() < 7) return;
            const key=stationKey(), palette=metadata?.analysis?.products[key];
            const shown=thinPoints(points,key,now(),p=>map.latLngToContainerPoint([p.lat,p.lon]),p=>map.getBounds().contains([p.lat,p.lon]));
            shown.forEach(p=>{
                const icon=L.divIcon({className:'surface-station-icon',iconSize:[46,24],iconAnchor:[23,12],html:`<span class="surface-station-value"><i style="background:${color(palette,p[key])}"></i>${Math.round(p[key])}</span>`});
                L.marker([p.lat,p.lon],{pane:'surfaceStations',icon,keyboard:true,title:`${p.id}: ${Math.round(p[key])} ${key==='wind_speed'?'kt':'°F'}, ${utc(p.time)}`,riseOnHover:true}).bindPopup(popup(p,now())).addTo(stations);
            });
        }
        function sync() {
            const key=selected();
            keys.forEach(k=>{
                const entry=current(k), visible=k===key && entry && state(entry.analysis,now()).visible;
                layers[k].eachLayer(layer=>{if(!visible || layer!==entry.image)layers[k].removeLayer(layer);});
                if(visible && !layers[k].hasLayer(entry.image)){entry.image.setOpacity(layers[k].options.opacity);layers[k].addLayer(entry.image);}
            });
            if(border){const show=key && current(key) && state(current(key).analysis,now()).visible;if(show&&!map.hasLayer(border))border.addTo(map);if(!show&&map.hasLayer(border))map.removeLayer(border);}
            renderStations();onChange();
        }
        async function asset(p, controller) {
            const url=new URL(p.path,new URL('.',new URL(metadataURL,document.baseURI)));
            const r=await fetch(url,{signal:controller.signal});if(!r.ok)throw Error('Surface asset unavailable');
            const data=await r.arrayBuffer();
            const digest=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',data)),v=>v.toString(16).padStart(2,'0')).join('');
            if(digest!==p.sha256)throw Error('Surface asset checksum mismatch');return data;
        }
        async function loadSelected() {
            const token=++serial,key=selected(),a=metadata?.analysis,o=metadata?.observations;
            const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),45000);
            const work=[];
            if(key && a && state(a,now()).visible && !item(key)) work.push((async()=>{
                const data=await asset(a.products[key],controller);
                const url=URL.createObjectURL(new Blob([data],{type:'image/png'}));urls.add(url);
                const decoded=new Image();decoded.src=url;
                try {await decoded.decode();if(decoded.naturalWidth!==a.width||decoded.naturalHeight!==a.height)throw Error('Surface image dimensions mismatch');}
                catch(e){URL.revokeObjectURL(url);urls.delete(url);throw e;}
                if(token!==serial){URL.revokeObjectURL(url);urls.delete(url);return;}
                cache.set(`${a.generation}/${key}`,{key,analysis:a,url,image:L.imageOverlay(url,a.bounds,{pane:'surfaceAnalysis',opacity:layers[key].options.opacity,interactive:false,className:'surface-analysis-raster'})});
            })().catch(e=>{if(token===serial){failed=true;console.warn('Surface analysis retained validated image:',e.message);}}));
            if(map.hasLayer(stations) && o && pointHash!==o.sha256) work.push((async()=>{
                const data=await asset(o,controller),json=JSON.parse(new TextDecoder().decode(data));
                if(json.schema!=='surface-stations-v1'||!Array.isArray(json.points)||json.points.length!==o.count||json.fetched_at!==o.fetched_at)throw Error('Invalid METAR package');
                if(token!==serial)return;
                points=json.points.filter(p=>typeof p.id==='string'&&/^[A-Z0-9]{3,5}$/.test(p.id));pointHash=o.sha256;
            })().catch(e=>{if(token===serial){stationFailed=true;console.warn('Surface stations retained previous reports:',e.message);}}));
            await Promise.all(work);
            clearTimeout(timeout);
            if(token===serial){
                sync();
                for(const [id,value] of cache){if(cache.size<=6)break;if(!keys.some(k=>layers[k].hasLayer(value.image))){cache.delete(id);URL.revokeObjectURL(value.url);urls.delete(value.url);}}
            }
        }
        async function refresh() {
            if(busy || !active())return;busy=true;
            const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),25000);
            try {
                const url=new URL(metadataURL,document.baseURI);url.searchParams.set('_check',now());
                const r=await fetch(url,{cache:'no-store',signal:controller.signal});if(!r.ok)throw Error('Surface metadata unavailable');
                const next=await r.json();validate(next,metadata);metadata=next;failed=next.last_attempt?.analysis?.ok===false;stationFailed=next.last_attempt?.observations?.ok===false;
            } catch(e) {failed=true;stationFailed=true;console.warn('Surface metadata refresh retained previous data:',e.message);}
            finally {clearTimeout(timeout);busy=false;await loadSelected();}
        }
        function legendHTML() {
            const key=selected(), hasStations=map.hasLayer(stations);if(!key&&!hasStations)return '';
            let html='<div class="surface-card"><strong>Surface Observations & Analysis</strong>';
            if(key){
                const loaded=current(key),a=loaded?.analysis || metadata?.analysis,p=a?.products[key],s=state(a,now(),failed || Boolean(loaded && loaded.analysis.generation!==metadata?.analysis?.generation));
                const status=!loaded && s.visible ? (failed?'Analysis unavailable — waiting for a complete image':'Loading the hourly analysis…') : s.label;
                html+=`<div class="surface-card-heading">${esc(p?.label||names[key])} · ${key==='wind_speed'?'kt':'°F'}</div><div class="surface-status">${esc(status)}</div>`;
                if(p)html+=scale(p);
                html+=`<p><b>Analysis valid:</b> ${esc(utc(a?.valid_time))}<br>NOAA RTMA · hourly · 2.5 km</p><p class="surface-note">Observations combined with a model background. The fill is an analysis; zooming adds no source resolution.</p>`;
            }
            if(hasStations){
                const k=stationKey();
                html+=`<div class="surface-station-heading">METAR observations · ${esc(names[k])} (${k==='wind_speed'?'kt':'°F'})</div>`;
                if(!key)html+=`<label>Station values <select data-surface-field aria-label="Surface station variable">${keys.map(k=>`<option value="${k}" ${k===stationField?'selected':''}>${names[k]}</option>`).join('')}</select></label>`;
                html+=`<p>${map.getZoom()<7?'Zoom in to see station values.':'Point values show actual station reports. Click for details.'}<br>${points.length?'Reports older than 90 minutes are hidden.':'Waiting for usable station observations.'}${stationFailed?' Previous reports retained within their age limit.':''}</p><p class="surface-note">Each report has its own observation time, independent of the hourly analysis. Values are thinned to limit overlap.</p>`;
            }
            return html+'</div>';
        }
        function setBorders(data){if(border&&map.hasLayer(border))map.removeLayer(border);border=L.layerGroup([
            L.geoJSON(data,{pane:'mapReference',interactive:false,style:{color:'#132332',weight:2.5,opacity:.8,fill:false}}),
            L.geoJSON(data,{pane:'mapReference',interactive:false,style:{color:'#fff',weight:1,opacity:.8,fill:false}})]);sync();}
        const layerEvent=e=>{if(keys.some(k=>layers[k]===e.layer)||e.layer===stations){if(selected())stationField=selected();sync();if(active())refresh();else serial++;}};
        map.on('layeradd layerremove',layerEvent);map.on('moveend zoomend',()=>{if(map.hasLayer(stations)){renderStations();onChange();}});
        document.addEventListener('change',e=>{if(e.target.matches('[data-surface-field]')&&keys.includes(e.target.value)){stationField=e.target.value;sync();}},true);
        const timer=setInterval(()=>{if(active())sync();},30000),poll=setInterval(refresh,300000);
        return {layers,stations,refresh,legendHTML,setBorders,getMetadata:()=>metadata,
            stop:()=>{clearInterval(timer);clearInterval(poll);serial++;urls.forEach(u=>URL.revokeObjectURL(u));}};
    }
    root.SurfaceSuite={keys,state,validate,freshPoint,thinPoints,color,scale,popup,create};
})(typeof window==='undefined'?globalThis:window);
