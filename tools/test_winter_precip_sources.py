"""Source fallback, image integrity and atomic failure contracts."""
import hashlib
import json
import sys
import tempfile
from datetime import datetime,timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import fetch_mrms_winter_type as builder
from PIL import Image

now=datetime(2026,10,24,5,34,tzinfo=timezone.utc)
name='MRMS_PrecipFlag_00.00_20261024-053400.grib2.gz'
key='CONUS/PrecipFlag_00.00/20261024/'+name
def request(session,url,**kwargs):
    if url.endswith('PrecipFlag/'):
        return SimpleNamespace(text=f'<a href="{name}">{name}</a>')
    return SimpleNamespace(content=f'<ListBucketResult><IsTruncated>false</IsTruncated><Contents><Key>{key}</Key></Contents></ListBucketResult>'.encode())
with patch.object(builder,'request',request):
    candidates,errors=builder.flag_inventory(None,now)
assert not errors and len(candidates)==2
assert {c.provider for c in candidates}=={'NCEP MRMS HTTPS','NOAA NODD MRMS (AWS)'}
assert candidates[0].timestamp==candidates[1].timestamp

with tempfile.TemporaryDirectory() as td:
    root=Path(td);rel='winter_frames_v2/winter_20261024T053440Z.png'
    image=root/rel;image.parent.mkdir();Image.new('RGBA',(2,3),(0,255,0,255)).save(image)
    frame={'valid_time_utc':'2026-10-24T05:34:40Z'}
    display={'image_width_px':2,'image_height_px':3}
    meta={'flag_valid_time_utc':'2026-10-24T05:34:00Z','image_sha256':hashlib.sha256(image.read_bytes()).hexdigest(),'hrrr':None}
    builder.validate_frame(frame,rel,meta,root,display)
    for broken in ({**meta,'image_sha256':'0'*64},{**meta,'flag_valid_time_utc':'2026-10-24T05:30:00Z'},
                   {**meta,'hrrr':{'valid_time_utc':'2026-10-24T06:00:00Z','cycle_utc':'2026-10-24T05:00:00Z','forecast_hour':1}}):
        try:builder.validate_frame(frame,rel,broken,root,display)
        except ValueError:pass
        else:raise AssertionError('Invalid supplement accepted')
    manifest=root/builder.loop.MANIFEST_NAME
    original=json.dumps({'latest_valid_time_utc':frame['valid_time_utc'],'display':display,'frames':[frame]}).encode()
    manifest.write_bytes(original)
    with patch.object(builder,'flag_inventory',return_value=([],[])):
        try:builder.build(SimpleNamespace(output_dir=root,cache_dir=root/'no-cache'))
        except RuntimeError:pass
        else:raise AssertionError('Incomplete supplement accepted')
    assert manifest.read_bytes()==original,'failed supplement changed baseline manifest'
print('Winter source contracts PASS: equal-time provider fallback, integrity/time checks, atomic failure.')
