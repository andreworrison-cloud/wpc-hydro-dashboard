"""Produce model forecasts, merged GDI TLE, and CAM-aligned Day 1 maxima."""
import argparse
import datetime as dt
import hashlib
import json
import pathlib
import subprocess
import sys
import urllib.request
import numpy as np
from guidance_contract import (UTC, RECIPE, THRESHOLDS, TLE_RUNS_PER_MODEL,
    TLE_HOURS, NEIGHBORHOOD_KM, MIN_VALID_FRACTION, PERCENT_COLORS,
    PERCENT_EDGES, MemberAccumulator, cam_ero_contract, hourly_times,
    check_grids, equal_model_mean, tle_fields, verify_spec)

SCRIPTS = pathlib.Path(__file__).parent
CAM_URL = ('https://raw.githubusercontent.com/andreworrison-cloud/'
           'wpc-hydro-dashboard/pages-live/static/ero_cam_metadata.json')


def read_cam(now):
    with urllib.request.urlopen(CAM_URL + '?gdi=' + str(int(now.timestamp())), timeout=30) as response:
        return json.load(response)


def horizon(model, cycle):
    return 48 if model == 'hrrr' and cycle.hour % 6 == 0 else 18 if model == 'hrrr' else 84


def probe(model, cycle, times, source_factory):
    leads = [int((t - cycle).total_seconds() / 3600) for t in times]
    if min(leads) < 0 or max(leads) > horizon(model, cycle):
        raise ValueError('Valid window exceeds model horizon')
    source = source_factory(model, cycle.strftime('%Y%m%d%H'))
    for lead in sorted({leads[0], leads[-1]}):
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


