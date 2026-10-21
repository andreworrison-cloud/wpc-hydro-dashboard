const assert = require('node:assert/strict');
const {ffgDisplayState: state} = require('./rfc_ffg_display.js');
const m = {active: {snapshot_time:'2026-10-17T14:00:00Z', reference_time:'2026-10-17T12:00:00Z'},
 policy:{max_snapshot_age_hours:3,max_reference_age_hours:9,future_tolerance_minutes:5},
 usable:true, state:'updated',last_attempt:{ok:true}};
const at = s => Date.parse('2026-10-17T'+s+'Z');
assert.equal(state(m,at('16:59:59')).state,'current');
assert.equal(state(m,at('17:00:00')).visible,false); // no ingest/status change needed
assert.equal(state({...m,last_attempt:{ok:false}},at('16:00:00')).state,'retained');
assert.equal(state({...m,last_attempt:{ok:false}},at('18:00:00')).state,'expired');
assert.equal(state({...m,active:null},at('16:00:00')).state,'unavailable');
assert.equal(state({...m,active:{...m.active,snapshot_time:'bad'}},at('16:00:00')).visible,false);
assert.equal(state(m,at('13:00:00')).visible,false);
assert.equal(state({...m,active:{...m.active,reference_time:'2026-10-17T06:00:00Z'}},at('16:00:00')).visible,false);
assert.equal(state({...m,usable:false,state:'unavailable'},at('16:00:00')).visible,false);
assert.equal(state({...m,policy:{...m.policy,max_snapshot_age_hours:0}},at('16:00:00')).visible,false);
console.log('10 freshness assertions passed');
