#!/usr/bin/env python3
"""Hourly WPC numerical FFG ingest. Public generations and science stay separate.

Publish metadata.json last; consumers must use the referenced immutable assets
and independently enforce expires_at. No dashboard registration is performed.
"""
import argparse
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

import numpy as np
import rasterio

sys.path.insert(0, str(Path(__file__).resolve().parent / 'tools'))
from probe_rfc_ffg_numeric import (SOURCE, HOURS, download, snapshot_names,
                                  validate_grib, band_contract, checked_array, preview)

REVISION = 'rfc-ffg-ingest-v0.2-mercator'
BASELINE = Path(__file__).resolve().parent / 'tools/rfc_ffg_coverage_baseline.json'
POLICY = {'max_snapshot_age_hours': 3, 'max_reference_age_hours': 9,
          'future_tolerance_minutes': 5, 'max_total_mask_change_fraction': .005,
          'max_tile_mask_change_fraction': .02, 'small_tile_tolerance_cells': 5,
          'max_previous_mask_change_fraction': .005,
          'max_value_mm': 1000, 'keep_generations': 48}


def dt(value):
    value = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if value.tzinfo is None:
        raise ValueError('Timestamp must have timezone')
    return value.astimezone(timezone.utc)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.pending-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(payload, stream, indent=2, allow_nan=False)
            stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def safe_path(root, relative):
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError('Asset path escapes output directory')
    return path


def verify_active(root, active):
    if set(active.get('assets', {})) != {'1', '3', '6'}:
        raise ValueError('Retained product lacks a complete duration set')
    for item in active['assets'].values():
        path = safe_path(root, item['path'])
        if not path.is_file() or digest(path) != item['sha256']:
            raise ValueError('Retained product is missing or corrupt')


def expires_at(active, policy):
    return min(dt(active['snapshot_time']) + timedelta(hours=policy['max_snapshot_age_hours']),
               dt(active['reference_time']) + timedelta(hours=policy['max_reference_age_hours']))


def freshness(active, current, policy):
    expiry = expires_at(active, policy)
    return {'snapshot_age_hours': (current-dt(active['snapshot_time'])).total_seconds()/3600,
            'reference_age_hours': (current-dt(active['reference_time'])).total_seconds()/3600,
            'expires_at': expiry.isoformat(), 'expired': current >= expiry}


def validate_times(snapshot, reference, request, current, policy):
    tolerance = timedelta(minutes=policy['future_tolerance_minutes'])
    if snapshot > current+tolerance or reference > snapshot+tolerance:
        raise ValueError('Future or inconsistent source timestamps')
    active = {'snapshot_time': snapshot.isoformat(), 'reference_time': reference.isoformat()}
    if freshness(active, current, policy)['expired']:
        raise ValueError('Source snapshot or reference cycle is too old')
    modified = request.get('http_last_modified')
    if modified:
        modified = parsedate_to_datetime(modified)
        if modified.tzinfo is None:
            modified = modified.replace(tzinfo=timezone.utc)
        if modified > current+tolerance:
            raise ValueError('Source HTTP modification time is in the future')
        if modified < snapshot-tolerance:
            raise ValueError('HTTP modification time predates snapshot')
    return modified.isoformat() if modified else None


def coverage(fields, crs, affine, baseline, policy):
    if list(next(iter(fields.values())).shape) != baseline['shape']:
        raise ValueError('Unexpected grid dimensions')
    if crs != rasterio.crs.CRS.from_wkt(baseline['crs_wkt']) or not np.allclose(list(affine)[:6], baseline['affine'], rtol=0, atol=.001):
        raise ValueError('Unexpected grid geometry or CRS')
    size=baseline['tile_size']; summaries={}
    for h,a in fields.items():
        valid=~np.ma.getmaskarray(a)
        expected=baseline['durations'][str(h)]
        count=int(valid.sum())
        if abs(count-expected['valid_cells']) > expected['valid_cells']*policy['max_total_mask_change_fraction']:
            raise ValueError(f'{h}h total coverage changed excessively')
        tiles=[]
        for iy,y in enumerate(range(0,a.shape[0],size)):
            row=[]
            for ix,x in enumerate(range(0,a.shape[1],size)):
                actual=int(valid[y:y+size,x:x+size].sum()); wanted=expected['tiles'][iy][ix]
                limit=max(policy['small_tile_tolerance_cells'], wanted*policy['max_tile_mask_change_fraction'])
                if abs(actual-wanted)>limit:
                    raise ValueError(f'{h}h regional coverage changed at tile {iy},{ix}')
                row.append(actual)
            tiles.append(row)
        summaries[str(h)]={'valid_cells':count,'tiles':tiles,'baseline_passed':True}
    return summaries


