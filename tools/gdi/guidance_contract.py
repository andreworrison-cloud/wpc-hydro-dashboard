"""Time and aggregation contracts for the focused dashboard GDI products.

These functions aggregate already calculated GDI. They do not change José's
thermodynamic formulation, its humidity inputs, or its terrain correction.
"""
import datetime as dt
import numpy as np
from scipy.signal import fftconvolve

UTC = dt.timezone.utc
RECIPE = 'gdi_focused_v3'
THRESHOLDS = (30, 40, 50)
TLE_RUNS_PER_MODEL = 6
TLE_HOURS = 12
NEIGHBORHOOD_KM = 40
GRID_KM = 3
MIN_VALID_FRACTION = .8
PERCENT_COLORS = ['#142d41', '#205269', '#267991', '#359fa4', '#62c6b4', '#a5debd', '#e5efa6']
PERCENT_EDGES = [0, 10, 25, 50, 75, 90, 100]
PRODUCT_KEYS = {
    'forecast': {f'{model}{h}' for model in ('hrrr', 'rrfs', 'blend') for h in range(7)},
    'tle': {f'{metric}{t}' for metric in ('exceedance', 'persistence') for t in THRESHOLDS},
    'day1': {'hrrr_maximum', 'rrfs_maximum', 'blend_maximum'},
}


def utc(value):
    result = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('An explicit UTC offset is required')
    result = result.astimezone(UTC)
    if result.minute or result.second or result.microsecond:
        raise ValueError('Forecast samples and cycles must be on whole hours')
    return result


def hourly_times(start, end, include_start=True):
    first = 0 if include_start else 1
    hours = (end - start).total_seconds() / 3600
    if hours != int(hours) or hours <= 0:
        raise ValueError('Invalid hourly window')
    return [start + dt.timedelta(hours=h) for h in range(first, int(hours) + 1)]


def cam_ero_contract(metadata, now):
    """Use the exact published HREF/REFS cycles and their common ERO period.

    GDI is instantaneous, so include the initial boundary as well as the hourly
    endpoints. Accumulated CAM QPF instead describes the hours ending at them.
    """
    h = utc(metadata['href_init_utc'])
    r = utc(metadata['refs_init_utc'])
    start, end = utc(metadata['ero_start_utc']), utc(metadata['ero_end_utc'])
    if h.hour not in (0, 6, 12, 18) or r.hour not in (0, 6, 12, 18):
        raise ValueError('ERO CAM source uses a non-synoptic cycle')
    base = h.replace(hour=12)
    if r.replace(hour=12) != base:
        raise ValueError('CAM source cycles target different ERO days')
    expected_start = h if h.hour == 18 else base
    if start != expected_start or end != base + dt.timedelta(hours=24):
        raise ValueError('CAM source does not match the Day 1 window rules')
    if h.hour == 18 and r != h:
        raise ValueError('An 18Z update requires both models initialized at 18Z')
    if h.hour != 18 and r.hour == 18:
        raise ValueError('Do not combine a full-day maximum with an 18Z update')
    if h > now or r > now or end <= now:
        raise ValueError('CAM cycles are future-dated or their window is expired')
    expected = {0: list(range(13, 37)), 6: list(range(7, 31)),
                12: list(range(1, 25)), 18: list(range(1, 19))}
    for model, cycle in (('href', h), ('refs', r)):
        if metadata.get(model + '_forecast_hours') != expected[cycle.hour]:
            raise ValueError('CAM hourly endpoints are incomplete or misaligned')
    if metadata.get('ero_coverage_hours') != int((end - start).total_seconds() / 3600):
        raise ValueError('CAM coverage duration disagrees with its window')
    return {'hrrr': [h], 'rrfs': [r]}, start, end, hourly_times(start, end)


def check_grids(grids):
    lat, lon, _ = grids['hrrr']
    rlat, rlon, _ = grids['rrfs']
    if (lat.shape != rlat.shape or not np.allclose(lat, rlat, atol=1e-6, rtol=0)
            or not np.allclose(lon, rlon, atol=1e-6, rtol=0)):
        raise ValueError('HRRR/RRFS grids differ; explicit regridding is required')
    return lat, lon


def equal_model_mean(hrrr, rrfs):
    """Require both models at each cell; never renormalize a missing model."""
    return np.where(np.isfinite(hrrr) & np.isfinite(rrfs), .5 * hrrr + .5 * rrfs, np.nan)


