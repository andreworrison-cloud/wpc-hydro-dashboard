/* Actual module tests for freshness, observed points, palettes and map lifecycle. */
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),{execFileSync}=require('node:child_process');
const context={};vm.runInNewContext(fs.readFileSync('surface_layer.js','utf8'),context);const S=context.SurfaceSuite;
const palettes=JSON.parse(execFileSync('python',['-c','import json,surface_analysis;print(json.dumps(surface_analysis.PRODUCTS))'],{encoding:'utf8'}));
const now=Date.parse('2026-10-24T15:00:00Z'),at=min=>new Date(now-min*60000).toISOString();
assert.equal(S.state(null,now).visible,false);assert.equal(S.state({valid_time:at(-1)},now).visible,false);
assert.equal(S.state({valid_time:at(239.99)},now).visible,true);assert.equal(S.state({valid_time:at(240)},now).visible,false);
assert.match(S.state({valid_time:at(150)},now).label,/Aging/);assert.match(S.state({valid_time:at(60)},now,true).label,/Retained/);
const point={id:'KAAA',lat:39,lon:-100,time:at(30),temperature:0,dewpoint:null,wind_speed:0};
assert.equal(S.freshPoint(point,'temperature',now),true);assert.equal(S.freshPoint(point,'wind_speed',now),true);assert.equal(S.freshPoint(point,'dewpoint',now),false);
assert.equal(S.freshPoint({...point,time:at(91)},'temperature',now),false);assert.equal(S.freshPoint({...point,time:at(-1)},'temperature',now),false);
const fresh={...point,id:'KBBB',time:at(10)};const thinned=S.thinPoints([point,fresh,{...point,id:'KCCC',lon:-90}],'temperature',now,p=>({x:p.lon*100,y:0}),()=>true);
assert.equal(thinned.length,2);assert.equal(thinned[0].id,'KBBB');
Object.entries(palettes).forEach(([key,p])=>{
 assert.equal(S.color(p,p.stops[0]-100),p.colors[0]);assert.equal(S.color(p,p.stops.at(-1)+100),p.colors.at(-1));
 p.stops.forEach((value,i)=>assert.equal(S.color(p,value),p.colors[i]));
 const html=S.scale(p);p.colors.forEach(c=>assert.ok(html.includes(c)));assert.ok(html.includes('≤'));assert.ok(html.includes('≥'));
});
assert.match(S.popup({...point,raw:'<img onerror=alert(1)>'},now),/&lt;img/);assert.match(S.popup(point,now),/Calm/);
const a={revision:'rtma-surface-v1',crs:'EPSG:3857',width:3600,height:2024,native_spacing_km:2.5,bounds:[[24,-125],[50,-66]],valid_time:at(60),generation:'2026102414-1234567890abcdef',products:{}};
for(const k of S.keys)a.products[k]={...palettes[k],path:`generations/${a.generation}/${k}.png`,sha256:'a'.repeat(64)};
const m={schema:'surface-suite-v1',policy:{analysis_warn_minutes:150,analysis_hide_minutes:240,station_hide_minutes:90},analysis:a};
S.validate(m);assert.throws(()=>S.validate({...m,analysis:{...a,bounds:[[0,0],[1,1]]}}));assert.throws(()=>S.validate({...m,analysis:{...a,products:{temperature:a.products.temperature}}}));
assert.throws(()=>S.validate({...m,analysis:{...a,valid_time:at(120)}},m));
assert.throws(()=>S.validate({...m,analysis:{...a,products:{...a.products,temperature:{...a.products.temperature,path:'../secret'}}}}));

