/* Actual adapter: pressure sources, observed barbs, freshness and layer lifecycle. */
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),{execFileSync}=require('node:child_process');
const context={};vm.runInNewContext(fs.readFileSync('surface_cartography.js','utf8'),context);vm.runInNewContext(fs.readFileSync('surface_sampling.js','utf8'),context);vm.runInNewContext(fs.readFileSync('surface_layer.js','utf8'),context);const S=context.SurfaceSuite;
const palettes=JSON.parse(execFileSync('python',['-c','import json,surface_analysis;print(json.dumps(surface_analysis.PRODUCTS))'],{encoding:'utf8'}));
const now=Date.parse('2026-10-24T15:00:00Z'),at=min=>new Date(now-min*60000).toISOString();
assert.equal(S.state(null,now).visible,false);assert.equal(S.state({valid_time:at(-1)},now).visible,false);
assert.equal(S.state({valid_time:at(239.99)},now).visible,true);assert.equal(S.state({valid_time:at(240)},now).visible,false);
assert.match(S.state({valid_time:at(150)},now).label,/Aging/);assert.match(S.state({valid_time:at(60)},now,true).label,/Retained/);
const point={id:'KAAA',lat:39,lon:-100,time:at(30),temperature:0,dewpoint:null,wind_speed:0,wind_direction:null};
assert.equal(S.freshPoint(point,'temperature',now),true);assert.equal(S.freshPoint(point,'wind_speed',now),true);assert.equal(S.freshPoint(point,'dewpoint',now),false);
assert.equal(S.freshPoint({...point,time:at(91)},'temperature',now),false);assert.equal(S.freshPoint({...point,time:at(-1)},'temperature',now),false);
const fresh={...point,id:'KBBB',time:at(10)};const thinned=S.thinPoints([point,fresh,{...point,id:'KCCC',lon:-90}],'temperature',now,p=>({x:p.lon*100,y:0}),()=>true);
assert.equal(thinned.length,2);assert.equal(thinned[0].id,'KBBB');
assert.equal(S.thinPoints([point,fresh],'temperature',now,p=>({x:p.id==='KAAA'?51:53,y:25}),()=>true).length,1,'adjacent cells reject overlapping labels');
assert.equal(S.thinPoints([point,fresh],'wind_speed',now,p=>({x:p.id==='KAAA'?63:65,y:63}),()=>true,{width:64,height:64}).length,1,'barbs use two-dimensional screen spacing');
Object.entries(palettes).forEach(([key,p])=>{
 assert.equal(S.color(p,p.stops[0]-100),p.colors[0]);assert.equal(S.color(p,p.stops.at(-1)+100),p.colors.at(-1));
 p.stops.forEach((value,i)=>assert.equal(S.color(p,value),p.colors[i]));
 const html=S.scale(p);p.colors.forEach(c=>assert.ok(html.includes(c)));assert.ok(html.includes('≤'));assert.ok(html.includes('≥'));
});
assert.equal(S.keys.length,8);assert.ok(S.stationKeys.includes('mslp'));assert.ok(!S.keys.includes('wind_direction'));assert.ok(!S.keys.includes('surface_pressure'));
assert.ok(S.stationKeys.includes('wind'));assert.ok(!S.stationKeys.includes('wind_gust'));
assert.equal(S.windLabel({...point,wind_speed:12,wind_direction:45,wind_gust:20}),'NE 12 G20');
assert.equal(S.windLabel(point),'Calm');assert.equal(S.windLabel({...point,wind_speed:5}),'VRB 5');
assert.ok(S.stationSpacing(4,'temperature').width>S.stationSpacing(7,'temperature').width);
assert.equal(S.cardinal(0),'N');assert.equal(S.cardinal(360),'N');assert.equal(S.cardinal(270),'W');assert.equal(S.cardinal(45),'NE');
assert.equal(S.valueLabel('mslp',1013.2),'1013.2');assert.equal(S.units.mslp,'hPa');
assert.equal(S.freshPoint({...point,wind_direction:0},'wind_direction',now),false,'calm is not north');
assert.equal(S.windPoint(point,now),true,'explicit calm is a valid circle');
assert.equal(S.windPoint({...point,wind_speed:10},now),false,'variable/missing direction is not invented');
assert.equal(S.windPoint({...point,wind_speed:10,wind_direction:0},now),true,'true north is valid');
assert.equal(S.windPoint({...point,wind_speed:-1,wind_direction:0},now),false);
assert.equal(S.windPoint({...point,time:at(91)},now),false);assert.equal(S.windPoint({...point,time:at(-1)},now),false);
for(const [speed,flags,full,half] of [[0,0,0,0],[5,0,0,1],[10,0,1,0],[50,1,0,0],[65,1,1,1],[245,4,4,1]]){
 const b=S.barbParts(speed);assert.equal(b.flags,flags);assert.equal(b.full,full);assert.equal(b.half,half);
}
assert.match(S.barbSVG(null,0),/<circle/);assert.ok(!S.barbSVG(null,0).includes('<path'));
for(const direction of [0,90,180,270])assert.ok(S.barbSVG(direction,10).includes(`rotate(${direction})`),'shaft points FROM direction');
assert.equal((S.barbSVG(0,65).match(/<polygon/g)||[]).length,2,'50-kt flag has a white halo and dark foreground');
assert.equal(S.barbSVG(null,10),'');assert.equal(S.barbSVG(360,10),'');assert.match(S.barbSVG(0,10,'<unsafe>'),/&lt;unsafe&gt;/);
assert.match(S.popup({...point,raw:'<img onerror=alert(1)>'},now),/&lt;img/);assert.match(S.popup(point,now),/Calm/);
assert.match(S.popup({...point,mslp:1013.2,relative_humidity:60},now),/Reported MSLP: 1013.2 hPa/);
assert.match(S.popup({...point,relative_humidity:60},now),/RH \(calculated\): 60 %/);