def read_fields(path):
    fields={}; refs=set(); ends={}
    with rasterio.open(path) as source:
        if source.driver!='GRIB' or source.crs is None:
            raise ValueError('Not a georeferenced numerical GRIB')
        for b in source.indexes:
            h,ref,end=band_contract(source.tags(b))
            if h not in HOURS:
                continue
            if h in fields:
                raise ValueError('Duplicate duration')
            fields[h]=checked_array(source.read(b,masked=True))
            refs.add(ref);ends[str(h)]=datetime.fromtimestamp(end,timezone.utc).isoformat()
        if set(fields)!=set(HOURS) or len(refs)!=1:
            raise ValueError('Missing duration or mixed reference cycles')
        return fields, source.crs, source.transform, datetime.fromtimestamp(refs.pop(),timezone.utc), ends


def previous_coverage(science, active, fields, policy):
    if not active:
        return
    path=safe_path(science, active['science']['path'])
    if not path.exists() or digest(path)!=active['science']['sha256']:
        raise ValueError('Previous numerical fields missing or corrupt; cannot verify continuity')
    with rasterio.open(path) as previous:
        for band,h in enumerate(HOURS,1):
            old=previous.read(band,masked=True)
            if old.shape!=fields[h].shape:
                raise ValueError('Previous grid dimensions differ')
            changes=np.count_nonzero(np.ma.getmaskarray(old)!=np.ma.getmaskarray(fields[h]))
            if changes>old.count()*policy['max_previous_mask_change_fraction']:
                raise ValueError(f'{h}h mask changed excessively since last accepted product')


def write_science(path, fields, crs, affine):
    shape=fields[1].shape
    with rasterio.open(path,'w',driver='GTiff',width=shape[1],height=shape[0],count=3,
                       dtype='float64',crs=crs,transform=affine,nodata=9999,compress='deflate') as out:
        for b,h in enumerate(HOURS,1):
            out.write(fields[h].filled(9999),b)
            out.set_band_description(b,f'{h}-hour RFC FFG (mm)')
            out.update_tags(b,units='mm',duration_hours=str(h))
    with rasterio.open(path) as out:
        for b,h in enumerate(HOURS,1):
            a=out.read(b,masked=True)
            if not np.array_equal(a.mask,fields[h].mask) or not np.array_equal(a.compressed(),fields[h].compressed()):
                raise ValueError('Scientific derivative round-trip failed')


def prune(root, active_id, keep):
    folders=sorted((root/'generations').glob('*'),key=lambda p:p.stat().st_mtime,reverse=True)
    for folder in folders[keep:]:
        if folder.is_dir() and folder.name!=active_id:
            shutil.rmtree(folder)


