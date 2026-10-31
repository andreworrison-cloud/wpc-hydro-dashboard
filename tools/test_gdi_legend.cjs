/* DOM regression: GDI controls survive rapid radar/forecast legend updates. */
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const {JSDOM}=require(process.env.GDI_TEST_DOM_MODULE||'jsdom');
const dom=new JSDOM('<!doctype html><div id="legend-container"></div>');
const document=dom.window.document;
const source=fs.readFileSync('app.js','utf8');
const start=source.indexOf('function patchGDILegendNode('),end=source.indexOf('\nfunction updateLegends()',start);
assert.ok(start>=0&&end>start);
const patch=vm.runInNewContext(source.slice(start,end)+'\npatchGDILegendNode;');
const card=document.createElement('div');document.querySelector('#legend-container').appendChild(card);
function markup(frame,checked=true){return `<div class="gdi-legend" data-gdi-pane="test"><strong>HRRR GDI</strong><div class="gdi-time">Valid ${frame}</div><div class="gdi-controls"><button data-gdi-play="test">${frame%2?'Play':'Pause'}</button><select aria-label="GDI forecast valid time">${Array.from({length:7},(_,i)=>`<option value="${i}" ${i===frame?'selected':''}>Hour ${i}</option>`).join('')}</select><input type="checkbox" ${checked?'checked':''}></div></div>`;}
card.innerHTML=markup(0);
const button=card.querySelector('button'),select=card.querySelector('select'),checkbox=card.querySelector('input');
let clicks=0,captured=0;button.addEventListener('click',()=>clicks++);
// Reproduce Leaflet's suppression of bubbling control clicks.
card.addEventListener('click',event=>event.stopPropagation());
document.addEventListener('click',()=>captured++,true);
select.focus();
for(let frame=1;frame<7;frame++){
 const fresh=document.createElement('div');fresh.innerHTML=markup(frame,false);patch(card,fresh);
 assert.equal(card.querySelector('button'),button,'button identity survives frame updates');
 assert.equal(card.querySelector('select'),select,'select identity survives frame updates');
 assert.equal(document.activeElement,select,'focused select stays attached');
 assert.equal(select.value,String(frame));assert.equal(checkbox.checked,false);
 assert.equal(card.querySelector('.gdi-time').textContent,'Valid '+frame);
 button.click();
}
assert.equal(clicks,6);assert.equal(captured,6,'capture handlers receive clicks even inside Leaflet controls');
const changed=document.createElement('div');changed.innerHTML='<div class="gdi-legend" data-gdi-pane="test"><strong>HRRR/RRFS TLE</strong><div>Hourly RRFS inputs unavailable</div></div>';
patch(card,changed);assert.equal(card.querySelector('button'),null,'availability changes remove obsolete controls');
console.log('GDI legend DOM checks passed: stable controls/focus, valid-time updates, click capture, unavailable-state transition.');

