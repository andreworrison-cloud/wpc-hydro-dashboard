/* Exercise actual dashboard controls with native DOM change events. */
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const {JSDOM}=require(process.env.GDI_TEST_DOM_MODULE||'jsdom');
const display=require('../winter_precip_display.js');
const dom=new JSDOM('<!doctype html><div id="control"></div><div id="mrms-rala-time-box"></div>');
const document=dom.window.document,source=fs.readFileSync('app.js','utf8');
const extract=name=>{const start=source.indexOf('function '+name+'(');assert.ok(start>=0);return source.slice(start,source.indexOf('\n}',start)+2);};
const context={document,WinterPrecipDisplay:display,
 dashboardTimeControl:{_container:document.querySelector('#control')},mrmsRalaSpeedControl:null,mrmsRalaModeSelect:null,
 MRMS_RALA_WINDOW_OPTIONS_MINUTES:[120,240,360],MRMS_RALA_MAX_FRAME_STEP_MS:2000,MRMS_RALA_MIN_FRAME_STEP_MS:100,MRMS_RALA_FRAME_STEP_INCREMENT_MS:50,
 L:{DomUtil:{create:(tag,cls,parent)=>{const e=document.createElement(tag);e.className=cls;parent.appendChild(e);return e;}},DomEvent:{disableClickPropagation(){},disableScrollPropagation(){}}},
 syncMRMSRALAFrameStepControl(){},syncMRMSRALAWindowControl(){},syncRadarSpeedControlVisibility(){},
 setMRMSRALAWindowMinutes(){},setMRMSRALAFrameStep(){},setMRMSRALADisplayMode:mode=>{context.changed=mode;},
 mrmsRalaMetadata:null,mrmsRalaDisplayMode:'reflectivity',mrmsRalaFrameRequestSerial:0,mrmsRalaCurrentImageUrl:'',mrmsRalaVisibleLayer:{setOpacity(){}},
 map:{hasLayer:()=>true},mrmsRalaLayer:{},formatMRMSRALATimeBox:()=>'<strong>Radar time</strong>',bindMRMSRALAOpacityControl(){},refreshLegendDockSummary(){},
};
vm.createContext(context);
vm.runInContext(['createMRMSRALAFrameStepControl','createMRMSRALADisplayModeControl','syncMRMSRALADisplayMode','updateMRMSRALATimeBox'].map(extract).join('\n'),context);
context.createMRMSRALAFrameStepControl();
context.updateMRMSRALATimeBox();
const select=context.mrmsRalaModeSelect;
assert.equal(select.options.length,2);assert.equal(select.options[1].disabled,true);
assert.equal(select.getAttribute('aria-label'),'Radar display');
context.mrmsRalaMetadata={frames:[{valid_time_utc:'2026-10-24T05:34:40Z',ptype_png:'winter_frames/winter_20261024T053440Z.png',ptype:{flag_valid_time_utc:'2026-10-24T05:34:00Z',hrrr:null}}],winter_type:{revision:'mrms-hrrr-winter-v1',experimental:true,classes:['Rain','Mix','Snow','Ice (sleet/freezing rain)'].map((label,i)=>({id:i+1,label,color:'#123456'}))}};
context.syncMRMSRALADisplayMode();assert.equal(select.options[1].disabled,false);
select.value='ptype';select.dispatchEvent(new dom.window.Event('change'));assert.equal(context.changed,'ptype');
context.mrmsRalaDisplayMode='ptype';context.mrmsRalaCurrentImageUrl='old-type.png';
context.mrmsRalaMetadata={frames:[]};context.syncMRMSRALADisplayMode();
assert.equal(select.value,'reflectivity');assert.equal(select.options[1].disabled,true);
assert.equal(context.mrmsRalaCurrentImageUrl,'');assert.equal(context.mrmsRalaFrameRequestSerial,1);
assert.equal(context.mrmsRalaModeSelect,select,'existing control survives metadata changes');
select.focus();
for(let i=0;i<30;i++) context.updateMRMSRALATimeBox();
assert.equal(context.mrmsRalaModeSelect,select);assert.equal(document.activeElement,select,'animation updates preserve focus');
assert.equal(select.closest('#mrms-rala-time-box').id,'mrms-rala-time-box');
assert.equal(document.querySelector('#control select[aria-label="Radar display"]'),null,'playback bar stays compact');
console.log('Winter type DOM PASS: accessible card control, availability, switching, recovery, stable focus during animation.');