def ingest(output, science, current=None, fetcher=download, policy=None, baseline=None):
    current=current or datetime.now(timezone.utc);policy=dict(POLICY if policy is None else policy)
    baseline=baseline or json.loads(BASELINE.read_text())
    output=Path(output);science=Path(science)
    if science.resolve().is_relative_to(output.resolve()) or output.resolve().is_relative_to(science.resolve()):
        raise ValueError('Public and scientific roots must be separate')
    output.mkdir(parents=True,exist_ok=True);science.mkdir(parents=True,exist_ok=True)
    # One writer across publication and retention updates.
    with (output/'.ingest.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        pointer=output/'metadata.json';active=None;stages=[];candidate=None
        try:
            if pointer.exists():
                prior=json.loads(pointer.read_text());active=prior.get('active')
                if active:
                    verify_active(output,active)
            listing,listing_request=fetcher(SOURCE)
            names=snapshot_names(listing.decode(),current)
            if not names:
                raise ValueError('No eligible hourly snapshots listed')
            candidate=names[-1]
            snapshot=datetime.strptime(candidate[7:17],'%Y%m%d%H').replace(tzinfo=timezone.utc)
            if active and snapshot<dt(active['snapshot_time']):
                raise ValueError('Source discovery regressed behind last accepted snapshot')
            if (current-snapshot).total_seconds()>policy['max_snapshot_age_hours']*3600:
                raise ValueError('Newest listed snapshot is too old')
            print(f'RFC FFG: fetching {candidate}',flush=True)
            raw,request=fetcher(SOURCE+candidate)
            validate_grib(raw)
            source_hash=hashlib.sha256(raw).hexdigest()
            generation=f'{candidate[7:17]}-{source_hash}-{REVISION}'
            stage_science=Path(tempfile.mkdtemp(prefix='.stage-',dir=science));stages.append(stage_science)
            source_path=stage_science/'source.g2';source_path.write_bytes(raw)
            fields,crs,affine,reference,ends=read_fields(source_path)
            modified=validate_times(snapshot,reference,request,current,policy)
            if active and reference<dt(active['reference_time']):
                raise ValueError('Reference cycle regressed')
            for h,a in fields.items():
                if a.max()>policy['max_value_mm']:
                    raise ValueError(f'{h}h value exceeds configured sanity bound')
            cov=coverage(fields,crs,affine,baseline,policy)
            previous_coverage(science,active,fields,policy)
            # Source is re-fetched and decoded even when the filename was seen before.
            if active and generation==active['generation']:
                state='unchanged'
            else:
                print('RFC FFG: coverage accepted; staging all three durations',flush=True)
                stage_public=Path(tempfile.mkdtemp(prefix='.stage-',dir=output));stages.append(stage_public)
                native=stage_science/'ffg_native_mm.tif';write_science(native,fields,crs,affine)
                assets={};legend=None
                for h in HOURS:
                    name=f'rfc_ffg_{h}h.png'
                    legend=preview(fields[h],crs,affine,stage_public/name,width=3000,height=1650,target_crs="EPSG:3857")
                    with rasterio.open(stage_public/name) as image:
                        if image.count!=4 or not np.any(image.read(4)>0):
                            raise ValueError('Empty or invalid rendered image')
                    assets[str(h)]={'path':f'generations/{generation}/{name}',
                                    'sha256':digest(stage_public/name),'duration_hours':h}
                next_active={'generation':generation,'source_url':SOURCE+candidate,'source_sha256':source_hash,
                    'snapshot_time':snapshot.isoformat(),'reference_time':reference.isoformat(),
                    'http_modified_time':modified,'retrieved_at':request.get('retrieved_at'),
                    'accepted_at':current.isoformat(),'encoded_period_ends':ends,
                    'individual_rfc_issue_times':None,'assets':assets,'legend':legend,
                    'science':{'path':f'generations/{generation}/ffg_native_mm.tif','sha256':digest(native),'units':'mm'},
                    'coverage':cov,'coverage_baseline_sha256':digest(BASELINE),
                    'coverage_caveat':baseline['baseline_type'],'render_revision':REVISION}
                atomic_json(stage_public/'generation.json',next_active)
                atomic_json(stage_science/'provenance.json',{'source':request,'active':next_active})
                for root,stage in [(science,stage_science),(output,stage_public)]:
                    target=root/'generations'/generation;target.parent.mkdir(exist_ok=True)
                    if target.exists():
                        # A previous interrupted attempt may have staged this generation.
                        for p in stage.iterdir():
                            if p.is_file() and p.suffix not in ('.json',) and (not (target/p.name).exists() or digest(target/p.name)!=digest(p)):
                                raise ValueError('Conflicting immutable generation')
                    else:
                        os.rename(stage,target)
                # Reuse the originally staged metadata after an interrupted attempt.
                committed=json.loads((output/'generations'/generation/'generation.json').read_text())
                if committed['source_sha256']!=source_hash or committed['assets']!=next_active['assets']:
                    raise ValueError('Immutable generation metadata conflicts')
                verify_active(output,committed)
                active=committed;state='updated'
            status={'schema_version':1,'render_revision':REVISION,'state':state,'stale':False,
                    'last_attempt':{'at':current.isoformat(),'ok':True,'candidate':candidate,
                                    'source_request':request,'directory_request':listing_request},
                    'policy':policy,'active':active,'freshness':freshness(active,current,policy)}
            status['usable']=not status['freshness']['expired']
            atomic_json(pointer,status)
            for root in (science,output):
                try:prune(root,active['generation'],policy['keep_generations'])
                except OSError as error:print(f'Retention cleanup deferred: {error}',flush=True)
            print(f'RFC FFG: {state}; snapshot {active["snapshot_time"]}; cycle {active["reference_time"]}',flush=True)
            return status
        except Exception as exc:
            # Never erase good assets. Advertise failed refresh even if still within age limits.
            if active:
                try:verify_active(output,active)
                except Exception:active=None
            age=freshness(active,current,policy) if active else None
            status={'schema_version':1,'render_revision':REVISION,
                    'state':('expired' if age and age['expired'] else 'retained') if active else 'unavailable',
                    'stale':True,'usable':bool(active and not age['expired']),
                    'last_attempt':{'at':current.isoformat(),'ok':False,'candidate':candidate,'error':str(exc)},
                    'policy':policy,'active':active,'freshness':age}
            atomic_json(pointer,status)
            print(f'RFC FFG: {status["state"]}; {exc}',flush=True)
            return status
        finally:
            for stage in stages:
                if stage.exists():shutil.rmtree(stage)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--science-dir',type=Path,required=True)
    args=parser.parse_args()
    result=ingest(args.output_dir,args.science_dir)
    return 0 if result['last_attempt']['ok'] else 1


if __name__=='__main__':
    raise SystemExit(main())