// RAP change: range labels must describe the renderer's actual clamped bins.
const {execFileSync}=require('node:child_process');
const rap=JSON.parse(execFileSync('python',['-c',`import ast,json,pathlib
root=ast.parse(pathlib.Path('tools/gdi/build_rap.py').read_text())
def constant(name):
 return next(ast.literal_eval(n.value) for n in ast.walk(root) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id==name for t in n.targets))
colors=constant('CHANGE_COLORS');edges=constant('CHANGE_EDGES')
print(json.dumps({'colors':colors,'edges':edges}))`],{encoding:'utf8'}));
const display={};vm.runInNewContext(fs.readFileSync('gdi_display.js','utf8'),display);
const ranges=display.GDIDisplay.binRanges(rap.edges);
const probes=[-100,-20,-15,-10,-5,-Number.EPSILON,0,Number.EPSILON,4.999,5,10,15,20,100];
const expectedBins=[0,1,2,3,4,4,5,5,5,6,7,8,9,9];
probes.forEach((value,i)=>assert.equal(ranges.findIndex(r=>value>=r.lower&&value<r.upper),expectedBins[i]));
const scale=document.createElement('div');scale.innerHTML=display.GDIDisplay.scale(rap.colors,rap.edges,'GDI change (3 h)',{zeroCentered:true});
const swatches=scale.querySelectorAll('.gdi-scale-bar span');assert.equal(swatches.length,10);
assert.equal(swatches[0].title,'< −20 GDI change (3 h)');
assert.equal(swatches[4].title,'−5 to < 0 GDI change (3 h)');
assert.equal(swatches[5].title,'0 to < +5 GDI change (3 h)');
assert.equal(swatches[9].title,'≥ +20 GDI change (3 h)');
assert.equal(scale.querySelector('.gdi-change-zero').textContent,'0');assert.equal(scale.querySelector('.gdi-change-zero').style.left,'50%');
assert.equal(scale.querySelectorAll('.gdi-change-zero').length,1);
assert.equal(scale.querySelectorAll('.gdi-change-neutral-ticks').length,0);
assert.ok(!scale.querySelector('.gdi-scale-ticks').textContent.includes('−30'));
assert.ok(!scale.textContent.includes('Near zero'));
assert.ok(!rap.colors.includes('#f7f7f7'),'no neutral color band');
rap.colors.forEach((color,i)=>assert.ok(swatches[i].getAttribute('style').includes(color)));
// A previous data generation may remain visible until the next atomic publish.
const legacy=document.createElement('div');legacy.innerHTML=display.GDIDisplay.scale([...rap.colors.slice(0,5),'#f7f7f7',...rap.colors.slice(5)],[-30,-20,-15,-10,-5,-2,2,5,10,15,20],'GDI change (3 h)',{zeroCentered:true});
assert.match(legacy.querySelector('.gdi-change-ranges').textContent,/Near zero: −2 to < \+2/);
assert.ok(legacy.querySelector('.gdi-change-neutral-ticks .gdi-change-zero'));
console.log('RAP change legend checks passed: source palette, zero boundary, five-unit bins, tails and previous-generation compatibility.');

// Exercise the real row and group logic with native checkbox click behavior.
function sourceFunction(name){const a=source.indexOf('function '+name+'(');assert.ok(a>=0);return source.slice(a,source.indexOf('\n}',a)+2);}
const active=new Set(),entries=[],entryIndex=new Map(),events=[];
const rows=document.createElement('div');document.body.appendChild(rows);
const rowContext={document,selectedDashboardLayerId:null,layerEntriesById:entryIndex,
 map:{hasLayer:layer=>active.has(layer),addLayer:layer=>active.add(layer),removeLayer:layer=>active.delete(layer),fire:(type,event)=>events.push([type,event.name])},
 getAllDashboardLayerEntries:()=>entries,selectDashboardLayer(){},updateActiveLayerCount(){}};
vm.createContext(rowContext);
for(const name of ['dispatchOverlayEvent','syncSidebarWithMap','setDashboardLayerActive','enforceExclusiveGDISelection','renderLayerRow'])vm.runInContext(sourceFunction(name),rowContext);
for(const [id,group] of [['analysis','gdi'],['change','gdi'],['forecast','gdi'],['pwat',null]]){
 const entry={id,label:id,layer:{id},searchText:id,exclusiveGroup:group};
 if(group)entry.onActivate=e=>rowContext.enforceExclusiveGDISelection(e);
 entries.push(entry);entryIndex.set(id,entry);rows.appendChild(rowContext.renderLayerRow(entry));
}
const inputs=Array.from(rows.querySelectorAll('input'));assert.ok(inputs.every(input=>input.type==='checkbox'));
inputs[0].click();assert.ok(active.has(entries[0].layer));
inputs[1].click();assert.ok(active.has(entries[1].layer));assert.ok(!active.has(entries[0].layer));assert.equal(inputs[0].checked,false);
inputs[1].click();assert.equal(active.size,0,'checked GDI square can be switched off');assert.equal(inputs[1].checked,false);
inputs[3].click();inputs[2].click();assert.equal(active.size,2,'independent layers remain available with GDI');
rows.querySelector('[data-layer-id="analysis"] .layer-label').click();assert.ok(active.has(entries[0].layer));assert.ok(!active.has(entries[2].layer));assert.ok(active.has(entries[3].layer));
console.log('Square layer-control checks passed: native toggling, label clicks, GDI exclusivity and independent overlays.');
