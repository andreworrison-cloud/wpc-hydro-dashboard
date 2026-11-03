const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const display = require('../cam_display.js');
const root = path.resolve(__dirname, '..');
let count = 0;
function test(name, fn) { fn(); count++; console.log('PASS', name); }
const meta = {schema:display.SCHEMA, spc_refs_init_utc:'2026-11-03T12:00:00Z', omd_refs_init_utc:'2026-11-03T12:00:00Z', spc_member_count:10,
    ffg:{snapshot_time_utc:'2026-11-03T11:00:00Z'},
    window_contract:{'3h_to_9h':{valid_start_utc:'2026-11-03T15:00:00Z',valid_end_utc:'2026-11-03T21:00:00Z'},
        '9h_to_15h':{valid_start_utc:'2026-11-03T21:00:00Z',valid_end_utc:'2026-11-04T03:00:00Z'},
        ero:{valid_start_utc:'2026-11-03T12:00:00Z',valid_end_utc:'2026-11-04T12:00:00Z'}}};
test('Archived HREF metadata cannot enable a new SPC image',()=>assert.throws(()=>display.validate({href_init_utc:'2026-11-03T06:00:00Z'},'cam')));
test('Different suite cycles cannot enable a blend',()=>assert.throws(()=>display.validate({...meta,omd_refs_init_utc:'2026-11-03T06:00:00Z'},'cam')));
test('A nine-member metadata package is rejected',()=>assert.throws(()=>display.validate({...meta,spc_member_count:9},'cam')));
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
test('Time box uses selected window and cycle-time FFG snapshot',()=>{
    const html=display.timeHTML(meta,'cam','ffg_9h_to_15h_spc_refs','SPC REFS: Max FFG Exceedance',new Date('2026-11-03T20:00:00Z'));
    assert.match(html,/03 Nov 21Z – 04 Nov 03Z/);assert.match(html,/03 Nov 11Z/);assert.match(html,/Experimental/);
});
test('Legends keep all five original colors and identify each suite',()=>{
    for (const ffg of [true,false]) {
        const html=display.legend(ffg,['SPC REFS (Exp): Max','OMD REFS: Max','SuperEnsemble: Max']);
        for (const c of display.colors[ffg?'ffg':'qpf'])assert.ok(html.includes(c));
        for (const n of ['SPC REFS','OMD REFS','50% SPC maximum + 50% OMD maximum'])assert.ok(html.includes(n));
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
    assert.match(html,/app\.js\?cam=spc-omd-cam-v1/);
});
console.log(`${count} CAM presentation checks passed.`);