const a={revision:'rtma-surface-v4',crs:'EPSG:3857',width:3600,height:2024,native_spacing_km:2.5,bounds:[[24,-125],[50,-66]],valid_time:at(60),generation:'2026102414-1234567890abcdef',products:{}};
for(const k of S.rtmaKeys)a.products[k]={...palettes[k],path:`generations/${a.generation}/${k}.png`,sha256:'a'.repeat(64),applicable_pixels:k==='heat_index'?0:100,contours:{path:`generations/${a.generation}/${k}_contours.geojson`,sha256:'a'.repeat(64),interval:palettes[k].contour_interval,feature_count:0}};
const pressure={...a,revision:'hrrr-mslp-v2',native_spacing_km:3,valid_time:at(0),generation:'2026102415-abcdef1234567890',products:{}};
pressure.products.mslp={...palettes.mslp,path:`pressure/${pressure.generation}/mslp.png`,sha256:'a'.repeat(64),applicable_pixels:100,contours:{path:`pressure/${pressure.generation}/mslp_contours.geojson`,sha256:'a'.repeat(64),interval:4,feature_count:0}};
const m={schema:'surface-suite-v1',policy:{analysis_warn_minutes:150,analysis_hide_minutes:240,station_hide_minutes:90},analysis:a,pressure_analysis:pressure};
const numeric=JSON.parse(JSON.stringify(m));numeric.analysis.revision='rtma-surface-v5';numeric.pressure_analysis.revision='hrrr-mslp-v3';
for(const analysis of [numeric.analysis,numeric.pressure_analysis])for(const [key,p] of Object.entries(analysis.products))p.sampling={path:`${key==='mslp'?'pressure':'generations'}/${analysis.generation}/${key}_samples.bin.gz`,sha256:'a'.repeat(64),encoding:'gzip-int16-v1'};
const blended=JSON.parse(JSON.stringify(numeric));blended.pressure_analysis.revision='hrrr-metar-mslp-v7';
blended.pressure_analysis.objective_analysis={accepted_stations:850,mode:'observation-adjusted'};S.validate(blended);
const badBlend=JSON.parse(JSON.stringify(blended));badBlend.pressure_analysis.objective_analysis.accepted_stations='bad';assert.throws(()=>S.validate(badBlend),/diagnostics/);
S.validate(numeric);const incomplete=JSON.parse(JSON.stringify(numeric));delete incomplete.analysis.products.temperature.sampling;assert.throws(()=>S.validate(incomplete));
const invalid=JSON.parse(JSON.stringify(numeric));invalid.pressure_analysis.products.mslp.sampling.path='../bad';assert.throws(()=>S.validate(invalid));
S.validate(m);assert.throws(()=>S.validate({...m,analysis:{...a,bounds:[[0,0],[1,1]]}}));assert.throws(()=>S.validate({...m,analysis:{...a,products:{temperature:a.products.temperature}}}));
S.validate({...m,analysis:{...a,revision:'rtma-surface-v1',products:Object.fromEntries(['temperature','dewpoint','wind_speed'].map(k=>[k,a.products[k]]))}});
const legacy=JSON.parse(JSON.stringify(a));legacy.revision='rtma-surface-v2';
legacy.products.wind_direction={unit:'°',cyclic:true,stops:[0,180,360],colors:['#000000','#ffffff','#000000'],ticks:[0,180,360],path:`generations/${a.generation}/wind_direction.png`,sha256:'a'.repeat(64),applicable_pixels:100};
legacy.products.surface_pressure={...palettes.mslp,path:`generations/${a.generation}/surface_pressure.png`,applicable_pixels:100,sha256:'a'.repeat(64)};
S.validate({...m,analysis:legacy,pressure_analysis:undefined});
assert.throws(()=>S.validate({...m,analysis:{...a,valid_time:at(120)}},m));
assert.throws(()=>S.validate({...m,pressure_analysis:{...pressure,valid_time:at(60)}},m));
assert.throws(()=>S.validate({...m,analysis:{...a,products:{...a.products,temperature:{...a.products.temperature,path:'../secret'}}}}));
assert.throws(()=>S.validate({...m,pressure_analysis:{...pressure,products:{mslp:{...pressure.products.mslp,parameter:'PRES'}}}}));

