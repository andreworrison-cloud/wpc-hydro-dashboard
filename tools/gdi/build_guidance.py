"""Produce model forecasts, merged GDI TLE, and CAM-aligned Day 1 maxima."""
import argparse
import datetime as dt
import hashlib
import json
import pathlib
import subprocess
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
import numpy as np
from guidance_contract import (UTC, RECIPE, FORECAST_SAMPLING, THRESHOLDS, TLE_RUNS_PER_MODEL,
    TLE_HOURS, NEIGHBORHOOD_KM, MIN_VALID_FRACTION, PERCENT_COLORS,
    PERCENT_EDGES, MemberAccumulator, cam_ero_contract, hourly_times,
    check_grids, equal_model_mean, tle_fields, verify_spec, verify_unavailable)

SCRIPTS = pathlib.Path(__file__).parent
CAM_URL = ('https://raw.githubusercontent.com/andreworrison-cloud/'
           'wpc-hydro-dashboard/pages-live/static/ero_cam_metadata.json')


def read_cam(now):
    with urllib.request.urlopen(CAM_URL + '?gdi=' + str(int(now.timestamp())), timeout=30) as response:
        return json.load(response)


def horizon(model, cycle):
    return (48 if model == 'hrrr' else 84) if cycle.hour % 6 == 0 else 18


def probe(model, cycle, times, source_factory, all_hours=False):
    leads = [int((t - cycle).total_seconds() / 3600) for t in times]
    if min(leads) < 0 or max(leads) > horizon(model, cycle):
        raise ValueError('Valid window exceeds model horizon')
    source = source_factory(model, cycle.strftime('%Y%m%d%H'))
    # Fail quickly on missing endpoints, then check every intermediate forecast
    # hour before choosing a run for the synchronized loops.
    checks = sorted({leads[0], leads[-1]}) + (leads[1:-1] if all_hours else [])
    for lead in checks:
        source.tasks(lead)


def latest_cycles(model, limit, upper, times, source_factory, lookback=48):
    found = []
    for age in range(lookback + 1):
        cycle = upper - dt.timedelta(hours=age)
        try:
            probe(model, cycle, times, source_factory)
        except Exception as exc:
            print('Unavailable', model, cycle.isoformat(), str(exc)[:150], flush=True)
            continue
        found.append(cycle)
        print('Selected', model, cycle.isoformat(), flush=True)
        if len(found) == limit:
            return found
    raise ValueError(f'{limit} complete {model} runs unavailable')


class HourlyInputsUnavailable(ValueError):
    def __init__(self, report):
        super().__init__('Six consecutive hourly GDI input cycles are unavailable')
        self.report = report


def consecutive_cycles(model, hour, times, source_factory):
    attempts=[]
    # A run older than T0-1 would put the oldest lag beyond the short-run F18
    # horizon. Never move the requested window backward to make it fit.
    for age in (0,1):
        newest=hour-dt.timedelta(hours=age)
        cycles=[newest-dt.timedelta(hours=h) for h in range(6)]
        def check(cycle):
            try:
                probe(model,cycle,times,source_factory)
                return {'cycle':cycle.isoformat(),'available':True}
            except Exception as exc:
                return {'cycle':cycle.isoformat(),'available':False,'reason':str(exc)[:700]}
        with ThreadPoolExecutor(max_workers=4) as pool:
            checks=list(pool.map(check,cycles))
        attempts.append({'newest_cycle':newest.isoformat(),'cycles':checks})
        if all(x['available'] for x in checks):return cycles,attempts
    return None,attempts


