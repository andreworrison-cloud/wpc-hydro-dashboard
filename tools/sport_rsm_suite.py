"""Atomic two-depth SPoRT RSM ingest. Explicit opt-in; legacy production is unchanged."""
import hashlib
import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
import re
import numpy as np
import rasterio
from PIL import Image
from fetch_sport import build_session, read_and_reproject_geotiff
DEPTHS=('10','200')
BASE_URL='https://nssrgeo.ndc.nasa.gov/SPoRT/modeling/lis/conus3km/geotiff'
SOURCE_KEYS={'10':'0-10cm','200':'0-2m'}
COLORS=np.array([[150,110,70,224],[210,190,120,224],[170,215,130,224],[90,190,120,224],[35,185,190,224],[45,125,230,224],[20,50,170,245],[125,0,175,255]],dtype=np.uint8)
EDGES=np.array([0,40,50,60,70,80,90,95,100])
FORMULA='100 * (theta - theta_wilting) / (theta_saturation - theta_wilting)'

def filename(date,d):return f'{date}_0000_sport_lis_rsm{SOURCE_KEYS[d]}_conus3km_float_wgs84.tif'
def source_url(d,name):return f'{BASE_URL}/rsm_{SOURCE_KEYS[d]}/{name}'
def inventory(html,d):
    names=set(re.findall(r'\d{8}_0000_sport_lis_rsm'+re.escape(SOURCE_KEYS[d])+r'_conus3km_float_wgs84\.tif',html))
    return {name[:8]:{'filename':name} for name in names}
def create_rgba_image(data):
    valid=np.isfinite(data)&(data>=0)&(data<=100)
    out=np.zeros(data.shape+(4,),dtype=np.uint8)
    out[valid]=COLORS[np.searchsorted(EDGES[1:-1],data[valid],side='right')]
    return out


REVISION='sport-suite-rsm-v1'
DISPLAY_MAX_DIMENSION=4000
POLICY={'warn_age_hours':48,'expire_age_hours':72,'status':'approved_dashboard_policy_v1'}

def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def iso(t):return t.isoformat().replace('+00:00','Z')
def parse(t):return datetime.fromisoformat(t.replace('Z','+00:00'))

def freshness(active,now):
    if not active:return {'usable':False,'status':'unavailable'}
    age=(now-parse(active['valid_time'])).total_seconds()/3600
    return {'age_hours':round(age,2),'usable':0<=age<POLICY['expire_age_hours'],'status':'expired' if age>=POLICY['expire_age_hours'] else 'future' if age<0 else 'aging' if age>=POLICY['warn_age_hours'] else 'within_review_limits'}

def atomic_json(path,data):
    tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(data,indent=2,allow_nan=False)+'\n');os.replace(tmp,path)

def verify(root,active,require_sources=True):
    if not active or set(active['products'])!=set(DEPTHS):raise ValueError('Missing depth suite')
    generation=active['generation']
    if not re.fullmatch(r'\d{8}-[a-f0-9]{20}-sport-suite-rsm-v1',generation):raise ValueError('Invalid generation')
    for depth,p in active['products'].items():
        if p['depth_cm']!=[0,int(depth)] or p['valid_time']!=active['valid_time']:raise ValueError('Depth/time mismatch')
        for role in ('source','image'):
            asset=p[role];rel=Path(asset['path'])
            if rel.is_absolute() or '..' in rel.parts or rel.parts[:2]!=('generations',generation):raise ValueError('Unsafe asset path')
            path=root/rel
            if not re.fullmatch(r'[a-f0-9]{64}',asset['sha256']):raise ValueError('Invalid asset hash')
            if role=='source' and not require_sources:continue
            if not path.is_file() or digest(path)!=asset['sha256']:raise ValueError('Missing or corrupt '+role)
    return True

def validate_source(path):
    with rasterio.open(path) as ds:
        if ds.count!=1 or ds.crs!=rasterio.crs.CRS.from_epsg(4326) or ds.dtypes[0] not in ('float32','float64'):raise ValueError('Unexpected source type/CRS')
        if (ds.height,ds.width)!=(929,1929) or not np.allclose(tuple(ds.bounds),[-124.94,25.06,-67.07,52.93],atol=.00001):raise ValueError('Unexpected source grid')
        a=ds.read(1);valid=np.isfinite(a)&(a>=0)&(a<=100.0001)&(ds.read_masks(1)>0)
        unexpected=np.isfinite(a)&~valid&(a!=9999)
        if ds.nodata is not None:unexpected &= a!=ds.nodata
        if unexpected.any():raise ValueError('Unexpected RSM outside 0–100 (roundoff tolerance 0.0001)')
        if abs(int(valid.sum())-1290511)>12905:raise ValueError('Coverage changed by more than 1% from H6 baseline')
        return {'shape':[ds.height,ds.width],'transform':list(ds.transform),'crs':str(ds.crs),'valid_cells':int(valid.sum()),'min':float(a[valid].min()),'max':float(a[valid].max()),'roundoff_above_100_cells':int(np.count_nonzero(valid&(a>100)))},valid

