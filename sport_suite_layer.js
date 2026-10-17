/* Four-depth review adapter. Field interpolation precedes the exact wet-tail palette. */
(function (root) {
    const depths = [10, 40, 100, 200];
    const colors = [[170,220,255,90],[80,170,255,150],[20,110,235,200],[0,45,180,235],[120,0,180,255]];
    const edges = [70,80,90,95,98,100];
    const esc = value => String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    const utc = value => Number.isFinite(Date.parse(value)) ? new Date(value).toISOString().replace('T',' ').replace(/\.\d{3}Z$/,'Z') : 'Unavailable';
    function displayState(metadata, now = Date.now(), failed = false) {
        const a = metadata?.active, time = Date.parse(a?.valid_time), age = (now-time)/3600000;
        if (!a || !Number.isFinite(age)) return {visible:false, state:'unavailable', label:'Unavailable — no validated suite'};
        if (age < 0) return {visible:false, state:'future', label:'Hidden — invalid future valid time'};
        if (age >= 72) return {visible:false, state:'expired', age, label:'Expired—awaiting newer data (hidden at 72 hours)'};
        const retained = failed || metadata.last_attempt?.ok === false;
        return {visible:true, age, state:retained?'retained':age>=48?'aging':'available',
            label:(retained?'Retained previous suite · ':'')+(age>=48?'Aging soil-moisture data':'Within dashboard age limit')+` · ${age.toFixed(1)} h old`};
    }
    function validate(metadata, previous) {
        if (metadata?.schema_version !== 1 || metadata.policy?.warn_age_hours !== 48 || metadata.policy?.expire_age_hours !== 72 || metadata.policy?.status !== 'approved_dashboard_policy_v1') throw Error('SPoRT dashboard policy mismatch');
        const a=metadata.active;if(!a)return;
        if (!Number.isFinite(Date.parse(a.valid_time)) || !/^\d{8}-[a-f0-9]{20}-sport-suite-wet-tail-v2$/.test(a.generation) || a.render_revision!=='sport-suite-wet-tail-v2') throw Error('Invalid SPoRT generation');
        if (Object.keys(a.products || {}).sort().join(',') !== ['10','100','200','40'].join(',')) throw Error('Incomplete SPoRT suite');
        let bounds;
        depths.forEach(d=>{
            const p=a.products[d],i=p.image;
            if(JSON.stringify(p.depth_cm)!==JSON.stringify([0,d]) || p.valid_time!==a.valid_time)throw Error('SPoRT depth/time mismatch');
            if(i?.crs!=='EPSG:3857'||i.width!==4000||i.height!==2538||i.resampling!=='bilinear'||i.mask_resampling!=='nearest'||i.palette!=='sport-wet-tail-v4')throw Error('SPoRT display contract mismatch');
            if(i.path!==`generations/${a.generation}/sport_0_${d}cm.png`||!/^[a-f0-9]{64}$/.test(i.sha256))throw Error('Unsafe SPoRT image');
            const b=i.bounds;
            if(!Array.isArray(b)||b.length!==2||!b.every(x=>Array.isArray(x)&&x.length===2&&x.every(Number.isFinite))||b[0][0]<24||b[0][0]>26||b[1][0]<52||b[1][0]>54||b[0][1]<-126||b[0][1]>-124||b[1][1]<-68||b[1][1]>-66)throw Error('Invalid SPoRT bounds');
            if(bounds && JSON.stringify(bounds)!==JSON.stringify(b))throw Error('SPoRT grids differ');bounds=b;
        });
        if(previous?.active){
            if(Date.parse(a.valid_time)<Date.parse(previous.active.valid_time))throw Error('Regressing SPoRT time');
            if(a.generation===previous.active.generation && JSON.stringify(a)!==JSON.stringify(previous.active))throw Error('Immutable SPoRT generation changed');
        }
    }
    function create({map, metadataURL, onChange=()=>{}, now=()=>Date.now()}) {
        const layers={},images={};let metadata=null,loaded=null,busy=false,failed=false,objectURLs=[],borders=null;
        map.createPane('sportSuite');map.getPane('sportSuite').style.zIndex=341;
        depths.forEach(d=>{const group=L.layerGroup();group.options.opacity=1;
            group.setOpacity=v=>{group.options.opacity=v;group.eachLayer(l=>l.setOpacity(v));};layers[d]=group;});
        const state=()=>displayState(metadata,now(),failed);
        const selected=()=>depths.filter(d=>map.hasLayer(layers[d]));
        function sync(){const s=state();depths.forEach(d=>{
            if(s.visible&&images[d]&&!layers[d].hasLayer(images[d]))layers[d].addLayer(images[d]);
            if(!s.visible)layers[d].clearLayers();
        });
            if(borders){if(selected().length&&!map.hasLayer(borders))borders.addTo(map);if(!selected().length&&map.hasLayer(borders))map.removeLayer(borders);}onChange();
        }
        async function refresh(){if(busy)return;busy=true;
            const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),30000),staged=[];
            try{
                const url=new URL(metadataURL,document.baseURI);url.searchParams.set('_check',String(now()));
                const response=await fetch(url,{cache:'no-store',signal:controller.signal});if(!response.ok)throw Error('SPoRT metadata unavailable');
                const next=await response.json();validate(next,metadata);
                if(next.active && Date.parse(next.active.valid_time)>now())throw Error('Future SPoRT valid time');
                if(next.active&&displayState(next,now()).visible&&next.active.generation!==loaded){
                    const results=await Promise.allSettled(depths.map(async d=>{
                        const asset=next.active.products[d].image;
                        const r=await fetch(new URL(asset.path,new URL('.',url)),{signal:controller.signal});if(!r.ok)throw Error('SPoRT image unavailable');
                        const data=await r.arrayBuffer(),hash=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',data)),v=>v.toString(16).padStart(2,'0')).join('');
                        if(hash!==asset.sha256)throw Error('SPoRT checksum mismatch');
                        const blobURL=URL.createObjectURL(new Blob([data],{type:'image/png'}));staged.push(blobURL);
                        const decoded=new Image();decoded.src=blobURL;await decoded.decode();
                        if(decoded.naturalWidth!==4000||decoded.naturalHeight!==2538)throw Error('SPoRT image dimensions mismatch');
                        return [d,L.imageOverlay(blobURL,asset.bounds,{pane:'sportSuite',opacity:layers[d].options.opacity,interactive:false,className:'sport-suite-raster'})];
                    }));
                    const error=results.find(r=>r.status==='rejected');if(error)throw error.reason;
                    depths.forEach(d=>layers[d].clearLayers());results.forEach(r=>{const [d,image]=r.value;image.setOpacity(layers[d].options.opacity);images[d]=image;});loaded=next.active.generation;
                    const old=objectURLs;objectURLs=staged.splice(0);old.forEach(u=>URL.revokeObjectURL(u));
                }
                if(!next.active&&metadata?.active)failed=true;else{metadata=next;failed=false;}
            }catch(error){failed=true;console.warn('SPoRT refresh retained prior validated suite:',error.message);}
            finally{staged.forEach(u=>URL.revokeObjectURL(u));clearTimeout(timeout);busy=false;sync();}
        }
        function legendHTML(){const ds=selected();if(!ds.length)return '';const s=state(),a=metadata?.active;
            let html=`<div class="sport-suite-card"><strong>NASA SPoRT-LIS VSM Percentile<br>${ds.map(d=>`0–${d} cm`).join(' / ')}</strong><p><b>Antecedent soil moisture</b> · <span style="font-weight:700;${s.state==='aging'||s.state==='retained'?'color:#7a3e00;background:#fff0c2;padding:2px 4px;':''}">${esc(s.label)}</span></p><div>Soil moisture percentile · wet tail</div>`;
            colors.forEach((c,i)=>{html+=`<div><i class="sport-suite-swatch" style="background:rgba(${c.slice(0,3).join(',')},${c[3]/255})"></i>${edges[i]}–${i===4?'100':`&lt;${edges[i+1]}`}</div>`;});
            html+='<p>Below the 70th percentile and missing data are transparent. Transparency does not establish dry ground. Percentiles are not saturation percentages or flood probabilities.</p>';
            if(a){const p=a.products[ds[0]];html+=`<div>Valid: ${esc(utc(a.valid_time))}<br>Source file modified: ${esc(utc(p.http_modified_at || p.directory_modified_at))}<br>Retrieved: ${esc(utc(p.retrieved_at))}<br>Last ingest attempt: ${esc(utc(metadata.last_attempt?.at))}<br>Mode: ${esc(p.retrieval_mode)}<br>Display cutoff: ${esc(utc(new Date(Date.parse(a.valid_time)+72*3600000).toISOString()))}</div>`;}
            return html+'<p>Dashboard policy: warning at 48 h; hidden at 72 h; age measured from valid time. Nominal 3-km source; bilinear display reprojection adds no scientific resolution.</p></div>';
        }
        function setBorders(data){if(borders&&map.hasLayer(borders))map.removeLayer(borders);borders=L.layerGroup([
            L.geoJSON(data,{pane:'mapReference',interactive:false,style:{color:'#101820',weight:2.6,opacity:.85,fill:false}}),
            L.geoJSON(data,{pane:'mapReference',interactive:false,style:{color:'#fff',weight:1,opacity:.9,fill:false}})]);sync();}
        map.on('layeradd layerremove',e=>{if(depths.some(d=>layers[d]===e.layer))sync();});
        const timer=setInterval(sync,30000),poll=setInterval(refresh,300000);setTimeout(refresh,0);
        return {layers,refresh,legendHTML,setBorders,sync,getState:state,getMetadata:()=>metadata,stop:()=>{clearInterval(timer);clearInterval(poll);}};
    }
    root.SPoRTSuite={depths,displayState,validate,create};
})(typeof window==='undefined'?globalThis:window);
