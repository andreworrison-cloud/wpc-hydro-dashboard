/* Shared GDI transport and legends. Does not alter meteorological fields. */
(function(root){
'use strict';
const esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const utc=t=>new Date(t).toISOString().slice(5,16).replace('T',' ')+'Z';
async function request(url,type){
 let last;
 for(let attempt=0;attempt<2;attempt++){
  const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),15000);
  try{const r=await fetch(url,{cache:'no-store',signal:controller.signal});if(!r.ok)throw Error('HTTP '+r.status);return await r[type]();}
  catch(e){last=e;}finally{clearTimeout(timer);}
 }
 throw last;
}
async function metadata(url){const u=new URL(url);u.searchParams.set('gdi_refresh',Math.floor(Date.now()/60000));return request(u,'json');}
const cache=new Map();
let cacheBytes=0;
function forget(key){const old=cache.get(key);if(old)cacheBytes-=old.byteLength;cache.delete(key);}
async function image(m,key,base){
 const a=m.assets[key],url=new URL(a.path,base).href,cacheKey=url+'#'+a.sha256;
 let bytes=cache.get(cacheKey);
 if(!bytes){
  bytes=await request(url,'arrayBuffer');
  const hash=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))).map(x=>x.toString(16).padStart(2,'0')).join('');
  if(hash!==a.sha256)throw Error('Image checksum mismatch');
  forget(cacheKey);cache.set(cacheKey,bytes);cacheBytes+=bytes.byteLength;
  while(cache.size&&(cache.size>64||cacheBytes>96*1024*1024))forget(cache.keys().next().value);
 }
 const objectURL=URL.createObjectURL(new Blob([bytes],{type:'image/png'}));
 try{const im=new Image();im.src=objectURL;await im.decode();if(im.width!==m.width||im.height!==m.height)throw Error('Image dimensions');return objectURL;}catch(e){forget(cacheKey);URL.revokeObjectURL(objectURL);throw e;}
}
const number=v=>Number.isInteger(Number(v))?String(v):Number(v).toFixed(1);
// The renderer clamps the first/last colors. edges[0] is a legacy display
// reference; actual finite boundaries begin at edges[1].
function binRanges(edges){
 if(edges.length<2||edges.some((v,i)=>!Number.isFinite(v)||(i&&v<=edges[i-1])))throw Error('Invalid GDI color boundaries');
 return edges.map((v,i)=>({lower:i?Number(v):-Infinity,upper:i===edges.length-1?Infinity:Number(edges[i+1])}));
}
const signed=v=>v<0?'−'+number(-v):v>0?'+'+number(v):'0';
function changeScale(colors,edges,unit){
 const n=colors.length,ranges=binRanges(edges);
 const labels=ranges.map(r=>r.lower===-Infinity?'< '+signed(r.upper):r.upper===Infinity?'≥ '+signed(r.lower):signed(r.lower)+' to < '+signed(r.upper));
 const center=ranges.findIndex(r=>r.lower<=0&&r.upper>0),neutral=ranges[center];
 let html='<div class="gdi-scale-unit">'+esc(unit)+'</div><div class="gdi-scale gdi-change-scale" role="img" aria-label="'+esc(unit+' color intervals: '+labels.join('; '))+'"><div class="gdi-scale-bar">';
 colors.forEach((color,i)=>{html+='<span style="background:'+(/^#[0-9a-f]{6}$/i.test(color)?color:'#000000')+'" title="'+esc(labels[i]+' '+unit)+'"></span>';});
 html+='</div><div class="gdi-scale-ticks gdi-change-scale-ticks">';
 edges.slice(1).forEach((v,i)=>{html+='<span style="left:'+(100*(i+1)/n)+'%">'+esc(signed(v))+'</span>';});
 if(neutral&&Number.isFinite(neutral.lower)&&Number.isFinite(neutral.upper)){
  const position=100*(center+(0-neutral.lower)/(neutral.upper-neutral.lower))/n;
  html+='<span class="gdi-change-zero" style="left:'+position+'%">0</span>';
 }
 html+='</div><div class="gdi-change-ranges"><span>'+esc(labels[0])+'</span><span>'+(neutral?'Near zero: '+esc(labels[center]):'')+'</span><span>'+esc(labels[n-1])+'</span></div></div>';
 return html;
}
function scale(colors,edges,unit,options={}){
 const n=colors.length;if(!n||edges.length!==n)return '';
 if(options.zeroCentered)return changeScale(colors,edges,unit);
 const picks=n>12?[0,3,6,9,12,15,n-1]:n>8?[0,2,4,6,8,n-1]:edges.map((_,i)=>i);
 let html='<div class="gdi-scale-unit">'+esc(unit)+'</div><div class="gdi-scale" role="img" aria-label="'+esc(unit+' color scale; '+edges.map(number).join(', '))+'"><div class="gdi-scale-bar">';
 colors.forEach((c,i)=>{const range=i===0?'Below '+number(edges[1]):i===n-1?'≥ '+number(edges[i]):number(edges[i])+' to < '+number(edges[i+1]);html+='<span style="background:'+(/^#[0-9a-f]{6}$/i.test(c)?c:'#000000')+'" title="'+esc(range+' '+unit)+'"></span>';});
 html+='</div><div class="gdi-scale-ticks">';
 picks.forEach(i=>{const label=(i===n-1?'≥':'')+number(edges[i]);html+='<span style="left:'+(100*i/n)+'%">'+esc(label)+'</span>';});
 return html+'</div></div>';
}
function controls(id,checked){return '<div class="gdi-controls"><label><input type="checkbox" '+id+' '+(checked?'checked':'')+'> Labeled contours</label></div>';}
root.GDIDisplay={esc,utc,metadata,image,scale,controls,binRanges};
})(typeof window==='undefined'?globalThis:window);
