/* Optional GDI companion overlays. Every overlay matches the displayed base time. */
(function(root){
'use strict';
const FIELDS={
 mfc:{label:'Moisture convergence',unit:'g kg⁻¹ h⁻¹',layer:'950–700 hPa · above-ground segments',levels:[-8,-4,-2,-1,1,2,4,8],color:'#56f29a',negative_color:'#dcab82',kind:'contours'},
 div:{label:'Upper divergence',unit:'10⁻⁵ s⁻¹',layer:'400–200 hPa',levels:[-12,-8,-4,-2,2,4,8,12],color:'#ffe16b',negative_color:'#91b8ff',kind:'contours'},
 rh:{label:'Upper humidity',unit:'%',layer:'400–300 hPa',levels:[30,50,70,90],color:'#f4b5c8',kind:'contours'},
 pw:{label:'Precipitable water',unit:'in',layer:'Total atmospheric column',levels:[.5,1,1.5,2,2.5,3,3.5],color:'#72e3ff',kind:'contours'},
 low:{label:'Low-level flow',unit:'kt',layer:'1000–850 hPa · above-ground segments',color:'#f5f5ef',kind:'barbs'},
 upper:{label:'Upper-level flow',unit:'kt',layer:'400–200 hPa',color:'#a8c2ff',kind:'barbs'}
};
function validate(m){
 const cycle=Date.parse(m?.cycle);
 if(m?.schema!=='gdi_dynamics_suite_v1'||m.recipe!=='rap_gdi_dynamics_v1'||m.model!=='rap'||m.crs!=='EPSG:3857'||m.width!==2400||m.height!==1360||JSON.stringify(m.bounds)!=='[[24,-125],[50,-66]]'||m.smoothing_sigma_km!==20||!/^\d{10}-[a-f0-9]{12}-v1$/.test(m.generation)||!Number.isFinite(cycle)||cycle%3600000||Date.parse(m.expires_at)!==cycle+6*3600000)throw Error('Invalid RAP dynamics metadata');
 if(Object.keys(m.products||{}).length!==12||Object.keys(m.assets||{}).length!==12||Object.keys(m.definitions||{}).length!==6||m.source_metadata?.length!==2)throw Error('Incomplete RAP dynamics');
 Object.entries(FIELDS).forEach(([name,definition])=>{
  if(Object.keys(m.definitions[name]||{}).length!==Object.keys(definition).length||Object.entries(definition).some(([k,v])=>JSON.stringify(m.definitions[name][k])!==JSON.stringify(v)))throw Error('Changed dynamics definition');
  [0,3].forEach(lead=>{const key=name+'_'+lead,p=m.products[key],a=m.assets[key];if(p?.field!==name||p.lead!==lead||p.cycle!==m.cycle||Date.parse(p.valid_time)!==cycle+lead*3600000||a?.path!==`generations/${m.generation}/${key}.png`||!/^[a-f0-9]{64}$/.test(a.sha256))throw Error('Misaligned or unsafe dynamics asset');});
 });
 m.source_metadata.forEach((s,i)=>{if(s.model!=='rap'||s.recipe!==m.recipe||s.cycle!==m.cycle||s.lead!==i*3||!/^[a-f0-9]{32}$/.test(s.grid_md5))throw Error('Invalid dynamics provenance');});
 if(m.source_metadata[0].grid_md5!==m.source_metadata[1].grid_md5)throw Error('Mixed dynamics grids');
}
function create({map,metadataURL,paneName='rapGDIDynamics',onChange=()=>{}}){
 const ui=root.GDIDisplay,enabled={mfc:true,div:true,rh:false,pw:false,low:false,upper:false};
 let context=null,packages=[],serial=0,fetching=null,loading=false,failed=false,errors=[],lastCheck=0;
 const buffers=new Map(),groups={};
 map.createPane(paneName);map.getPane(paneName).style.zIndex=355;map.getPane(paneName).style.pointerEvents='none';
 Object.keys(FIELDS).forEach(k=>{groups[k]=L.layerGroup().addTo(map);});
 const expired=m=>Date.now()>=Date.parse(m.expires_at);
 const signature=c=>c?`${c.cycle}/${c.lead}/${c.grid_md5}`:'';
 const matching=m=>context&&m.cycle===context.cycle&&!expired(m)&&m.source_metadata[context.lead===3?1:0].grid_md5===context.grid_md5;
 function drop(k){const b=buffers.get(k);groups[k].clearLayers();if(b)URL.revokeObjectURL(b.url);buffers.delete(k);}
 function clear(){Object.keys(FIELDS).forEach(drop);}
 async function draw(){
  const token=++serial,c=context,m=packages.find(matching);
  if(!c||!m){clear();loading=false;onChange();return;}
  Object.keys(FIELDS).filter(k=>!enabled[k]).forEach(drop);
  const names=Object.keys(FIELDS).filter(k=>enabled[k]&&buffers.get(k)?.generation!==m.generation);
  if(!names.length){loading=false;onChange();return;}
  loading=true;onChange();
  const results=await Promise.allSettled(names.map(k=>ui.image(m,k+'_'+c.lead,metadataURL)));
  if(token!==serial||signature(c)!==signature(context)||expired(m)){
   results.forEach(r=>{if(r.status==='fulfilled')URL.revokeObjectURL(r.value);});
   if(token===serial){clear();loading=false;onChange();}return;
  }
  errors=[];
  results.forEach((r,i)=>{
   const k=names[i];
   if(r.status==='rejected'){errors.push(k);return;}
   drop(k);L.imageOverlay(r.value,m.bounds,{pane:paneName,opacity:1,interactive:false}).addTo(groups[k]);
   buffers.set(k,{url:r.value,generation:m.generation});
  });
  loading=false;onChange();
 }
 function setContext(m,p){
  const lead=m?.model==='rap'?(Date.parse(p?.valid_time)-Date.parse(m.cycle))/3600000:null;
  let next=[0,3].includes(lead)?{cycle:m.cycle,lead,valid_time:p.valid_time,grid_md5:m.source_metadata?.[lead===3?'forecast':'analysis']?.grid_md5}:null;
  if(next&&!next.grid_md5)next=null;
  if(signature(next)===signature(context))return;
  ++serial;clear();context=next;errors=[];draw();
  if(context&&(!packages.length||Date.now()-lastCheck>60000))refresh();
 }
 function refresh(){
  if(fetching)return fetching;
  fetching=(async()=>{try{
   const m=await ui.metadata(metadataURL);validate(m);
   if(packages[0]&&Date.parse(m.cycle)<Date.parse(packages[0].cycle))throw Error('Regressing dynamics cycle');
   const same=packages.find(x=>x.generation===m.generation);
   if(same&&JSON.stringify(same)!==JSON.stringify(m))throw Error('Changed immutable dynamics generation');
   const displayed=packages.find(matching);
   packages=[m,...(displayed&&displayed.generation!==m.generation?[displayed]:packages.filter(x=>x.generation!==m.generation))].slice(0,2);failed=false;lastCheck=Date.now();await draw();
  }catch(e){failed=true;if(!packages.some(matching))clear();onChange();}finally{fetching=null;}})();return fetching;
 }
 document.addEventListener('change',e=>{
  const t=e.target;
  if(t?.dataset?.gdiDynamics!==paneName||!Object.hasOwn(FIELDS,t.dataset.field))return;
  enabled[t.dataset.field]=t.checked;draw();
 });
 function legendHTML(){
  if(!context)return '';
  const m=packages.find(matching),esc=ui.esc;
  let html='<div class="gdi-dynamics"><strong>Dynamics</strong><div class="gdi-dynamics-options">';
  Object.entries(FIELDS).forEach(([k,d])=>{html+='<label><input type="checkbox" data-gdi-dynamics="'+paneName+'" data-field="'+k+'" '+(enabled[k]?'checked':'')+'> '+esc(d.label)+'</label>';});
  html+='</div><div class="gdi-dynamics-status gdi-status">'+(!m?'Awaiting dynamics for this RAP cycle and valid time':loading?'Loading selected dynamics…':errors.length?'Some dynamics unavailable · retrying':failed?'Update unavailable · retaining matching dynamics':'')+'</div>';
  Object.entries(FIELDS).forEach(([k,d])=>{
   if(!enabled[k])return;
   const levels=d.levels?.filter(v=>v>0).join(' / ');
   html+='<div class="gdi-dynamics-key"><i style="color:'+d.color+'"></i>'+esc(d.label)+' · '+esc(d.unit)+'<small>'+esc(d.layer)+(levels?' · '+esc(levels):' · barbs ≥10 kt')+'</small>';
   if(d.negative_color)html+='<small><i class="is-negative" style="color:'+d.negative_color+'"></i>'+(k==='mfc'?'Moisture divergence':'Upper convergence')+' · same magnitudes</small>';
   html+='</div>';
  });
  html+='<div class="gdi-note">RAP '+esc(ui.utc(context.valid_time))+' · '+(context.lead?'F03':'analysis')+'<br>Nominal 20-km Gaussian sigma. Below-ground levels excluded; moisture convergence requires ≥100 hPa of valid layer.</div></div>';
  return html;
 }
 setInterval(()=>{if(context){if(!packages.some(matching)){++serial;clear();onChange();}if(failed||errors.length||Date.now()-lastCheck>=120000)refresh();}},15000);
 return {setContext,legendHTML,refresh};
}
function forecastContexts(base){
 const out={};
 for(let h=0;h<7;h++){
  const valid=base.sample_times?.[h],pair=[];
  for(const model of ['hrrr','rrfs']){
   const runs=base.source_metadata?.filter(s=>s.model===model),s=runs?.length===1?runs[0].samples?.[h]:null;
   if(!s||s.valid_time!==valid||!/^[a-f0-9]{32}$/.test(s.grid_md5))throw Error('Missing forecast base provenance');
   const source={cycle:s.cycle,lead:s.lead,grid_md5:s.grid_md5,model};pair.push(source);
   out[model+h]={model,valid_time:valid,sources:[source]};
  }
  out['blend'+h]={model:'blend',valid_time:valid,sources:pair};
 }
 return out;
}
function validateForecast(m){
 const start=Date.parse(m?.window_start),end=Date.parse(m?.window_end),frames=m?.frame_contexts;
 if(m?.schema!=='gdi_forecast_dynamics_v1'||m.recipe!=='cam_gdi_dynamics_v1'||m.model!=='hrrr_rrfs'||m.crs!=='EPSG:3857'||m.width!==2400||m.height!==1360||JSON.stringify(m.bounds)!=='[[24,-125],[50,-66]]'||m.resampling!=='masked_bilinear'||m.smoothing_sigma_km!==20||!/^\d{10}-[a-f0-9]{12}-v1$/.test(m.generation)||!/^[a-f0-9]{64}$/.test(m.base_selection_signature)||!Number.isFinite(start)||start%3600000||end-start!==6*3600000||Date.parse(m.expires_at)!==end)throw Error('Invalid forecast dynamics metadata');
 if(m.sample_times?.length!==7||Object.keys(frames||{}).length!==21||m.source_metadata?.length!==14||Object.keys(m.products||{}).length!==126||Object.keys(m.assets||{}).length!==126||Object.keys(m.definitions||{}).length!==6)throw Error('Incomplete forecast dynamics');
 Object.entries(FIELDS).forEach(([name,d])=>{if(Object.keys(m.definitions[name]||{}).length!==Object.keys(d).length||Object.entries(d).some(([k,v])=>JSON.stringify(m.definitions[name][k])!==JSON.stringify(v)))throw Error('Changed dynamics definition');});
 const origins={},grids={},seen=new Set();
 for(let h=0;h<7;h++){
  const valid=start+h*3600000,pair=[];
  if(Date.parse(m.sample_times[h])!==valid)throw Error('Misaligned forecast dynamics time');
  for(const model of ['hrrr','rrfs']){
   const c=frames[model+h],s=c?.sources?.[0],cycle=Date.parse(s?.cycle);
   if(c?.model!==model||Date.parse(c.valid_time)!==valid||c.sources.length!==1||s.model!==model||!Number.isInteger(s.lead)||s.lead<0||s.lead>18||cycle+s.lead*3600000!==valid||!(cycle>start-6*3600000&&cycle<=start)||!/^[a-f0-9]{32}$/.test(s.grid_md5))throw Error('Misaligned dynamics source');
   if(h&&(origins[model]!==cycle||grids[model]!==s.grid_md5))throw Error('Mixed native dynamics cycles/grids');
   origins[model]=cycle;grids[model]=s.grid_md5;pair.push(s);
   const records=m.source_metadata.filter(x=>x.model===model&&x.cycle===s.cycle&&x.lead===s.lead);
   const r=records[0],signature=model+'/'+s.cycle+'/'+s.lead;
   if(records.length!==1||seen.has(signature)||r.recipe!==m.recipe||r.smoothing_sigma_km!==20||r.grid_md5!==s.grid_md5||!r.sources?.length||!/^[a-f0-9]{64}$/.test(r.sha256)||!r.projection)throw Error('Invalid forecast dynamics provenance');
   seen.add(signature);
  }
  const b=frames['blend'+h];if(b?.model!=='blend'||Date.parse(b.valid_time)!==valid||JSON.stringify(b.sources)!==JSON.stringify(pair))throw Error('Incomplete blend sources');
  for(const model of ['hrrr','rrfs','blend'])for(const name of Object.keys(FIELDS)){
   const frame=model+h,key=name+'_'+frame,p=m.products[key],a=m.assets[key];
   if(p?.field!==name||p.frame!==frame||Date.parse(p.valid_time)!==valid||a?.path!==`generations/${m.generation}/${key}.png`||!/^[a-f0-9]{64}$/.test(a.sha256))throw Error('Misaligned or unsafe forecast dynamics asset');
  }
 }
 if(Date.parse(m.cycle)!==Math.max(...Object.values(origins)))throw Error('Invalid forecast dynamics cycle');
}
function createForecast({map,metadataURL,paneName='forecastGDIDynamics',onChange=()=>{}}){
 const ui=root.GDIDisplay,enabled={mfc:true,div:true,rh:false,pw:false,low:false,upper:false},groups={},mounted={},bundles=new Map(),pending=new Map(),retryAt=new Map();
 let context=null,packages=[],fetching=null,failed=false,lastCheck=0;
 map.createPane(paneName);map.getPane(paneName).style.zIndex=355;map.getPane(paneName).style.pointerEvents='none';
 Object.keys(FIELDS).forEach(k=>{groups[k]=L.layerGroup().addTo(map);});
 const expired=m=>Date.now()>=Date.parse(m.expires_at);
 const matches=m=>context&&!expired(m)&&m.base_selection_signature===context.selection&&JSON.stringify(m.frame_contexts[context.key])===JSON.stringify(context.frame);
 const bundleKey=(m,model,field)=>m.generation+'/'+model+'/'+field;
 function drop(field){groups[field].clearLayers();delete mounted[field];}
 function clear(){Object.keys(FIELDS).forEach(drop);}
 function prune(){
  packages=packages.filter(m=>!expired(m));const allowed=new Set(packages.map(m=>m.generation));
  for(const [key,b] of bundles)if(!allowed.has(b.generation)){b.urls.forEach(URL.revokeObjectURL);bundles.delete(key);retryAt.delete(key);}
 }
 function preload(m,model,field){
  const key=bundleKey(m,model,field);
  if(bundles.has(key)||pending.has(key)||(retryAt.get(key)||0)>Date.now())return;
  const request=(async()=>{
   const r=await Promise.allSettled(Array.from({length:7},(_,h)=>ui.image(m,field+'_'+model+h,metadataURL)));
   if(r.some(x=>x.status==='rejected')||expired(m)||!packages.some(p=>p.generation===m.generation)){
    r.forEach(x=>{if(x.status==='fulfilled')URL.revokeObjectURL(x.value);});retryAt.set(key,Date.now()+15000);
   }else{bundles.set(key,{generation:m.generation,urls:r.map(x=>x.value)});retryAt.delete(key);}
  })().finally(()=>{pending.delete(key);draw();});
  pending.set(key,request);
 }
 function draw(){
  const m=packages.find(matches);
  if(!context||!m){clear();onChange();return;}
  const {model,index}=context;
  for(const field of Object.keys(FIELDS)){
   if(!enabled[field]){drop(field);continue;}
   const key=bundleKey(m,model,field),b=bundles.get(key);
   if(!b){drop(field);preload(m,model,field);continue;}
   if(mounted[field]?.key!==key){
    drop(field);mounted[field]={key,overlays:b.urls.map(url=>L.imageOverlay(url,m.bounds,{pane:paneName,opacity:0,interactive:false}).addTo(groups[field]))};
   }
   mounted[field].overlays.forEach((o,h)=>o.setOpacity(h===index?1:0));
  }
  onChange();
 }
 function setContext(base,p,key){
  let next=null;
  if(base?.kind==='forecast'&&base.forecast_sampling==='common_valid_hourly_v1'&&/^(hrrr|rrfs|blend)[0-6]$/.test(key||'')&&/^[a-f0-9]{64}$/.test(base.selection_signature)&&base.products?.[key]===p){
   try{
    const frame=forecastContexts(base)[key],index=Number(key.slice(-1)),model=key.slice(0,-1);
    if(frame.valid_time===p.valid_time)next={selection:base.selection_signature,key,model,index,frame};
   }catch(e){next=null;}
  }
  if(JSON.stringify(next)===JSON.stringify(context))return;
  if(next?.model!==context?.model||next?.selection!==context?.selection)clear();
  context=next;draw();
  if(context&&(!lastCheck||Date.now()-lastCheck>60000))refresh();
 }
 function refresh(){
  if(fetching)return fetching;
  lastCheck=Date.now();
  fetching=(async()=>{try{
   const m=await ui.metadata(metadataURL);validateForecast(m);
   if(packages[0]&&Date.parse(m.window_start)<Date.parse(packages[0].window_start))throw Error('Regressing companion window');
   const same=packages.find(x=>x.generation===m.generation);if(same&&JSON.stringify(same)!==JSON.stringify(m))throw Error('Changed immutable companion package');
   const displayed=packages.find(matches);
   packages=[m,...(displayed&&displayed.generation!==m.generation?[displayed]:packages.filter(x=>x.generation!==m.generation))].slice(0,2);
   lastCheck=Date.now();failed=false;prune();draw();
  }catch(e){failed=true;if(!packages.some(matches))clear();onChange();}finally{fetching=null;}})();return fetching;
 }
 document.addEventListener('change',e=>{
  const t=e.target;if(t?.dataset?.gdiDynamics!==paneName||!Object.hasOwn(FIELDS,t.dataset.field))return;
  enabled[t.dataset.field]=t.checked;draw();
 });
 function legendHTML(){
  if(!context)return '';
  const m=packages.find(matches),esc=ui.esc;
  const keys=m?Object.keys(FIELDS).filter(k=>enabled[k]).map(k=>bundleKey(m,context.model,k)):[];
  const error=keys.some(k=>retryAt.has(k)),loading=keys.some(k=>!bundles.has(k));
  let html='<div class="gdi-dynamics"><strong>Dynamics</strong><div class="gdi-dynamics-options">';
  Object.entries(FIELDS).forEach(([k,d])=>{html+='<label><input type="checkbox" data-gdi-dynamics="'+paneName+'" data-field="'+k+'" '+(enabled[k]?'checked':'')+'> '+esc(d.label)+'</label>';});
  html+='</div><div class="gdi-dynamics-status gdi-status">'+(!m?'Awaiting companions for this model selection and valid time':error?'Some dynamics unavailable · retrying':loading?'Loading complete companion loops…':failed?'Update unavailable · retaining matching dynamics':'')+'</div>';
  Object.entries(FIELDS).forEach(([k,d])=>{
   if(!enabled[k])return;const levels=d.levels?.filter(v=>v>0).join(' / ');
   html+='<div class="gdi-dynamics-key"><i style="color:'+d.color+'"></i>'+esc(d.label)+' · '+esc(d.unit)+'<small>'+esc(d.layer)+(levels?' · '+esc(levels):' · barbs ≥10 kt')+'</small>';
   if(d.negative_color)html+='<small><i class="is-negative" style="color:'+d.negative_color+'"></i>'+(k==='mfc'?'Moisture divergence':'Upper convergence')+' · same magnitudes</small>';
   html+='</div>';
  });
  html+='<div class="gdi-note">'+esc(context.model==='blend'?'HRRR/RRFS blend':context.model.toUpperCase())+' · '+esc(ui.utc(context.frame.valid_time))+'<br>20-km Gaussian sigma on companions. GDI unchanged. Below-ground levels excluded; moisture convergence requires ≥100 hPa of valid layer.</div></div>';
  return html;
 }
 setInterval(()=>{prune();if(context){if(!packages.some(matches))clear();draw();if(failed||retryAt.size||Date.now()-lastCheck>=120000)refresh();}},15000);
 return {setContext,legendHTML,refresh};
}
root.GDIDynamics={create,validate,FIELDS,createForecast,validateForecast,forecastContexts};
})(typeof window==='undefined'?globalThis:window);
