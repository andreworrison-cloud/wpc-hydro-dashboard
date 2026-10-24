const assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const flush=()=>new Promise(resolve=>setImmediate(resolve));
const visibleImages=g=>g.images.filter(x=>x.opacity>0);
async function scenario(named,forecast=false){
 const keys=named?['analysis','change']:['gdi','coverage','persistence','longest'];
 const cycle=new Date(Date.now()-3600000).toISOString(),generation=cycle.replace(/[-:]/g,'').slice(0,11).replace('T','')+'-aaaaaaaaaaaa-v1';
 const assets={};const add=k=>assets[k]={path:`generations/${generation}/${k}.png`,sha256:'a'.repeat(64)};
 if(named)keys.forEach(k=>{add(k);add(k+'_numbers');});else{for(let h=0;h<7;h++)for(const p of ['gdi','numbers','coverage30','coverage40','coverage50'])add(p+'_'+h);for(const p of ['persistence','longest'])for(const t of [30,40,50])add(p+t);}
 let m={schema:'gdi_named_suite_v1',schema_version:1,cycle,generation,width:2400,height:1360,crs:'EPSG:3857',resampling:'nearest',bounds:[[24,-125],[50,-66]],assets,overlay_type:'labeled_contours_v1',products:Object.fromEntries(keys.map(k=>[k,{label:k,valid_time:cycle,colors:['#000000','#ffffff'],edges:[0,1],legend:'test'}])),colors:['#000000'],coverage_colors:['#000000'],valid_times:Array.from({length:7},(_,h)=>new Date(Date.parse(cycle)+h*3600000).toISOString())};
 let failContour=true,failBase=false,hold=null,handlers={},listeners={},active=new Set(),revoked=[];
 const map={createPane(){},getPane(){return {style:{}};},hasLayer:g=>active.has(g),on(events,fn){events.split(' ').forEach(e=>handlers[e]=fn);},removeLayer(g){active.delete(g);handlers.layerremove({type:'layerremove',layer:g});},addLayer(g){active.add(g);handlers.layeradd({type:'layeradd',layer:g});}};
 let timerId=0,timers=new Map();
 const ctx={setTimeout:(fn,ms)=>{const id=++timerId;timers.set(id,{fn,ms});return id;},clearTimeout:id=>timers.delete(id),console,URL:{revokeObjectURL:u=>revoked.push(u)},Date,setInterval(){},document:{hidden:false,addEventListener:(n,f)=>listeners[n]=f},L:{layerGroup:()=>({options:{},images:[],clearLayers(){this.images=[];},eachLayer(f){this.images.forEach(f);}}),imageOverlay:(u,b,o)=>({u,opacity:o.opacity,setOpacity(v){this.opacity=v;},addTo(g){g.images.push(this);return this;}})},GDIDisplay:{utc:t=>t,esc:String,scale:()=>'',controls:()=>'',metadata:async()=>structuredClone(m),image:async(meta,k)=>{if(hold)await hold;if(failBase&&!k.includes('numbers'))throw Error('base unavailable');if(failContour&&k.includes('numbers'))throw Error('contour unavailable');return meta.generation+'/'+k;}}};
 vm.runInNewContext(fs.readFileSync(named?'gdi_suite_layer.js':'gdi_layer.js','utf8'),ctx);
 const suite=(named?ctx.GDINamedSuite:ctx.HRRRGDI).create({map,metadataURL:'https://example.test/metadata.json',keys,paneName:'test',forecastGroups:forecast?{analysis:['analysis','change','analysis']}:{}});await flush();
 map.addLayer(suite.layers[keys[0]]);await flush();
 assert.equal(visibleImages(suite.layers[keys[0]]).length,1,'base remains visible if contours fail');
 assert.match(suite.legendHTML(),/contours unavailable/i);
 failContour=false;await suite.refresh();assert.equal(visibleImages(suite.layers[keys[0]]).length,2,'same-generation retry restores contour');
 failBase=true;await suite.refresh(); // Normal unchanged refresh intentionally does not redraw.
 // Force a redraw via a contour toggle, exercising retained data after base failure.
 listeners.change({target:{dataset:named?{gdiSuite:'test'}:{gdiControl:'numbers'},checked:false}});await flush();
 assert.equal(visibleImages(suite.layers[keys[0]]).length,2,'retain verified displayed field on failed update');assert.match(suite.legendHTML(),/retaining/);
 failBase=false;await suite.refresh();assert.doesNotMatch(suite.legendHTML(),/retaining/);
 if(forecast){
  listeners.change({target:{dataset:{gdiForecast:'test'},value:'1'}});await flush();
  assert.ok(visibleImages(suite.layers.analysis)[0].u.endsWith('/change'),'valid-time control selects the corresponding immutable image');
  assert.ok(map.hasLayer(suite.layers.analysis),'forecast time changes preserve the selected menu layer');
  assert.match(suite.legendHTML(),/<strong>change<\/strong>/);
  listeners.change({target:{dataset:{gdiForecast:'test'},value:'0'}});await flush();
 }
 let release;hold=new Promise(r=>release=r);listeners.change({target:{dataset:named?{gdiSuite:'test'}:{gdiControl:'numbers'},checked:true}});
 map.removeLayer(suite.layers[keys[0]]);map.addLayer(suite.layers[keys[1]]);release();hold=null;await flush();
 assert.equal(suite.layers[keys[0]].images.length,0,'late old request cannot overwrite new selection');assert.ok(suite.layers[keys[1]].images.length);
 if(named){m={...m,expires_at:new Date(Date.now()-1).toISOString(),generation:generation.replace('aaaaaaaaaaaa','bbbbbbbbbbbb')};for(const a of Object.values(m.assets))a.path=a.path.replace(generation,m.generation);await suite.refresh();assert.equal(suite.layers[keys[1]].images.length,0);assert.match(suite.legendHTML(),/window ended/);}
}
async function hourlyLoop(){
 const cycle=new Date(Math.floor(Date.now()/3600000)*3600000).toISOString();
 let generation=cycle.replace(/[-:]/g,'').slice(0,11).replace('T','')+'-cccccccccccc-v1';
 const keys=Array.from({length:7},(_,h)=>'hrrr'+h);
 function metadata(){return {schema:'gdi_named_suite_v1',recipe:'gdi_focused_v3',kind:'forecast',cycle,generation,width:2400,height:1360,crs:'EPSG:3857',bounds:[[24,-125],[50,-66]],resampling:'nearest',overlay_type:'labeled_contours_v1',products:Object.fromEntries(keys.map((k,i)=>[k,{label:'HRRR GDI',valid_time:new Date(Date.parse(cycle)+i*3600000).toISOString(),legend:'Hourly loop',unit:'GDI'}])),assets:Object.fromEntries(keys.flatMap(k=>[k,k+'_numbers']).map(k=>[k,{path:`generations/${generation}/${k}.png`,sha256:'a'.repeat(64)}]))};}
 let m=metadata(),id=0,timers=new Map(),listeners={},handlers={},active=new Set(),calls=0,failKey=null;
 const map={createPane(){},getPane(){return {style:{}};},hasLayer:g=>active.has(g),on(events,fn){events.split(' ').forEach(e=>handlers[e]=fn);},removeLayer(g){active.delete(g);handlers.layerremove({type:'layerremove',layer:g});},addLayer(g){active.add(g);handlers.layeradd({type:'layeradd',layer:g});}};
 const ctx={Date,console,URL:{revokeObjectURL(){}},setInterval(){},setTimeout:(fn,ms)=>{timers.set(++id,{fn,ms});return id;},clearTimeout:n=>timers.delete(n),document:{hidden:false,addEventListener:(n,f,capture)=>{if(n==='click')assert.equal(capture,true,'playback clicks must be captured before Leaflet stops bubbling');listeners[n]=f;}},L:{layerGroup:()=>({options:{},images:[],clearLayers(){this.images=[];},eachLayer(f){this.images.forEach(f);}}),imageOverlay:(u,b,o)=>({u,opacity:o.opacity,setOpacity(v){this.opacity=v;},addTo(g){g.images.push(this);return this;}})},GDIDisplay:{utc:t=>t,scale:()=>'',controls:()=>'',metadata:async()=>structuredClone(m),image:async(meta,k)=>{calls++;if(k===failKey)throw Error('missing frame');return meta.generation+'/'+k;}}};
 vm.runInNewContext(fs.readFileSync('gdi_suite_layer.js','utf8'),ctx);
 const suite=ctx.GDINamedSuite.create({map,metadataURL:'https://example.test/hourly.json',keys,paneName:'hourly',requiredRecipe:'gdi_focused_v3',forecastGroups:{hrrr0:keys}});await flush();map.addLayer(suite.layers.hrrr0);await flush();
 assert.equal(calls,14,'preload all seven shading and contour pairs');
 const firstImages=suite.layers.hrrr0.images.slice();assert.equal(firstImages.length,14);
 assert.equal(visibleImages(suite.layers.hrrr0).length,2);
 assert.match(suite.legendHTML(),/Frame 1 \/ 7/);assert.match(suite.legendHTML(),/Pause GDI forecast loop/);
 function tick(){const [n,t]=timers.entries().next().value;timers.delete(n);t.fn();return t.ms;}
 for(let i=1;i<=7;i++){assert.equal(tick(),800);assert.ok(visibleImages(suite.layers.hrrr0)[0].u.endsWith('/hrrr'+i%7));}
 assert.deepEqual(suite.layers.hrrr0.images,firstImages,'playback reuses mounted overlays');
 suite.layers.hrrr0.setOpacity(.3);assert.equal(visibleImages(suite.layers.hrrr0).length,2,'opacity changes do not reveal other hours');
 assert.equal(visibleImages(suite.layers.hrrr0)[0].opacity,.3);
 listeners.click({target:{dataset:{gdiPlay:'hourly'}}});assert.equal(timers.size,0,'pause stops playback');
 listeners.change({target:{dataset:{gdiForecast:'hourly'},value:'6'}});await flush();
 assert.ok(visibleImages(suite.layers.hrrr0)[0].u.endsWith('/hrrr6'));assert.equal(calls,14,'scrubbing reuses the verified buffer');
 assert.match(suite.legendHTML(),new RegExp(m.products.hrrr6.valid_time.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')));
 listeners.click({target:{dataset:{gdiStep:'hourly',direction:'-1'}}});assert.ok(visibleImages(suite.layers.hrrr0)[0].u.endsWith('/hrrr5'));
 listeners.change({target:{dataset:{gdiSpeed:'hourly'},value:'1400'}});listeners.click({target:{dataset:{gdiPlay:'hourly'}}});assert.equal(tick(),1400);
 generation=generation.replace('cccccccccccc','dddddddddddd');m=metadata();failKey='hrrr3';await suite.refresh();
 assert.ok(visibleImages(suite.layers.hrrr0)[0].u.includes('cccccccccccc'),'an incomplete new loop retains its verified prior generation');assert.match(suite.legendHTML(),/retaining/);
 m={...m,kind:'tle',status:'awaiting_hourly_inputs',status_message:'Hourly RRFS GDI inputs unavailable',products:{},assets:{},generation:generation.replace('dddddddddddd','eeeeeeeeeeee'),built_at:cycle,window_start:cycle,window_end:new Date(Date.parse(cycle)+12*3600000).toISOString()};await suite.refresh();
 assert.equal(suite.layers.hrrr0.images.length,0,'hourly-input status removes old shading');assert.equal(timers.size,0);assert.match(suite.legendHTML(),/Hourly RRFS/);
 console.log('Hourly GDI loop tests passed: seven frames, wrap, pause, scrub, speed, generation failure retention, unavailable-input clearing.');
}
(async()=>{await scenario(true);await scenario(false);await scenario(true,true);await hourlyLoop();
 const ctx={URL,AbortController,setTimeout,clearTimeout,Date,fetch:async()=>{throw Error('network');}};vm.runInNewContext(fs.readFileSync('gdi_display.js','utf8'),ctx);
 let calls=0;ctx.fetch=async()=>{calls++;if(calls===1)return {ok:false,status:503};return {ok:true,json:async()=>({ok:true})};};assert.equal((await ctx.GDIDisplay.metadata('https://example.test/m.json')).ok,true);assert.equal(calls,2);
 const legend=ctx.GDIDisplay.scale(['#000000','#ffffff'],[0,100],'Support (%)');assert.match(legend,/left:50%/);assert.match(legend,/≥100/);
 console.log('GDI display tests passed: contour isolation/recovery, retained frames, selection races, expiry, transport retry, scale alignment.');
})().catch(e=>{console.error(e);process.exitCode=1;});
