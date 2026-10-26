const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const c={};vm.runInNewContext(fs.readFileSync('surface_cartography.js','utf8'),c);const C=c.SurfaceCartography;
const time='2026-10-26T00:00:00Z',a={valid_time:time,generation:'2026102600-1234567890abcdef',products:{mslp:{unit:'hPa'},temperature:{unit:'°F'}}};
const line=(value,lat=40)=>({type:'Feature',properties:{kind:'contour',value,unit:'hPa'},geometry:{type:'LineString',coordinates:[[-123,lat],[-98,lat],[-68,lat]]}});
const data={type:'FeatureCollection',schema:'surface-contours-v1',key:'mslp',valid_time:time,interval:4,features:[line(1020),line(1024,38),line(1028,36)]};
C.validate(data,'mslp',a);
const asset={path:`pressure/${a.generation}/mslp_contours.geojson`,sha256:'a'.repeat(64),interval:4,feature_count:3};C.descriptor(asset,a,'mslp');
assert.throws(()=>C.descriptor({...asset,path:'../secret'},a,'mslp'));assert.throws(()=>C.descriptor({...asset,interval:2},a,'mslp'));
for(const mutate of [d=>d.valid_time='2026-10-25T23:00:00Z',d=>d.features[0].properties.unit='Pa',d=>d.features[0].properties.value=1003,d=>d.features[0].geometry.coordinates[0]=[0,0],d=>d.features[0].geometry.coordinates[0]=['-100',40]]){
 const bad=JSON.parse(JSON.stringify(data));mutate(bad);assert.throws(()=>C.validate(bad,'mslp',a));
}
const project=p=>({x:(p[0]+125)*20,y:(50-p[1])*20});
const labels=C.labels(data,'mslp',4,project,1200,600);
assert.ok(labels.length>=6,'national pressure view has repeated readable labels');
for(const p of labels){assert.ok(p.x>=28&&p.x<=1172&&p.y>=28&&p.y<=572);assert.equal(p.angle,0);assert.ok([1020,1024,1028].includes(p.value));}
const boxes=labels.map(p=>({...p,w:100,h:42}));for(let i=0;i<boxes.length;i++)for(let j=i+1;j<boxes.length;j++)assert.equal(C.overlap(boxes[i],boxes[j]),false);
const blocked={x:labels[0].x,y:labels[0].y,w:100,h:42};
assert.ok(C.labels(data,'mslp',4,project,1200,600,[blocked]).every(p=>!C.overlap({...p,w:100,h:42},blocked)),'station labels reserve screen space');
const temp={...data,key:'temperature',interval:10,features:[{...line(20),properties:{kind:'contour',value:20,unit:'°F'}}]};
C.validate(temp,'temperature',a);assert.equal(C.labels(temp,'temperature',4,project,1200,600).length,0);assert.ok(C.labels(temp,'temperature',5,project,1200,600).length>0);
assert.equal(C.visibleLevel(10,'temperature',4),false);assert.equal(C.visibleLevel(10,'temperature',6),true);assert.equal(C.visibleLevel(32,'temperature',4),true);
assert.equal(C.visibleLevel(1004,'mslp',3),true,'every 4-mb isobar remains visible at national scale');
const clipped=C.clip({x:-100,y:300},{x:1300,y:300},1200,600);assert.equal(clipped[0].x,28);assert.equal(clipped[1].x,1172);
assert.equal(C.clip({x:-100,y:-100},{x:1300,y:-100},1200,600),null);
assert.equal(C.labels({...data,features:[]},'mslp',4,project,1200,600).length,0);
console.log('Surface cartography checks passed: generation/time, 4-mb levels, masks/coordinates, viewport clipping, zoom labels and collision spacing.');
