/* GDI suites: immutable frames, hourly forecast loops, labeled contours. */
(function(root){
'use strict';
const esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const commonForecast=m=>m?.kind==='forecast'&&m.forecast_sampling==='common_valid_hourly_v1';
function validate(m,keys,previous){
 const interpolated=m?.model==='rap'&&m.resampling==='masked_bilinear'&&m.display_rendering==='rap_scalar_bilinear_v1';
 if(m?.schema!=='gdi_named_suite_v1'||m.width!==2400||m.height!==1360||m.crs!=='EPSG:3857'||!(m.resampling==='nearest'||interpolated)||!/^\d{10}-[a-f0-9]{12}-v1$/.test(m.generation)||JSON.stringify(m.bounds)!=='[[24,-125],[50,-66]]'||!Number.isFinite(Date.parse(m.cycle)))throw Error('Invalid GDI suite');
 if(previous&&Date.parse(m.cycle)<Date.parse(previous.cycle))throw Error('Regressing suite');
 if(previous?.generation===m.generation&&JSON.stringify(previous)!==JSON.stringify(m))throw Error('Changed immutable suite');
 if(m.status==='awaiting_hourly_inputs'){
  if(m.kind!=='tle'||m.recipe!=='gdi_focused_v3'||Object.keys(m.assets||{}).length||Object.keys(m.products||{}).length||!m.status_message)throw Error('Invalid hourly-input status');
  return;
 }
 keys.forEach(k=>{if(!m.products[k]||!Number.isFinite(Date.parse(m.products[k].valid_time)))throw Error('Missing product/time');for(const suffix of ['','_numbers']){const a=m.assets[k+suffix];if(a?.path!==`generations/${m.generation}/${k+suffix}.png`||!/^[a-f0-9]{64}$/.test(a.sha256))throw Error('Invalid image');}});
 if(commonForecast(m)){
  const start=Date.parse(m.window_start),end=Date.parse(m.window_end),built=Date.parse(m.built_at);
  if(!Number.isFinite(start)||Math.floor(built/3600000)*3600000!==start||end-start!==6*3600000||Date.parse(m.expires_at)!==end||m.sample_count!==7||m.sample_times?.length!==7)throw Error('Invalid common forecast window');
  for(let h=0;h<7;h++){
   const valid=start+h*3600000;if(Date.parse(m.sample_times[h])!==valid)throw Error('Misaligned forecast samples');
   for(const model of ['hrrr','rrfs','blend']){
    const p=m.products[model+h];if(!p||Date.parse(p.valid_time)!==valid)throw Error('Misaligned forecast frame');
    if(model!=='blend'&&(!Number.isInteger(p.forecast_hour)||Date.parse(p.cycle)+p.forecast_hour*3600000!==valid))throw Error('Invalid forecast cycle/lead');
   }
  }
 }
}
function create({map,metadataURL,keys,paneName,forecastGroups={},requiredRecipe=null,onChange=()=>{}}){
 const ui=root.GDIDisplay;
 let metadata=null,shown=null,buffer=null,failed=false,numbers=true,serial=0,contourFailed=false,loading=false,lastCheck=0,refreshing=null,forecastIndex=0,forecastValidTime=null,playing=true,speed=800,timer=null,switching=false;
 const layers={};
 map.createPane(paneName);map.getPane(paneName).style.zIndex=340;map.getPane(paneName).style.pointerEvents='none';
 keys.forEach(k=>{const g=L.layerGroup();g.options.opacity=.8;g.setOpacity=v=>{g.options.opacity=v;if(buffer?.base===k)buffer.frames.forEach((f,i)=>f.overlays.forEach(o=>o.setOpacity(!buffer.loop||i===forecastIndex?v:0)));else g.eachLayer(x=>x.setOpacity(v));};layers[k]=g;});
 const selected=()=>keys.find(k=>map.hasLayer(layers[k]));
 const expired=m=>m?.expires_at&&Date.now()>=Date.parse(m.expires_at);
 const release=b=>{if(b)b.frames.forEach(f=>f.urls.forEach(URL.revokeObjectURL));};
 function stop(){if(timer!==null)clearTimeout(timer);timer=null;}
 function clear(){stop();keys.forEach(k=>layers[k].clearLayers());release(buffer);buffer=null;shown=null;}
 function schedule(){
  stop();if(!playing||document.hidden||!buffer?.loop||selected()!==buffer.base||expired(buffer.m))return;
  timer=setTimeout(()=>{timer=null;if(!buffer||expired(buffer.m)){draw();return;}forecastIndex=(forecastIndex+1)%buffer.frames.length;showFrame();},speed);
 }
 function showFrame(){
  if(!buffer)return;
  const base=selected();if(base!==buffer.base)return;
  forecastIndex=Math.min(forecastIndex,buffer.frames.length-1);
  const f=buffer.frames[buffer.loop?forecastIndex:0];
  if(buffer.loop&&commonForecast(buffer.m))forecastValidTime=buffer.m.products[f.key].valid_time;
  // Keep decoded overlays mounted: playback changes visibility, not image URLs.
  buffer.frames.forEach((frame,index)=>frame.overlays.forEach(o=>o.setOpacity(!buffer.loop||index===forecastIndex?layers[base].options.opacity:0)));
  shown={m:buffer.m,k:f.key,base};onChange();schedule();
 }
 async function draw(){
  stop();const base=selected(),token=++serial,m=metadata;
  if(!base||!m){if(!base)clear();loading=false;onChange();return;}
  if(expired(m)||m.status==='awaiting_hourly_inputs'){clear();loading=false;onChange();return;}
  const want=numbers&&m.overlay_type==='labeled_contours_v1',group=forecastGroups[base];
  if(buffer?.base===base&&buffer.m.generation===m.generation&&buffer.want===want&&!failed&&!contourFailed){showFrame();return;}
  loading=true;onChange();
  // Complete the loop before playback: never skip a missing hour or mix generations.
  const result=await Promise.all((group||[base]).map(async key=>{
   const parts=await Promise.allSettled([key,...(want?[key+'_numbers']:[])].map(k=>ui.image(m,k,metadataURL)));
   return {key,baseOK:parts[0].status==='fulfilled',contourOK:!want||parts[1].status==='fulfilled',urls:parts.filter(x=>x.status==='fulfilled').map(x=>x.value)};
  }));
  const fresh={m,base,want,loop:!!group,frames:result};
  if(token!==serial){release(fresh);return;}
  loading=false;
  if(result.some(f=>!f.baseOK)){release(fresh);failed=true;onChange();schedule();return;}
  if(expired(m)){release(fresh);clear();onChange();return;}
  contourFailed=result.some(f=>!f.contourOK);
  if(group&&commonForecast(m)&&forecastValidTime&&(buffer?.m.generation!==m.generation||buffer?.base!==base)){
   const time=Date.parse(forecastValidTime),i=group.findIndex(k=>Date.parse(m.products[k].valid_time)===time);
   forecastIndex=i>=0?i:time<Date.parse(m.products[group[0]].valid_time)?0:group.length-1;
  }
  keys.forEach(k=>layers[k].clearLayers());release(buffer);buffer=fresh;
  buffer.frames.forEach(f=>{f.overlays=f.urls.map(u=>L.imageOverlay(u,m.bounds,{pane:paneName,opacity:0,interactive:false}).addTo(layers[base]));});
  failed=false;showFrame();
 }
 function refresh(){
  if(refreshing)return refreshing;
  refreshing=(async()=>{try{
   const m=await ui.metadata(metadataURL);if(requiredRecipe&&m.recipe!==requiredRecipe)throw Error('Awaiting current product definition');validate(m,keys,metadata);lastCheck=Date.now();
   const changed=m.generation!==metadata?.generation;metadata=m;
   if(changed||failed||contourFailed||expired(m)||!shown)await draw();else onChange();
  }catch(e){failed=true;if(expired(metadata)){++serial;clear();}onChange();}
  finally{refreshing=null;}})();return refreshing;
 }
 map.on('layeradd layerremove',e=>{
  if(switching)return;
  const k=keys.find(x=>layers[x]===e.layer);if(!k)return;
  if(e.type==='layeradd'){switching=true;try{keys.filter(x=>x!==k).forEach(x=>{if(map.hasLayer(layers[x]))map.removeLayer(layers[x]);});}finally{switching=false;}}
  draw();if(e.type==='layeradd'&&(!metadata||Date.now()-lastCheck>60000))refresh();
 });
 document.addEventListener('change',e=>{
  if(e.target?.dataset?.gdiSuite===paneName){numbers=e.target.checked;draw();}
  else if(e.target?.dataset?.gdiForecast===paneName){const i=Number(e.target.value),group=forecastGroups[selected()];if(Number.isInteger(i)&&i>=0&&i<(group?.length||0)){playing=false;forecastIndex=i;const displayed=buffer?.m||metadata;if(commonForecast(displayed))forecastValidTime=displayed.products[group[i]].valid_time;draw();}}
  else if(e.target?.dataset?.gdiSpeed===paneName){const value=Number(e.target.value);if([400,800,1400].includes(value)){speed=value;schedule();}}
 });
 // Leaflet stops bubbling clicks inside controls. Capture these first.
 document.addEventListener('click',e=>{
  const t=e.target?.closest?.('[data-gdi-play],[data-gdi-step]')||e.target;
  if(t?.dataset?.gdiPlay===paneName){playing=!playing;onChange();schedule();}
  else if(t?.dataset?.gdiStep===paneName&&buffer?.loop){playing=false;forecastIndex=(forecastIndex+Number(t.dataset.direction)+buffer.frames.length)%buffer.frames.length;showFrame();}
 },true);
 document.addEventListener('focusin',e=>{if(e.target?.dataset?.gdiForecast===paneName){playing=false;stop();onChange();}});
 document.addEventListener('visibilitychange',()=>{if(document.hidden)stop();else if(selected()){refresh();schedule();}});
 function legendHTML(){
  const base=selected();if(!base)return '';
  const open='<div class="gdi-legend" data-gdi-pane="'+esc(paneName)+'">';
  if(metadata?.status==='awaiting_hourly_inputs')return open+'<strong>HRRR/RRFS TLE</strong><div class="gdi-status">'+esc(metadata.status_message)+'</div><div class="gdi-note">'+(expired(metadata)?'Awaiting the current F00–F12 window. ':'Requested period '+ui.utc(metadata.window_start)+' – '+ui.utc(metadata.window_end)+'. ')+'Last source check '+ui.utc(metadata.built_at)+'.</div></div>';
  const group=forecastGroups[base],k=group?.[forecastIndex]||base;
  const d=shown?.base===base?shown:null,m=d?.m,p=m?.products[d?.k];
  if(!d)return open+'<strong>'+esc(metadata?.products[k]?.label||'GDI')+'</strong><div class="gdi-status">'+(expired(metadata)?'Forecast window ended · awaiting current guidance':failed?'Data unavailable · retrying automatically':group?'Loading hourly forecast loop…':'Loading selected field…')+'</div></div>';
  let html=open+'<strong>'+esc(p.label)+'</strong>';
  html+='<div class="gdi-time">'+(p.window_start?'Period '+ui.utc(p.window_start)+' – '+ui.utc(p.valid_time):'Valid '+ui.utc(p.valid_time))+'</div>';
  html+='<div class="gdi-note">'+(p.source_label?esc(p.source_label):esc((m.model||'Model').toUpperCase())+' cycle '+ui.utc(p.cycle||m.cycle))+'</div>';
  if(group&&commonForecast(m))html+='<div class="gdi-note">Window '+ui.utc(m.window_start)+' – '+ui.utc(m.window_end)+'</div>';
  if(loading)html+='<div class="gdi-status">Loading update · displayed times shown above</div>';
  else if(failed)html+='<div class="gdi-status">Update unavailable · retaining displayed data; retrying</div>';
  if(contourFailed)html+='<div class="gdi-status">Some contours unavailable · shading loaded; retrying</div>';
  if(group){
   html+='<div class="gdi-controls gdi-playback"><button type="button" data-gdi-step="'+paneName+'" data-direction="-1" aria-label="Previous GDI forecast frame">◀</button><button type="button" data-gdi-play="'+paneName+'" aria-label="'+(playing?'Pause':'Play')+' GDI forecast loop">'+(playing?'Pause':'Play')+'</button><button type="button" data-gdi-step="'+paneName+'" data-direction="1" aria-label="Next GDI forecast frame">▶</button><span>Frame '+(forecastIndex+1)+' / '+group.length+'</span></div>';
   html+='<div class="gdi-controls"><label>Valid time <select aria-label="GDI forecast valid time" data-gdi-forecast="'+paneName+'">'+group.map((key,i)=>'<option value="'+i+'" '+(i===forecastIndex?'selected':'')+'>'+esc(ui.utc(m.products[key].valid_time))+'</option>').join('')+'</select></label><label>Speed <select aria-label="GDI forecast loop speed" data-gdi-speed="'+paneName+'">'+[[1400,'Slow'],[800,'Normal'],[400,'Fast']].map(([v,label])=>'<option value="'+v+'" '+(v===speed?'selected':'')+'>'+label+'</option>').join('')+'</select></label></div>';
  }
  html+=ui.controls('data-gdi-suite="'+paneName+'"',numbers);
  const unit=p.unit||(k==='change'?'GDI change (3 h)':'GDI');
  html+=ui.scale(p.colors||[],p.edges||[],unit,{zeroCentered:k==='change'});
  if(m.display_rendering==='rap_scalar_bilinear_v1')html+='<div class="gdi-note">13-km RAP · interpolated display</div>';
  html+='<div class="gdi-note">'+esc(p.legend)+'</div></div>';return html;
 }
 refresh();setInterval(()=>{if(selected()&&(failed||contourFailed||Date.now()-lastCheck>=120000||expired(metadata)))refresh();},15000);
 return {layers,legendHTML,refresh};
}
root.GDINamedSuite={create,validate};
})(typeof window==='undefined'?globalThis:window);
