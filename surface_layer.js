/* Hourly RTMA/HRRR fills and independently timed METAR values and wind barbs. */
(function (root) {
    'use strict';
    const carto=root.SurfaceCartography;
    const legacyKeys = ['temperature', 'dewpoint', 'wind_speed'];
    const v2Keys = [...legacyKeys,'wind_direction','wind_gust','surface_pressure','relative_humidity','heat_index','wind_chill'];
    const keys = ['temperature','dewpoint','wind_speed','wind_gust','mslp','relative_humidity','heat_index','wind_chill'];
    const rtmaKeys = keys.filter(k=>k!=='mslp');
    const stationKeys = ['temperature','dewpoint','wind','relative_humidity','heat_index','wind_chill','mslp'];
    const bounds = [[24, -125], [50, -66]];
    const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[c]));
    const utc = value => Number.isFinite(Date.parse(value)) ? new Date(value).toISOString().replace('T', ' ').replace(/\.\d{3}Z$/, 'Z') : 'Unavailable';
    const names = {temperature:'Temperature',dewpoint:'Dewpoint',wind:'Wind (speed / gust)',wind_speed:'Wind speed',wind_direction:'Wind direction',wind_gust:'Wind gust',mslp:'Barometric pressure (MSLP)',relative_humidity:'Relative humidity',heat_index:'Heat index',wind_chill:'Wind chill'};
    const units = {temperature:'°F',dewpoint:'°F',wind:'kt',wind_speed:'kt',wind_direction:'°',wind_gust:'kt',surface_pressure:'hPa',relative_humidity:'%',heat_index:'°F',wind_chill:'°F',mslp:'hPa'};
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
            const expected=a.revision==='rtma-surface-v1'?legacyKeys:a.revision==='rtma-surface-v2'?v2Keys:['rtma-surface-v3','rtma-surface-v4'].includes(a.revision)?rtmaKeys:null;
            if (!expected || a.crs !== 'EPSG:3857' || a.width !== 3600 || a.height !== 2024 || a.native_spacing_km !== 2.5 || JSON.stringify(a.bounds) !== JSON.stringify(bounds) || !Number.isFinite(Date.parse(a.valid_time)) || !/^\d{10}-[a-f0-9]{16}$/.test(a.generation)) throw Error('Invalid RTMA display grid/time');
            if (Object.keys(a.products || {}).sort().join() !== [...expected].sort().join()) throw Error('Incomplete RTMA surface suite');
            expected.forEach(key => {
                const p = a.products[key];
                if (p.path !== `generations/${a.generation}/${key}.png` || !/^[a-f0-9]{64}$/.test(p.sha256) || p.unit !== units[key]) throw Error('Invalid RTMA asset');
                if (!Array.isArray(p.stops) || p.stops.length !== p.colors?.length || p.stops.length < 3 || !p.stops.every((v,i)=>Number.isFinite(v) && (!i || v > p.stops[i-1])) || !p.colors.every(c=>/^#[a-f0-9]{6}$/i.test(c)) || !p.ticks?.every(Number.isFinite)) throw Error('Invalid surface palette');
                if(key==='wind_direction' && (p.cyclic!==true || p.stops[0]!==0 || p.stops.at(-1)!==360 || p.colors[0]!==p.colors.at(-1)))throw Error('Invalid cyclic wind-direction palette');
                if(a.revision!=='rtma-surface-v1' && (!Number.isInteger(p.applicable_pixels)||p.applicable_pixels<0||p.applicable_pixels>a.width*a.height))throw Error('Invalid surface applicability count');
                if(a.revision==='rtma-surface-v4'&&!p.contours)throw Error('Missing surface contours');
                carto.descriptor(p.contours,a,key);
            });
            if (previous?.analysis && Date.parse(a.valid_time) < Date.parse(previous.analysis.valid_time)) throw Error('Regressing RTMA time');
            if (previous?.analysis?.generation === a.generation && JSON.stringify(previous.analysis) !== JSON.stringify(a)) throw Error('Immutable RTMA generation changed');
        }
        const pressure=m.pressure_analysis;
        if(pressure){
            const p=pressure.products?.mslp;
            if(!['hrrr-mslp-v1','hrrr-mslp-v2'].includes(pressure.revision) || pressure.native_spacing_km!==3 || pressure.crs!=='EPSG:3857' || pressure.width!==3600 || pressure.height!==2024 || JSON.stringify(pressure.bounds)!==JSON.stringify(bounds) || !Number.isFinite(Date.parse(pressure.valid_time)) || !/^\d{10}-[a-f0-9]{16}$/.test(pressure.generation))throw Error('Invalid pressure analysis grid/time');
            if(Object.keys(pressure.products||{}).join()!=='mslp' || p.path!==`pressure/${pressure.generation}/mslp.png` || !/^[a-f0-9]{64}$/.test(p.sha256) || p.unit!=='hPa' || p.parameter!=='MSLMA')throw Error('Invalid mean-sea-level pressure asset');
            if(!Array.isArray(p.stops)||p.stops.length!==p.colors?.length||p.stops.length<3||!p.stops.every((v,i)=>Number.isFinite(v)&&(!i||v>p.stops[i-1]))||!p.colors.every(c=>/^#[a-f0-9]{6}$/i.test(c))||!p.ticks?.every(Number.isFinite))throw Error('Invalid pressure palette');
            if(!Number.isInteger(p.applicable_pixels)||p.applicable_pixels<0||p.applicable_pixels>pressure.width*pressure.height)throw Error('Invalid pressure coverage');
            if(pressure.revision==='hrrr-mslp-v2'&&!p.contours)throw Error('Missing pressure isobars');
            carto.descriptor(p.contours,pressure,'mslp');
            if(previous?.pressure_analysis && Date.parse(pressure.valid_time)<Date.parse(previous.pressure_analysis.valid_time))throw Error('Regressing pressure time');
            if(previous?.pressure_analysis?.generation===pressure.generation && JSON.stringify(previous.pressure_analysis)!==JSON.stringify(pressure))throw Error('Immutable pressure generation changed');
        }
        const o = m.observations;
        if (o && (!/^stations\/\d{14}-[a-f0-9]{16}\.json$/.test(o.path) || !/^[a-f0-9]{64}$/.test(o.sha256) || !Number.isInteger(o.count) || o.count < 500 || !Number.isFinite(Date.parse(o.fetched_at)))) throw Error('Invalid METAR asset');
        if (previous?.observations && o && Date.parse(o.fetched_at) < Date.parse(previous.observations.fetched_at)) throw Error('Regressing METAR retrieval time');
        if (!a && !pressure && !o) throw Error('Empty surface suite');
    }
    function freshPoint(p, key, now = Date.now()) {
        const age = now - Date.parse(p?.time);
        return p && Number.isFinite(p[key==='wind'?'wind_speed':key]) && (key!=='wind_direction'||Number.isFinite(p.wind_speed)&&p.wind_speed>=1) && Number.isFinite(age) && age >= 0 && age <= 90*60000 && Number.isFinite(p.lat) && Number.isFinite(p.lon) && p.lat >= 24 && p.lat <= 50 && p.lon >= -125 && p.lon <= -66;
    }
    function stationSpacing(zoom,key){const factor=Math.max(1,Math.min(2,Math.pow(2,(6-zoom)/2)));return {width:(key==='wind'?116:key==='mslp'?76:52)*factor,height:28*factor};}
    function windLabel(p){const d=p.wind_speed===0?'Calm':Number.isFinite(p.wind_direction)?cardinal(p.wind_direction):'VRB';return `${d}${p.wind_speed>0?' '+Math.round(p.wind_speed):''}${Number.isFinite(p.wind_gust)?' G'+Math.round(p.wind_gust):''}`;}
    function thinPoints(points, key, now, project, contains, spacing={}) {
        const occupied = new Map(), result = [];
        points.filter(p=>freshPoint(p,key,now) && contains(p)).sort((a,b)=>Date.parse(b.time)-Date.parse(a.time) || a.id.localeCompare(b.id)).forEach(p=>{
            const width=spacing.width||(key==='wind'?116:key==='mslp'?76:52),height=spacing.height||28;
            const pt=project(p), x=Math.floor(pt.x/width), y=Math.floor(pt.y/height);
            let overlap=false;
            for(let dx=-1;dx<=1;dx++)for(let dy=-1;dy<=1;dy++){
                const neighbor=occupied.get(`${x+dx},${y+dy}`);
                if(neighbor && Math.abs(neighbor.x-pt.x)<width && Math.abs(neighbor.y-pt.y)<height)overlap=true;
            }
            if (!overlap && result.length < 800) {occupied.set(`${x},${y}`,pt);result.push(p);}
        });
        return result;
    }
    function windPoint(p,now=Date.now()) {
        return freshPoint(p,'wind_speed',now) && p.wind_speed>=0 && p.wind_speed<=250 &&
            (p.wind_speed===0 || Number.isFinite(p.wind_direction)&&p.wind_direction>=0&&p.wind_direction<360);
    }
    function barbParts(speed) {
        let n=Math.round(speed/5);
        const flags=Math.floor(n/10);n%=10;
        return {flags,full:Math.floor(n/2),half:n%2};
    }
    function barbSVG(direction,speed,title='') {
        if(!Number.isFinite(speed)||speed<0||speed>250 || speed>0&&(!Number.isFinite(direction)||direction<0||direction>=360))return '';
        const {flags,full,half}=barbParts(speed),length=Math.max(28,flags*6+full*3.5+half*3.5+3),extent=Math.max(36,length+9);
        let shape='<circle cx="0" cy="0" r="4"/>';
        if(speed>0){
            shape=`<path d="M 0 0 L 0 ${-length}"/>`;
            let y=-length;
            for(let i=0;i<flags;i++){shape+=`<polygon points="0,${y} 10,${y} 0,${y+5}" fill="currentColor"/>`;y+=6;}
            for(let i=0;i<full;i++){shape+=`<path d="M 0 ${y} L 10 ${y-5}"/>`;y+=3.5;}
            if(half)shape+=`<path d="M 0 ${y+(flags+full===0?3.5:0)} l 5 -2.5"/>`;
        }
        return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="${-extent} ${-extent} ${extent*2} ${extent*2}" width="64" height="64" role="img" aria-label="${esc(title||`${speed} kt wind`)}"><g transform="rotate(${speed===0?0:direction})" fill="none" stroke-linecap="round" stroke-linejoin="round"><g stroke="#fff" color="#fff" stroke-width="4.5">${shape}</g><g stroke="#142c40" color="#142c40" stroke-width="2">${shape}</g></g></svg>`;
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
        const layers={}, cache=new Map(), urls=new Set(), stationMarkers=new Map(),barbMarkers=new Map();
        let metadata=null, points=[], pointHash=null, busy=false, serial=0, stationField='auto', markerField=null, failed=false,pressureFailed=false, stationFailed=false, border=null,windField='wind_speed',windBarbs=true,contoursEnabled=true,stationObstacles=[];
        map.createPane('surfaceAnalysis');map.getPane('surfaceAnalysis').style.zIndex=338;map.getPane('surfaceAnalysis').style.pointerEvents='none';
        map.createPane('surfaceStations');map.getPane('surfaceStations').style.zIndex=588;
        map.createPane('surfaceWindBarbs');map.getPane('surfaceWindBarbs').style.zIndex=585;
        keys.forEach(key=>{const group=L.layerGroup();group.options.opacity=.93;group.setOpacity=value=>{group.options.opacity=value;group.eachLayer(layer=>layer.setOpacity(value));};layers[key]=group;});
        const stations=L.layerGroup(),barbs=L.layerGroup();
        const wind=L.layerGroup([layers.wind_speed,barbs]);wind.options.opacity=.93;
        wind.setOpacity=value=>{wind.options.opacity=value;layers[windField].setOpacity(value);};
        const cartography=carto.create(map);
        const selected=()=>keys.find(key=>map.hasLayer(layers[key]));
        const stationKey=()=>stationField==='auto'?(['wind_speed','wind_gust'].includes(selected())?'wind':selected()||'temperature'):stationField;
        const active=()=>selected() || map.hasLayer(stations) || map.hasLayer(barbs);
        const analysisFor=key=>key==='mslp'?metadata?.pressure_analysis:metadata?.analysis;
        const item=key=>cache.get(`${analysisFor(key)?.generation}/${key}`);
        const current=key=>Array.from(cache.values()).filter(v=>v.key===key).at(-1);
        function renderStations() {
            stationObstacles=[];
            if (!map.hasLayer(stations)) {stations.clearLayers();stationMarkers.clear();return;}
            const key=stationKey(),field=key==='wind'?'wind_speed':key,palette=analysisFor(field)?.products[field];
            if(markerField!==key){stations.clearLayers();stationMarkers.clear();markerField=key;}
            const shown=thinPoints(points,key,now(),p=>map.latLngToContainerPoint([p.lat,p.lon]),p=>map.getBounds().contains([p.lat,p.lon]),stationSpacing(map.getZoom(),key));
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
                const value=key==='wind'?windLabel(p):valueLabel(key,p[key]);
                const html=`<span class="surface-station-value"><i style="background:${color(palette,p[field])}"></i>${value}</span>`, content=popup(p,now());
                const title=`${p.id}: ${value} ${units[key]}, ${utc(p.time)}`;
                const width=key==='wind'?110:key==='mslp'?74:46;
                const anchor=map.hasLayer(barbs)?-15:12,identity=html+'/'+anchor;
                const screen=map.latLngToContainerPoint([p.lat,p.lon]);stationObstacles.push({x:screen.x,y:screen.y+(anchor<0?27:0),w:width+10,h:32});
                const icon=()=>L.divIcon({className:'surface-station-icon',iconSize:[width,24],iconAnchor:[width/2,anchor],html});
                const entry=stationMarkers.get(p.id);
                if(entry){
                    if(entry.html!==identity){entry.marker.setIcon(icon());entry.html=identity;}
                    if(entry.content!==content){entry.marker.setPopupContent(content);entry.content=content;}
                    if(entry.lat!==p.lat || entry.lon!==p.lon){entry.marker.setLatLng([p.lat,p.lon]);entry.lat=p.lat;entry.lon=p.lon;}
                    entry.marker.getElement?.()?.setAttribute('title',title);
                }else{
                    const marker=L.marker([p.lat,p.lon],{pane:'surfaceStations',icon:icon(),keyboard:true,title,riseOnHover:true}).bindPopup(content).addTo(stations);
                    stationMarkers.set(p.id,{marker,html:identity,content,lat:p.lat,lon:p.lon});
                }
            });
        }
        function renderBarbs() {
            if(!map.hasLayer(barbs)){barbs.clearLayers();barbMarkers.clear();return;}
            const shown=thinPoints(points.filter(p=>windPoint(p,now())),'wind_speed',now(),p=>map.latLngToContainerPoint([p.lat,p.lon]),p=>map.getBounds().contains([p.lat,p.lon]),{width:64,height:64});
            barbMarkers.forEach((entry,id)=>{
                const p=points.find(p=>p.id===id);
                if(entry.marker.isPopupOpen?.() && p && windPoint(p,now()) && map.getBounds().contains([p.lat,p.lon]) && !shown.some(q=>q.id===id))shown.push(p);
            });
            const keep=new Set(shown.map(p=>p.id));
            barbMarkers.forEach((entry,id)=>{if(!keep.has(id)){barbs.removeLayer(entry.marker);barbMarkers.delete(id);}});
            shown.forEach(p=>{
                const title=`${p.id}: ${p.wind_speed===0?'Calm':`${cardinal(p.wind_direction)} (${Math.round(p.wind_direction)%360}°), ${Math.round(p.wind_speed)} kt`}${Number.isFinite(p.wind_gust)?` · gust ${Math.round(p.wind_gust)} kt`:''}, ${utc(p.time)}`;
                const html=barbSVG(p.wind_direction,p.wind_speed,title),content=popup(p,now());
                const icon=()=>L.divIcon({className:'surface-windbarb-icon',iconSize:[64,64],iconAnchor:[32,32],html});
                const entry=barbMarkers.get(p.id);
                if(entry){
                    if(entry.html!==html){entry.marker.setIcon(icon());entry.html=html;}
                    if(entry.content!==content){entry.marker.setPopupContent(content);entry.content=content;}
                    if(entry.lat!==p.lat||entry.lon!==p.lon){entry.marker.setLatLng([p.lat,p.lon]);entry.lat=p.lat;entry.lon=p.lon;}
                    entry.marker.getElement?.()?.setAttribute('title',title);
                }else{
                    const marker=L.marker([p.lat,p.lon],{pane:'surfaceWindBarbs',icon:icon(),keyboard:true,title,riseOnHover:true}).bindPopup(content).addTo(barbs);
                    barbMarkers.set(p.id,{marker,html,content,lat:p.lat,lon:p.lon});
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
            renderBarbs();renderStations();renderContours();onChange();
        }
        function renderContours(){
            const key=selected(),entry=current(key),valid=entry&&state(entry.analysis,now()).visible;
            const obstacles=[...stationObstacles];
            if(map.hasLayer(barbs))barbMarkers.forEach(p=>{const c=map.latLngToContainerPoint([p.lat,p.lon]);obstacles.push({x:c.x,y:c.y,w:46,h:46});});
            cartography.draw({data:valid?entry.contours:null,key,generation:entry?.analysis.generation,enabled:contoursEnabled,obstacles});
        }
        async function asset(p, controller) {
            const url=new URL(p.path,new URL('.',new URL(metadataURL,document.baseURI)));
            const r=await fetch(url,{signal:controller.signal});if(!r.ok)throw Error('Surface asset unavailable');
            const data=await r.arrayBuffer();
            const digest=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',data)),v=>v.toString(16).padStart(2,'0')).join('');
            if(digest!==p.sha256)throw Error('Surface asset checksum mismatch');return data;
        }
        async function loadSelected() {
            const token=++serial,key=selected(),a=analysisFor(key),o=metadata?.observations;
            const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),45000);
            const work=[];
            if(key && a?.products[key] && state(a,now()).visible) work.push((async()=>{
                let entry=item(key);
                if(!entry){
                    const data=await asset(a.products[key],controller);
                    const url=URL.createObjectURL(new Blob([data],{type:'image/png'}));urls.add(url);
                    const decoded=new Image();decoded.src=url;
                    try {await decoded.decode();if(decoded.naturalWidth!==a.width||decoded.naturalHeight!==a.height)throw Error('Surface image dimensions mismatch');}
                    catch(e){URL.revokeObjectURL(url);urls.delete(url);throw e;}
                    if(token!==serial){URL.revokeObjectURL(url);urls.delete(url);return;}
                    entry={key,analysis:a,url,image:L.imageOverlay(url,a.bounds,{pane:'surfaceAnalysis',opacity:layers[key].options.opacity,interactive:false,className:'surface-analysis-raster'})};
                    cache.set(`${a.generation}/${key}`,entry);
                    sync(); // A slow optional contour asset must not delay the fill.
                }
                if(a.products[key].contours&&!entry.contours){
                    try{
                        const raw=await asset(a.products[key].contours,controller),data=JSON.parse(new TextDecoder().decode(raw));
                        carto.validate(data,key,a);
                        if(data.features.length!==a.products[key].contours.feature_count)throw Error('Surface contour count mismatch');
                        if(token===serial){entry.contours=data;entry.contourError=false;}
                    }catch(e){if(token===serial){entry.contourError=true;console.warn('Surface contours unavailable; shading retained:',e.message);}}
                }
            })().catch(e=>{if(token===serial){if(key==='mslp')pressureFailed=true;else failed=true;console.warn('Surface analysis retained validated image:',e.message);}}));
            if((map.hasLayer(stations)||map.hasLayer(barbs)) && o && pointHash!==o.sha256) work.push((async()=>{
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
                const next=await r.json();validate(next,metadata);metadata=next;failed=next.last_attempt?.analysis?.ok===false;pressureFailed=next.last_attempt?.pressure_analysis?.ok===false;stationFailed=next.last_attempt?.observations?.ok===false;
            } catch(e) {failed=true;pressureFailed=true;stationFailed=true;console.warn('Surface metadata refresh retained previous data:',e.message);}
            finally {clearTimeout(timeout);busy=false;await loadSelected();}
        }
        function legendHTML() {
            const key=selected(),hasStations=map.hasLayer(stations),hasBarbs=map.hasLayer(barbs);if(!key&&!hasStations&&!hasBarbs)return '';
            let html='<div class="surface-card" data-surface-pane="surface"><strong>Surface Observations & Analysis</strong>';
            if(map.hasLayer(wind))html+=`<div class="surface-wind-controls"><label>Wind shading <select data-surface-wind aria-label="Surface wind shading"><option value="wind_speed" ${windField==='wind_speed'?'selected':''}>Sustained speed</option><option value="wind_gust" ${windField==='wind_gust'?'selected':''}>Gusts</option></select></label><label><input type="checkbox" data-surface-barbs ${windBarbs?'checked':''}> Wind barbs</label></div>`;
            if(key){
                const loaded=current(key),a=loaded?.analysis || analysisFor(key),p=a?.products[key],componentFailed=key==='mslp'?pressureFailed:failed,s=state(a,now(),componentFailed || Boolean(loaded && loaded.analysis.generation!==analysisFor(key)?.generation));
                let status=!loaded && s.visible ? (componentFailed?'Analysis unavailable — waiting for a complete image':!p?'Waiting for the expanded hourly analysis…':'Loading the hourly analysis…') : s.label;
                if(p?.applicable_pixels===0 && loaded)status+=' · No qualifying conditions in this analysis';
                html+=`<div class="surface-card-heading">${esc(p?.label||(key==='mslp'?'Barometric Pressure (MSLP)':names[key]))} · ${units[key]}</div><div class="surface-status">${esc(status)}</div>`;
                if(p)html+=scale(p);
                html+=`<div class="surface-contour-controls"><label><input type="checkbox" data-surface-contours ${contoursEnabled?'checked':''}> ${key==='mslp'?'Isobars & H/L':'Contours'}</label>${p?.contours?`<span>${p.contours.interval} ${units[key]==='hPa'?'mb':units[key]} intervals</span>`:''}</div>`;
                if(loaded?.contourError)html+='<p class="surface-note">Contours unavailable · fill shown. Retrying on refresh.</p>';
                else if(p?.contours&&loaded&&!loaded.contours)html+='<p class="surface-note">Loading contours…</p>';
                else if(!p?.contours)html+='<p class="surface-note">New contours are updating.</p>';
                if(key==='mslp'&&p?.smoothing_km)html+='<p class="surface-note">Smoothed analysis · automated H/L centers with central pressure.</p>';
                if(p?.note)html+=`<p class="surface-note">${esc(p.note)}</p>`;
                html+=`<p><b>Analysis valid:</b> ${esc(utc(a?.valid_time))}<br>${key==='mslp'?'NOAA HRRR · hourly · 3 km':'NOAA RTMA · hourly · 2.5 km'}</p><p class="surface-note">The fill is a gridded analysis. Zooming adds no source resolution.</p>`;
            }
            if(hasBarbs){
                const count=points.filter(p=>windPoint(p,now())).length;
                html+=`<div class="surface-station-heading">METAR Wind Barbs · kt</div><div class="surface-barb-key">${[5,10,50].map(v=>`<span>${barbSVG(0,v)}${v} kt</span>`).join('')}</div><p class="surface-note">Shaft points FROM the reported wind direction; feathers show sustained speed, rounded to 5 kt. Calm reports use a circle. Gust shading is separate.</p><p class="surface-note">${count?`${count} usable wind reports; more barbs appear as you zoom.`:'Waiting for usable wind reports.'} Reports older than 90 minutes are hidden.${stationFailed?' Previous reports retained within their age limit.':''} Click a barb for report time and gusts.</p>`;
            }
            if(hasStations){
                const k=stationKey();
                html+=`<div class="surface-station-heading">${calculated.includes(k)?'Calculated from METAR':'METAR observations'} · ${esc(k==='mslp'?'Reported MSLP':names[k])} (${units[k]})</div>`;
                html+=`<label>Station values <select data-surface-field aria-label="Surface station variable"><option value="auto" ${stationField==='auto'?'selected':''}>Follow selected analysis</option>${stationKeys.map(k=>`<option value="${k}" ${k===stationField?'selected':''}>${k==='mslp'?'Reported MSLP':names[k]}</option>`).join('')}</select></label>`;
                if(calculated.includes(k))html+='<p class="surface-note">Values are calculated from each station’s report; heat index and wind chill appear only within their calculation ranges.</p>';
                html+=`<p>Actual station reports · more values appear as you zoom. Click for details.<br>${points.length?'Reports older than 90 minutes are hidden.':'Waiting for usable station observations.'}${stationFailed?' Previous reports retained within their age limit.':''}</p><p class="surface-note">Each report has its own observation time, independent of the hourly analysis. Values are thinned to limit overlap.</p>`;
            }
            return html+'</div>';
        }
        function setBorders(data){if(border&&map.hasLayer(border))map.removeLayer(border);border=L.layerGroup([
            L.geoJSON(data,{pane:'mapReference',interactive:false,style:{color:'#132332',weight:2.5,opacity:.8,fill:false}}),
            L.geoJSON(data,{pane:'mapReference',interactive:false,style:{color:'#fff',weight:1,opacity:.8,fill:false}})]);sync();}
        const layerEvent=e=>{if(keys.some(k=>layers[k]===e.layer)||e.layer===stations||e.layer===barbs||e.layer===wind){sync();if(active())refresh();else serial++;}};
        map.on('layeradd layerremove',layerEvent);map.on('moveend zoomend',()=>{if(active()){renderBarbs();renderStations();renderContours();onChange();}});
        document.addEventListener('change',e=>{
            if(e.target.matches('[data-surface-field]')&&['auto',...stationKeys].includes(e.target.value)){stationField=e.target.value;sync();}
            else if(e.target.matches('[data-surface-wind]')&&['wind_speed','wind_gust'].includes(e.target.value)){
                wind.removeLayer(layers[windField]);windField=e.target.value;layers[windField].setOpacity(wind.options.opacity);wind.addLayer(layers[windField]);sync();if(active())loadSelected();
            }else if(e.target.matches('[data-surface-barbs]')){windBarbs=e.target.checked;if(windBarbs)wind.addLayer(barbs);else wind.removeLayer(barbs);sync();}
            else if(e.target.matches('[data-surface-contours]')){contoursEnabled=e.target.checked;sync();if(contoursEnabled&&active())loadSelected();}
        },true);
        const timer=setInterval(()=>{if(active())sync();},30000),poll=setInterval(refresh,300000);
        return {layers,wind,stations,barbs,refresh,legendHTML,setBorders,getMetadata:()=>metadata,
            stop:()=>{clearInterval(timer);clearInterval(poll);serial++;cartography.clear();urls.forEach(u=>URL.revokeObjectURL(u));}};
    }
    root.SurfaceSuite={keys,rtmaKeys,stationKeys,units,cardinal,valueLabel,state,validate,freshPoint,stationSpacing,windLabel,thinPoints,windPoint,barbParts,barbSVG,color,scale,popup,create};
})(typeof window==='undefined'?globalThis:window);
