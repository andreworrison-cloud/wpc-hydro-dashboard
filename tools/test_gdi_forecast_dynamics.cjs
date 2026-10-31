const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const flush=()=>new Promise(r=>setImmediate(r));
async function main(){
 let now=Math.floor(Date.now()/3600000)*3600000,metadata,offline=false,blocked=null,failKey=null,calls=[],metadataCalls=0;
 const groups=[],listeners={},timers=[],revoked=[];
 class Clock extends Date{static now(){return now;}}
 const context={console,Date:Clock,Object,JSON,URL:{revokeObjectURL:u=>revoked.push(u)},setInterval:fn=>timers.push(fn),
  document:{addEventListener:(event,fn)=>listeners[event]=fn},
  L:{layerGroup:()=>({items:[],addTo(){groups.push(this);return this;},clearLayers(){this.items=[];}}),
     imageOverlay:(url,bounds,options)=>({url,bounds,options,setOpacity(value){this.options.opacity=value;return this;},addTo(g){g.items.push(this);return this;}})},
  GDIDisplay:{esc:String,utc:String,metadata:async()=>{metadataCalls++;if(offline)throw Error('offline');return structuredClone(metadata);},
              image:async(m,key)=>{calls.push(key);if(blocked)await blocked;if(key===failKey)throw Error('missing hour');return m.generation+'/'+key;}}};
 vm.runInNewContext(fs.readFileSync('gdi_dynamics_layer.js','utf8'),context);
 const iso=t=>new Date(t).toISOString(),start=now,times=Array.from({length:7},(_,h)=>iso(start+h*3600000));
 const base={kind:'forecast',forecast_sampling:'common_valid_hourly_v1',selection_signature:'d'.repeat(64),sample_times:times,products:{},source_metadata:[]},native=[];
 for(const [model,age,grid] of [['hrrr',1,'a'.repeat(32)],['rrfs',2,'b'.repeat(32)]]){
  const cycle=iso(start-age*3600000),samples=times.map((valid_time,h)=>({cycle,lead:age+h,valid_time,grid_md5:grid}));
  base.source_metadata.push({model,cycle,samples});
  native.push(...samples.map(s=>({model,cycle,lead:s.lead,grid_md5:grid,recipe:'cam_gdi_dynamics_v1',smoothing_sigma_km:20,sources:[{variable:'PRES'}],sha256:'a'.repeat(64),projection:{lat_1:38.5}})));
 }
 for(const model of ['hrrr','rrfs','blend'])for(let h=0;h<7;h++)base.products[model+h]={valid_time:times[h]};
 const frames=context.GDIDynamics.forecastContexts(base),generation=times[0].replace(/[-:T]/g,'').slice(0,10)+'-aaaaaaaaaaaa-v1';
 metadata={schema:'gdi_forecast_dynamics_v1',recipe:'cam_gdi_dynamics_v1',model:'hrrr_rrfs',cycle:base.source_metadata[0].cycle,window_start:times[0],window_end:times[6],expires_at:times[6],sample_times:times,base_selection_signature:base.selection_signature,frame_contexts:frames,source_metadata:native,definitions:structuredClone(context.GDIDynamics.FIELDS),smoothing_sigma_km:20,generation,width:2400,height:1360,bounds:[[24,-125],[50,-66]],crs:'EPSG:3857',resampling:'masked_bilinear',products:{},assets:{}};
 for(const frame of Object.keys(frames))for(const field of Object.keys(context.GDIDynamics.FIELDS)){
  const key=field+'_'+frame;metadata.products[key]={field,frame,valid_time:frames[frame].valid_time};metadata.assets[key]={path:`generations/${generation}/${key}.png`,sha256:'a'.repeat(64)};
 }
 context.GDIDynamics.validateForecast(metadata);
 const map={createPane(){},getPane(){return {style:{}};}},suite=context.GDIDynamics.createForecast({map,metadataURL:'https://example.test/metadata.json'});
 const all=()=>groups.flatMap(g=>g.items),visible=()=>all().filter(o=>o.options.opacity===1),set=key=>suite.setContext(base,base.products[key],key);
 const toggle=(field,checked)=>listeners.change({target:{dataset:{gdiDynamics:'forecastGDIDynamics',field},checked}});
 assert.equal(suite.legendHTML(),'');set('hrrr0');await flush();await flush();
 assert.equal(calls.length,14);assert.equal(all().length,14);assert.equal(visible().length,2);
 assert.ok(visible().every(o=>o.url.endsWith('hrrr0')));
 for(let h=0;h<35;h++)set('hrrr'+h%7);
 assert.equal(calls.length,14,'playback uses already-loaded complete companion loops');
 assert.equal(metadataCalls,1);assert.equal(all().length,14);assert.equal(revoked.length,0);
 // One missing hour hides the whole companion loop, not just that hour.
 failKey='upper_hrrr3';toggle('upper',true);await flush();
 assert.equal(all().length,14);assert.match(suite.legendHTML(),/Some dynamics unavailable/);
 const attempts=calls.length;set('hrrr1');set('hrrr2');assert.equal(calls.length,attempts,'failed assets are throttled across animation steps');
 failKey=null;now+=16000;timers[0]();await flush();await flush();
 assert.equal(all().length,21);assert.equal(visible().length,3);toggle('upper',false);
 // Optional fields do not appear until their seven frames all finish loading.
 let release;blocked=new Promise(r=>release=r);toggle('pw',true);await flush();
 assert.equal(visible().length,2);set('hrrr6');release();blocked=null;await flush();await flush();
 assert.equal(all().length,21);assert.ok(visible().every(o=>o.url.endsWith('hrrr6')));
 set('rrfs6');assert.equal(visible().length,0);await flush();
 assert.equal(all().length,21);assert.ok(visible().every(o=>o.url.endsWith('rrfs6')));
 set('blend6');await flush();assert.ok(visible().every(o=>o.url.endsWith('blend6')));
 const changed=structuredClone(base);changed.source_metadata[1].samples[6].grid_md5='c'.repeat(32);
 suite.setContext(changed,changed.products.blend6,'blend6');await flush();assert.equal(visible().length,0);
 assert.match(suite.legendHTML(),/Awaiting companions/);set('blend6');await flush();
 offline=true;await suite.refresh();assert.equal(visible().length,3,'retain only matching unexpired companions during an outage');offline=false;
 // Disabling GDI while downloads finish cannot resurrect its companions.
 blocked=new Promise(r=>release=r);toggle('rh',true);await flush();suite.setContext(null,null);release();blocked=null;await flush();
 assert.equal(all().length,0);assert.equal(suite.legendHTML(),'');
 set('hrrr0');await flush();assert.ok(visible().length>0);
 for(const mutate of [m=>m.assets.pw_rrfs6.path='../unsafe.png',m=>m.products.div_hrrr2.valid_time=times[3],m=>m.frame_contexts.blend0.sources.pop(),m=>m.source_metadata[0].grid_md5='c'.repeat(32),m=>m.smoothing_sigma_km=3]){
  const m=structuredClone(metadata);mutate(m);assert.throws(()=>context.GDIDynamics.validateForecast(m));
 }
 offline=true;now=start+6*3600000;timers[0]();await flush();
 assert.equal(all().length,0);assert.ok(revoked.length>0);
 console.log('CAM dynamics display PASS: 126-asset contract, exact model sources, complete-loop preload, playback without refetch, independent toggles, blend/grid guards, throttled retries, late responses, expiry and outage retention.');
}
main().catch(e=>{console.error(e);process.exitCode=1;});
