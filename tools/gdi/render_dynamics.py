"""Transparent, color-keyed diagnostic contours and wind barbs; no index shading."""
import hashlib
import argparse
import io
import json
from pathlib import Path
import numpy as np
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib import patheffects
from PIL import Image
from pyproj import Transformer
from render_suite import rap_coordinates, bilinear_sample
from dynamics_contract import DEFINITIONS, verify_metadata

WIDTH, HEIGHT = 2400, 1360
STYLE = 'colored_dynamics_contours_v1'


def image_for(arrays, definition):
    fig = Figure(figsize=(WIDTH/100,HEIGHT/100),dpi=100,facecolor='none')
    canvas = FigureCanvasAgg(fig)
    ax = fig.add_axes([0,0,1,1],frameon=False)
    ax.set(xlim=(-.5,WIDTH-.5),ylim=(HEIGHT-.5,-.5))
    ax.set_axis_off()
    color = definition['color']
    halo = [patheffects.Stroke(linewidth=1.8,foreground='#15202a',alpha=.75),patheffects.Normal()]
    if definition['kind'] == 'barbs':
        u,v = arrays
        yy,xx = np.mgrid[50:HEIGHT-30:100,50:WIDTH-30:110]
        uu,vv = u[yy,xx],v[yy,xx]
        good = np.isfinite(uu)&np.isfinite(vv)&(np.hypot(uu,vv) >= 10)
        # Matplotlib barbs orient their glyphs in display coordinates, so an
        # inverted image y axis does not require reversing the northward wind.
        barbs = ax.barbs(xx[good],yy[good],uu[good],vv[good],color=color,length=5,
                        linewidth=.8,pivot='middle',sizes={'emptybarb':0.},rounding=False)
        barbs.set_path_effects(halo)
    else:
        a = arrays[0]
        finite = a[np.isfinite(a)]
        levels = [x for x in definition['levels'] if finite.size and finite.min() < x < finite.max()]
        if levels:
            colors = [definition.get('negative_color',color) if x < 0 else color for x in levels]
            cs = ax.contour(np.ma.masked_invalid(a),levels=levels,colors=colors,linewidths=.85,
                            linestyles=['dashed' if x < 0 else 'solid' for x in levels],corner_mask=False)
            cs.set_path_effects(halo)
            positions,placed = [],[]
            for segments in cs.allsegs:
                count = 0
                for segment in sorted(segments,key=len,reverse=True):
                    if len(segment) < 2 or np.linalg.norm(np.diff(segment,axis=0),axis=1).sum() < 190:continue
                    point = segment[len(segment)//2]
                    if not (40 < point[0] < WIDTH-40 and 30 < point[1] < HEIGHT-30):continue
                    if any(np.linalg.norm(point-other) < 175 for other in placed):continue
                    positions.append(tuple(point));placed.append(point.copy());count += 1
                    if count >= 5:break
            if positions:
                labels = cs.clabel(manual=positions,inline=True,inline_spacing=5,fontsize=12,fmt='%g')
                for label in labels:label.set_path_effects([patheffects.withStroke(linewidth=2.,foreground='#15202a')])
    canvas.draw()
    image = Image.fromarray(np.asarray(canvas.buffer_rgba()).copy())
    fig.clear()
    return image


def render(root, public, spec):
    root,public = Path(root),Path(public)
    digest = hashlib.sha256(STYLE.encode()+json.dumps(spec,sort_keys=True).encode())
    for lead in (0,3):digest.update((root/f'f{lead:02d}.npz').read_bytes())
    generation = spec['cycle'].replace('-','').replace(':','')[:11].replace('T','')+'-'+digest.hexdigest()[:12]+'-v1'
    dest = public/'generations'/generation
    dest.mkdir(parents=True,exist_ok=True)
    project = Transformer.from_crs(4326,3857,always_xy=True)
    w,s = project.transform(-125,24)
    e,n = project.transform(-66,50)
    x,y = np.meshgrid(w+(np.arange(WIDTH)+.5)*(e-w)/WIDTH,n-(np.arange(HEIGHT)+.5)*(n-s)/HEIGHT)
    lon,lat = Transformer.from_crs(3857,4326,always_xy=True).transform(x,y)
    assets = {}
    for lead in (0,3):
        with np.load(root/f'f{lead:02d}.npz') as native:
            xx,yy = rap_coordinates(native['longitude'],native['latitude'],lon,lat)
            for name,definition in DEFINITIONS.items():
                keys = [name+'_u',name+'_v'] if definition['kind'] == 'barbs' else [name]
                arrays = [bilinear_sample(native[key],xx,yy) for key in keys]
                image = image_for(arrays,definition)
                key = f'{name}_{lead}'
                p = dest/(key+'.png')
                encoded = io.BytesIO()
                image.save(encoded,format='PNG',optimize=True)
                raw = encoded.getvalue()
                temporary = p.with_suffix('.tmp')
                temporary.write_bytes(raw)
                temporary.replace(p)
                image.close()
                assets[key] = {'path':str(p.relative_to(public)),'sha256':hashlib.sha256(raw).hexdigest()}
    m = {**spec,'generation':generation,'assets':assets,'width':WIDTH,'height':HEIGHT,
         'bounds':[[24,-125],[50,-66]],'crs':'EPSG:3857','resampling':'masked_bilinear','overlay_type':STYLE}
    for key,asset in assets.items():
        current=hashlib.sha256((public/asset['path']).read_bytes()).hexdigest()
        if current!=asset['sha256']:raise ValueError('Late image change: '+key)
    verify_metadata(m)
    (dest/'provenance.json').write_text(json.dumps(spec,indent=2))
    temporary = public/'metadata.tmp'
    temporary.write_text(json.dumps(m,indent=2))
    temporary.replace(public/'metadata.json')
    print('Rendered RAP dynamics',generation,len(assets),'overlays',flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--input',required=True)
    parser.add_argument('--public',required=True)
    args = parser.parse_args()
    root = Path(args.input)
    render(root,args.public,json.loads((root/'suite.json').read_text()))
