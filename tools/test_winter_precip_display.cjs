const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const display = require('../winter_precip_display.js');
const frame = {valid_time_utc:'2026-10-24T05:34:40Z',png:'frames/radar.png',ptype_png:'winter_frames/winter_20261024T053440Z.png',ptype:{flag_valid_time_utc:'2026-10-24T05:34:00Z',hrrr:{valid_time_utc:'2026-10-24T05:00:00Z',cycle_utc:'2026-10-24T04:00:00Z',forecast_hour:1}}};
const manifest = {frames:[frame],winter_type:{revision:'mrms-hrrr-winter-v1',experimental:true,classes:['Rain','Mix','Snow','Ice (sleet/freezing rain)'].map((label,i)=>({id:i+1,label,color:'#123456'}))}};
assert.ok(display.available(manifest));
assert.equal(display.path(frame,'ptype'),frame.ptype_png);
assert.equal(display.path(frame,'reflectivity'),frame.png);
assert.ok(display.legend(manifest).includes('Ice (sleet/freezing rain)'));
assert.ok(!display.legend(manifest).includes('Hail'));
for(const change of [f=>delete f.ptype_png,f=>f.ptype_png='../bad.png',f=>f.ptype.flag_valid_time_utc='2026-10-24T05:30:00Z',f=>f.ptype.hrrr.valid_time_utc='2026-10-24T06:00:00Z',f=>f.ptype.hrrr.valid_time_utc='2026-10-24T03:00:00Z']) {
 const broken=structuredClone(manifest);change(broken.frames[0]);assert.equal(display.available(broken),false);
}
const fallback=structuredClone(manifest);fallback.frames[0].ptype.hrrr=null;assert.ok(display.available(fallback));
assert.equal(display.available({frames:[]}),false);
const {execFileSync}=require('node:child_process');
const intensity=JSON.parse(execFileSync('python',['-c','import json; from winter_precip import intensity_metadata; print(json.dumps(intensity_metadata()))'],{encoding:'utf8'}));
const v2=structuredClone(manifest);v2.winter_type.revision='mrms-hrrr-winter-v2';v2.winter_type.intensity=intensity;
v2.frames[0].ptype_png=v2.frames[0].ptype_png.replace('winter_frames/','winter_frames_v2/');
assert.ok(display.available(v2));
const html=display.legend(v2);
assert.equal((html.match(/title="/g)||[]).length,60,'four actual fifteen-bin ramps');
for(const colors of Object.values(intensity.colors))for(const color of colors)assert.ok(html.includes('background:'+color));
assert.ok(html.includes('5 to &lt;10') || html.includes('5 to <10'));
assert.ok(html.includes('75+ dBZ'));assert.ok(html.includes('Radar reflectivity (dBZ)'));
v2.winter_type.intensity.thresholds_dbz[1]=11;assert.equal(display.available(v2),false,'invalid intensity legend disables mismatched data');

// The actual buffer loader must key cache hits by URL, not just radar time.
const source=fs.readFileSync('app.js','utf8');
const start=source.indexOf('function loadMRMSRALAFrameIntoLayer(');
const end=source.indexOf('\nfunction nextMRMSRALAFrameAfter(',start);
const states=new Map(),listeners={};let assigned='';
const layer={on:(name,fn)=>listeners[name]=fn,off:(name,fn)=>{if(listeners[name]===fn)delete listeners[name];},setUrl:url=>{assigned=url;}};
const context={mrmsRalaFrameUrl:f=>f.url,mrmsRalaLayerLoadState:states,applyMRMSRALABrowserRendering:()=>{},window:{setTimeout,clearTimeout},Symbol,Promise,Error};
vm.createContext(context);vm.runInContext(source.slice(start,end),context);
(async()=>{
 const f={valid_time_utc:frame.valid_time_utc,url:'radar.png'};
 let p=context.loadMRMSRALAFrameIntoLayer(layer,f);listeners.load();await p;
 p=context.loadMRMSRALAFrameIntoLayer(layer,{...f,url:'winter.png'});
 assert.equal(assigned,'winter.png');assert.equal(states.get(layer).loaded,false);
 listeners.load();await p;
 let decoded;
 layer.getElement=()=>({decode:()=>new Promise(resolve=>decoded=resolve)});
 p=context.loadMRMSRALAFrameIntoLayer(layer,{...f,url:'decoded-winter.png'});
 const loading=listeners.load();assert.equal(states.get(layer).loaded,false,'load event alone does not expose an undecoded raster');
 decoded();await loading;await p;assert.equal(states.get(layer).loaded,true);
 layer.getElement=()=>({decode:async()=>{throw Error('temporary decode failure');}});
 p=context.loadMRMSRALAFrameIntoLayer(layer,{...f,url:'retry-winter.png'});p.catch(()=>{});
 await listeners.load();await assert.rejects(p,/temporary decode failure/);
 layer.getElement=()=>({decode:async()=>{}});
 p=context.loadMRMSRALAFrameIntoLayer(layer,{...f,url:'retry-winter.png'});
 await listeners.load();await p;assert.equal(states.get(layer).loaded,true,'a failed buffer can retry the same URL');
 console.log('Winter type display PASS: categories, source times, paths, fallback, buffer switching at same radar time.');
})().catch(e=>{console.error(e);process.exitCode=1;});