class MemberAccumulator:
    """Stream one run, preserving hour-specific recurrence and missing values."""
    def __init__(self):
        self.maximum = None
        self.complete = None
        self.recent = []
        self.persistent = {}
        self.count = 0

    def update(self, field):
        a = np.asarray(field, dtype='float32')
        good = np.isfinite(a)
        if self.maximum is None:
            self.maximum = np.where(good, a, -np.inf)
            self.complete = good.copy()
            self.persistent = {t: np.zeros(a.shape, dtype=bool) for t in THRESHOLDS}
        else:
            if a.shape != self.maximum.shape:
                raise ValueError('Member grid shape changed')
            self.maximum = np.maximum(self.maximum, np.where(good, a, -np.inf))
            self.complete &= good
        self.recent.append({t: good & (a >= t) for t in THRESHOLDS})
        self.recent = self.recent[-3:]
        if len(self.recent) == 3:
            for t in THRESHOLDS:
                self.persistent[t] |= sum(x[t].astype('uint8') for x in self.recent) >= 2
        self.count += 1

    def finish(self, expected_count):
        if self.count != expected_count:
            raise ValueError('Incomplete hourly member')
        return {'max': np.where(self.complete, self.maximum, np.nan),
                'complete': self.complete,
                'persistent': self.persistent}


def footprint():
    # Same nominal 40-km radius / nearest native grid-cell convention as HRRR-TLE.
    radius = max(1, int(round(NEIGHBORHOOD_KM / GRID_KM)))
    yy, xx = np.mgrid[-radius:radius + 1, -radius:radius + 1]
    return (xx * xx + yy * yy <= radius * radius).astype('float32')


def disk_sum(binary, kernel):
    # Inputs are 0/1 and disk weights are integers. FFT convolution avoids
    # billions of direct 40-km stencil operations on each native 3-km field.
    # Round numerical FFT noise to the exact integer count, including zero.
    return np.clip(np.rint(fftconvolve(binary.astype('float32'), kernel, mode='same')),
                   0, kernel.sum())


def tle_fields(members):
    expected = [(model, lag) for model in ('hrrr', 'rrfs') for lag in range(TLE_RUNS_PER_MODEL)]
    if sorted((m['model'], m['lag']) for m in members) != expected:
        raise ValueError('Six distinct lagged runs from each model are required')
    for model in ('hrrr', 'rrfs'):
        if len({m['cycle'] for m in members if m['model'] == model}) != TLE_RUNS_PER_MODEL:
            raise ValueError('Repeated cycle would double-weight a member')
    results = {}
    all_valid = np.logical_and.reduce([m['complete'] for m in members])
    for threshold in THRESHOLDS:
        # Every actual run has one vote. Spatial coverage is not member frequency.
        hit = sum((m['max'] >= threshold).astype('uint8') for m in members)
        persistent = sum(m['persistent'][threshold].astype('uint8') for m in members)
        results[f'exceedance{threshold}'] = np.where(all_valid, 100 * hit.astype('float32') / len(members), np.nan)
        results[f'persistence{threshold}'] = np.where(all_valid, 100 * persistent.astype('float32') / len(members), np.nan)
    return results