(async()=>{
 const handlers={},onMap=new Set(),panes={},changeHandlers=[],clickHandlers=[];let calls=0,clock=now,zoom=4;const nodes=[];
 const add=l=>{onMap.add(l);l.eachLayer?.(add);return l},remove=l=>{onMap.delete(l);l.eachLayer?.(remove)};
 const map={createPane:n=>panes[n]={style:{}},getPane:n=>panes[n],hasLayer:l=>onMap.has(l),getZoom:()=>zoom,getSize:()=>({x:1200,y:900}),getBounds:()=>({contains:()=>true}),latLngToContainerPoint:()=>({x:5,y:5}),containerPointToLatLng:p=>p,removeLayer:remove,addLayer:add,on:(events,f)=>events.split(' ').forEach(e=>(handlers[e]??=[]).push(f))};
 let onRemove=()=>{};
 function group(initial=[]){const children=new Set(initial);return {options:{},hasLayer:l=>children.has(l),addLayer(l){children.add(l);if(onMap.has(this))add(l);return this},removeLayer(l){onRemove();children.delete(l);if(onMap.has(this))remove(l)},clearLayers(){[...children].forEach(l=>this.removeLayer(l))},eachLayer:f=>[...children].forEach(f),addTo(parent){if(parent===map)add(this);else parent.addLayer(this);return this}};}
 const markerInstances=[];
 const L={layerGroup:group,geoJSON:()=>group(),imageOverlay:()=>({setOpacity(){}}),divIcon:x=>x,marker:(latlon,options)=>{const marker={options,bindPopup(content){this.content=content;return this},setPopupContent(content){this.content=content},setLatLng(){},setIcon(icon){this.options.icon=icon},isPopupOpen:()=>true,addTo(g){g.addLayer(this);return this}};markerInstances.push(marker);return marker;}};
 const count=group=>{let n=0;group.eachLayer(()=>n++);return n};
 const crypto=require('node:crypto').webcrypto,bytes=new Uint8Array([1,2,3]);const hash=Buffer.from(await crypto.subtle.digest('SHA-256',bytes)).toString('hex');
 const mock=JSON.parse(JSON.stringify(m));for(const k of S.rtmaKeys)mock.analysis.products[k].sha256=hash;mock.pressure_analysis.products.mslp.sha256=hash;
 const contourBytes=new Map();
 for(const analysis of [mock.analysis,mock.pressure_analysis])for(const [key,p] of Object.entries(analysis.products)){
  const data={type:'FeatureCollection',schema:'surface-contours-v1',key,valid_time:analysis.valid_time,interval:p.contour_interval,features:[]},bytes=new TextEncoder().encode(JSON.stringify(data));
  contourBytes.set('/'+p.contours.path,bytes);p.contours.sha256=Buffer.from(await crypto.subtle.digest('SHA-256',bytes)).toString('hex');
 }
 const points={schema:'surface-stations-v1',fetched_at:at(0),points:Array.from({length:500},(_,i)=>({...point,id:'K'+String(i).padStart(3,'0'),wind_speed:10,wind_direction:270,mslp:1013.2,relative_humidity:60}))};
 const allBytes=new TextEncoder().encode(JSON.stringify(points));
 mock.observations={path:'stations/20261024150000-1234567890abcdef.json',sha256:Buffer.from(await crypto.subtle.digest('SHA-256',allBytes)).toString('hex'),count:500,fetched_at:at(0)};
 const c={L,Image:class{constructor(){this.naturalWidth=3600;this.naturalHeight=2024;}decode(){return Promise.resolve()}},Blob,URL,TextDecoder,crypto,AbortController,console,setTimeout,clearTimeout,setInterval:()=>1,clearInterval:()=>{},document:{baseURI:'https://example.org/',addEventListener(event,f){if(event==='change')changeHandlers.push(f);if(event==='click')clickHandlers.push(f);}},fetch:async url=>{calls++;const text=String(url),contour=contourBytes.get(new URL(text).pathname);return {ok:true,json:async()=>mock,arrayBuffer:async()=>text.includes('stations/')?allBytes.buffer:contour?contour.buffer:bytes.buffer}}};
 c.URL.createObjectURL=()=>`blob:${nodes.push(1)}`;c.URL.revokeObjectURL=()=>{};
 vm.runInNewContext(fs.readFileSync('surface_cartography.js','utf8'),c);vm.runInNewContext(fs.readFileSync('surface_sampling.js','utf8'),c);vm.runInNewContext(fs.readFileSync('surface_layer.js','utf8'),c);
 const suite=c.SurfaceSuite.create({map,metadataURL:'https://example.org/metadata.json',now:()=>clock});
 const consumed=[];clickHandlers[0]({target:{matches:s=>s==='[data-surface-unpin]'},preventDefault:()=>consumed.push('prevent'),stopPropagation:()=>consumed.push('stop')});assert.deepEqual(consumed,['prevent','stop'],'clear-pin clicks are consumed before a redraw can detach their target and let the map repin');
 onMap.add(suite.barbs);await suite.refresh();
 assert.equal(count(suite.barbs),1,'barbs work without any fill or numeric station layer');assert.equal(calls,2,'barbs fetch only metadata and observations');
 assert.match(suite.legendHTML(),/METAR Wind Barbs/);assert.match(suite.legendHTML(),/gust shading/i);
 const firstBarb=markerInstances[0];assert.match(firstBarb.options.icon.html,/rotate\(270\)/);
 clock=now+60000;await suite.refresh();handlers.moveend.forEach(f=>f());
 assert.equal(markerInstances[0],firstBarb);assert.equal(markerInstances.length,1,'barb identity and open popup survive refresh and map movement');
 onMap.delete(suite.barbs);add(suite.wind);onMap.add(suite.stations);await suite.refresh();
 assert.equal(count(suite.layers.wind_speed),1);assert.equal(count(suite.barbs),1);assert.equal(count(suite.stations),1);
 const station=markerInstances[1];assert.equal(station.options.icon.iconAnchor[1],-15,'numeric labels are offset from the barbs');
 assert.match(station.options.icon.html,/W 10/);assert.equal(zoom,4,'numeric station values are visible at national scale');
 const change=(selector,value,checked)=>changeHandlers[0]({target:{matches:s=>s===selector,value,checked}});
 const windTarget={matches:s=>s==='[data-surface-wind]',value:'wind_gust'};
 onRemove=()=>{windTarget.value='wind_speed';};changeHandlers[0]({target:windTarget});onRemove=()=>{};await suite.refresh();
 assert.equal(onMap.has(suite.layers.wind_speed),false);assert.equal(onMap.has(suite.layers.wind_gust),true);assert.equal(count(suite.barbs),1,'barbs persist across shading changes');
 assert.match(suite.legendHTML(),/Surface wind shading/);assert.match(suite.legendHTML(),/value="wind_gust" selected/);
 change('[data-surface-barbs]',undefined,false);assert.equal(count(suite.barbs),0);assert.equal(count(suite.layers.wind_gust),1);
 change('[data-surface-barbs]',undefined,true);assert.equal(count(suite.barbs),1);
 const afterControlChanges=markerInstances.length;handlers.moveend.forEach(f=>f());assert.equal(markerInstances.length,afterControlChanges,'map movement preserves markers after changing wind controls');
 remove(suite.wind);
 for(const key of S.keys){
  S.keys.forEach(k=>onMap.delete(suite.layers[k]));onMap.add(suite.layers[key]);await suite.refresh();
  assert.equal(count(suite.layers[key]),1,`loads ${key}`);assert.ok(suite.legendHTML().includes(S.units[key]));
  assert.ok(suite.legendHTML().includes(`${key==='mslp'?4:palettes[key].contour_interval*2} ${S.units[key]==='hPa'?'mb':S.units[key]} intervals`),'national legend matches displayed contour spacing');
  zoom=6;assert.ok(suite.legendHTML().includes(`${palettes[key].contour_interval} ${S.units[key]==='hPa'?'mb':S.units[key]} intervals`),'zoomed legend matches full contour spacing');zoom=4;
 }
 S.keys.forEach(k=>onMap.delete(suite.layers[k]));onMap.add(suite.layers.heat_index);await suite.refresh();assert.match(suite.legendHTML(),/No qualifying conditions/);
 onMap.delete(suite.layers.heat_index);onMap.add(suite.layers.mslp);await suite.refresh();
 assert.match(suite.legendHTML(),/NOAA HRRR background · hourly · 3 km/);assert.match(suite.legendHTML(),/METAR observations · Reported MSLP/);assert.equal(count(suite.stations),1,'MSLP follows the pressure fill automatically');
 changeHandlers[0]({target:{matches:()=>true,value:'relative_humidity'}});assert.match(suite.legendHTML(),/Calculated from METAR · Relative humidity/);
 clock=now+190*60000;await suite.refresh();assert.equal(count(suite.layers.mslp),1,'pressure uses its own valid time');
 onMap.delete(suite.layers.mslp);onMap.add(suite.layers.temperature);await suite.refresh();assert.equal(count(suite.layers.temperature),0,'older RTMA expires independently');
 assert.equal(count(suite.barbs),0,'old wind reports disappear independently');assert.equal(count(suite.stations),0);
 clock=now+241*60000;onMap.delete(suite.layers.temperature);onMap.add(suite.layers.mslp);await suite.refresh();assert.equal(count(suite.layers.mslp),0,'old pressure expires');
 suite.stop();onMap.clear();clock=now;
 // A pressure asset failure cannot prevent wind shading, barbs or station values.
 mock.pressure_analysis.products.mslp.sha256='b'.repeat(64);
 const partial=c.SurfaceSuite.create({map,metadataURL:'https://example.org/metadata.json',now:()=>clock});
 onMap.add(partial.layers.mslp);onMap.add(partial.barbs);onMap.add(partial.stations);await partial.refresh();
 assert.equal(count(partial.layers.mslp),0);assert.equal(count(partial.barbs),1);assert.equal(count(partial.stations),1);assert.match(partial.legendHTML(),/Analysis unavailable/);
 const validContourHash=mock.analysis.products.wind_gust.contours.sha256;mock.analysis.products.wind_gust.contours.sha256='c'.repeat(64);
 onMap.delete(partial.layers.mslp);onMap.add(partial.layers.wind_gust);await partial.refresh();
 assert.equal(count(partial.layers.wind_gust),1);assert.equal(count(partial.barbs),1);assert.ok(!partial.legendHTML().includes('Analysis unavailable'));
 assert.match(partial.legendHTML(),/Contours unavailable/,'contour failure does not hide valid shading');
 mock.analysis.products.wind_gust.contours.sha256=validContourHash;await partial.refresh();assert.ok(!partial.legendHTML().includes('Contours unavailable'),'contours recover independently');
 partial.stop();
 // The dashboard keeps barbs outside the filled-field exclusivity group.
 const app=fs.readFileSync('app.js','utf8'),start=app.indexOf('function enforceExclusiveSurfaceSelection('),end=app.indexOf('\nconst dashboardSections',start);
 const rows=[{id:'temperature',exclusiveGroup:'surface-analysis'},{id:'wind',exclusiveGroup:'surface-analysis'},{id:'stations'}];const off=[];
 const exclusive=vm.runInNewContext(app.slice(start,end)+'\nenforceExclusiveSurfaceSelection',{getAllDashboardLayerEntries:()=>rows,setDashboardLayerActive:(entry,value)=>off.push([entry.id,value])});
 exclusive(rows[1]);assert.deepEqual(off,[['temperature',false]]);
 assert.ok(app.includes("id: 'surface-wind', label: 'Surface Wind'"));assert.ok(!app.includes("id: 'surface-wind-speed'"));assert.ok(!app.includes('METAR Station Values (Zoom In)'));
 console.log('Surface checks passed: consolidated wind controls, national station values, eight fills, independent pressure, observed wind-barb geometry, zoom thinning, migration, expiry, stable popups and failures.');
})().catch(e=>{console.error(e);process.exitCode=1;});