def select(mode, now, source_factory, cam=None):
    hour = now.replace(minute=0, second=0, microsecond=0)
    if mode == 'ero':
        cam = read_cam(now) if cam is None else cam
        cycles, start, end, times = cam_ero_contract(cam, now)
        for model, runs in cycles.items():
            probe(model, runs[0], times, source_factory)
        return 'day1', cycles, start, end, times, cam
    if mode == 'forecast':
        start=hour;end=start+dt.timedelta(hours=6);times=hourly_times(start,end)
        cycles={}
        for model in ('hrrr','rrfs'):
            for age in range(6):
                cycle=hour-dt.timedelta(hours=age)
                try:probe(model,cycle,times,source_factory,all_hours=True)
                except Exception:continue
                cycles[model]=[cycle];break
            else:raise ValueError('No complete '+model+' run covers the common six-hour window')
        return 'forecast', cycles, start, end, times, None
    times=hourly_times(hour,hour+dt.timedelta(hours=12))
    cycles,report={},{}
    for model in ('hrrr','rrfs'):
        cycles[model],report[model]=consecutive_cycles(model,hour,times,source_factory)
    if not all(cycles.values()):raise HourlyInputsUnavailable(report)
    return 'tle',cycles,hour,times[-1],times,None


def unavailable_publication(public, now, report):
    start=now.replace(minute=0,second=0,microsecond=0)
    missing=[model.upper() for model,attempts in report.items()
             if not any(all(c['available'] for c in a['cycles']) for a in attempts)]
    spec={'recipe':RECIPE,'kind':'tle','model':'hrrr_rrfs','status':'awaiting_hourly_inputs',
        'status_message':'Hourly '+ '/'.join(missing)+' GDI inputs unavailable · six consecutive hourly runs required',
        'availability':report,'cycle':start.isoformat(),'built_at':now.isoformat(),
        'window_start':start.isoformat(),'window_end':(start+dt.timedelta(hours=12)).isoformat(),
        'expires_at':(start+dt.timedelta(hours=1)).isoformat(),'products':{},'assets':{},
        'schema':'gdi_named_suite_v1','overlay_type':'labeled_contours_v1',
        'width':2400,'height':1360,'bounds':[[24,-125],[50,-66]],'crs':'EPSG:3857','resampling':'nearest'}
    verify_unavailable(spec)
    digest=hashlib.sha256(json.dumps(spec,sort_keys=True).encode()).hexdigest()[:12]
    spec['generation']=start.strftime('%Y%m%d%H')+'-'+digest+'-v1'
    public=pathlib.Path(public);dest=public/'generations'/spec['generation'];dest.mkdir(parents=True,exist_ok=True)
    (dest/'provenance.json').write_text(json.dumps(spec,indent=2))
    tmp=public/'metadata.tmp';tmp.write_text(json.dumps(spec,indent=2));tmp.replace(public/'metadata.json')
    print(spec['status_message'],flush=True)
    return spec


