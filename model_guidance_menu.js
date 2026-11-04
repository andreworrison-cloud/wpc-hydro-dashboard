/* One guidance menu; existing layers, legends and data adapters remain authoritative. */
(function(root) {
    'use strict';
    const MODELS = {hrrr:'HRRR', rrfs:'RRFS', blend:'HRRR/RRFS Blend'};
    const FAMILIES = {diagnostics:'Flash Flood Diagnostics', tle:'TLE Guidance', gdi:'GDI Thermodynamic Guidance'};
    const GROUPS = {core:'FFG Exceedance', heavy:'Heavy Rain & Persistence', timing:'Timing & Trends'};
    const STORAGE_KEY = 'wpcModelGuidanceMenuV1';
    const flatten = section => [...(section.layers || []), ...(section.groups || []).flatMap(flatten)];

    function consolidate(sections) {
        const ids = new Set(['gdi','hrrr-diagnostics','hrrr-tle','rrfs-diagnostics','rrfs-tle','hrrr-rrfs-diagnostics','hrrr-rrfs-tle']);
        const source = sections.filter(s => ids.has(s.id));
        if (source.length !== 7) throw Error('Expected all seven model guidance sections');
        const entries = [];
        source.forEach(section => flatten(section).forEach(entry => {
            let model, family, product, group;
            if (section.id === 'gdi') {
                const match = /^gdi-(forecast|day1)-(hrrr|rrfs|blend)$/.exec(entry.id);
                if (!match) throw Error('Unknown GDI guidance entry');
                [,product,model] = match; family = 'gdi';
                entry.menuLabel = product === 'forecast' ? 'Hourly GDI Forecast' : 'Day 1 ERO · Maximum GDI';
            } else {
                model = section.id.startsWith('hrrr-rrfs-') ? 'blend' : section.id.startsWith('rrfs-') ? 'rrfs' : 'hrrr';
                family = section.id.endsWith('-diagnostics') ? 'diagnostics' : 'tle';
                product = entry.id.replace(/^(?:hrrr-rrfs|hrrr|rrfs)-/, '');
                if (family === 'tle') {
                    const parent = section.groups.find(g => flatten(g).includes(entry));
                    group = /Core/.test(parent.title) ? 'core' : /Heavy/.test(parent.title) ? 'heavy' : 'timing';
                }
                entry.menuLabel = entry.label.replace(/^(?:HRRR\/RRFS|RRFS) · /, '').replace(/3 HRRR Cycles/, '3 Cycles');
            }
            entry.guidance = {model, family, product, group};
            entries.push(entry);
        }));
        const key = g => [g.model,g.family,g.product].join('/');
        const byKey = new Map(entries.map(e => [key(e.guidance),e]));
        if (entries.length !== 66 || byKey.size !== 66) throw Error('Incomplete or duplicate model guidance registry');
        const section = {id:'model-guidance', title:'HRRR / RRFS Forecast Guidance', modelGuidance:true, layers:[], groups:source};
        const position = sections.findIndex(s => ids.has(s.id));
        sections.splice(0, sections.length, ...sections.filter(s => !ids.has(s.id)));
        sections.splice(position,0,section);
        return {section, entries, find:(model,family,product)=>byKey.get(key({model,family,product}))};
    }

    function create({registry, isActive, setActive, select, getStatus=()=>({}), formatTime=x=>x,
                     storage, clearSearch=()=>{}}) {
        const entries = registry.entries;
        const byId = new Map(entries.map(e => [e.id,e]));
        let saved;
        try { saved = JSON.parse(storage?.getItem(STORAGE_KEY) || 'null'); } catch (_) {}
        const state = {model:'hrrr', family:'diagnostics', open:false,
            products:{diagnostics:'diag-max-ratio',tle:'tle-ffg-consensus',gdi:'forecast'},
            groups:{core:true,heavy:false,timing:false}, active:[]};
        if (saved?.version === 1) {
            if (Object.hasOwn(MODELS,saved.model)) state.model = saved.model;
            if (Object.hasOwn(FAMILIES,saved.family)) state.family = saved.family;
            state.open = saved.open === true;
            Object.keys(FAMILIES).forEach(f => {
                if (registry.find(state.model,f,saved.products?.[f])) state.products[f] = saved.products[f];
            });
            Object.keys(GROUPS).forEach(g => {if (typeof saved.groups?.[g] === 'boolean') state.groups[g] = saved.groups[g];});
            if (Array.isArray(saved.active)) state.active = [...new Set(saved.active.filter(id=>byId.has(id)))];
        }
        let node=null, statusNode=null, heading=null, searchNote=null, panels=[], controls=[], query='', busy=false, restored=false, lastSaved='';
        const current = () => registry.find(state.model,state.family,state.products[state.family]);
        function save() {
            const text = JSON.stringify({version:1,...state});
            if (text === lastSaved) return;
            try {storage?.setItem(STORAGE_KEY,text);lastSaved=text;} catch (_) {}
        }
        function pick(entry) {
            if (busy || !entry?.guidance) return;
            const g = entry.guidance;
            state.model=g.model;state.family=g.family;state.products[g.family]=g.product;state.open=true;
            if(g.group)state.groups[g.group]=true;
            save(); applySearch(query);
        }
        function chooseModel(model) {
            if (!Object.hasOwn(MODELS,model) || model === state.model) return;
            const active = entries.filter(isActive);
            // Preserve every active product and its opacity, even when a user
            // deliberately overlays several diagnostics. Context layers are external.
            const targets = new Map();
            active.forEach(e=>{
                const g=e.guidance, next=registry.find(model,g.family,g.product);
                if (!next) throw Error('Missing matching model product');
                const opacity=e.layer.options?.opacity;
                if (!targets.has(next.id)) targets.set(next.id,{entry:next,opacity});
            });
            busy=true;
            try {
                active.forEach(e=>setActive(e,false));
                state.model=model;
                targets.forEach(({entry,opacity})=>{
                    if (Number.isFinite(opacity) && typeof entry.layer.setOpacity==='function') entry.layer.setOpacity(opacity);
                    setActive(entry,true);
                });
                select(current());
            } finally {busy=false;}
            clearSearch();query='';sync();applySearch('');
        }
        function chooseFamily(family) {
            if (!Object.hasOwn(FAMILIES,family)) return;
            state.family=family;state.open=true;
            busy=true;try {select(current());} finally {busy=false;}
            clearSearch();query='';save();applySearch('');
        }
        function refreshStatus() {
            if (!statusNode) return;
            const active=entries.filter(isActive), preferred=current();
            const selected=active.includes(preferred) ? preferred : active[active.length-1];
            statusNode.replaceChildren();
            const title=document.createElement('strong');
            if (!selected) {
                title.textContent='Select a product to display';statusNode.append(title);return;
            }
            title.textContent=MODELS[selected.guidance.model]+' · '+selected.menuLabel;
            statusNode.append(title);
            const info=getStatus(selected) || {};
            const line=text=>{const item=document.createElement('small');item.textContent=text;statusNode.append(item);};
            if (info.cycle) line('Cycle: '+formatTime(info.cycle));
            if (info.start) line('Valid: '+formatTime(info.start)+(info.end&&info.end!==info.start?' — '+formatTime(info.end):''));
            if (info.message) line(info.message);
            if (active.length>1) line(active.length+' guidance layers active');
        }
        function sync() {
            if (busy || !restored) return;
            state.active=entries.filter(isActive).map(e=>e.id);save();refreshStatus();
        }
        function applySearch(value='') {
            query=value.trim().toLowerCase();
            if (!node) return;
            let matches=0;
            controls.forEach(input=>{input.checked=state[input.name==='guidance-model'?'model':'family']===input.value;});
            heading.textContent=FAMILIES[state.family];
            heading.hidden=Boolean(query);
            searchNote.hidden=!query;
            panels.forEach(panel=>{
                const filtered=panel.model===state.model&&panel.family===state.family;
                let visible=0;
                panel.rows.forEach(({entry,row})=>{
                    const show=query ? entry.searchText.includes(query) : filtered;
                    row.hidden=!show;if(show)visible++;
                    row.classList.toggle('guidance-last-used',entry===current());
                });
                panel.node.hidden=visible===0;
                panel.context.hidden=!query;
                panel.groups.forEach(({name,node:group,rows})=>{
                    const hasRows=rows.some(row=>!row.hidden);
                    group.hidden=!hasRows;
                    group.open=query ? hasRows : state.groups[name];
                });
                matches+=visible;
            });
            node.hidden=query ? matches===0 : false;
            node.open=query ? matches>0 : state.open;
            refreshStatus();
        }
        function mount(section, body, renderRow) {
            node=section;panels=[];controls=[];
            function selector(name,title,values,change) {
                const field=document.createElement('fieldset');field.className='guidance-selector';
                const legend=document.createElement('legend');legend.textContent=title;field.append(legend);
                const choices=document.createElement('div');choices.className='guidance-selector-options';
                Object.entries(values).forEach(([value,text])=>{
                    const label=document.createElement('label'),input=document.createElement('input'),caption=document.createElement('span');
                    input.type='radio';input.name=name;input.value=value;
                    input.addEventListener('change',()=>{if(input.checked)change(value);});
                    caption.textContent=text;label.append(input,caption);choices.append(label);controls.push(input);
                });field.append(choices);body.append(field);
            }
            selector('guidance-model','Model',MODELS,chooseModel);
            selector('guidance-family','Product family',{diagnostics:'Diagnostics',tle:'TLE',gdi:'GDI'},chooseFamily);
            statusNode=document.createElement('div');statusNode.className='guidance-active-status';body.append(statusNode);
            heading=document.createElement('h3');heading.className='guidance-family-title';body.append(heading);
            searchNote=document.createElement('p');searchNote.className='guidance-search-note';searchNote.textContent='Search results across all models and product families';body.append(searchNote);
            Object.keys(MODELS).forEach(model=>Object.keys(FAMILIES).forEach(family=>{
                const panelNode=document.createElement('div');panelNode.className='model-guidance-panel';
                panelNode.dataset.guidanceModel=model;panelNode.dataset.guidanceFamily=family;
                const context=document.createElement('h4');context.className='guidance-search-context';context.textContent=MODELS[model]+' · '+FAMILIES[family];panelNode.append(context);
                const panel={node:panelNode,model,family,context,rows:[],groups:[]};
                const productEntries=entries.filter(e=>e.guidance.model===model&&e.guidance.family===family);
                function addRows(parent,list,groupRows) {
                    list.forEach(entry=>{const row=renderRow(entry);parent.append(row);panel.rows.push({entry,row});groupRows?.push(row);});
                }
                if (family==='tle') Object.entries(GROUPS).forEach(([name,title])=>{
                    const group=document.createElement('details');group.className='dashboard-layer-group';group.dataset.guidanceGroup=name;
                    const summary=document.createElement('summary'),text=document.createElement('span'),count=document.createElement('span');
                    text.textContent=title;count.className='section-count';
                    const list=productEntries.filter(e=>e.guidance.group===name);count.textContent=String(list.length);summary.append(text,count);
                    const content=document.createElement('div');content.className='dashboard-layer-group-body';const rows=[];addRows(content,list,rows);
                    group.append(summary,content);panelNode.append(group);panel.groups.push({name,node:group,rows});
                    group.addEventListener('toggle',()=>{if(!query&&!panelNode.hidden&&group.open!==state.groups[name]){state.groups[name]=group.open;save();}});
                });else addRows(panelNode,productEntries);
                body.append(panelNode);panels.push(panel);
            }));
            node.addEventListener('toggle',e=>{if(e.target===node&&!query&&state.open!==node.open){state.open=node.open;save();}});
            applySearch(query);
            if (!restored) {
                restored=true;const active=state.active.slice();busy=true;
                try {active.forEach(id=>setActive(byId.get(id),true));if(saved?.version===1)select(current());} finally {busy=false;}
                sync();
            }
        }
        return {mount,pick,chooseModel,chooseFamily,applySearch,sync,refreshStatus,
                getState:()=>JSON.parse(JSON.stringify(state)),current};
    }
    root.WPCModelGuidance={consolidate,create,MODELS,FAMILIES,STORAGE_KEY};
    if(typeof module!=='undefined')module.exports=root.WPCModelGuidance;
})(typeof window==='undefined'?globalThis:window);
