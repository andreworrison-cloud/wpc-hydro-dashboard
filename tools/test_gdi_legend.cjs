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
