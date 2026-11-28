"""Self-contained Leaflet comparison from original SPoRT floats, never PNG-derived science."""
import argparse
import base64
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fetch_sport import DEPTHS,read_and_reproject_geotiff,create_rgba_image
from rasterio.warp import Resampling
from PIL import Image,ImageDraw,ImageFont
import io
import math

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--source-dir',type=Path,required=True);ap.add_argument('--date',required=True);ap.add_argument('--vendor-dir',type=Path,required=True);ap.add_argument('--output-dir',type=Path,required=True);a=ap.parse_args();a.output_dir.mkdir(parents=True,exist_ok=True)
    variants=[('current','Current: 1,808 px · browser smoothing',1808,Resampling.bilinear,False),('crisp','4,000 px · bilinear field · crisp classes',4000,Resampling.bilinear,True),('nearest','4,000 px · nearest source · crisp classes',4000,Resampling.nearest,True)]
    assets={};images={};bounds=None
    for d in DEPTHS:
        assets[d]={}
        for key,label,size,method,upscale in variants:
            values,bounds=read_and_reproject_geotiff(a.source_dir/f'{a.date}_0000_sport_lis_vsm0-{d}cm_percentile_conus3km_float_wgs84.tif',max_dimension=size,resampling=method,upscale=upscale)
            im=Image.fromarray(create_rgba_image(values));images[d,key]=im
            buffer=io.BytesIO();im.save(buffer,format='PNG',optimize=True)
            assets[d][key]='data:image/png;base64,'+base64.b64encode(buffer.getvalue()).decode()
    states=json.loads((a.vendor_dir/'us-states.json').read_text())
    def merc(lat):return math.log(math.tan(math.pi/4+math.radians(lat)/2))
    def point(lon,lat,w,h):
        return ((lon-bounds[0][1])/(bounds[1][1]-bounds[0][1])*w,(merc(bounds[1][0])-merc(lat))/(merc(bounds[1][0])-merc(bounds[0][0]))*h)
    def panel(d,key,region,size):
        im=images[d,key];x0,y1=point(region[0],region[1],*im.size);x1,y0=point(region[2],region[3],*im.size)
        im=im.crop((round(x0),round(y0),round(x1),round(y1))).resize(size,Image.Resampling.BILINEAR if key=='current' else Image.Resampling.NEAREST)
        bg=Image.new('RGBA',size,(27,35,46,255));bg.alpha_composite(im);draw=ImageDraw.Draw(bg)
        for feature in states['features']:
            geom=feature['geometry'];polys=geom['coordinates'] if geom['type']=='MultiPolygon' else [geom['coordinates']]
            for poly in polys:
                for ring in poly:
                    pts=[]
                    for lon,lat,*rest in ring:
                        x,y=point(lon,lat,*images[d,key].size);pts.append(((x-x0)/(x1-x0)*size[0],(y-y0)/(y1-y0)*size[1]))
                    draw.line(pts,fill=(210,221,228,255),width=1)
        return bg.convert('RGB')
    font=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',18)
    comparison=Image.new('RGB',(1500,520),'#111923');draw=ImageDraw.Draw(comparison)
    for i,(key,label,*_) in enumerate(variants):
        comparison.paste(panel('100',key,[-98,32,-84,41],(490,430)),(i*500,55));draw.text((i*500+10,15),label,fill='white',font=font)
    draw.text((12,492),'Same 0–100 cm source and wet-tail palette | 2026-10-17 00Z | Display detail adds no source resolution',fill='white',font=font)
    comparison.save(a.output_dir/'sport_sharpness_comparison.png')
    montage=Image.new('RGB',(1400,1040),'#111923');draw=ImageDraw.Draw(montage)
    for i,d in enumerate(DEPTHS):
        x=(i%2)*700;y=(i//2)*500;montage.paste(panel(d,'crisp',[-125,25,-67,50],(690,430)),(x,y+50));draw.text((x+15,y+15),'SPoRT-LIS percentile · 0–'+d+' cm',fill='white',font=font)
    draw.text((15,1000),'2026-10-17 00Z · Identical wet-tail bins: 70 / 80 / 90 / 95 / 98 · Below 70 and NoData transparent',fill='white',font=font);montage.save(a.output_dir/'sport_four_depths.png')
    css=(a.vendor_dir/'leaflet-1.9.4.css').read_text();js=(a.vendor_dir/'leaflet-1.9.4.js').read_text()
    html='''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>H6 SPoRT-LIS depth and clarity review</title><style>LEAFLET_CSS
body{margin:0;background:#111923;color:#e9f1f8;font:15px system-ui}header{padding:16px}h1{font-size:22px;margin:0 0 10px}select,button{padding:8px;background:#253447;color:white;border:1px solid #607080;border-radius:4px}#maps{display:grid;grid-template-columns:repeat(3,1fr);gap:6px}.map{height:66vh;min-height:360px;background:#1b232e}.caption{padding:10px;font-size:13px}.crisp{image-rendering:pixelated!important}footer{padding:12px;line-height:1.6}.swatch{display:inline-block;width:24px;height:14px;margin-left:12px} @media(max-width:800px){#maps{grid-template-columns:1fr}.map{height:55vh}}</style></head><body><header><h1>SPoRT-LIS · four depths, one consistent palette</h1><label>Depth <select id="depth"><option value="10">0–10 cm</option><option value="40">0–40 cm</option><option value="100" selected>0–100 cm</option><option value="200">0–200 cm</option></select></label> <label>Background <select id="background"><option value="dark">Dark canvas</option><option value="light">Light canvas</option><option value="esri">Esri Light Gray (internet)</option></select></label> <button id="conus">CONUS</button> <button id="regional">Regional detail</button><p>Frozen review · valid DATE 00Z · nominal 3-km model source · pan and zoom synchronize all panels.</p></header><div id="maps"><section><div class="caption">Current: 1,808 px, bilinear field, browser smoothing</div><div id="current" class="map"></div></section><section><div class="caption">Candidate: 4,000 px, bilinear field, crisp class edges</div><div id="crisp" class="map"></div></section><section><div class="caption">Comparison: 4,000 px, nearest source, crisp edges</div><div id="nearest" class="map"></div></section></div><footer id="legend"></footer><script>LEAFLET_JS</script><script>
const assets=ASSETS, bounds=BOUNDS, states=STATES;
const keys=['current','crisp','nearest'], maps=[],layers=[],tiles=[];let syncing=false;
keys.forEach((key,i)=>{const m=L.map(key,{zoomControl:true}).setView([38,-96],4);maps.push(m);layers.push(L.imageOverlay(assets['100'][key],bounds,{className:key==='current'?'':'crisp',opacity:1}).addTo(m));L.geoJSON(states,{style:{color:'#8697a5',weight:1,fillOpacity:0}}).addTo(m);tiles.push(L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}',{attribution:'Esri',maxZoom:16}));m.on('move',()=>{if(syncing)return;syncing=true;maps.forEach(other=>{if(other!==m)other.setView(m.getCenter(),m.getZoom(),{animate:false})});syncing=false})});
document.getElementById('depth').onchange=e=>layers.forEach((layer,i)=>layer.setUrl(assets[e.target.value][keys[i]]));
document.getElementById('background').onchange=e=>maps.forEach((m,i)=>{if(m.hasLayer(tiles[i]))m.removeLayer(tiles[i]);m.getContainer().style.background=e.target.value==='light'?'#e4e8eb':'#1b232e';if(e.target.value==='esri')tiles[i].addTo(m)});
document.getElementById('conus').onclick=()=>maps[0].setView([38,-96],4);document.getElementById('regional').onclick=()=>maps[0].setView([36.5,-91],7);
const colors=['rgba(170,220,255,.353)','rgba(80,170,255,.588)','rgba(20,110,235,.784)','rgba(0,45,180,.922)','rgb(120,0,180)'];document.getElementById('legend').innerHTML='<b>Soil-moisture percentile</b>'+['70–80','80–90','90–95','95–98','98–100'].map((t,i)=>'<span class="swatch" style="background:'+colors[i]+'"></span> '+t).join('')+'<br>Below 70 is transparent. NoData is also transparent; transparency does not identify missing data by itself. Percentile is not percent saturation.<br>Review only: all panels use the same source and palette. Larger rendering improves display sampling; it does not create finer hydrologic information.';
</script></body></html>'''
    for key,value in {'LEAFLET_CSS':css,'LEAFLET_JS':js,'ASSETS':json.dumps(assets),'BOUNDS':json.dumps(bounds),'STATES':json.dumps(states),'DATE':a.date}.items():html=html.replace(key,value)
    (a.output_dir/'sport_depth_review.html').write_text(html)
    print('Wrote self-contained review and two comparison figures',flush=True)
if __name__=='__main__':main()
