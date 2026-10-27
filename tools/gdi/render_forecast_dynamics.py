"""Filtered native CAM diagnostics, sparse labeled contours and fixed barb density."""
import argparse
import datetime as dt
import hashlib
import io
import json
from pathlib import Path
import numpy as np
from pyproj import CRS,Transformer
from render_suite import bilinear_sample
from render_dynamics import WIDTH,HEIGHT,image_for
from dynamics_contract import DEFINITIONS
from forecast_dynamics_contract import verify_metadata
from guidance_contract import equal_model_mean

STYLE = 'colored_cam_dynamics_contours_v1'


def native_coordinates(native_lon,native_lat,display_lon,display_lat,projection):
    p = projection
    native = CRS.from_proj4(f"+proj=lcc +lat_1={p['lat_1']} +lat_2={p['lat_2']} +lat_0={p['lat_0']} +lon_0={p['lon_0']} +R={p['radius']} +units=m")
    project = Transformer.from_crs(4326,native,always_xy=True)
    gx,gy = project.transform(native_lon,native_lat)
    iy,ix = np.indices(native_lat.shape)
    sel = (slice(None,None,15),slice(None,None,15))
    design = np.column_stack([gx[sel].ravel(),gy[sel].ravel(),np.ones(gx[sel].size)])
    target = np.column_stack([ix[sel].ravel(),iy[sel].ravel()])
    coef = np.linalg.lstsq(design,target,rcond=None)[0]
    if np.max(abs(design@coef-target)) > .01:raise ValueError('Native grid does not match decoded Lambert projection')
    px,py = project.transform(display_lon,display_lat)
    return px*coef[0,0]+py*coef[1,0]+coef[2,0],px*coef[0,1]+py*coef[1,1]+coef[2,1]


def render(root,native_root,public):
    root,native_root,public = Path(root),Path(native_root),Path(public)
    spec = json.loads((root/'suite.json').read_text())
    verify_metadata(spec,assets=False)
    digest = hashlib.sha256(STYLE.encode()+json.dumps(spec,sort_keys=True).encode()).hexdigest()[:12]
    generation = dt.datetime.fromisoformat(spec['cycle']).strftime('%Y%m%d%H')+'-'+digest+'-v1'
    dest = public/'generations'/generation
    dest.mkdir(parents=True,exist_ok=True)
    project = Transformer.from_crs(4326,3857,always_xy=True)
    w,s = project.transform(-125,24);e,n = project.transform(-66,50)
    x,y = np.meshgrid(w+(np.arange(WIDTH)+.5)*(e-w)/WIDTH,n-(np.arange(HEIGHT)+.5)*(n-s)/HEIGHT)
    lon,lat = Transformer.from_crs(3857,4326,always_xy=True).transform(x,y)
    coords,assets,reference = {},{},None
    for h in range(7):
        arrays = {}
        for model in ('hrrr','rrfs'):
            s = spec['frame_contexts'][model+str(h)]['sources'][0]
            cycle = dt.datetime.fromisoformat(s['cycle']).strftime('%Y%m%d%H')
            p = native_root/model/cycle/f"F{s['lead']:03d}.npz"
            meta = json.loads(p.with_suffix('.json').read_text())
            if hashlib.sha256(p.read_bytes()).hexdigest() != meta['sha256']:raise ValueError('Native diagnostics changed before rendering')
            with np.load(p) as a:
                if model not in coords:
                    if reference is None:reference = (a['longitude'].copy(),a['latitude'].copy())
                    elif (a['longitude'].shape != reference[0].shape
                          or not np.allclose(a['longitude'],reference[0],atol=1e-6,rtol=0)
                          or not np.allclose(a['latitude'],reference[1],atol=1e-6,rtol=0)):
                        raise ValueError('Blended companion grids differ; explicit regridding is required')
                    coords[model] = native_coordinates(a['longitude'],a['latitude'],lon,lat,meta['projection'])
                arrays[model] = {k:a[k].copy() for name,d in DEFINITIONS.items()
                                 for k in ([name+'_u',name+'_v'] if d['kind']=='barbs' else [name])}
        arrays['blend'] = {k:equal_model_mean(arrays['hrrr'][k],arrays['rrfs'][k]) for k in arrays['hrrr']}
        for model in ('hrrr','rrfs','blend'):
            xx,yy = coords['hrrr' if model=='blend' else model]
            for name,d in DEFINITIONS.items():
                keys = [name+'_u',name+'_v'] if d['kind']=='barbs' else [name]
                display = [bilinear_sample(arrays[model][k],xx,yy) for k in keys]
                im = image_for(display,d)
                encoded = io.BytesIO();im.save(encoded,format='PNG',optimize=True);im.close()
                raw = encoded.getvalue();key = name+'_'+model+str(h)
                p = dest/(key+'.png');temporary = p.with_suffix('.tmp')
                temporary.write_bytes(raw);temporary.replace(p)
                assets[key] = {'path':str(p.relative_to(public)),'sha256':hashlib.sha256(raw).hexdigest()}
        print('Rendered CAM dynamics hour',h,flush=True)
    if dt.datetime.now(dt.timezone.utc) >= dt.datetime.fromisoformat(spec['expires_at']):raise ValueError('Forecast expired during processing')
    m = {**spec,'generation':generation,'assets':assets,'width':WIDTH,'height':HEIGHT,
         'bounds':[[24,-125],[50,-66]],'crs':'EPSG:3857','resampling':'masked_bilinear','overlay_type':STYLE}
    for key,a in assets.items():
        if hashlib.sha256((public/a['path']).read_bytes()).hexdigest() != a['sha256']:raise ValueError('Late image change: '+key)
    verify_metadata(m)
    (dest/'provenance.json').write_text(json.dumps(spec,indent=2))
    tmp = public/'metadata.tmp';tmp.write_text(json.dumps(m,indent=2));tmp.replace(public/'metadata.json')
    print('Rendered CAM dynamics',generation,len(assets),'overlays',flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--input',required=True);p.add_argument('--native',required=True);p.add_argument('--public',required=True)
    a = p.parse_args();render(a.input,a.native,a.public)
