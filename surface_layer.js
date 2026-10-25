/* Hourly RTMA scalar fills and actual, independently timed METAR point values. */
(function (root) {
    'use strict';
    const legacyKeys = ['temperature', 'dewpoint', 'wind_speed'];
    const keys = ['temperature','dewpoint','wind_speed','wind_direction','wind_gust','surface_pressure','relative_humidity','heat_index','wind_chill'];
    const stationKeys = keys.filter(k=>k!=='surface_pressure').concat('mslp');
    const bounds = [[24, -125], [50, -66]];
    const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[c]));
    const utc = value => Number.isFinite(Date.parse(value)) ? new Date(value).toISOString().replace('T', ' ').replace(/\.\d{3}Z$/, 'Z') : 'Unavailable';
    const names = {temperature:'Temperature',dewpoint:'Dewpoint',wind_speed:'Wind speed',wind_direction:'Wind direction',wind_gust:'Wind gust',surface_pressure:'Surface pressure',relative_humidity:'Relative humidity',heat_index:'Heat index',wind_chill:'Wind chill',mslp:'Reported MSLP'};
    const units = {temperature:'°F',dewpoint:'°F',wind_speed:'kt',wind_direction:'°',wind_gust:'kt',surface_pressure:'hPa',relative_humidity:'%',heat_index:'°F',wind_chill:'°F',mslp:'hPa'};
    const calculated = ['relative_humidity','heat_index','wind_chill'];
    function cardinal(value) {return ['N','NNE','NE','ENE','E','ESE','SE','SSE','S','SSW','SW','WSW','W','WNW','NW','NNW'][Math.round(((value%360)+360)%360/22.5)%16];}
    function valueLabel(key,value) {return key==='wind_direction'?cardinal(value):key==='mslp'||key==='surface_pressure'?value.toFixed(1):String(Math.round(value));}
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
            const expected=a.revision==='rtma-surface-v1'?legacyKeys:a.revision==='rtma-surface-v2'?keys:null;
            if (!expected || a.crs !== 'EPSG:3857' || a.width !== 3600 || a.height !== 2024 || a.native_spacing_km !== 2.5 || JSON.stringify(a.bounds) !== JSON.stringify(bounds) || !Number.isFinite(Date.parse(a.valid_time)) || !/^\d{10}-[a-f0-9]{16}$/.test(a.generation)) throw Error('Invalid RTMA display grid/time');
            if (Object.keys(a.products || {}).sort().join() !== [...expected].sort().join()) throw Error('Incomplete RTMA surface suite');
            expected.forEach(key => {
                const p = a.products[key];
                if (p.path !== `generations/${a.generation}/${key}.png` || !/^[a-f0-9]{64}$/.test(p.sha256) || p.unit !== units[key]) throw Error('Invalid RTMA asset');
                if (!Array.isArray(p.stops) || p.stops.length !== p.colors?.length || p.stops.length < 3 || !p.stops.every((v,i)=>Number.isFinite(v) && (!i || v > p.stops[i-1])) || !p.colors.every(c=>/^#[a-f0-9]{6}$/i.test(c)) || !p.ticks?.every(Number.isFinite)) throw Error('Invalid surface palette');
                if(key==='wind_direction' && (p.cyclic!==true || p.stops[0]!==0 || p.stops.at(-1)!==360 || p.colors[0]!==p.colors.at(-1)))throw Error('Invalid cyclic wind-direction palette');
                if(a.revision==='rtma-surface-v2' && (!Number.isInteger(p.applicable_pixels)||p.applicable_pixels<0||p.applicable_pixels>a.width*a.height))throw Error('Invalid surface applicability count');
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
        return p && Number.isFinite(p[key]) && (key!=='wind_direction'||Number.isFinite(p.wind_speed)&&p.wind_speed>=1) && Number.isFinite(age) && age >= 0 && age <= 90*60000 && Number.isFinite(p.lat) && Number.isFinite(p.lon) && p.lat >= 24 && p.lat <= 50 && p.lon >= -125 && p.lon <= -66;
    }
    function thinPoints(points, key, now, project, contains) {
        const occupied = new Map(), result = [];
        points.filter(p=>freshPoint(p,key,now) && contains(p)).sort((a,b)=>Date.parse(b.time)-Date.parse(a.time) || a.id.localeCompare(b.id)).forEach(p=>{
            const width=key==='mslp'||key==='surface_pressure'?76:52;
            const pt=project(p), x=Math.floor(pt.x/width), y=Math.floor(pt.y/28);
            let overlap=false;
            for(let dx=-1;dx<=1;dx++)for(let dy=-1;dy<=1;dy++){
                const neighbor=occupied.get(`${x+dx},${y+dy}`);
                if(neighbor && Math.abs(neighbor.x-pt.x)<width && Math.abs(neighbor.y-pt.y)<28)overlap=true;
            }
            if (!overlap && result.length < 800) {occupied.set(`${x},${y}`,pt);result.push(p);}
        });
        return result;
    }
    function color(p, value) {
        if (!p) return '#d9e2e7';
        if(p.cyclic)value=((value%360)+360)%360;
        let i = p.stops.findIndex(x=>x>=value);if(i<0)i=p.stops.length-1;if(!i)return p.colors[0];
        const f=Math.max(0,Math.min(1,(value-p.stops[i-1])/(p.stops[i]-p.stops[i-1])));
        const c=n=>[1,3,5].map(j=>parseInt(p.colors[n].slice(j,j+2),16));
        const lo=c(i-1),hi=c(i);return '#'+lo.map((v,j)=>Math.round(v+(hi[j]-v)*f).toString(16).padStart(2,'0')).join('');
    }
    function scale(p) {
        const lo=p.stops[0],hi=p.stops.at(-1),pos=v=>100*(v-lo)/(hi-lo);
        return `<div class="surface-scale" style="background:linear-gradient(to right,${p.colors.map((c,i)=>`${c} ${pos(p.stops[i])}%`).join(',')})"></div><div class="surface-scale-ticks">${p.ticks.map((v,i)=>`<span style="left:${pos(v)}%;transform:translateX(${i===0?'0':i===p.ticks.length-1?'-100':'-50'}%)">${p.cyclic?`${cardinal(v)} ${v}°`:`${i===0?'≤':i===p.ticks.length-1?'≥':''}${v}`}</span>`).join('')}</div>`;
    }
    function popup(p, now) {
        const fmt=(v,u)=>Number.isFinite(v)?`${u==='hPa'?v.toFixed(1):Math.round(v)} ${u}`:'Not reported';
        const direction=p.wind_speed===0?'Calm':Number.isFinite(p.wind_direction)?`${cardinal(p.wind_direction)} (${Math.round(p.wind_direction)%360}° from true north)`:'Variable / unavailable';
        const derived=(k)=>Number.isFinite(p[k])?fmt(p[k],units[k]):'Not applicable / missing inputs';
        return `<div class="surface-popup"><strong>${esc(p.id)} · METAR observation</strong><br>${esc(utc(p.time))} · ${Math.floor((now-Date.parse(p.time))/60000)} min old<br>Temperature: ${fmt(p.temperature,'°F')}<br>Dewpoint: ${fmt(p.dewpoint,'°F')}<br>Wind: ${fmt(p.wind_speed,'kt')} · ${direction}<br>Gust: ${fmt(p.wind_gust,'kt')}<br>Reported MSLP: ${fmt(p.mslp,'hPa')}<br>RH (calculated): ${derived('relative_humidity')}<br>Heat index (calculated): ${derived('heat_index')}<br>Wind chill (calculated): ${derived('wind_chill')}<p>${esc(p.raw)}</p></div>`;
    }
    function create({map, metadataURL, onChange=()=>{}, now=()=>Date.now()}) {
        const layers={}, cache=new Map(), urls=new Set(), stationMarkers=new Map();
        let metadata=null, points=[], pointHash=null, busy=false, serial=0, stationField='auto', markerField=null, failed=false, stationFailed=false, border=null;
        map.createPane('surfaceAnalysis');map.getPane('surfaceAnalysis').style.zIndex=338;map.getPane('surfaceAnalysis').style.pointerEvents='none';
        map.createPane('surfaceStations');map.getPane('surfaceStations').style.zIndex=588;
        keys.forEach(key=>{const group=L.layerGroup();group.options.opacity=.85;group.setOpacity=value=>{group.options.opacity=value;group.eachLayer(layer=>layer.setOpacity(value));};layers[key]=group;});
        const stations=L.layerGroup();
        const selected=()=>keys.find(key=>map.hasLayer(layers[key]));
        const stationKey=()=>stationField==='auto'?(selected()||'temperature'):stationField;
        const active=()=>selected() || map.hasLayer(stations);
        const item=key=>cache.get(`${metadata?.analysis?.generation}/${key}`);
        const current=key=>Array.from(cache.values()).filter(v=>v.key===key).at(-1);
        function renderStations() {
            if (!map.hasLayer(stations) || map.getZoom() < 7) {stations.clearLayers();stationMarkers.clear();return;}
            const key=stationKey(), palette=metadata?.analysis?.products[key];
            if(markerField!==key){stations.clearLayers();stationMarkers.clear();markerField=key;}
            const shown=thinPoints(points,key,now(),p=>map.latLngToContainerPoint([p.lat,p.lon]),p=>map.getBounds().contains([p.lat,p.lon]));
            // Popup auto-pan emits moveend. Preserve the selected station across
            // redraws while its report is fresh, even if thinning priorities move.
            stationMarkers.forEach((entry,id)=>{
                if(entry.marker.isPopupOpen?.() && !shown.some(p=>p.id===id)){
                    const p=points.find(p=>p.id===id);
                    if(freshPoint(p,key,now()) && map.getBounds().contains([p.lat,p.lon]))shown.push(p);
                }
            });
            const keep=new Set(shown.map(p=>p.id));
            stationMarkers.forEach((entry,id)=>{if(!keep.has(id)){stations.removeLayer(entry.marker);stationMarkers.delete(id);}});
            shown.forEach(p=>{
                const html=`<span class="surface-station-value"><i style="background:${color(palette,p[key])}"></i>${valueLabel(key,p[key])}</span>`, content=popup(p,now());
                const title=`${p.id}: ${valueLabel(key,p[key])}${key==='wind_direction'?` (${Math.round(p[key])%360}°)`:''} ${units[key]}, ${utc(p.time)}`;
                const width=key==='mslp'?74:46;
                const icon=()=>L.divIcon({className:'surface-station-icon',iconSize:[width,24],iconAnchor:[width/2,12],html});
                const entry=stationMarkers.get(p.id);
                if(entry){
                    if(entry.html!==html){entry.marker.setIcon(icon());entry.html=html;}
                    if(entry.content!==content){entry.marker.setPopupContent(content);entry.content=content;}
                    if(entry.lat!==p.lat || entry.lon!==p.lon){entry.marker.setLatLng([p.lat,p.lon]);entry.lat=p.lat;entry.lon=p.lon;}
                    entry.marker.getElement?.()?.setAttribute('title',title);
                }else{
                    const marker=L.marker([p.lat,p.lon],{pane:'surfaceStations',icon:icon(),keyboard:true,title,riseOnHover:true}).bindPopup(content).addTo(stations);
                    stationMarkers.set(p.id,{marker,html,content,lat:p.lat,lon:p.lon});
                }
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
            if(key && a?.products[key] && state(a,now()).visible && !item(key)) work.push((async()=>{
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
            let html='<div class="surface-card" data-surface-pane="surface"><strong>Surface Observations & Analysis</strong>';
            if(key){
                const loaded=current(key),a=loaded?.analysis || metadata?.analysis,p=a?.products[key],s=state(a,now(),failed || Boolean(loaded && loaded.analysis.generation!==metadata?.analysis?.generation));
                let status=!loaded && s.visible ? (failed?'Analysis unavailable — waiting for a complete image':!p?'Waiting for the expanded hourly analysis…':'Loading the hourly analysis…') : s.label;
                if(p?.applicable_pixels===0 && loaded)status+=' · No qualifying conditions in this analysis';
                html+=`<div class="surface-card-heading">${esc(p?.label||names[key])} · ${units[key]}</div><div class="surface-status">${esc(status)}</div>`;
                if(p)html+=scale(p);
                if(p?.note)html+=`<p class="surface-note">${esc(p.note)}</p>`;
                html+=`<p><b>Analysis valid:</b> ${esc(utc(a?.valid_time))}<br>NOAA RTMA · hourly · 2.5 km</p><p class="surface-note">Observations combined with a model background. The fill is an analysis; zooming adds no source resolution.</p>`;
            }
            if(hasStations){
                const k=stationKey();
                html+=`<div class="surface-station-heading">${calculated.includes(k)?'Calculated from METAR':'METAR observations'} · ${esc(names[k])} (${units[k]})</div>`;
                html+=`<label>Station values <select data-surface-field aria-label="Surface station variable"><option value="auto" ${stationField==='auto'?'selected':''}>Follow selected analysis</option>${stationKeys.map(k=>`<option value="${k}" ${k===stationField?'selected':''}>${names[k]}</option>`).join('')}</select></label>`;
                if(k==='surface_pressure')html+='<p class="surface-note">Surface pressure is not reported in this METAR feed. Choose Reported MSLP above to view sea-level-pressure reports.</p>';
                else if(calculated.includes(k))html+='<p class="surface-note">Values are calculated from each station’s report; heat index and wind chill appear only within their calculation ranges.</p>';
                html+=`<p>${map.getZoom()<7?'Zoom in to see station values.':'Point values show actual station reports. Click for details.'}<br>${points.length?'Reports older than 90 minutes are hidden.':'Waiting for usable station observations.'}${stationFailed?' Previous reports retained within their age limit.':''}</p><p class="surface-note">Each report has its own observation time, independent of the hourly analysis. Values are thinned to limit overlap.</p>`;
            }
            return html+'</div>';
        }
        function setBorders(data){if(border&&map.hasLayer(border))map.removeLayer(border);border=L.layerGroup([
            L.geoJSON(data,{pane:'mapReference',interactive:false,style:{color:'#132332',weight:2.5,opacity:.8,fill:false}}),
            L.geoJSON(data,{pane:'mapReference',interactive:false,style:{color:'#fff',weight:1,opacity:.8,fill:false}})]);sync();}
        const layerEvent=e=>{if(keys.some(k=>layers[k]===e.layer)||e.layer===stations){sync();if(active())refresh();else serial++;}};
        map.on('layeradd layerremove',layerEvent);map.on('moveend zoomend',()=>{if(map.hasLayer(stations)){renderStations();onChange();}});
        document.addEventListener('change',e=>{if(e.target.matches('[data-surface-field]')&&['auto',...stationKeys].includes(e.target.value)){stationField=e.target.value;sync();}},true);
        const timer=setInterval(()=>{if(active())sync();},30000),poll=setInterval(refresh,300000);
        return {layers,stations,refresh,legendHTML,setBorders,getMetadata:()=>metadata,
            stop:()=>{clearInterval(timer);clearInterval(poll);serial++;urls.forEach(u=>URL.revokeObjectURL(u));}};
    }
    root.SurfaceSuite={keys,stationKeys,units,cardinal,valueLabel,state,validate,freshPoint,thinPoints,color,scale,popup,create};
})(typeof window==='undefined'?globalThis:window);
