/* Validated vector contours, labels that follow zoom, and automated H/L centers. */
(function(root){
 'use strict';
 const esc=v=>String(v).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const intervals={temperature:10,dewpoint:10,wind_speed:10,wind_gust:10,mslp:4,relative_humidity:10,heat_index:5,wind_chill:10};
 function descriptor(p,a,key){
  if(!p)return;
  const folder=key==='mslp'?'pressure':'generations';
  if(p.path!==`${folder}/${a.generation}/${key}_contours.geojson` || !/^[a-f0-9]{64}$/.test(p.sha256) || p.interval!==intervals[key] || !Number.isInteger(p.feature_count)||p.feature_count<0||p.feature_count>10000)throw Error('Invalid surface contour asset');
 }
 function validate(data,key,a){
  if(data?.type!=='FeatureCollection'||data.schema!=='surface-contours-v1'||data.key!==key||data.valid_time!==a.valid_time||data.interval!==intervals[key]||!Array.isArray(data.features)||data.features.length>10000)throw Error('Contours do not match the displayed analysis');
  let vertices=0;
  for(const f of data.features){
   const p=f.properties,g=f.geometry;
   if(f.type!=='Feature'||!p||!Number.isFinite(p.value)||p.unit!==a.products[key].unit||!g)throw Error('Invalid contour properties');
   let coords;
   if(p.kind==='center'){
    if(key!=='mslp'||!['H','L'].includes(p.symbol)||g.type!=='Point')throw Error('Invalid pressure center');
    coords=[g.coordinates];
   }else{
    if(p.kind!=='contour'||g.type!=='LineString'||!Array.isArray(g.coordinates)||g.coordinates.length<2)throw Error('Invalid contour geometry');
    if(Math.abs(p.value/data.interval-Math.round(p.value/data.interval))>1e-6 && !(key==='temperature'&&p.value===32))throw Error('Invalid contour level');
    coords=g.coordinates;
   }
   vertices+=coords.length;
   if(!coords.every(c=>Array.isArray(c)&&c.length===2&&c.every(Number.isFinite)&&c[0]>=-125&&c[0]<=-66&&c[1]>=24&&c[1]<=50))throw Error('Invalid contour coordinate');
  }
  if(vertices>250000)throw Error('Oversized surface contours');
  return data;
 }
 function visibleLevel(value,key,zoom){return key==='mslp'||key==='temperature'&&value===32||zoom>=6||Math.abs(value/(intervals[key]*2)-Math.round(value/(intervals[key]*2)))<1e-6;}
 function overlap(a,b){return Math.abs(a.x-b.x)<(a.w+b.w)/2&&Math.abs(a.y-b.y)<(a.h+b.h)/2;}
 function clip(a,b,width,height){
  const dx=b.x-a.x,dy=b.y-a.y;let lo=0,hi=1;
  for(const [p,q] of [[-dx,a.x-28],[dx,width-28-a.x],[-dy,a.y-28],[dy,height-28-a.y]]){
   if(p===0){if(q<0)return null;continue;}
   const t=q/p;if(p<0)lo=Math.max(lo,t);else hi=Math.min(hi,t);if(lo>hi)return null;
  }
  return [{x:a.x+lo*dx,y:a.y+lo*dy},{x:a.x+hi*dx,y:a.y+hi*dy}];
 }
 function labels(data,key,zoom,project,width,height,obstacles=[]){
  if(zoom<(key==='mslp'?3:5))return [];
  const placed=[],occupied=[...obstacles];
  const lines=data.features.filter(f=>f.properties.kind==='contour'&&visibleLevel(f.properties.value,key,zoom)).sort((a,b)=>(b.properties.value===32&&key==='temperature')-(a.properties.value===32&&key==='temperature')||b.geometry.coordinates.length-a.geometry.coordinates.length);
  for(const line of lines){
   const coords=line.geometry.coordinates,parts=[];let total=0;
   for(let i=1;i<coords.length;i++){
    const clipped=clip(project(coords[i-1]),project(coords[i]),width,height);if(!clipped)continue;
    const [a,b]=clipped,d=Math.hypot(b.x-a.x,b.y-a.y);if(d<1)continue;
    parts.push({a,b,d,start:total});total+=d;
   }
   if(total<75)continue;
   for(let at=Math.min(75,total/2);at<total;at+=210){
    const part=parts.find(p=>at>=p.start&&at<=p.start+p.d);if(!part)continue;
    const t=(at-part.start)/part.d,x=part.a.x+t*(part.b.x-part.a.x),y=part.a.y+t*(part.b.y-part.a.y);
    const box={x,y,w:key==='mslp'?100:80,h:42};
    if(occupied.some(b=>overlap(box,b)))continue;
    let angle=Math.atan2(part.b.y-part.a.y,part.b.x-part.a.x)*180/Math.PI;
    if(angle>90)angle-=180;if(angle<-90)angle+=180;
    placed.push({x,y,value:line.properties.value,angle});occupied.push(box);
    if(placed.length>=100)return placed;
   }
  }
  return placed;
 }
 function create(map){
  for(const [name,z] of [['surfaceContours',430],['surfaceContourLabels',574],['surfacePressureCenters',590]]){map.createPane(name);map.getPane(name).style.zIndex=z;map.getPane(name).style.pointerEvents='none';}
  const lines=L.layerGroup(),text=L.layerGroup();let signature='';
  function clear(){lines.clearLayers();text.clearLayers();if(map.hasLayer(lines))map.removeLayer(lines);if(map.hasLayer(text))map.removeLayer(text);signature='';}
  function draw({data,key,generation,enabled,obstacles=[],labelColor=()=>'#4c718b'}){
   if(!data||!enabled){clear();return;}
   const zoom=map.getZoom(),next=`${generation}/${key}/${key==='mslp'||zoom>=6?1:2}`;
   if(signature!==next){
    lines.clearLayers();
    const features=data.features.filter(f=>f.properties.kind==='contour'&&visibleLevel(f.properties.value,key,zoom));
    const collection={type:'FeatureCollection',features};
    L.geoJSON(collection,{pane:'surfaceContours',interactive:false,style:{color:'#fff',weight:key==='mslp'?3.2:2.5,opacity:.65,fill:false}}).addTo(lines);
    L.geoJSON(collection,{pane:'surfaceContours',interactive:false,style:f=>({color:'#102330',weight:key==='mslp'?1.25:f.properties.value===32&&key==='temperature'?1.4:.85,opacity:key==='mslp'?.9:.72,fill:false})}).addTo(lines);
    signature=next;
   }
   if(!map.hasLayer(lines))lines.addTo(map);if(!map.hasLayer(text))text.addTo(map);text.clearLayers();
   const size=map.getSize(),project=c=>map.latLngToContainerPoint([c[1],c[0]]),blocked=[...obstacles];
   for(const center of data.features.filter(f=>f.properties.kind==='center')){
    const c=center.geometry.coordinates,p=project(c),box={x:p.x,y:p.y,w:90,h:70};
    if(p.x<25||p.y<35||p.x>size.x-25||p.y>size.y-35)continue;
    const value=center.properties.value,symbol=center.properties.symbol;
    L.marker([c[1],c[0]],{pane:'surfacePressureCenters',interactive:false,keyboard:false,
     icon:L.divIcon({className:`surface-pressure-center surface-pressure-${symbol.toLowerCase()}`,iconSize:[66,58],iconAnchor:[33,29],html:`<b>${symbol}</b><span>${Math.round(value)}</span>`}),
     title:`Automated ${symbol==='H'?'high':'low'} · ${value.toFixed(1)} hPa`}).addTo(text);blocked.push(box);
   }
   for(const p of labels(data,key,zoom,project,size.x,size.y,blocked)){
    L.marker(map.containerPointToLatLng([p.x,p.y]),{pane:'surfaceContourLabels',interactive:false,keyboard:false,
     icon:L.divIcon({className:'surface-contour-label',iconSize:[42,18],iconAnchor:[21,9],html:`<span style="--surface-contour-tint:${esc(labelColor(p.value))};transform:rotate(${p.angle.toFixed(1)}deg)">${esc(p.value)}</span>`})}).addTo(text);
   }
  }
  return {draw,clear};
 }
 root.SurfaceCartography={intervals,descriptor,validate,visibleLevel,overlap,clip,labels,create};
})(typeof window==='undefined'?globalThis:window);
