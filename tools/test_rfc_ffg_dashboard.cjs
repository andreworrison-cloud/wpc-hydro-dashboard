const fs=require('fs'),path=require('path'),assert=require('assert/strict');
const root=process.argv[2]||'.',fixture=process.argv[3];
if(!fixture)throw Error('Usage: node test_rfc_ffg_dashboard.cjs REPO PUBLIC_FIXTURE_DIR; fixture from Mercator review rebuild');
const {chromium}=require('playwright');
(async()=>{
const browser=await chromium.launch({executablePath:process.env.CHROMIUM_EXECUTABLE_PATH||undefined,headless:true,args:['--no-sandbox','--disable-gpu']});const page=await browser.newPage({viewport:{width:1440,height:1050}});
let mode='good',generation='fixture-a',errors=[],imageRequests=[];
const m=JSON.parse(fs.readFileSync(path.join(fixture,'metadata.json')));m.active.generation=generation;
for(const h of [1,3,6])m.active.assets[h].path=`generations/${generation}/rfc_ffg_${h}h.png`;
await page.addInitScript(()=>{window.ffgTestNow=Date.parse('2026-10-17T16:00:00Z');Date.now=()=>window.ffgTestNow;});
page.on('pageerror',e=>errors.push(e.message));
await page.route('**/*',async route=>{const url=route.request().url(),u=new URL(url);
 if(url.includes('/data/rfc-ffg-review/public/metadata.json')){
  if(mode==='offline')return route.fulfill({status:503,body:'outage'});
  const next=structuredClone(m);next.active.generation=generation;for(const h of [1,3,6])next.active.assets[h].path=`generations/${generation}/rfc_ffg_${h}h.png`;
  return route.fulfill({json:next});
 }
 if(url.includes('/data/rfc-ffg-review/public/generations/')){imageRequests.push(url);if(mode==='partial'&&url.endsWith('6h.png'))return route.fulfill({status:503,body:'partial'});const h=url.match(/rfc_ffg_(\d)h/)[1];return route.fulfill({body:fs.readFileSync(path.join(fixture,`rfc_ffg_${h}h.png`)),contentType:'image/png'});}
 if(u.hostname==='h5.local'){let f=path.join(root,u.pathname==='/'?'index.html':u.pathname);if(fs.existsSync(f)&&fs.statSync(f).isFile())return route.fulfill({body:fs.readFileSync(f),contentType:f.endsWith('.js')?'application/javascript':f.endsWith('.css')?'text/css':f.endsWith('.html')?'text/html':'application/json'});return route.fulfill({status:404,body:'missing fixture'});}
 if(url.includes('leaflet@1.9.4/dist/leaflet.js'))return route.fulfill({body:fs.readFileSync(path.join(root,'review/vendor/leaflet-1.9.4.js')),contentType:'application/javascript'});
 if(url.includes('leaflet@1.9.4/dist/leaflet.css'))return route.fulfill({body:fs.readFileSync(path.join(root,'review/vendor/leaflet-1.9.4.css')),contentType:'text/css'});
 if(url.includes('iso8601.min.js'))return route.fulfill({body:fs.readFileSync('/tmp/h5_iso.js'),contentType:'application/javascript'});
 if(url.includes('leaflet.timedimension.min.js'))return route.fulfill({body:fs.readFileSync('/tmp/h5_time.js'),contentType:'application/javascript'});
 if(url.includes('us-states.json'))return route.fulfill({body:fs.readFileSync(path.join(root,'review/vendor/us-states.json')),contentType:'application/json'});
 return route.fulfill({status:503,body:'Non-FFG services isolated for dashboard integration test'});
});
await page.goto('https://h5.local/');await page.waitForFunction(()=>window.RFCFFG?.getState().state==='current',{timeout:10000});
await page.evaluate(()=>{getAllDashboardLayerEntries().forEach(e=>setDashboardLayerActive(e,false));setDashboardLayerActive(layerEntriesById.get('rfc-ffg-3h'),true);selectDashboardLayer('rfc-ffg-3h');});
assert.equal(await page.locator('.rfc-ffg-raster').count(),1);assert.match(await page.locator('.rfc-ffg-card').innerText(),/3-hour/);
await page.evaluate(()=>{RFCFFG.layers[3].setOpacity(.65);});assert.equal(await page.locator('.rfc-ffg-raster').evaluate(x=>x.style.opacity),'0.65');
await page.evaluate(()=>setDashboardLayerActive(layerEntriesById.get('rfc-ffg-6h'),true));assert.equal(await page.evaluate(()=>map.hasLayer(RFCFFG.layers[3])),false);
assert.equal(await page.locator('.rfc-ffg-raster').count(),1);
mode='partial';generation='fixture-b';await page.evaluate(()=>RFCFFG.refresh());assert.equal(await page.evaluate(()=>RFCFFG.getMetadata().active.generation),'fixture-a');assert.equal(await page.evaluate(()=>RFCFFG.getState().state),'retained');
mode='good';await page.evaluate(()=>RFCFFG.refresh());assert.equal(await page.evaluate(()=>RFCFFG.getMetadata().active.generation),'fixture-b');
const before=imageRequests.length;await page.evaluate(()=>RFCFFG.refresh());assert.equal(imageRequests.length,before);
mode='offline';await page.evaluate(()=>RFCFFG.refresh());assert.equal(await page.evaluate(()=>RFCFFG.getState().state),'retained');assert.equal(await page.locator('.rfc-ffg-raster').count(),1);
await page.screenshot({path:'/tmp/h5_integrated_dashboard.png',fullPage:true});
await page.evaluate(()=>{ffgTestNow=Date.parse('2026-10-17T17:00:00Z');RFCFFG.sync();});assert.equal(await page.locator('.rfc-ffg-raster').count(),0);assert.match(await page.locator('.rfc-ffg-card').innerText(),/Expired/);
assert.deepEqual(errors,[]);console.log(JSON.stringify({actualDashboard:true,checks:['3 layer registration','legend and times','exclusive selection','opacity','partial generation retained','successful atomic replacement','unchanged no download','metadata outage retained','clock expiry hidden'],pageErrors:errors}));await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});