// Lifecycle uses the real adapter with mock Leaflet, network and decoded images.
(async()=>{
 const handlers={},onMap=new Set(),panes={};let calls=0,clock=now;const nodes=[];
 const map={createPane:n=>panes[n]={style:{}},getPane:n=>panes[n],hasLayer:l=>onMap.has(l),getZoom:()=>8,getBounds:()=>({contains:()=>true}),latLngToContainerPoint:()=>({x:5,y:5}),on:(events,f)=>events.split(' ').forEach(e=>(handlers[e]??=[]).push(f))};
 function group(){const children=new Set();return {options:{},hasLayer:l=>children.has(l),addLayer(l){children.add(l);return this},removeLayer:l=>children.delete(l),clearLayers:()=>children.clear(),eachLayer:f=>[...children].forEach(f),addTo:()=>{}};}
 const L={layerGroup:group,imageOverlay:()=>({setOpacity(){}}),divIcon:x=>x,marker:()=>({bindPopup(){return this},addTo(g){g.addLayer(this);return this}})};
 const crypto=require('node:crypto').webcrypto,bytes=new Uint8Array([1,2,3]);const hash=Buffer.from(await crypto.subtle.digest('SHA-256',bytes)).toString('hex');
 const mock=JSON.parse(JSON.stringify(m));for(const k of S.keys)mock.analysis.products[k].sha256=hash;
 const points={schema:'surface-stations-v1',fetched_at:at(0),points:[point]};const pointBytes=new TextEncoder().encode(JSON.stringify(points));const pointSha=Buffer.from(await crypto.subtle.digest('SHA-256',pointBytes)).toString('hex');
 mock.observations={path:'stations/20261024150000-1234567890abcdef.json',sha256:pointSha,count:500,fetched_at:at(0)};
 // Manifest minimum is 500, so build 500 distinct station reports; screen thinning still shows one.
 points.points=Array.from({length:500},(_,i)=>({...point,id:'K'+String(i).padStart(3,'0')}));const allBytes=new TextEncoder().encode(JSON.stringify(points));mock.observations.sha256=Buffer.from(await crypto.subtle.digest('SHA-256',allBytes)).toString('hex');
 const c={L,Image:class{constructor(){this.naturalWidth=3600;this.naturalHeight=2024;}decode(){return Promise.resolve()}},Blob,URL,TextDecoder,crypto,AbortController,console,setTimeout,clearTimeout,setInterval:()=>1,clearInterval:()=>{},document:{baseURI:'https://example.org/',addEventListener(){}},fetch:async url=>{calls++;const text=String(url);return {ok:true,json:async()=>mock,arrayBuffer:async()=>text.includes('stations/')?allBytes.buffer:bytes.buffer}}};
 c.URL.createObjectURL=()=>`blob:${nodes.push(1)}`;c.URL.revokeObjectURL=()=>{};
 vm.runInNewContext(fs.readFileSync('surface_layer.js','utf8'),c);
 const suite=c.SurfaceSuite.create({map,metadataURL:'https://example.org/metadata.json',now:()=>clock});
 onMap.add(suite.layers.temperature);onMap.add(suite.stations);await suite.refresh();
 assert.equal(suite.layers.temperature.hasLayer(undefined),false);let n=0;suite.layers.temperature.eachLayer(()=>n++);assert.equal(n,1);let s=0;suite.stations.eachLayer(()=>s++);assert.equal(s,1);assert.ok(calls>=3);
 clock=now+241*60000;await suite.refresh();n=0;suite.layers.temperature.eachLayer(()=>n++);assert.equal(n,0,'expired analysis hides');s=0;suite.stations.eachLayer(()=>s++);assert.equal(s,0,'individual old reports hide');
 suite.stop();onMap.clear();clock=now;
 // An unavailable image must not prevent usable, independent station values.
 mock.analysis.products.temperature.sha256='b'.repeat(64);
 const partial=c.SurfaceSuite.create({map,metadataURL:'https://example.org/metadata.json',now:()=>clock});
 onMap.add(partial.layers.temperature);onMap.add(partial.stations);await partial.refresh();
 n=0;partial.layers.temperature.eachLayer(()=>n++);assert.equal(n,0);
 s=0;partial.stations.eachLayer(()=>s++);assert.equal(s,1,'stations still load after analysis image failure');
 assert.match(partial.legendHTML(),/Analysis unavailable/);partial.stop();
 // Exercise the dashboard's actual field exclusivity handler.
 const app=fs.readFileSync('app.js','utf8'),start=app.indexOf('function enforceExclusiveSurfaceSelection('),end=app.indexOf('\nconst dashboardSections',start);
 const rows=[{id:'temperature',exclusiveGroup:'surface-analysis'},{id:'dewpoint',exclusiveGroup:'surface-analysis'},{id:'stations'}];const off=[];
 const exclusive=vm.runInNewContext(app.slice(start,end)+'\nenforceExclusiveSurfaceSelection',{getAllDashboardLayerEntries:()=>rows,setDashboardLayerActive:(entry,value)=>off.push([entry.id,value])});
 exclusive(rows[1]);assert.deepEqual(off,[['temperature',false]]);
 console.log('Surface checks passed: units/palettes, time cutoffs, point thinning, safe paths, decoded overlays, independent component failures and field exclusivity.');
})().catch(e=>{console.error(e);process.exitCode=1;});
