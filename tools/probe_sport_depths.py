"""Read-only H6 source audit. Retains original float TIFFs outside production assets."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import urllib.request
import numpy as np
import rasterio

BASE='https://nssrgeo.ndc.nasa.gov/SPoRT/modeling/lis/conus3km/geotiff/vsm_percentiles/'
DEPTHS=('10','40','100','200')
PATTERN=re.compile(r'(\d{8})_0000_sport_lis_vsm0-(10|40|100|200)cm_percentile_conus3km_float_wgs84\.tif')

def retrieve(url):
    request=urllib.request.Request(url,headers={'User-Agent':'WPC-Hydro-Dashboard-H6-source-audit/1.0'})
    with urllib.request.urlopen(request,timeout=120) as response:
        return response.read(),dict(response.headers)

def inventory(html):
    result={}
    for row in re.findall(r'<tr\b[^>]*>(.*?)</tr>',html,re.S):
        match=PATTERN.search(row)
        if not match:continue
        stamp=re.search(r"class=['\"]m['\"]>(.*?)</td>",row,re.S)
        modified=None
        if stamp:
            try:modified=datetime.strptime(' '.join(stamp.group(1).split()),'%Y-%b-%d %H:%M:%S').replace(tzinfo=timezone.utc).isoformat()
            except ValueError:pass
        date,depth=match.groups()
        result.setdefault(date,{})[depth]={'filename':match.group(0),'directory_modified_at':modified}
    return result

def audit_one(item,out):
    depth,entry=item
    url=BASE+entry['filename']
    print('Downloading '+entry['filename'],flush=True)
    raw,headers=retrieve(url)
    if raw[:4] not in (b'II*\x00',b'MM\x00*'):raise ValueError('Not TIFF: '+url)
    path=out/entry['filename'];path.write_bytes(raw)
    with rasterio.open(path) as ds:
        if ds.count!=1 or ds.crs is None or ds.dtypes[0] not in ('float32','float64'):raise ValueError('Unexpected raster structure')
        a=ds.read(1);valid=np.isfinite(a)&(a>=0)&(a<=100)&(ds.read_masks(1)>0)
        if not valid.any():raise ValueError('No valid percentile data')
        invalid=np.unique(a[~valid & np.isfinite(a)])
        if np.any((invalid!=9999)&(invalid!=ds.nodata)):raise ValueError('Unexpected out-of-range values')
        info=dict(entry,depth_cm=[0,int(depth)],source_url=url,sha256=hashlib.sha256(raw).hexdigest(),bytes=len(raw),http_last_modified=headers.get('Last-Modified'),shape=list(a.shape),crs=str(ds.crs),transform=list(ds.transform),bounds=list(ds.bounds),dtype=ds.dtypes[0],declared_nodata=ds.nodata,valid_cells=int(valid.sum()),range=[float(a[valid].min()),float(a[valid].max())],wet_tail_percent=float(100*np.mean(a[valid]>=70)),invalid_values=invalid.tolist(),tags=ds.tags())
    return depth,info,valid

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=True)
    html,headers=retrieve(BASE);(args.output/'source_inventory.html').write_bytes(html)
    inv=inventory(html.decode());now=datetime.now(timezone.utc)
    dates=sorted(d for d in inv if datetime.strptime(d,'%Y%m%d').replace(tzinfo=timezone.utc)<=now)
    if not dates:raise ValueError('No dated products')
    latest=dates[-1]
    if set(inv[latest])!=set(DEPTHS):raise ValueError('Newest date lacks complete depth suite; no silent older fallback')
    with ThreadPoolExecutor(max_workers=4) as pool:
        items=list(pool.map(lambda item:audit_one(item,args.output),inv[latest].items()))
    products={d:info for d,info,mask in items};reference=items[0]
    for d,info,mask in items:
        if any(info[k]!=reference[1][k] for k in ('shape','crs','transform')):raise ValueError('Depth grids differ')
        info['mask_difference_from_'+reference[0]]=int(np.count_nonzero(mask!=reference[2]))
    latency=[]
    for date in dates[-10:]:
        valid=datetime.strptime(date,'%Y%m%d').replace(tzinfo=timezone.utc)
        for depth,entry in inv[date].items():
            modified=entry['directory_modified_at']
            latency.append({'valid_time':valid.isoformat(),'depth_cm':int(depth),'modified_at':modified,'modified_minus_valid_hours':(datetime.fromisoformat(modified)-valid).total_seconds()/3600 if modified else None})
    report={'observed_at':now.isoformat(),'source':BASE,'valid_time':datetime.strptime(latest,'%Y%m%d').replace(tzinfo=timezone.utc).isoformat(),'grid_alignment_passed':True,'products':products,'recent_directory_timestamps':latency,'caveat':'Directory modification times are not proven first-publication times. Valid time comes from source filenames; inspect embedded tags separately. This is a diagnostic, not a production freshness policy.'}
    (args.output/'sport_depth_audit.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({d:{k:p[k] for k in ('shape','crs','valid_cells','range','wet_tail_percent')} for d,p in products.items()},indent=2),flush=True)
if __name__=='__main__':main()
