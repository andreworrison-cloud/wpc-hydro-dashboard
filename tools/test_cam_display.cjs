const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const display = require('../cam_display.js');
const root = path.resolve(__dirname, '..');
let count = 0;
function test(name, fn) { fn(); count++; console.log('PASS', name); }
const meta = {schema:display.SCHEMA, spc_refs_init_utc:'2026-11-03T12:00:00Z', omd_refs_init_utc:'2026-11-03T12:00:00Z', spc_member_count:10,
    method:{probability_method:'emc-neighborhood-qpf-local-ffg-gaussian-v1'},
    common_ffg_reference_utc:'2026-11-03T12:00:00Z',
    ffg:{snapshot_time_utc:'2026-11-03T12:00:00Z', reference_time_utc:'2026-11-03T12:00:00Z',
        model_cycle_utc:'2026-11-03T12:00:00Z',ffg_cycle_policy:'official_synoptic_model_cycle'},
    window_contract:{'3h_to_9h':{valid_start_utc:'2026-11-03T15:00:00Z',valid_end_utc:'2026-11-03T21:00:00Z'},
        '9h_to_15h':{valid_start_utc:'2026-11-03T21:00:00Z',valid_end_utc:'2026-11-04T03:00:00Z'},
        ero:{valid_start_utc:'2026-11-03T12:00:00Z',valid_end_utc:'2026-11-04T12:00:00Z'}}};
