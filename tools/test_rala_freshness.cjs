/* Exercise real refresh functions with stalled network/image operations. */
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('app.js','utf8');
function extract(name){const a=source.indexOf('function '+name+'(');assert.ok(a>=0);const begin=source.slice(a-6,a)==='async '?a-6:a;return source.slice(begin,source.indexOf('\n}',a)+2);}
const flush=async()=>{for(let i=0;i<15;i++)await Promise.resolve();};
function context(){
 let serial=0;const timers=new Map(),images=[];
 class Image{constructor(){images.push(this);}decode(){return Promise.resolve();}set src(value){this.url=value;}}
 const ctx={AbortController,Date,Image,console:{error(){},warn(){},debug(){}},
  window:{setTimeout(fn,delay){timers.set(++serial,{fn,delay});return serial;},clearTimeout(id){timers.delete(id);}},
  MRMS_RALA_METADATA_TIMEOUT_MS:15000,MRMS_RALA_IMAGE_TIMEOUT_MS:20000,
  MRMS_RALA_MANIFEST_URL:'https://example.test/manifest.json',mrmsRalaPreloadCache:new Map(),mrmsRalaFrameUrl:f=>f.png,
  mrmsRalaManifestCheckInFlight:false,mrmsRalaLastManifestVersion:'old',mrmsRalaReady:false,mrmsRalaFresh:true,
  mrmsRalaFrames:[],mrmsRalaLayer:{setBounds(){},setOpacity(){}},mrmsRalaBufferLayer:{setBounds(){}},mrmsRalaVisibleLayer:{setOpacity(){}},mrmsRalaHiddenLayer:{setOpacity(){}},
  map:{hasLayer:()=>false},validateMRMSRALAManifest:m=>({manifest:m,frames:m.frames,bounds:[]}),mrmsRalaManifestVersion:m=>m.generated_utc,
  syncMRMSRALADisplayMode(){},applyMRMSRALAFreshnessState(){},activateMRMSRALATimeline(){},showMRMSRALAFrame:async()=>true,updateLegends(){},
  mrmsRalaDisplayMode:'reflectivity',mrmsRalaActiveFrames:()=>ctx.mrmsRalaFrames,preloadMRMSRALAFrame:async()=>{},
  document:{},timers,images};
 vm.createContext(ctx);
 ctx.load=(...names)=>vm.runInContext(names.map(extract).join('\n'),ctx);
 ctx.fire=delay=>{const found=[...timers].find(([,t])=>t.delay===delay);assert.ok(found,'expected timeout');timers.delete(found[0]);found[1].fn();};
 return ctx;
}
const manifest={generated_utc:'new',frames:[{valid_time_utc:'2026-11-04T23:00:00Z',png:'frame.png'}]};
let passed=0;
async function check(name,run){await run();passed++;console.log('PASS '+name);}
(async()=>{
 await check('stalled manifest request aborts and releases the refresh lock',async()=>{
  const c=context();let calls=0;c.fetch=(url,{signal})=>{calls++;return new Promise((_,reject)=>signal.addEventListener('abort',()=>reject(Error('aborted'))));};
  c.load('fetchMRMSRALAManifest','refreshMRMSRALAFromManifest');
  const pending=c.refreshMRMSRALAFromManifest();assert.equal(c.mrmsRalaManifestCheckInFlight,true);
  assert.equal(await c.refreshMRMSRALAFromManifest(),false);assert.equal(calls,1);
  c.fire(15000);assert.equal(await pending,false);assert.equal(c.mrmsRalaManifestCheckInFlight,false);
  c.fetch=async()=>({ok:true,json:async()=>structuredClone(manifest)});
  assert.equal(await c.refreshMRMSRALAFromManifest(),true);assert.equal(c.mrmsRalaLastManifestVersion,'new');
 });
 await check('metadata timeout remains active while reading the response body',async()=>{
  const c=context();c.fetch=async(url,{signal})=>({ok:true,json:()=>new Promise((_,reject)=>signal.addEventListener('abort',()=>reject(Error('body aborted'))))});
  c.load('fetchMRMSRALAManifest');const pending=c.fetchMRMSRALAManifest();await flush();c.fire(15000);
  await assert.rejects(pending,/body aborted/);assert.equal(c.timers.size,0);
 });
 await check('stalled PNG preload is evicted and the same URL can recover',async()=>{
  const c=context();c.load('preloadMRMSRALAFrame');const frame=manifest.frames[0];
  const pending=c.preloadMRMSRALAFrame(frame);assert.equal(c.mrmsRalaPreloadCache.size,1);
  c.fire(20000);await assert.rejects(pending,/timed out/);assert.equal(c.mrmsRalaPreloadCache.size,0);
  const retry=c.preloadMRMSRALAFrame(frame);await c.images[1].onload();assert.equal(await retry,'frame.png');assert.equal(c.timers.size,0);
 });
 await check('a stalled image decode cannot hold future manifest checks',async()=>{
  const c=context();c.load('preloadMRMSRALAFrame');
  const pending=c.preloadMRMSRALAFrame(manifest.frames[0]);c.images[0].decode=()=>new Promise(()=>{});
  c.images[0].onload();c.fire(20000);await assert.rejects(pending,/timed out/);assert.equal(c.mrmsRalaPreloadCache.size,0);
 });
 await check('failed new-image loading retries an unchanged manifest on the next poll',async()=>{
  const c=context();let preloads=0;
  c.fetchMRMSRALAManifest=async()=>structuredClone(manifest);
  c.preloadMRMSRALAFrame=async()=>{if(++preloads===1)throw Error('temporary image error');};
  c.load('refreshMRMSRALAFromManifest');
  assert.equal(await c.refreshMRMSRALAFromManifest(),false);assert.equal(c.mrmsRalaLastManifestVersion,'old');assert.equal(c.mrmsRalaManifestCheckInFlight,false);
  assert.equal(await c.refreshMRMSRALAFromManifest(),true);assert.equal(preloads,2);assert.equal(c.mrmsRalaLastManifestVersion,'new');
  assert.equal(await c.refreshMRMSRALAFromManifest(),false);assert.equal(preloads,2,'healthy unchanged metadata avoids redundant image loading');
 });
 await check('failed polling still hides an observation beyond the twenty-minute limit',async()=>{
  const c=context();let hidden=0;c.fetchMRMSRALAManifest=async()=>{throw Error('offline');};
  c.mrmsRalaReady=true;c.mrmsRalaFresh=true;c.MRMS_RALA_FRESHNESS_LIMIT_MINUTES=20;
  c.mrmsRalaMetadata={latest_valid_time_utc:new Date(Date.now()-21*60000).toISOString()};
  c.mrmsRalaVisibleLayer.setOpacity=value=>{assert.equal(value,0);hidden++;};c.mrmsRalaHiddenLayer.setOpacity=()=>{};
  c.updateMRMSRALATimeBox=()=>{};
  c.load('mrmsRalaAgeMinutes','applyMRMSRALAFreshnessState','refreshMRMSRALAFromManifest');
  assert.equal(await c.refreshMRMSRALAFromManifest(),false);assert.equal(c.mrmsRalaFresh,false);assert.ok(hidden>0);
 });
 console.log(`${passed} RALA refresh and freshness scenarios passed.`);
})().catch(error=>{console.error(error);process.exitCode=1;});
