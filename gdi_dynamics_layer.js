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
root.GDIDynamics={create,validate,FIELDS};
})(typeof window==='undefined'?globalThis:window);
