/* Two-depth NASA SPoRT RSM adapter. Values are relative to wilting and saturation. */
(function (root) {
    const depths = [10, 200];
    const colors = [[150,110,70,224],[210,190,120,224],[170,215,130,224],[90,190,120,224],[35,185,190,224],[45,125,230,224],[20,50,170,245],[125,0,175,255]];
    const edges = [0,40,50,60,70,80,90,95,100];
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
        if(a.quantity!=='relative_soil_moisture'||a.units!=='percent between wilting and saturation'||a.formula!=='100 * (theta - theta_wilting) / (theta_saturation - theta_wilting)')throw Error('SPoRT RSM definition mismatch');
        if (!Number.isFinite(Date.parse(a.valid_time)) || !/^\d{8}-[a-f0-9]{20}-sport-suite-rsm-v1$/.test(a.generation) || a.render_revision!=='sport-suite-rsm-v1') throw Error('Invalid SPoRT generation');
        if (Object.keys(a.products || {}).sort().join(',') !== ['10','200'].join(',')) throw Error('Incomplete SPoRT suite');
        let bounds;
        depths.forEach(d=>{
            const p=a.products[d],i=p.image;
            if(JSON.stringify(p.depth_cm)!==JSON.stringify([0,d]) || p.valid_time!==a.valid_time)throw Error('SPoRT depth/time mismatch');
            if(i?.crs!=='EPSG:3857'||i.width!==4000||i.height!==2538||i.resampling!=='bilinear'||i.mask_resampling!=='nearest'||i.palette!=='sport-rsm-v1')throw Error('SPoRT display contract mismatch');
            if(i.path!==`generations/${a.generation}/sport_rsm_0_${d}cm.png`||!/^[a-f0-9]{64}$/.test(i.sha256))throw Error('Unsafe SPoRT image');
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
        map.createPane('sportRSM');map.getPane('sportRSM').style.zIndex=341;
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
                        return [d,L.imageOverlay(blobURL,asset.bounds,{pane:'sportRSM',opacity:layers[d].options.opacity,interactive:false,className:'sport-rsm-raster'})];
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
            let html=`<div class="sport-suite-card"><strong>NASA SPoRT-LIS Relative Soil Moisture<br>${ds.map(d=>`0–${d} cm`).join(' / ')}</strong><p><b>Antecedent soil moisture</b> · <span style="font-weight:700;${s.state==='aging'||s.state==='retained'?'color:#7a3e00;background:#fff0c2;padding:2px 4px;':''}">${esc(s.label)}</span></p><div>RSM (%) · wilting point to saturation</div>`;
            colors.forEach((c,i)=>{html+=`<div><i class="sport-suite-swatch" style="background:rgba(${c.slice(0,3).join(',')},${c[3]/255})"></i>${edges[i]}–${i===7?'100':`&lt;${edges[i+1]}`}</div>`;});
            html+='<p>0% = wilting point; 100% = saturation. Missing data are transparent. Values are not percentiles or flood probabilities. NLDAS percent of saturation uses a different normalization.</p>';
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
    root.SPoRTRSM={depths,displayState,validate,create};
})(typeof window==='undefined'?globalThis:window);