def frame(model, cycle, lead, cache, grids):
    path = cache / model / cycle.strftime('%Y%m%d%H') / f'F{lead:03d}.npz'
    meta = path.with_suffix('.json')
    path.parent.mkdir(parents=True, exist_ok=True)
    good = False
    if path.exists() and meta.exists():
        try:
            m = json.loads(meta.read_text())
            good = (m.get('model') == model and m.get('cycle') == cycle.isoformat()
                    and m.get('lead') == lead
                    and m.get('sha256') == hashlib.sha256(path.read_bytes()).hexdigest()
                    and (cache / model / (m['grid_md5'] + '-grid.npz')).exists())
        except (OSError, ValueError, KeyError):
            pass
    if not good:
        subprocess.run([sys.executable, str(SCRIPTS / 'decode_model.py'), '--model', model,
                        '--cycle', cycle.strftime('%Y%m%d%H'), '--lead', str(lead),
                        '--out', str(path)], check=True, timeout=300)
    m = json.loads(meta.read_text())
    gridpath = cache / model / (m['grid_md5'] + '-grid.npz')
    with np.load(path) as f:
        a = f['gdi'].copy()
        compact = 'latitude' in f
        if compact:
            if not gridpath.exists():
                np.savez_compressed(gridpath, latitude=f['latitude'], longitude=f['longitude'])
    if compact:
        np.savez_compressed(path, gdi=a)
        m['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
        meta.write_text(json.dumps(m, indent=2))
    if model not in grids:
        with np.load(gridpath) as f:
            grids[model] = (f['latitude'].copy(), f['longitude'].copy(), m['grid_md5'])
    elif grids[model][2] != m['grid_md5']:
        raise ValueError('Model grid changed across source runs')
    return a, m


def main(mode, work, public, now=None, cam=None, cache_root=None):
    supplied_time = now is not None
    supplied_cam = cam is not None
    now = now or dt.datetime.now(UTC)
    if now.tzinfo is None:
        raise ValueError('Use a timezone-aware time')
    from model_source import PressureSource
    try:kind, cycles, start, end, times, cam = select(mode, now, PressureSource, cam)
    except HourlyInputsUnavailable as exc:return unavailable_publication(public,now,exc.report)
    signature = hashlib.sha256(json.dumps({'recipe': RECIPE, 'kind': kind,
        'cycles': {k: [c.isoformat() for c in v] for k, v in cycles.items()},
        'times': [t.isoformat() for t in times],
        **({'forecast_sampling':FORECAST_SAMPLING} if kind=='forecast' else {})}, sort_keys=True).encode()).hexdigest()
    public = pathlib.Path(public)
    old_path = public / 'metadata.json'
    if old_path.exists():
        old = json.loads(old_path.read_text())
        if old.get('selection_signature') == signature and old.get('recipe') == RECIPE:
            print('Current complete selection already published', kind, flush=True)
            return old
        reference=start if kind=='tle' else max(cycles[m][0] for m in cycles)
        if dt.datetime.fromisoformat(old['cycle']) > reference:
            raise ValueError('Refusing to regress to older source cycles')
    work = pathlib.Path(work)
    cache = pathlib.Path(cache_root) if cache_root else work / 'cache'
    grids, records, members, selected = {}, [], [], {}
    for model in ('hrrr', 'rrfs'):
        for lag, cycle in enumerate(cycles[model]):
            acc, samples = MemberAccumulator(), []
            requested_times=times
            for valid in requested_times:
                lead = int((valid - cycle).total_seconds() / 3600)
                field, m = frame(model, cycle, lead, cache, grids)
                acc.update(field)
                if kind == 'forecast':
                    selected[model, valid] = field
                samples.append({'valid_time': valid.isoformat(), 'cycle': m['cycle'],
                    'lead': lead, 'grid_md5': m['grid_md5'], 'sha256': m['sha256'],
                    'humidity_inputs': m['humidity_inputs'], 'sources': m['sources']})
            member = acc.finish(len(requested_times))
            members.append({**member, 'model': model, 'lag': lag, 'cycle': cycle.isoformat()})
            records.append({'model': model, 'lag': lag, 'cycle': cycle.isoformat(), 'samples': samples})
            print('Completed', kind, model, cycle.isoformat(), len(samples), 'samples', flush=True)
    lat, lon = check_grids(grids)
    if not supplied_time and end <= dt.datetime.now(UTC):
        raise ValueError('Forecast window expired during processing; do not publish')
    if kind=='tle' and not supplied_time and dt.datetime.now(UTC)>=start+dt.timedelta(hours=1):
        raise ValueError('Clock hour changed during TLE processing; rebuild the current F00-F12 window')
    if kind == 'day1' and not supplied_cam:
        # A CAM update can finish while native GDI fields are downloading.
        # Never publish a newly built GDI package against superseded cycles.
        latest = cam_ero_contract(read_cam(dt.datetime.now(UTC)), dt.datetime.now(UTC))
        if latest != (cycles, start, end, times):
            raise ValueError('ERO CAM cycles/window changed during processing; retry current reference')
    arrays, products = {'latitude': lat, 'longitude': lon}, {}
    source_label = ('HRRR ' + cycles['hrrr'][0].strftime('%m-%d %HZ') +
                    ' / RRFS ' + cycles['rrfs'][0].strftime('%m-%d %HZ'))
    def add(key, a, label, legend, valid=end, period=True, unit='GDI', **extra):
        arrays[key] = a
        products[key] = {'label': label, 'legend': legend, 'valid_time': valid.isoformat(),
                         'source_label': source_label, 'unit': unit, **extra}
        if period:
            products[key]['window_start'] = start.isoformat()
    if kind == 'forecast':
        for h in range(7):
            valid=start+dt.timedelta(hours=h)
            for model in ('hrrr', 'rrfs'):
                lead=int((valid-cycles[model][0]).total_seconds()/3600)
                add(f'{model}{h}', selected[model, valid], model.upper() + ' GDI',
                    'Hourly forecast · common valid times · 5-unit color bins', valid, False,
                    cycle=cycles[model][0].isoformat(),forecast_hour=lead)
                products[f'{model}{h}']['source_label'] = model.upper() + ' cycle ' + cycles[model][0].strftime('%m-%d %HZ') + f' · F{lead:02d}'
            add(f'blend{h}', equal_model_mean(selected['hrrr', valid], selected['rrfs', valid]),
                'HRRR/RRFS GDI Blend', 'Equal-weight model mean at the same valid time',
                valid, False,forecast_hour=h)
            products[f'blend{h}']['source_label'] = ' / '.join(model.upper() + ' ' +
                cycles[model][0].strftime('%m-%d %HZ') +
                f' F{int((valid-cycles[model][0]).total_seconds()/3600):02d}'
                for model in ('hrrr','rrfs'))
    elif kind == 'day1':
        h, r = members[0]['max'], members[1]['max']
        add('hrrr_maximum', h, 'Day 1 ERO · Maximum HRRR GDI', 'Maximum HRRR GDI over the displayed ERO period')
        add('rrfs_maximum', r, 'Day 1 ERO · Maximum RRFS GDI', 'Maximum RRFS GDI over the displayed ERO period')
        add('blend_maximum', equal_model_mean(h, r), 'Day 1 ERO · HRRR/RRFS Maximum Blend',
            'Equal-weight mean of the HRRR and RRFS period maxima · same cycle/window pairing as ERO CAMs')
    else:
        for key, value in tle_fields(members).items():
            threshold = int(''.join(c for c in key if c.isdigit()))
            persistent = key.startswith('persistence')
            label = f'HRRR/RRFS TLE · GDI ≥{threshold} · ' + ('Persistence' if persistent else 'Member Exceedance Frequency')
            legend = ('Member frequency of GDI meeting the threshold at the same grid point in at least 2 of 3 successive hourly samples'
                      if persistent else 'Member frequency of GDI meeting the threshold at the grid point at any hourly sample in F00–F12')
            add(key, value, label, legend + ' · 6 HRRR + 6 RRFS runs; equal model weights',
                unit='Persistence member frequency (%)' if persistent else 'Member exceedance frequency (%)',
                colors=PERCENT_COLORS, edges=PERCENT_EDGES)
    target = work / 'render'
    target.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(target / 'fields.npz', **arrays)
    spec = {'recipe': RECIPE, 'kind': kind, 'cycle': (start if kind=='tle' else max(cycles[m][0] for m in cycles)).isoformat(),
        'model': 'hrrr_rrfs', 'native_spacing_km': 3, 'products': products,
        'window_start': start.isoformat(), 'window_end': end.isoformat(), 'expires_at': end.isoformat(),
        'sample_times': [t.isoformat() for t in times], 'sample_count': len(times),
        'member_count': len(members), 'weighting': 'Each model 1/2; equal lag weights within each model',
        'source_metadata': records, 'built_at': now.isoformat(), 'selection_signature': signature}
    if kind == 'tle':
        spec.update(expires_at=(start+dt.timedelta(hours=1)).isoformat(),
                    frequency_method='native_point_equal_member_frequency',
                    persistence_rule='at_least_2_of_3_hourly_samples')
    if kind=='forecast':
        spec.update(forecast_sampling=FORECAST_SAMPLING)
    if cam is not None:
        spec['ero_cam'] = cam
        spec['ero_cam_source'] = CAM_URL
    verify_spec(spec, kind)
    (target / 'suite.json').write_text(json.dumps(spec, indent=2))
    subprocess.run([sys.executable, str(SCRIPTS / 'render_suite.py'), '--input', str(target),
                    '--public', str(public)], check=True)
    return spec


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=['forecast', 'tle', 'ero'], required=True)
    parser.add_argument('--work', required=True)
    parser.add_argument('--public', required=True)
    parser.add_argument('--cache')
    parser.add_argument('--now')
    args = parser.parse_args()
    main(args.mode, args.work, args.public, dt.datetime.fromisoformat(args.now) if args.now else None,
         cache_root=args.cache)