def verify_spec(m, suite):
    """Validate scientific timing/aggregation provenance before publishing PNGs."""
    if m.get('recipe') != RECIPE or m.get('kind') != suite or set(m.get('products', {})) != PRODUCT_KEYS[suite]:
        raise ValueError('Unexpected focused GDI product set')
    start, end = utc(m['window_start']), utc(m['window_end'])
    times = [utc(t) for t in m['sample_times']]
    expected_times = hourly_times(start, end)
    if (times != expected_times or m['sample_count'] != len(times)
            or utc(m['expires_at']) > end):
        raise ValueError('Incomplete/misaligned sample times')
    runs = m['source_metadata']
    per_model = TLE_RUNS_PER_MODEL if suite == 'tle' else 1
    expected = [(model, lag) for model in ('hrrr', 'rrfs') for lag in range(per_model)]
    if (m['member_count'] != 2 * per_model
            or sorted((r['model'], r['lag']) for r in runs) != expected):
        raise ValueError('Incomplete model membership')
    for model in ('hrrr', 'rrfs'):
        if len({r['cycle'] for r in runs if r['model'] == model}) != per_model:
            raise ValueError('Duplicate member cycle')
    for run in runs:
        own_times = hourly_times(utc(run['cycle']), utc(run['cycle']) + dt.timedelta(hours=6))
        expected_run_times = sorted(set(times + own_times)) if suite == 'forecast' else times
        if [utc(s['valid_time']) for s in run['samples']] != expected_run_times:
            raise ValueError('Model samples do not share the same valid times')
        for s in run['samples']:
            if (utc(s['cycle']) != utc(run['cycle'])
                    or utc(s['cycle']) + dt.timedelta(hours=s['lead']) != utc(s['valid_time'])):
                raise ValueError('Sample cycle/lead/time mismatch')
    if suite == 'tle':
        if (end != start + dt.timedelta(hours=TLE_HOURS)
                or utc(m['expires_at']) != start + dt.timedelta(hours=1)
                or m.get('frequency_method') != 'native_point_equal_member_frequency'):
            raise ValueError('TLE must use the current F00-F12 window and point member frequency')
        if dt.datetime.fromisoformat(m['built_at']).replace(minute=0,second=0,microsecond=0) != start:
            raise ValueError('TLE reference hour must be the current clock hour')
        for model in ('hrrr','rrfs'):
            cycles = sorted(utc(r['cycle']) for r in runs if r['model'] == model)
            newest = cycles[-1]
            if newest not in (start, start-dt.timedelta(hours=1)) or cycles != [newest-dt.timedelta(hours=h) for h in reversed(range(6))]:
                raise ValueError('Each model needs its six consecutive hourly runs; do not fill gaps with older cycles')
        if m.get('persistence_rule') != 'at_least_2_of_3_hourly_samples':
            raise ValueError('Unexpected persistence rule')
    if suite == 'forecast':
        if end != start + dt.timedelta(hours=6) or m.get('forecast_sampling') != 'hourly_f00_f06':
            raise ValueError('Forecast loops require seven hourly frames')
        origins = {r['model']:utc(r['cycle']) for r in runs}
        if start != max(origins.values()):raise ValueError('Blend must start at the newest source cycle')
        if utc(m['expires_at']) != min(v+dt.timedelta(hours=6) for v in origins.values()):
            raise ValueError('Forecast expiry must respect the earliest model loop endpoint')
        for model in ('hrrr','rrfs','blend'):
            origin = start if model == 'blend' else origins[model]
            for h in range(7):
                if utc(m['products'][f'{model}{h}']['valid_time']) != origin+dt.timedelta(hours=h):
                    raise ValueError('Loop frame does not match its valid time')
    if suite == 'day1':
        if utc(m['expires_at']) != end:raise ValueError('Day 1 expiry must match the ERO endpoint')
        built_at = dt.datetime.fromisoformat(m['built_at'].replace('Z', '+00:00'))
        if built_at.tzinfo is None:
            raise ValueError('Build time needs an explicit UTC offset')
        cycles, s, e, t = cam_ero_contract(m['ero_cam'], built_at)
        if (s, e, t) != (start, end, times):
            raise ValueError('Day 1 GDI differs from its ERO CAM reference')
        if any(utc(r['cycle']) != cycles[r['model']][0] for r in runs):
            raise ValueError('Day 1 GDI source cycles differ from HREF/REFS cycles')


def verify_unavailable(m):
    if (m.get('recipe') != RECIPE or m.get('kind') != 'tle'
            or m.get('status') != 'awaiting_hourly_inputs'
            or m.get('products') != {} or m.get('assets') != {}
            or not m.get('availability') or not m.get('status_message')):
        raise ValueError('Invalid unavailable-hourly-input publication')
    start,end=utc(m['window_start']),utc(m['window_end'])
    if end != start+dt.timedelta(hours=12) or utc(m['expires_at']) != start+dt.timedelta(hours=1):
        raise ValueError('Unavailable TLE must still describe the current F00-F12 window')
    if utc(m['cycle']) != start or dt.datetime.fromisoformat(m['built_at']).replace(minute=0,second=0,microsecond=0)!=start:
        raise ValueError('Unavailable TLE must describe the current reference hour')
    if set(m['availability']) != {'hrrr','rrfs'} or all(any(all(c['available'] for c in a['cycles']) for a in attempts) for attempts in m['availability'].values()):
        raise ValueError('Unavailable status needs an actual incomplete hourly membership')