def select(mode, now, source_factory, cam=None):
    hour = now.replace(minute=0, second=0, microsecond=0)
    if mode == 'ero':
        cam = read_cam(now) if cam is None else cam
        cycles, start, end, times = cam_ero_contract(cam, now)
        for model, runs in cycles.items():
            probe(model, runs[0], times, source_factory)
        return 'day1', cycles, start, end, times, cam
    if mode == 'forecast':
        start = hour + dt.timedelta(hours=now != hour)
        end = start + dt.timedelta(hours=6)
        times = [start + dt.timedelta(hours=h) for h in (0, 3, 6)]
        cycles = {model: latest_cycles(model, 1, hour, times, source_factory, 18)
                  for model in ('hrrr', 'rrfs')}
        return 'forecast', cycles, start, end, times, None
    # The newest complete six-hourly-run HRRR anchor establishes one common
    # twelve-hour valid-time window, exactly as in the HRRR-TLE dashboard.
    for age in range(15):
        anchor = hour - dt.timedelta(hours=age)
        times = hourly_times(anchor, anchor + dt.timedelta(hours=TLE_HOURS), False)
        if times[-1] <= now:
            continue
        hrrr = [anchor - dt.timedelta(hours=h) for h in range(TLE_RUNS_PER_MODEL)]
        try:
            for cycle in hrrr:
                probe('hrrr', cycle, times, source_factory)
            rrfs = latest_cycles('rrfs', TLE_RUNS_PER_MODEL, anchor, times, source_factory)
        except Exception as exc:
            print('Incomplete TLE anchor', anchor.isoformat(), str(exc)[:160], flush=True)
            continue
        if anchor - rrfs[0] > dt.timedelta(hours=6):
            raise ValueError('Newest RRFS TLE run is too old for current guidance')
        return 'tle', {'hrrr': hrrr, 'rrfs': rrfs}, anchor, times[-1], times, None
    raise ValueError('No complete aligned HRRR/RRFS TLE window')


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
    now = now or dt.datetime.now(UTC)
    if now.tzinfo is None:
        raise ValueError('Use a timezone-aware time')
    from model_source import PressureSource
    kind, cycles, start, end, times, cam = select(mode, now, PressureSource, cam)
    signature = hashlib.sha256(json.dumps({'recipe': RECIPE, 'kind': kind,
        'cycles': {k: [c.isoformat() for c in v] for k, v in cycles.items()},
        'times': [t.isoformat() for t in times]}, sort_keys=True).encode()).hexdigest()
    public = pathlib.Path(public)
    old_path = public / 'metadata.json'
    if old_path.exists():
        old = json.loads(old_path.read_text())
        if old.get('selection_signature') == signature and old.get('recipe') == RECIPE:
            print('Current complete selection already published', kind, flush=True)
            return old
        if dt.datetime.fromisoformat(old['cycle']) > max(cycles[m][0] for m in cycles):
            raise ValueError('Refusing to regress to older source cycles')
    work = pathlib.Path(work)
    cache = pathlib.Path(cache_root) if cache_root else work / 'cache'
    grids, records, members, selected = {}, [], [], {}
    for model in ('hrrr', 'rrfs'):
        for lag, cycle in enumerate(cycles[model]):
            acc, samples = MemberAccumulator(), []
            for index, valid in enumerate(times):
                lead = int((valid - cycle).total_seconds() / 3600)
                field, m = frame(model, cycle, lead, cache, grids)
                acc.update(field)
                if kind == 'forecast':
                    selected[model, index * 3] = field
                samples.append({'valid_time': valid.isoformat(), 'cycle': m['cycle'],
                    'lead': lead, 'grid_md5': m['grid_md5'], 'sha256': m['sha256'],
                    'humidity_inputs': m['humidity_inputs'], 'sources': m['sources']})
            member = acc.finish(len(times))
            members.append({**member, 'model': model, 'lag': lag, 'cycle': cycle.isoformat()})
            records.append({'model': model, 'lag': lag, 'cycle': cycle.isoformat(), 'samples': samples})
            print('Completed', kind, model, cycle.isoformat(), len(samples), 'samples', flush=True)
    lat, lon = check_grids(grids)
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
        for h in (0, 3, 6):
            for model in ('hrrr', 'rrfs'):
                add(f'{model}{h}', selected[model, h], model.upper() + ' GDI',
                    'Native GDI · 5-unit color bins', start + dt.timedelta(hours=h), False,
                    cycle=cycles[model][0].isoformat())
                products[f'{model}{h}']['source_label'] = model.upper() + ' cycle ' + cycles[model][0].strftime('%m-%d %HZ')
            add(f'blend{h}', equal_model_mean(selected['hrrr', h], selected['rrfs', h]),
                'HRRR/RRFS GDI Blend', 'Equal-weight model mean at the same valid time',
                start + dt.timedelta(hours=h), False)
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
            label = f'HRRR/RRFS TLE · GDI ≥{threshold} · ' + ('Persistence' if persistent else 'Neighborhood Coverage')
            legend = ('Member frequency of GDI meeting the threshold in at least 2 of 3 successive hourly samples, somewhere within 40 km'
                      if persistent else 'Mean 40-km spatial coverage of GDI reaching the threshold during the forecast window')
            add(key, value, label, legend + ' · 6 HRRR + 6 RRFS runs; equal model weights',
                unit='Persistence member frequency (%)' if persistent else 'Neighborhood coverage (%)',
                colors=PERCENT_COLORS, edges=PERCENT_EDGES)
    target = work / 'render'
    target.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(target / 'fields.npz', **arrays)
    spec = {'recipe': RECIPE, 'kind': kind, 'cycle': max(cycles[m][0] for m in cycles).isoformat(),
        'model': 'hrrr_rrfs', 'native_spacing_km': 3, 'products': products,
        'window_start': start.isoformat(), 'window_end': end.isoformat(), 'expires_at': end.isoformat(),
        'sample_times': [t.isoformat() for t in times], 'sample_count': len(times),
        'member_count': len(members), 'weighting': 'Each model 1/2; equal lag weights within each model',
        'source_metadata': records, 'built_at': now.isoformat(), 'selection_signature': signature}
    if kind == 'tle':
        spec.update(neighborhood_km=NEIGHBORHOOD_KM, minimum_valid_fraction=MIN_VALID_FRACTION,
                    persistence_rule='at_least_2_of_3_hourly_samples')
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
