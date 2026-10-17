/* Node contract tests, not browser visual tests. */
const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),{webcrypto,createHash}=require('node:crypto');
require('../sport_rsm_layer.js');
const {displayState,validate}=globalThis.SPoRTRSM;
const fixture=JSON.parse(fs.readFileSync('review/sport_rsm_ingest_evidence.json')),valid=Date.parse(fixture.active.valid_time),fresh=()=>structuredClone(fixture);
fixture.policy={warn_age_hours:48,expire_age_hours:72,status:'approved_dashboard_policy_v1'};
test('clock-based freshness includes exact warning, expiry, future rejection and failure retention',()=>{
 for(const [hours,state,visible] of [[47.99,'available',true],[48,'aging',true],[71.999,'aging',true],[72,'expired',false],[-1,'future',false]]){const s=displayState(fixture,valid+hours*3600000);assert.equal(s.state,state);assert.equal(s.visible,visible);}
 assert.equal(displayState(null,valid).state,'unavailable');assert.equal(displayState(fixture,valid+20*3600000,true).state,'retained');assert.equal(displayState(fixture,valid+72*3600000,true).visible,false);
});
test('approved suite validates',()=>assert.doesNotThrow(()=>validate(fixture)));
for(const [name,change] of [
 ['policy',m=>m.policy.expire_age_hours=120],['missing depth',m=>delete m.active.products['200']],
 ['mixed date',m=>m.active.products['10'].valid_time='2026-10-16T00:00:00Z'],['wrong depth',m=>m.active.products['200'].depth_cm=[0,10]],
 ['dimensions',m=>m.active.products['200'].image.width=1808],['palette',m=>m.active.products['200'].image.palette='new'],
 ['interpolation',m=>m.active.products['200'].image.resampling='nearest'],['unsafe path',m=>m.active.products['200'].image.path='../other.png'],
 ['grid mismatch',m=>m.active.products['200'].image.bounds[0][0]+=.1],['time',m=>m.active.valid_time='invalid']
])test(`rejects invalid ${name}`,()=>{const m=fresh();change(m);assert.throws(()=>validate(m));});
test('rejects immutable generation change and time regression',()=>{const m=fresh();m.active.accepted_at='changed';assert.throws(()=>validate(m,fixture));const p=fresh();p.active.valid_time='2026-10-18T00:00:00Z';assert.throws(()=>validate(fixture,p));});
function harness(){
 const group=()=>({options:{},items:new Set(),eachLayer(f){this.items.forEach(f);},hasLayer(l){return this.items.has(l);},addLayer(l){this.items.add(l);return this;},clearLayers(){this.items.clear();},addTo(m){m.addLayer(this);return this;}});
 const map={items:new Set(),pane:{style:{}},handlers:[],createPane(){},getPane(){return this.pane;},hasLayer(l){return this.items.has(l);},on(e,f){this.handlers.push(f);},addLayer(l){this.items.add(l);this.handlers.forEach(f=>f({layer:l}));},removeLayer(l){this.items.delete(l);this.handlers.forEach(f=>f({layer:l}));}};
 let clock=valid+20*3600000,meta=fresh(),failure=null;const bytes=new TextEncoder().encode('test image bytes'),hash=createHash('sha256').update(bytes).digest('hex');Object.values(meta.active.products).forEach(p=>p.image.sha256=hash);
 const ctx={URL,Blob,AbortController,crypto:webcrypto,console:{warn(){}},document:{baseURI:'https://example.test/'},setInterval(){return 1;},clearInterval(){},setTimeout(){return 1;},clearTimeout(){},
 Image:class{naturalWidth=4000;naturalHeight=2538;async decode(){if(failure==='dimensions')this.naturalWidth=1808;}},
 L:{layerGroup:group,geoJSON:()=>({}),imageOverlay:(url,bounds,options)=>({url,bounds,options,setOpacity(v){this.options.opacity=v;}})},
 fetch:async url=>{if(String(url).includes('metadata.json')){if(failure==='metadata')throw Error('offline');return {ok:true,json:async()=>structuredClone(meta)};}return {ok:!(failure==='image'&&String(url).includes('sport_rsm_0_200cm')),arrayBuffer:async()=>bytes.buffer};}};
 vm.createContext(ctx);vm.runInContext(fs.readFileSync('sport_rsm_layer.js','utf8'),ctx);const adapter=ctx.SPoRTRSM.create({map,metadataURL:'review/sport-suite/metadata.json',now:()=>clock});
 return {adapter,map,setClock:v=>clock=v,setFailure:v=>{failure=v;if(v==='hash')meta.active.products['10'].image.sha256='0'.repeat(64);},next(){meta.active.generation=meta.active.generation.replace(/-[a-f0-9]{20}-/,'-aaaaaaaaaaaaaaaaaaaa-');Object.values(meta.active.products).forEach(p=>p.image.path=`generations/${meta.active.generation}/sport_rsm_0_${p.depth_cm[1]}cm.png`);}};
}
test('depth legend, state borders, opacity and expiry',async()=>{const h=harness(),a=h.adapter;await a.refresh();assert.equal(a.getState().visible,true);h.map.addLayer(a.layers[10]);a.setBorders({});for(const label of ['0–10 cm','Valid:','Source file modified:','48 h','72 h','95–100'])assert(a.legendHTML().includes(label));assert.equal(h.map.items.size,2);a.layers[10].setOpacity(.4);assert.equal([...a.layers[10].items][0].options.opacity,.4);h.map.removeLayer(a.layers[10]);assert.equal(h.map.items.size,0);assert.equal(a.legendHTML(),'');h.map.addLayer(a.layers[200]);assert.match(a.legendHTML(),/0–200 cm/);h.setClock(valid+72*3600000);a.sync();Object.values(a.layers).forEach(l=>assert.equal(l.items.size,0));assert.match(a.legendHTML(),/Expired/);});
test('metadata outage retains prior suite until expiry',async()=>{const h=harness();await h.adapter.refresh();const before=h.adapter.getMetadata();h.setFailure('metadata');await h.adapter.refresh();assert.equal(h.adapter.getMetadata(),before);assert.equal(h.adapter.getState().state,'retained');h.setClock(valid+72*3600000);h.adapter.sync();assert.equal(h.adapter.getState().visible,false);});
for(const failure of ['image','dimensions','hash'])test(`${failure} failure retains whole previous generation`,async()=>{const h=harness();await h.adapter.refresh();const before=h.adapter.getMetadata(),images=Object.values(h.adapter.layers).map(l=>[...l.items][0]);h.next();h.setFailure(failure);await h.adapter.refresh();assert.equal(h.adapter.getMetadata(),before);assert.equal(h.adapter.getState().state,'retained');Object.values(h.adapter.layers).forEach((l,i)=>assert.equal([...l.items][0],images[i]));});
test('depth selection excludes other depths and legacy SPoRT only',()=>{const source=fs.readFileSync('app.js','utf8'),fn=source.match(/function enforceExclusiveSPoRTSelection\(activeEntry\) \{[\s\S]*?\n\}/)[0],entries=['sport-percentile','sport-suite-10','sport-suite-40','sport-suite-100','sport-suite-200','sport-rsm-10','sport-rsm-200','nwm-soilsat'].map(id=>({id}));for(const selected of entries.slice(0,7)){const disabled=[],ctx={getAllDashboardLayerEntries:()=>entries,setDashboardLayerActive:(e,on)=>{assert.equal(on,false);disabled.push(e.id);}};vm.createContext(ctx);vm.runInContext(fn,ctx);ctx.enforceExclusiveSPoRTSelection(selected);assert.equal(disabled.length,6);assert(!disabled.includes(selected.id));assert(!disabled.includes('nwm-soilsat'));}assert(source.includes("sportRSM.layers[10]"));assert(source.includes("sportRSM.layers[200]"));});

test('RSM units cannot be confused with percentiles or percent saturation',()=>{for(const key of ['units','formula','quantity']){const m=fresh();m.active[key]='incorrect';assert.throws(()=>validate(m));}});

test('old permissive policy is rejected',()=>{const m=fresh();m.policy={warn_age_hours:72,expire_age_hours:96,status:'provisional_review_only'};assert.throws(()=>validate(m));});
test('retrieval and check timestamps cannot reset data age',()=>{const m=fresh();m.last_attempt.at=new Date(valid+73*3600000).toISOString();m.active.accepted_at=m.last_attempt.at;Object.values(m.active.products).forEach(p=>p.retrieved_at=m.last_attempt.at);assert.equal(displayState(m,valid+73*3600000).visible,false);});