def ingest(root,source_dir=None,date=None,now=None,session=None):
    root=Path(root);root.mkdir(parents=True,exist_ok=True);(root/'generations').mkdir(exist_ok=True)
    now=now or datetime.now(timezone.utc);previous=None;failure=None
    pointer=root/'metadata.json'
    if pointer.exists():
        try:
            previous=json.loads(pointer.read_text()).get('active');verify(root,previous,require_sources=False)
        except Exception as exc:previous=None;failure='Previous product invalid: '+str(exc)
    active=previous;state='unavailable';ok=False
    try:
        session=session or build_session()
        if source_dir:
            if not date or not re.fullmatch(r'\d{8}',date):raise ValueError('Offline review requires YYYYMMDD date')
            entries={d:{'filename':filename(date,d)} for d in DEPTHS}
        else:
            inventories={}
            for d in DEPTHS:
                response=session.get(f'{BASE_URL}/rsm_{SOURCE_KEYS[d]}/',timeout=(20,120));response.raise_for_status()
                inventories[d]=inventory(response.text,d)
                if not inventories[d]:raise ValueError('No dated RSM float products for '+d)
            date=max(max(inv) for inv in inventories.values())
            if not all(date in inv for inv in inventories.values()):raise ValueError('Newest RSM pair incomplete; retaining previous pair')
            entries={d:inventories[d][date] for d in DEPTHS}
        valid_time=datetime.strptime(date,'%Y%m%d').replace(tzinfo=timezone.utc)
        if not freshness({'valid_time':iso(valid_time)},now)['usable']:raise ValueError('Candidate outside review freshness limits')
        if previous and valid_time<parse(previous['valid_time']):raise ValueError('Source valid time regressed')
        with tempfile.TemporaryDirectory(prefix='.stage-',dir=root) as tmp:
            stage=Path(tmp);products={};masks=[];grid=None
            for d in DEPTHS:
                entry=entries[d];path=stage/entry['filename'];url=source_url(d,entry['filename']);modified=None
                print('SPoRT RSM: validating 0–'+d+' cm',flush=True)
                if source_dir:shutil.copyfile(Path(source_dir)/entry['filename'],path)
                else:
                    with session.get(url,stream=True,timeout=(20,240)) as response:
                        response.raise_for_status();modified=response.headers.get('Last-Modified')
                        with path.open('wb') as stream:
                            for chunk in response.iter_content(1024*1024):stream.write(chunk)
                stats,mask=validate_source(path);masks.append(mask)
                this_grid=(stats['shape'],stats['transform'],stats['crs'])
                if grid is not None and grid!=this_grid:raise ValueError('Depth grid mismatch')
                grid=this_grid
                if np.count_nonzero(mask!=masks[0])>12905:raise ValueError('Depth coverage masks differ excessively')
                products[d]={'depth_cm':[0,int(d)],'valid_time':iso(valid_time),'source_url':url,'http_modified_at':modified,'directory_modified_at':entry.get('directory_modified_at'),'retrieved_at':iso(datetime.now(timezone.utc)) if not source_dir else None,'retrieval_mode':'offline_review' if source_dir else 'live','coverage':stats,'source':{'path':path.name,'sha256':digest(path),'storage':'workflow_artifact','retention_days':14}}
            combined=hashlib.sha256(''.join(products[d]['source']['sha256'] for d in DEPTHS).encode()).hexdigest()[:20]
            generation=f'{date}-{combined}-{REVISION}'
            if previous and generation==previous['generation']:
                state='unchanged'
            else:
                for d in DEPTHS:
                    p=products[d];data,bounds=read_and_reproject_geotiff(stage/p['source']['path'], max_dimension=DISPLAY_MAX_DIMENSION, upscale=True, upper_tolerance=0.0001)
                    image=stage/f'sport_rsm_0_{d}cm.png';Image.fromarray(create_rgba_image(data)).save(image,optimize=True)
                    p['image']={'path':image.name,'sha256':digest(image),'width':data.shape[1],'height':data.shape[0],'crs':'EPSG:3857','bounds':bounds,'resampling':'bilinear','mask_resampling':'nearest','palette':'sport-rsm-v1'}
                    for role in ('source','image'):p[role]['path']=f'generations/{generation}/'+p[role]['path']
                active={'generation':generation,'valid_time':iso(valid_time),'accepted_at':iso(now),'products':products,'render_revision':REVISION,'quantity':'relative_soil_moisture','units':'percent between wilting and saturation','formula':FORMULA}
                target=root/'generations'/generation
                if target.exists():verify(root,active)
                else:os.replace(stage,target)
                verify(root,active);state='updated'
            ok=True;failure=None
    except Exception as exc:
        active=previous;failure=str(exc);state='retained' if active else 'unavailable'
        print('SPoRT RSM: '+failure,flush=True)
    status=freshness(active,now)
    if active and not status['usable']:state='expired'
    result={'schema_version':1,'state':state,'usable':status['usable'],'policy':POLICY,'freshness':status,'last_attempt':{'at':iso(now),'ok':ok,'error':failure},'active':active}
    atomic_json(pointer,result)
    print('SPoRT RSM: '+state,flush=True)
    return 0 if ok else 1

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument('--suite-dir',type=Path,required=True)
    parser.add_argument('--source-dir',type=Path)
    parser.add_argument('--date')
    args=parser.parse_args()
    raise SystemExit(ingest(args.suite_dir,args.source_dir,args.date))
