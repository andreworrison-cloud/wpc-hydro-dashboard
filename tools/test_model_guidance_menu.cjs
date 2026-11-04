const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const {JSDOM}=require(process.env.GDI_TEST_DOM_MODULE||'jsdom');
const menu=require('../model_guidance_menu.js');
const flash=require('../flash_flood_layer.js');
const app=fs.readFileSync(path.join(__dirname,'../app.js'),'utf8');
const configs=name=>vm.runInNewContext(app.match(new RegExp(`const ${name} = (\\[[\\s\\S]*?\\n\\]);`))[1]);
const overlay=(url,bounds,options)=>({url,bounds,options,setOpacity(v){this.options.opacity=v;return this;}});

function fixture(stored=null,unavailableStorage=false){
 const dom=new JSDOM('<details id="guidance"><summary>Guidance</summary><div id="body"></div></details>');
 global.document=dom.window.document;
 const diag=configs('HRRR_DIAGNOSTIC_LAYER_CONFIGS'),tle=configs('HRRR_TLE_LAYER_CONFIGS');
 const hrrr={id:'hrrr-diagnostics',layers:diag.map(c=>({...c,layer:overlay('',[],{opacity:1})}))};
 const hrrrTLE={id:'hrrr-tle',groups:['Core FFG Guidance','Heavy Rain / Persistence','Timing / Evolution'].map(title=>({title,layers:tle.filter(c=>c.group===title).map(c=>({...c,layer:overlay('',[],{opacity:1})}))}))};
 const other=['rrfs','hrrr_rrfs'].map(suite=>flash.create({L:{imageOverlay:overlay},suite,label:suite==='rrfs'?'RRFS':'HRRR/RRFS',diagnosticConfigs:diag,tleConfigs:tle}).sections).flat();
 const gdi={id:'gdi',layers:['forecast','day1'].flatMap(product=>['hrrr','rrfs','blend'].map(model=>({id:`gdi-${product}-${model}`,label:`${model} ${product} GDI`,layer:overlay('',[],{opacity:.8})})))};
 const sections=[{id:'before',layers:[]},gdi,hrrr,hrrrTLE,...other,{id:'after',layers:[]}];
 const flatten=s=>[...(s.layers||[]),...(s.groups||[]).flatMap(flatten)];
 const original=sections.flatMap(flatten).map(e=>({entry:e,id:e.id,label:e.label,layer:e.layer}));
 const registry=menu.consolidate(sections);
 assert.deepEqual(sections.map(s=>s.id),['before','model-guidance','after']);
 original.forEach(x=>{assert.equal(x.entry.id,x.id);assert.equal(x.entry.label,x.label);assert.equal(x.entry.layer,x.layer);});
 assert.equal(flatten(registry.section).length,66);
 registry.entries.forEach(e=>{e.searchText=[e.label,e.keywords||'',menu.MODELS[e.guidance.model],menu.FAMILIES[e.guidance.family]].join(' ').toLowerCase();});
 let saved=stored,selected=null,writes=0;
 const active=new Set(),external={id:'warnings'};active.add(external);
 const storage={getItem(){if(unavailableStorage)throw Error('blocked');return saved;},setItem(k,v){if(unavailableStorage)throw Error('blocked');saved=v;writes++;}};
 let api;
 const syncChecks=()=>document.querySelectorAll('input[data-entry]').forEach(input=>{input.checked=active.has(registry.entries.find(e=>e.id===input.dataset.entry));});
 const setActive=(entry,on)=>{assert.ok(entry);on?active.add(entry):active.delete(entry);syncChecks();api?.sync();};
 api=menu.create({registry,isActive:e=>active.has(e),setActive,select:e=>{selected=e;api.pick(e);},storage,
  getStatus:()=>({cycle:'2026-11-04T18:00:00Z',start:'2026-11-04T18:00:00Z',end:'2026-11-05T06:00:00Z'}),formatTime:x=>x});
 const renderRow=entry=>{const row=document.createElement('label'),input=document.createElement('input'),label=document.createElement('span');
  row.dataset.id=entry.id;input.type='checkbox';input.dataset.entry=entry.id;input.checked=active.has(entry);label.textContent=entry.menuLabel;
  input.addEventListener('change',()=>{api.pick(entry);setActive(entry,input.checked);api.sync();});row.append(input,label);return row;};
 api.mount(document.getElementById('guidance'),document.getElementById('body'),renderRow);
 const click=entry=>document.querySelector(`[data-entry="${entry.id}"]`).click();
 const panels=()=>[...document.querySelectorAll('.model-guidance-panel')].filter(p=>!p.hidden);
 return {dom,api,registry,active,external,click,setActive,panels,get saved(){return saved;},get selected(){return selected;},get writes(){return writes;}};
}

