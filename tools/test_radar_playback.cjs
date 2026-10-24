/* Deterministic async clock: loading, rapid speed changes and product switches. */
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('app.js','utf8');
function extract(name){const start=source.indexOf('function '+name+'(');assert.ok(start>=0);const asyncStart=source.slice(Math.max(0,start-6),start)==='async '?start-6:start;return source.slice(asyncStart,source.indexOf('\n}',start)+2);}
const flush=async()=>{for(let i=0;i<12;i++)await Promise.resolve();};
let now=0,id=0,advances=0,concurrent=0,maxConcurrent=0;const timers=new Map(),pending=[];
const ctx={window:{setTimeout:(fn,delay)=>{timers.set(++id,{fn,due:now+delay,delay});return id;},clearTimeout:i=>timers.delete(i)},
 dashboardRadarSpeedMode:'mrms',dashboardTimeControl:null,mrmsRalaAnimationPlaying:false,mrmsRalaAnimationTimer:null,mrmsRalaAnimationGeneration:0,mrmsRalaTickInFlight:false,mrmsRalaFrameStepMs:200,
 MRMS_RALA_MAX_FRAME_STEP_MS:1000,MRMS_RALA_MIN_FRAME_STEP_MS:100,MRMS_RALA_FRAME_STEP_INCREMENT_MS:50,syncMRMSRALAPlayButton(){},syncMRMSRALAFrameStepControl(){},
 advanceMRMSRALAOneFrame:()=>{advances++;concurrent++;maxConcurrent=Math.max(maxConcurrent,concurrent);return new Promise(resolve=>pending.push(()=>{concurrent--;resolve(true);}));}};
vm.createContext(ctx);vm.runInContext(['stopMRMSRALAAnimation','scheduleMRMSRALAAnimationTick','runMRMSRALAAnimationTick','startMRMSRALAAnimation','setMRMSRALAFrameStep'].map(extract).join('\n'),ctx);
function fire(){assert.ok(timers.size);const [i,t]=[...timers].sort((a,b)=>a[1].due-b[1].due)[0];timers.delete(i);now=t.due;return t.fn();}
(async()=>{
 ctx.startMRMSRALAAnimation();assert.equal(timers.size,1);const tick=fire();assert.equal(advances,1);
 ctx.setMRMSRALAFrameStep(100);fire();assert.equal(advances,1,'speed change cannot advance concurrently with a load');assert.equal(timers.size,1);
 now+=800;pending.shift()();await tick;await flush();assert.equal(timers.size,1);assert.equal([...timers.values()][0].due-now,100,'slow load gets a full frame hold, no catch-up burst');
 const oldTick=fire();assert.equal(advances,2);ctx.stopMRMSRALAAnimation();ctx.startMRMSRALAAnimation();fire();assert.equal(advances,2);
 pending.shift()();await oldTick;await flush();assert.equal(timers.size,1,'obsolete generation cannot add a second timer');
 const fresh=fire();assert.equal(advances,3);pending.shift()();await fresh;ctx.stopMRMSRALAAnimation();assert.equal(timers.size,0);assert.equal(maxConcurrent,1);

 const jobs=[],preloads=[];Object.assign(ctx,{console,mrmsRalaWarmSerial:0,mrmsRalaDisplayMode:'reflectivity',mrmsRalaLayer:{},map:{hasLayer:()=>true},mrmsRalaActiveFrames:()=>[0,1,2,3,4],
 preloadMRMSRALAFrame:frame=>{const mode=ctx.mrmsRalaDisplayMode;preloads.push({mode,frame});return new Promise(resolve=>jobs.push({mode,resolve}));}});
 vm.runInContext(extract('warmMRMSRALALoopCache'),ctx);
 ctx.warmMRMSRALALoopCache();assert.equal(preloads.length,3);
 ctx.mrmsRalaDisplayMode='ptype';ctx.warmMRMSRALALoopCache();assert.equal(preloads.length,6);
 jobs.filter(j=>j.mode==='reflectivity').forEach(j=>j.resolve());await flush();assert.equal(preloads.filter(j=>j.mode==='reflectivity').length,3,'old-product warmers stop after switching');
 jobs.filter(j=>j.mode==='ptype').forEach(j=>j.resolve());await flush();assert.equal(preloads.filter(j=>j.mode==='ptype').length,5,'selected type window is fully warmed');
 jobs.forEach(j=>j.resolve());await flush();
 assert.ok(extract('activateMRMSRALATimeline').includes('warmMRMSRALALoopCache()'),'switching/window activation warms the chosen product');
 console.log('Radar playback PASS: one async player, speed changes, restart generations, full frame holds, type preloading and obsolete-worker cancellation.');
})().catch(e=>{console.error(e);process.exitCode=1;});
