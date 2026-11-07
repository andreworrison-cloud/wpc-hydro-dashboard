const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),{execFileSync}=require('node:child_process');
const context={Blob,DecompressionStream,TextDecoder,DataView,Int16Array,Uint8Array,Date,console};
vm.runInNewContext(fs.readFileSync('surface_sampling.js','utf8'),context);const S=context.SurfaceSampling;
const time='2026-10-26T04:00:00Z',a={valid_time:time,generation:'2026102604-1234567890abcdef',width:3600,height:2024,products:{temperature:{label:'Temperature',unit:'°F',sampling:{path:'generations/2026102604-1234567890abcdef/temperature_samples.bin.gz',sha256:'a'.repeat(64),encoding:'gzip-int16-v1'}}}};
const raw=execFileSync('python',['-c',`import sys,numpy as np
from surface_sampling import pack_grid
y,x=np.indices((2024,3600));v=x*.1+y*.2;v[100,100]=np.nan
sys.stdout.buffer.write(pack_grid('temperature',v,'${time}'))`],{maxBuffer:30000000});
const merc=lat=>Math.log(Math.tan(Math.PI/4+lat*Math.PI/360));
const location=(x,y)=>({lng:-125+(x+.5)/3600*59,lat:(2*Math.atan(Math.exp(merc(50)-(y+.5)/2024*(merc(50)-merc(24))))-Math.PI/2)*180/Math.PI});
(async()=>{
 S.descriptor(a.products.temperature.sampling,a,'temperature');assert.throws(()=>S.descriptor({...a.products.temperature.sampling,path:'../bad'},a,'temperature'));
 const grid=await S.decode(raw,'temperature',a),p=location(400.25,600.75),result=S.sample(grid,p.lat,p.lng);
 assert.equal(result.status,'value');assert.ok(Math.abs(result.value-(400.25*.1+600.75*.2))<1e-8,'analytic plane is sampled bilinearly in projected grid coordinates');
 assert.equal(S.sample(grid,60,-100).status,'outside');assert.equal(S.sample(grid,NaN,-100).status,'outside');
 for(const [x,y] of [[100,100],[99.5,99.5]]){const p=location(x,y);assert.equal(S.sample(grid,p.lat,p.lng).status,'missing','interpolation must not bridge missing cells');}
 assert.equal(S.sample(grid,50,-125).value,0,'edge zero is a real value');
 const edge=location(99,100);assert.ok(Math.abs(S.sample(grid,edge.lat,edge.lng).value-29.9)<1e-8,'zero-weight missing neighbors do not erase exact valid grid centers');
 await assert.rejects(()=>S.decode(raw,'temperature',{...a,valid_time:'2026-10-26T03:00:00Z'}));
 await assert.rejects(()=>S.decode(raw,'temperature',{...a,products:{temperature:{unit:'K'}}}));
 await assert.rejects(()=>S.decode(raw.subarray(0,20),'temperature',a));
 const handlers={},layers=new Set(),keys={};let entry={analysis:a},current={entry,key:'temperature',visible:true},loads=0,tip;
 const map={on:(events,f)=>events.split(' ').forEach(e=>(handlers[e]??=[]).push(f)),hasLayer:l=>layers.has(l),removeLayer:l=>layers.delete(l)};
 context.document={addEventListener:(e,f)=>keys[e]=f};context.L={tooltip:()=>tip={setLatLng(p){this.position=p;return this},setContent(s){this.html=s;return this},addTo(){layers.add(this);return this}}};
 const c=S.create({map,getCurrent:()=>current,load:async()=>{loads++;return raw;},onChange:()=>{}});
 await c.sync();assert.equal(loads,0,'disabled sampling downloads no grids');
 await c.setEnabled(true);assert.equal(loads,1);assert.ok(entry.samples);
 handlers.mousemove[0]({latlng:p});assert.match(tip.html,/160.2 °F/);assert.match(tip.html,/Interpolated analysis/);
 handlers.click[0]({latlng:p});assert.match(tip.html,/Pinned/);handlers.mouseout[0]();assert.equal(layers.size,1,'pinned value survives mouse leaving map');
 current={...current,visible:false};await c.sync();assert.equal(layers.size,0,'expired or deselected analysis hides sampling');
 current={...current,visible:true};await c.sync();assert.equal(layers.size,1);assert.equal(loads,1,'same immutable grid is reused');
 keys.keydown({key:'Escape'});assert.equal(layers.size,0);assert.ok(!c.legend().includes('Clear pin'));
 await c.setEnabled(false);assert.equal(layers.size,0);c.stop();
 console.log('Surface sampling checks passed: Python/JS round trip, projected bilinear values, masks/edges, identity validation, opt-in loading, pinning and expiry.');
})().catch(e=>{console.error(e);process.exitCode=1;});
