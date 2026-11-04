const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const {create} = require('../flash_flood_layer.js');
const app = fs.readFileSync(require('node:path').join(__dirname,'../app.js'),'utf8');
const getConfigs = name => vm.runInNewContext(app.match(new RegExp(`const ${name} = (\\[[\\s\\S]*?\\n\\]);`))[1]);
const diagnosticConfigs = getConfigs('HRRR_DIAGNOSTIC_LAYER_CONFIGS');
const tleConfigs = getConfigs('HRRR_TLE_LAYER_CONFIGS');
const boxes = new Map();
global.document = {getElementById(id) {if (!boxes.has(id)) boxes.set(id,{style:{},innerHTML:''}); return boxes.get(id);}};
const imageOverlay = (url,bounds,options) => ({url,bounds,options,
    setUrl(url){this.url=url;return this;},setBounds(b){this.bounds=b;return this;},setOpacity(o){this.options.opacity=o;return this;}});
const active = new Set();
const shell = (title,subtitle,body,footer) => [title,subtitle,body,footer].join('|');
const rows = items => items.map(r=>r.label).join(';');
let preloaded = [], fetches = 0;
async function check(suiteName,label,count) {
    const s = create({L:{imageOverlay},suite:suiteName,label,diagnosticConfigs,tleConfigs,
        isActive:n=>active.has(n), formatTime:x=>x, legacyLegend:c=>c.label+' HRRR',
        legendShell:shell,legendRows:rows,preload:async url=>preloaded.push(url),changed:()=>{}});
    assert.equal(s.configs.length,20);
    assert.equal(s.sections.length,2);
    assert.deepEqual(s.sections[1].groups.map(g=>g.layers.length),[5,6,7]);
    assert.equal(new Set(s.configs.map(c=>c.id)).size,20);
    assert.ok(s.configs.every(c=>c.layer.options.opacity===0 && c.layer.url.startsWith('data:')));
    const anchor=new Date(Math.floor(Date.now()/3600000)*3600000-2*3600000).toISOString();
    const end=new Date(Date.parse(anchor)+12*3600000).toISOString();
    const metadata={schema:'wpc-flash-flood-suite-v1',suite:suiteName,complete:true,algorithm_version:'3.3',
        latest_cycle_utc:anchor,diagnostic_cycle_utc:anchor,common_valid_start_utc:anchor,common_valid_end_utc:end,
        diagnostic_valid_start_utc:anchor,diagnostic_valid_end_utc:end,generated_utc:anchor,
        diagnostic_ffg_analysis_utc:anchor,ffg_analysis_utc:anchor,members_available:count,
        bounds:[[23,-125],[50.5,-66.5]],layers:Object.fromEntries(s.configs.map(c=>[c.key,{file:c.file,sha256:'a'.repeat(64)}]))};
    const manifest=structuredClone(metadata);
    global.fetch=async url=>{fetches++; return {ok:true,json:async()=>structuredClone(url.includes('manifest')?manifest:metadata)};};
    const first=s.configs[0];active.add(first.label);
    first.layer.setOpacity(.45); // a model switch may precede the first metadata read
    assert.equal(await s.refresh(),true);
    assert.equal(preloaded.length,1,'Only the active layer should decode during refresh');
    assert.equal(first.layer.options.opacity,.45,'Initial metadata must retain a requested comparison opacity');
    assert.ok(s.configs.slice(1).every(c=>c.layer.options.opacity===1));
    assert.ok(boxes.get(s.timeBoxIds[0]).innerHTML.includes('Valid:'));
    const before=fetches;assert.equal(await s.refresh(),false);assert.equal(fetches,before+1);
    first.layer.setOpacity(.45);
    assert.equal(await s.refresh({force:true}),true);
    assert.equal(first.layer.options.opacity,.45,'Hourly updates must preserve the selected opacity');
    metadata.members_available=count-1;
    assert.equal(await s.refresh({force:true}),false);
    assert.equal(first.layer.options.opacity,.45,'A failed replacement must retain an unexpired package');
    if(count===12){
        assert.ok(s.legend(s.configs.find(c=>c.key==='ffg_consensus')).includes('1–2/12'));
        assert.ok(s.legend(s.configs.find(c=>c.key==='evolution_00_03')).includes('≥4/12'));
        assert.ok(s.legend(s.configs.find(c=>c.key==='run_change')).includes('≥4/6'));
        assert.ok(s.legend(s.configs.find(c=>c.key==='latest3')).includes('3 HRRR + 3 RRFS'));
    }
    const clock=Date.now;Date.now=()=>Date.parse(end)+1;
    try{s.syncTimeBoxes();assert.ok(s.configs.every(c=>c.layer.options.opacity===0));assert.ok(boxes.get(s.timeBoxIds[0]).innerHTML.includes('Expired'));}finally{Date.now=clock;}
    metadata.members_available=count;
    assert.equal(await s.refresh({force:true}),true);
    assert.equal(first.layer.options.opacity,.45,'Fresh recovery must restore opacity after expiry');
    active.clear();preloaded=[];
    return s;
}
(async()=>{
    const rrfs=await check('rrfs','RRFS',6);
    const blend=await check('hrrr_rrfs','HRRR/RRFS',12);
    assert.equal(new Set([...rrfs.configs,...blend.configs].map(c=>c.id)).size,40);
    assert.equal(new Set([...rrfs.configs,...blend.configs].map(c=>c.label)).size,40);
    console.log('Flash-flood display PASS: 40 distinct layers; menu groups, exact counts, active-image loading, refresh retention and expiry');
})().catch(e=>{console.error(e);process.exitCode=1;});