test('Archived HREF metadata cannot enable a new SPC image',()=>assert.throws(()=>display.validate({href_init_utc:'2026-11-03T06:00:00Z'},'cam')));
test('Different suite cycles cannot enable a blend',()=>assert.throws(()=>display.validate({...meta,omd_refs_init_utc:'2026-11-03T06:00:00Z'},'cam')));
test('A nine-member metadata package is rejected',()=>assert.throws(()=>display.validate({...meta,spc_member_count:9},'cam')));
test('An older FFG snapshot or encoded reference cannot enable guidance',()=>{
    for(const key of ['snapshot_time_utc','reference_time_utc','model_cycle_utc']) {
        const bad={...meta,ffg:{...meta.ffg,[key]:'2026-11-03T11:00:00Z'}};
        for(const kind of ['cam','ero'])assert.throws(()=>display.validate(bad,kind));
    }
    assert.throws(()=>display.validate({...meta,common_ffg_reference_utc:'2026-11-03T06:00:00Z'},'cam'));
    assert.throws(()=>display.validate({...meta,ffg:{...meta.ffg,ffg_cycle_policy:'published_before_initialization'}},'cam'));
});
test('The prior 17Z-baseline schema cannot be relabeled as corrected guidance',()=>{
    assert.throws(()=>display.validate({...meta,schema:'wpc-spc-omd-cam-v1'},'cam'));
});
test('The obsolete SPC event-first method is rejected',()=>{
    assert.throws(()=>display.validate({...meta,schema:'wpc-spc-omd-cam-v2'},'ero'));
    assert.throws(()=>display.validate({...meta,method:{}},'ero'));
});
test('First nowcast expires independently of the second',()=>{
    const now=new Date('2026-11-03T21:00:00Z');
    assert.equal(display.state(meta,'cam','ffg_3h_to_9h_spc_refs',now).available,false);
    assert.equal(display.state(meta,'cam','ffg_9h_to_15h_spc_refs',now).available,true);
});
test('Day 1 expires at its absolute end',()=>assert.equal(display.state(meta,'ero','ffg_super',new Date('2026-11-04T12:00:00Z')).available,false));
test('Provider labels distinguish SPC, OMD, and SuperEnsemble',()=>{
    assert.equal(display.modelFromName('SPC REFS (Exp) [ERO]: Max FFG Exceedance'),'spc_refs');
    assert.equal(display.modelFromName('OMD REFS [ERO]: Max FFG Exceedance'),'omd_refs');
    assert.equal(display.modelFromKey('qpf_3h_to_9h_0.5_inch_spc_refs'),'spc_refs');
    assert.equal(display.modelFromName('HRRR-TLE'),null);
});
test('Every FFG time box uses the selected window and common official cycle',()=>{
    for(const model of ['spc_refs','omd_refs','super']) {
        const html=display.timeHTML(meta,'cam','ffg_9h_to_15h_'+model,display.labels[model]+': Max FFG Exceedance',new Date('2026-11-03T20:00:00Z'));
        assert.match(html,/03 Nov 21Z – 04 Nov 03Z/);
        assert.match(html,/Common official RFC FFG: 03 Nov 12Z/);
        assert.ok(!html.includes('available by initialization'));
        if(model==='spc_refs')assert.match(html,/Experimental/);
    }
});
test('Legends keep all five original colors and identify each suite',()=>{
    for (const ffg of [true,false]) {
        const html=display.legend(ffg,['SPC REFS (Exp): Max','OMD REFS: Max','SuperEnsemble: Max']);
        for (const c of display.colors[ffg?'ffg':'qpf'])assert.ok(html.includes(c));
        for (const n of ['SPC REFS','OMD REFS','50% SPC maximum + 50% OMD maximum'])assert.ok(html.includes(n));
        assert.ok(html.includes('Below 10% or unavailable: transparent.'));
        assert.ok(html.includes('Suite peaks can occur at different times.'));
        if(ffg)assert.ok(html.includes('Same official model-cycle RFC FFG for SPC and OMD'));
        assert.ok(!html.includes('producer FFG baseline'));
    }
});
test('All 45 menu layers bind to real new image keys',()=>{
    const app=fs.readFileSync(path.join(root,'app.js'),'utf8');
    const menuIds=[...app.matchAll(/id: '([^']+)', label: '[^']+', layer: (?:camLayers|eroCamLayers)/g)].map(m=>m[1]);
    assert.equal(menuIds.length,45);assert.equal(new Set(menuIds).size,45);
    for(const id of menuIds)assert.match(id,/^[a-z0-9-]+$/);
    const refs=[...app.matchAll(/label: '([^']+)', layer: (camLayers|eroCamLayers)\['([^']+)'\]/g)];
    assert.equal(refs.length,45);assert.equal(refs.filter(r=>r[1].includes('SPC REFS')).length,15);assert.equal(refs.filter(r=>r[1].includes('OMD REFS')).length,15);
    for(const r of refs)assert.ok(display.modelFromKey(r[3]));
    assert.ok(!refs.some(r=>r[1].includes('HREF')));
    const html=fs.readFileSync(path.join(root,'index.html'),'utf8');
    assert.ok(html.indexOf('cam_display.js')<html.indexOf('app.js'));
    assert.match(html,/app\.js\?cam=spc-omd-cam-v3/);
});
test('Automatic refresh updates the real time-box element and tolerates pre-DOM startup',()=>{
    const app=fs.readFileSync(path.join(root,'app.js'),'utf8');
    const start=app.indexOf('function refreshCAMAvailability()');
    const body=app.slice(start,app.indexOf('\n}\n',start)+2);
    const box={innerHTML:''};
    const layer={options:{opacity:.7},setOpacity(value){this.options.opacity=value;}};
    const key='ffg_9h_to_15h_spc_refs';
    const fixed=new Date('2026-11-03T20:00:00Z');
    const context={camLayers:{[key]:layer},eroCamLayers:{},camMetadata:meta,eroCamMetadata:null,
        camActiveSelection:{kind:'cam',key,layer,name:'SPC REFS: Max FFG Exceedance'},
        map:{hasLayer:()=>true},document:{getElementById:()=>box},
        WPC_CAM:{...display,state:(m,k,p)=>display.state(m,k,p,fixed),timeHTML:(m,k,p,n)=>display.timeHTML(m,k,p,n,fixed)}};
    vm.runInNewContext('('+body+')()',context);
    assert.match(box.innerHTML,/03 Nov 21Z – 04 Nov 03Z/);
    layer.options.opacity=.25;
    vm.runInNewContext('('+body+')()',context);
    assert.equal(layer.options.opacity,.25);
    context.document.getElementById=()=>null;
    assert.doesNotThrow(()=>vm.runInNewContext('('+body+')()',context));
});
test('Switching any of the 45 CAM rasters replaces its predecessor and preserves context',()=>{
    const app=fs.readFileSync(path.join(root,'app.js'),'utf8');
    const start=app.indexOf('function setDashboardLayerActive(');
    const body=app.slice(start,app.indexOf('\n}\n',start)+2);
    const refs=[...app.matchAll(/id: '([^']+)', label: '[^']+', layer: (camLayers|eroCamLayers)\['([^']+)'\]/g)];
    const camRows=app.split('\n').filter(line=>/id: '[^']+', label: '[^']+', layer: (camLayers|eroCamLayers)\[/.test(line));
    assert.equal(camRows.length,45);
    camRows.forEach(line=>assert.ok(line.includes("exclusiveGroup: 'cam-probability'")));
    const entries=refs.map(r=>({id:r[1],exclusiveGroup:'cam-probability',layer:{id:r[1],options:{opacity:.37}},onActivate(){this.activations=(this.activations||0)+1;},onDeactivate(){this.deactivations=(this.deactivations||0)+1;}}));
    const radar={id:'radar',layer:{}},hazards={id:'hazards',layer:{}};
    const active=new Set([radar.layer,hazards.layer]);
    const events=[];
    const context={map:{hasLayer:l=>active.has(l),addLayer:l=>active.add(l),removeLayer:l=>active.delete(l)},
        getAllDashboardLayerEntries:()=>[...entries,radar,hazards],dispatchOverlayEvent:(type,e)=>events.push([type,e.id]),syncSidebarWithMap:()=>{}};
    vm.createContext(context);vm.runInContext(body,context);
    for(const entry of entries) {
        context.setDashboardLayerActive(entry,true);
        assert.deepEqual([...active],[radar.layer,hazards.layer,entry.layer]);
        assert.equal(entry.layer.options.opacity,.37);
        assert.equal(entry.activations,1);
    }
    assert.equal(events.filter(e=>e[0]==='overlayremove').length,44);
    assert.ok(entries.slice(0,-1).every(e=>e.deactivations===1));
    context.setDashboardLayerActive(hazards,false);
    assert.ok(active.has(entries[44].layer));
    context.setDashboardLayerActive(entries[44],false);
    assert.deepEqual([...active],[radar.layer]);
});
test('Reselecting a CAM raster removes an existing stack without reactivating it',()=>{
    const app=fs.readFileSync(path.join(root,'app.js'),'utf8');
    const start=app.indexOf('function setDashboardLayerActive(');
    const body=app.slice(start,app.indexOf('\n}\n',start)+2);
    const a={layer:{},exclusiveGroup:'cam-probability'},b={layer:{},exclusiveGroup:'cam-probability'},c={layer:{},exclusiveGroup:'cam-probability'};const active=new Set([a.layer,b.layer,c.layer]);
    const context={map:{hasLayer:l=>active.has(l),addLayer:l=>{throw new Error('duplicate activation');},removeLayer:l=>active.delete(l)},
        getAllDashboardLayerEntries:()=>[a,b,c],dispatchOverlayEvent:()=>{},syncSidebarWithMap:()=>{}};
    vm.createContext(context);vm.runInContext(body,context);context.setDashboardLayerActive(a,true);
    assert.deepEqual([...active],[a.layer]);
});
console.log(`${count} CAM presentation checks passed.`);