let checks=0;
function check(name,fn){fn();checks++;console.log('PASS '+name);}
check('all 66 existing layer identities survive seven-to-one consolidation',()=>{
 const f=fixture();
 for(const model of ['hrrr','rrfs','blend']){
  const entries=f.registry.entries.filter(e=>e.guidance.model===model);
  assert.equal(entries.length,22);
  assert.deepEqual(['core','heavy','timing'].map(g=>entries.filter(e=>e.guidance.group===g).length),[5,6,7]);
 }
 assert.equal(new Set(f.registry.entries.map(e=>e.id)).size,66);
 assert.equal(document.querySelectorAll('[data-entry]').length,66);
 assert.equal(f.panels().length,1);assert.equal(f.panels()[0].dataset.guidanceFamily,'diagnostics');
 f.dom.window.close();
});
check('active TLE product, opacity and external context survive all three models',()=>{
 const f=fixture(),original=f.registry.find('hrrr','tle','tle-ffg-consensus');
 f.click(original);original.layer.setOpacity(.45);
 for(const model of ['rrfs','blend','hrrr']){
  f.api.chooseModel(model);const next=f.registry.find(model,'tle','tle-ffg-consensus');
  assert.ok(f.active.has(next));assert.equal(f.active.size,2);assert.ok(f.active.has(f.external));
  assert.equal(next.layer.options.opacity,.45);assert.equal(f.selected,next);
  assert.match(document.querySelector('.guidance-active-status').textContent,/FFG Exceedance Consensus/);
  assert.match(document.querySelector('.guidance-active-status').textContent,/2026-11-05T06:00:00Z/);
 }
 f.dom.window.close();
});
check('multiple deliberate product overlays transfer without dropping a product',()=>{
 const f=fixture(),a=f.registry.find('hrrr','tle','tle-ffg-1h'),b=f.registry.find('hrrr','diagnostics','diag-ffg-coverage');
 f.click(a);f.click(b);a.layer.setOpacity(.3);b.layer.setOpacity(.6);f.api.chooseModel('blend');
 assert.equal(f.active.size,3);assert.ok(!f.active.has(a)&&!f.active.has(b));
 assert.equal(f.registry.find('blend','tle','tle-ffg-1h').layer.options.opacity,.3);
 assert.equal(f.registry.find('blend','diagnostics','diag-ffg-coverage').layer.options.opacity,.6);
 f.dom.window.close();
});
check('browsing controls never activate an unchecked product',()=>{
 const f=fixture();f.api.chooseModel('rrfs');f.api.chooseFamily('tle');
 assert.equal(f.active.size,1);assert.equal(f.panels()[0].dataset.guidanceModel,'rrfs');
 f.api.chooseFamily('gdi');assert.equal(f.panels()[0].querySelectorAll('input[data-entry]').length,2);
 assert.equal(f.api.current().guidance.product,'forecast');assert.equal(f.active.size,1);
 f.dom.window.close();
});
check('GDI forecast and Day 1 product identities follow the selected model',()=>{
 const f=fixture();f.click(f.registry.find('rrfs','gdi','day1'));f.api.chooseModel('blend');
 assert.ok(f.active.has(f.registry.find('blend','gdi','day1')));
 assert.equal(f.api.current().guidance.product,'day1');
 f.api.chooseFamily('tle');f.api.chooseFamily('gdi');assert.equal(f.api.current().guidance.product,'day1');
 f.dom.window.close();
});
check('search finds every model then returns to the selected family and group states',()=>{
 const f=fixture();f.api.chooseModel('rrfs');f.api.chooseFamily('gdi');
 f.api.applySearch('ffg exceedance consensus');assert.equal(f.panels().length,3);
 assert.ok(f.panels().every(p=>p.dataset.guidanceFamily==='tle'));
 assert.ok(f.panels().every(p=>p.querySelector('[data-guidance-group="core"]').open));
 f.api.applySearch('nothing-can-match-this');assert.equal(document.getElementById('guidance').hidden,true);
 f.api.applySearch('');assert.equal(document.getElementById('guidance').hidden,false);
 assert.equal(f.panels().length,1);assert.equal(f.panels()[0].dataset.guidanceModel,'rrfs');assert.equal(f.panels()[0].dataset.guidanceFamily,'gdi');
 f.api.chooseFamily('tle');assert.equal(f.panels()[0].querySelector('[data-guidance-group="heavy"]').open,false);
 f.dom.window.close();
});
check('model, family, last product and checked guidance restore after reload',()=>{
 const f=fixture();f.click(f.registry.find('blend','tle','tle-run-change'));const saved=f.saved;f.dom.window.close();
 const restored=fixture(saved);assert.equal(restored.api.getState().model,'blend');assert.equal(restored.api.getState().family,'tle');
 assert.equal(restored.api.current().guidance.product,'tle-run-change');
 assert.ok(restored.active.has(restored.registry.find('blend','tle','tle-run-change')));
 assert.equal(restored.panels()[0].querySelector('[data-guidance-group="timing"]').open,true);
 assert.equal(restored.api.getState().open,true);restored.dom.window.close();
});
check('invalid or inaccessible saved preferences fall back without breaking the menu',()=>{
 for(const saved of ['{bad json',JSON.stringify({version:1,model:'bad',family:'bad',products:{tle:'bad'},active:['delete-everything']}),null]){
  const f=fixture(saved,saved===null);assert.equal(f.api.getState().model,'hrrr');assert.equal(f.active.size,1);f.api.chooseModel('rrfs');f.dom.window.close();
 }
});
check('status refresh does not write preferences for every GDI animation frame',()=>{
 const f=fixture();const before=f.writes;for(let i=0;i<25;i++){f.api.refreshStatus();f.api.sync();}
 assert.equal(f.writes,before);f.dom.window.close();
});
console.log(`${checks} model-guidance menu scenarios passed.`);
