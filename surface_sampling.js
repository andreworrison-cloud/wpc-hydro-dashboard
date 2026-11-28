/* Numeric analysis sampling, independent of METARs and raster colors. */
(function(root){
 'use strict';
 const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const bounds=[[24,-125],[50,-66]],maxBytes=4+2048+3600*2024*2;
 function descriptor(p,a,key){
  if(!p)return;
  if(p.path!==`${key==='mslp'?'pressure':'generations'}/${a.generation}/${key}_samples.bin.gz`||p.encoding!=='gzip-int16-v1'||!/^[a-f0-9]{64}$/.test(p.sha256))throw Error('Invalid analysis sample asset');
 }
 function parse(buffer,key,a){
  const view=new DataView(buffer);if(buffer.byteLength<4||buffer.byteLength>maxBytes)throw Error('Invalid sample size');
  const n=view.getUint32(0,true);if(!n||n>2048||buffer.byteLength!==4+n+a.width*a.height*2)throw Error('Invalid sample length');
  const h=JSON.parse(new TextDecoder().decode(new Uint8Array(buffer,4,n)));
  if(h.schema!=='surface-sample-v1'||h.key!==key||h.valid_time!==a.valid_time||h.unit!==a.products[key].unit||h.width!==a.width||h.height!==a.height||h.width!==3600||h.height!==2024||h.crs!=='EPSG:3857'||JSON.stringify(h.bounds)!==JSON.stringify(bounds)||h.scale!==.1||h.nodata!==-32768||h.dtype!=='int16-le'||h.order!=='north-to-south')throw Error('Samples do not match displayed analysis');
  const values=new Int16Array(h.width*h.height);for(let i=0;i<values.length;i++)values[i]=view.getInt16(4+n+i*2,true);
  return {header:h,values};
 }
 async function decode(raw,key,a){
  if(typeof DecompressionStream==='undefined')throw Error('Gzip sampling is unsupported in this browser');
  const reader=new Blob([raw]).stream().pipeThrough(new DecompressionStream('gzip')).getReader(),chunks=[];let length=0;
  try{for(;;){const {done,value}=await reader.read();if(done)break;length+=value.byteLength;if(length>maxBytes)throw Error('Oversized sample grid');chunks.push(value);}}
  catch(e){await reader.cancel().catch(()=>{});throw e;}
  const data=new Uint8Array(length);let at=0;for(const c of chunks){data.set(c,at);at+=c.length;}return parse(data.buffer,key,a);
 }
 const merc=lat=>Math.log(Math.tan(Math.PI/4+lat*Math.PI/360));
 function sample(grid,lat,lon){
  if(!Number.isFinite(lat)||!Number.isFinite(lon)||lat<24||lat>50||lon< -125||lon> -66)return {status:'outside'};
  const {header:h,values}=grid;
  const x=Math.max(0,Math.min(h.width-1,(lon+125)/59*h.width-.5)),y=Math.max(0,Math.min(h.height-1,(merc(50)-merc(lat))/(merc(50)-merc(24))*h.height-.5));
  const x0=Math.floor(x),y0=Math.floor(y),x1=Math.min(x0+1,h.width-1),y1=Math.min(y0+1,h.height-1),dx=x-x0,dy=y-y0;
  let value=0;
  for(const [xx,yy,w] of [[x0,y0,(1-dx)*(1-dy)],[x1,y0,dx*(1-dy)],[x0,y1,(1-dx)*dy],[x1,y1,dx*dy]]){
   if(w<1e-10)continue;const q=values[yy*h.width+xx];if(q===h.nodata)return {status:'missing'};value+=q*h.scale*w;
  }
  return {status:'value',value};
 }
 function create({map,getCurrent,load,onChange}){
  let enabled=false,pinned=false,position=null,tooltip=null,request=0,lastIdentity='',lastPaint=0,stopped=false;
  const unavailable=key=>key==='wind_chill'?'Not applicable / unavailable · requires ≤50°F and sustained wind >3 mph':key==='heat_index'?'Not applicable / unavailable · requires the NWS warm-condition screen':'Analysis value unavailable';
  function hide(){if(tooltip){map.removeLayer(tooltip);tooltip=null;}}
  function paint(){
   const c=getCurrent();if(!enabled||!c?.visible||!c.entry||!position){hide();return;}
   const e=c.entry,p=e.analysis.products[c.key],result=e.samples?sample(e.samples,position.lat,position.lng):null;
   if(result?.status==='outside'){hide();return;}
   const detail=result?.status==='value'?`<b>${result.value.toFixed(1)} ${esc(p.unit)}</b>`:esc(result?unavailable(c.key):e.sampleError?'Sampling unavailable · toggle to retry':p.sampling?'Loading numeric analysis…':'Sampling grid is updating…');
   const html=`<div class="surface-sample-readout"><strong>${esc(p.label)}</strong>${detail}<span>${position.lat.toFixed(3)}°, ${position.lng.toFixed(3)}°</span><span>Analysis: ${esc(e.analysis.valid_time.replace('T',' '))}</span><small>${pinned?'Pinned · click map to move; Esc to release':'Interpolated analysis · click to pin'}</small></div>`;
   if(!tooltip)tooltip=L.tooltip({permanent:true,direction:'right',offset:[14,0],opacity:1,interactive:false,className:'surface-sample-tooltip'});
   tooltip.setLatLng(position).setContent(html);if(!map.hasLayer(tooltip))tooltip.addTo(map);
  }
  async function sync(){
   if(stopped)return;
   const c=getCurrent(),identity=c?.visible&&c.entry?`${c.entry.analysis.generation}/${c.key}`:'';
   if(identity!==lastIdentity){lastIdentity=identity;request++;hide();} // Keep a pinned location; refresh its field/time/value.
   paint();if(!enabled||!identity)return;
   const e=c.entry,p=e.analysis.products[c.key];if(!p.sampling||e.samples||e.sampleLoading||e.sampleError)return;
   const token=request;e.sampleLoading=true;onChange();
   try{const data=await load(p.sampling);e.samples=await decode(data,c.key,e.analysis);e.sampleError=false;}
   catch(error){e.sampleError=true;console.warn('Surface sampling unavailable; fill retained:',error.message);}
   finally{e.sampleLoading=false;if(!stopped&&token===request){paint();onChange();}}
  }
  function setEnabled(value){let pending;enabled=value;request++;if(!enabled){pinned=false;position=null;hide();}else{const c=getCurrent();if(c?.entry)c.entry.sampleError=false;pending=sync();}onChange();return pending;}
  function release(){pinned=false;position=null;hide();onChange();}
  map.on('mousemove',e=>{if(!enabled||pinned)return;position=e.latlng;const stamp=Date.now();if(stamp-lastPaint<40)return;lastPaint=stamp;paint();});
  map.on('click',e=>{if(!enabled)return;position=e.latlng;pinned=true;paint();onChange();});
  map.on('mouseout',()=>{if(!pinned){position=null;hide();}});
  map.on('movestart',()=>{if(!pinned){position=null;hide();}});
  document.addEventListener('keydown',e=>{if(enabled&&e.key==='Escape')release();});
  function legend(){const c=getCurrent(),e=c?.entry;return `<div class="surface-sample-controls"><label><input type="checkbox" data-surface-sample ${enabled?'checked':''}> Sample analysis</label>${enabled&&pinned?'<button type="button" data-surface-unpin>Clear pin</button>':''}</div>${enabled?`<p class="surface-note">${e?.sampleError?'Sampling unavailable · toggle to retry.':!e?.analysis.products[c.key]?.sampling?'Numeric grid is updating.':e.sampleLoading?'Loading numeric analysis…':'Hover for a value; click to pin. Works with METARs off.'}</p>`:''}`;}
  return {sync,setEnabled,release,legend,stop:()=>{stopped=true;enabled=false;request++;hide();}};
 }
 root.SurfaceSampling={descriptor,parse,decode,sample,create};
})(typeof window==='undefined'?globalThis:window);
