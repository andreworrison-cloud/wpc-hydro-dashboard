const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const flush=()=>new Promise(r=>setImmediate(r));
async function main(){
 const listeners={},groups=[],revoked=[];let timer=null,m,fail=false,pending=null,calls=[];
 const cycle=new Date(Math.floor(Date.now()/3600000)*3600000).toISOString();
 const grid='a'.repeat(32),generation=cycle.replace(/[-:T]/g,'').slice(0,10)+'-aaaaaaaaaaaa-v1';
 const ctx={console,Date,Object,JSON,URL:{revokeObjectURL:u=>revoked.push(u)},setInterval:fn=>timer=fn,
  document:{addEventListener:(event,fn)=>listeners[event]=fn},
  L:{layerGroup:()=>{const g={items:[],addTo(){groups.push(this);return this;},clearLayers(){this.items=[];}};return g;},imageOverlay:(url,bounds,options)=>({addTo(g){g.items.push({url,bounds,options});return this;}})},
  GDIDisplay:{esc:String,utc:s=>s,metadata:async()=>{if(fail)throw Error('offline');return structuredClone(m);},image:async(meta,k)=>{calls.push(k);if(pending)await pending;return meta.generation+'/'+k;}}};
 vm.runInNewContext(fs.readFileSync('gdi_dynamics_layer.js','utf8'),ctx);
 function metadata(c=cycle,g=generation){return {schema:'gdi_dynamics_suite_v1',recipe:'rap_gdi_dynamics_v1',model:'rap',cycle:c,expires_at:new Date(Date.parse(c)+6*3600000).toISOString(),smoothing_sigma_km:20,generation:g,crs:'EPSG:3857',width:2400,height:1360,bounds:[[24,-125],[50,-66]],definitions:structuredClone(ctx.GDIDynamics.FIELDS),source_metadata:[0,3].map(lead=>({cycle:c,lead,model:'rap',recipe:'rap_gdi_dynamics_v1',grid_md5:grid})),products:Object.fromEntries(Object.keys(ctx.GDIDynamics.FIELDS).flatMap(field=>[0,3].map(lead=>[field+'_'+lead,{field,lead,cycle:c,valid_time:new Date(Date.parse(c)+lead*3600000).toISOString()}]))),assets:Object.fromEntries(Object.keys(ctx.GDIDynamics.FIELDS).flatMap(field=>[0,3].map(lead=>[field+'_'+lead,{path:`generations/${g}/${field}_${lead}.png`,sha256:'a'.repeat(64)}])))};}
 m=metadata();ctx.GDIDynamics.validate(m);
 const map={createPane(){},getPane(){return {style:{}};}},suite=ctx.GDIDynamics.create({map,metadataURL:'https://example.test/metadata.json'});
 const base={model:'rap',cycle,source_metadata:{analysis:{grid_md5:grid},forecast:{grid_md5:grid}}};
 assert.equal(suite.legendHTML(),'','no standalone controls or overlays without a GDI base');
 suite.setContext(base,{valid_time:cycle});await flush();await flush();
 assert.deepEqual(calls.sort(),['div_0','mfc_0']);
 assert.equal(groups.flatMap(g=>g.items).length,2);
 assert.match(suite.legendHTML(),/Dynamics/);
 listeners.change({target:{dataset:{gdiDynamics:'rapGDIDynamics',field:'pw'},checked:true}});await flush();
 assert.equal(groups.flatMap(g=>g.items).length,3);
 // Forecast contexts must select F03, including after an analysis overlay loads.
 const forecast=new Date(Date.parse(cycle)+3*3600000).toISOString();
 suite.setContext(base,{valid_time:forecast});assert.equal(groups.flatMap(g=>g.items).length,0);
 await flush();assert.ok(groups.flatMap(g=>g.items).every(x=>x.url.endsWith('_3')));
 // Never use F03 as an approximation for a missing analysis cycle.
 const next=new Date(Date.parse(cycle)+3600000).toISOString();
 suite.setContext({...base,cycle:next},{valid_time:next});await flush();
 assert.equal(groups.flatMap(g=>g.items).length,0);assert.match(suite.legendHTML(),/Awaiting dynamics/);
 suite.setContext(base,{valid_time:cycle});await flush();
 fail=true;await suite.refresh();assert.equal(groups.flatMap(g=>g.items).length,3,'an outage retains only still-matching fields');fail=false;
 const changed=structuredClone(m);changed.products.mfc_0.valid_time=forecast;
 assert.throws(()=>ctx.GDIDynamics.validate(changed),/Misaligned/);
 const unsafe=structuredClone(m);unsafe.assets.mfc_0.path='../wrong.png';assert.throws(()=>ctx.GDIDynamics.validate(unsafe),/unsafe/);
 const wrong=structuredClone(m);wrong.source_metadata[1].grid_md5='b'.repeat(32);assert.throws(()=>ctx.GDIDynamics.validate(wrong),/Mixed/);
 // A late image response cannot resurrect overlays after the base is disabled.
 let release;pending=new Promise(resolve=>release=resolve);
 listeners.change({target:{dataset:{gdiDynamics:'rapGDIDynamics',field:'rh'},checked:true}});await flush();
 suite.setContext(null,null);release();pending=null;await flush();
 assert.equal(groups.flatMap(g=>g.items).length,0);assert.equal(suite.legendHTML(),'');
 assert.ok(revoked.length,'old object URLs are released');
 // Expired packages must disappear even when the server cannot be reached.
 const old=new Date(Date.parse(cycle)-7*3600000).toISOString();m=metadata(old,old.replace(/[-:T]/g,'').slice(0,10)+'-bbbbbbbbbbbb-v1');
 const expired=ctx.GDIDynamics.create({map,metadataURL:'https://example.test/expired.json',paneName:'expired'});
 expired.setContext({...base,cycle:old},{valid_time:old});await flush();await flush();timer();await flush();
 assert.equal(groups.flatMap(g=>g.items).length,0);
 console.log('RAP dynamics display checks passed: exact cycle/valid time/grid, independent toggles, F03 selection, outage retention, late responses, safe paths and expiry.');
}
main().catch(e=>{console.error(e);process.exitCode=1;});
