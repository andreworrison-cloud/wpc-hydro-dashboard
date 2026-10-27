"""Forecast companions must share the displayed GDI's complete hourly selection."""
import datetime as dt
import re
from dynamics import SIGMA_KM
from dynamics_contract import DEFINITIONS
from guidance_contract import utc, hourly_times

RECIPE = 'cam_gdi_dynamics_v1'
SCHEMA = 'gdi_forecast_dynamics_v1'
MODELS = ('hrrr','rrfs','blend')


def contexts(base):
    result = {}
    for h,valid in enumerate(base['sample_times']):
        sources = []
        for model in MODELS[:2]:
            runs = [s for s in base['source_metadata'] if s['model'] == model]
            if len(runs) != 1:raise ValueError('Exactly one run per model is required')
            s = runs[0]['samples'][h]
            if s['valid_time'] != valid:raise ValueError('Misaligned base source')
            source = {k:s[k] for k in ('cycle','lead','grid_md5')}
            source['model'] = model
            sources.append(source)
            result[model+str(h)] = {'model':model,'valid_time':valid,'sources':[source]}
        result['blend'+str(h)] = {'model':'blend','valid_time':valid,'sources':sources}
    return result


def verify_metadata(m, assets=True):
    if (m.get('schema') != SCHEMA or m.get('recipe') != RECIPE or m.get('model') != 'hrrr_rrfs'
        or m.get('smoothing_sigma_km') != SIGMA_KM or m.get('definitions') != DEFINITIONS
        or not re.fullmatch(r'[a-f0-9]{64}',m.get('base_selection_signature',''))):
        raise ValueError('Invalid forecast dynamics definition')
    start,end = utc(m['window_start']),utc(m['window_end'])
    times = [t.isoformat() for t in hourly_times(start,end)]
    if end-start != dt.timedelta(hours=6) or m.get('sample_times') != times or utc(m['expires_at']) != end:
        raise ValueError('Incomplete forecast dynamics window')
    frames = m.get('frame_contexts',{})
    if set(frames) != {model+str(h) for model in MODELS for h in range(7)}:
        raise ValueError('Incomplete dynamics frames')
    provenance = m.get('source_metadata',[])
    if len(provenance) != 14:raise ValueError('Missing native diagnostic provenance')
    by_source = {(s['model'],s['cycle'],s['lead']):s for s in provenance}
    if len(by_source) != 14:raise ValueError('Duplicate native diagnostics')
    origins,grids = {},{}
    for h,valid in enumerate(times):
        pair = []
        for model in MODELS[:2]:
            c = frames[model+str(h)]
            if c.get('model') != model or c.get('valid_time') != valid or len(c.get('sources',[])) != 1:
                raise ValueError('Invalid native frame context')
            source = c['sources'][0]
            cycle,lead,grid = source['cycle'],source['lead'],source['grid_md5']
            if (source.get('model') != model or not isinstance(lead,int) or not 0 <= lead <= 18
                or utc(cycle)+dt.timedelta(hours=lead) != utc(valid)
                or not start-dt.timedelta(hours=6) < utc(cycle) <= start
                or not re.fullmatch(r'[a-f0-9]{32}',grid)):
                raise ValueError('Invalid diagnostic cycle, lead or grid')
            if model in origins and (origins[model] != cycle or grids[model] != grid):
                raise ValueError('Changed native cycle/grid within a loop')
            origins[model],grids[model] = cycle,grid
            s = by_source.get((model,cycle,lead),{})
            if (s.get('recipe') != RECIPE or s.get('grid_md5') != grid or s.get('smoothing_sigma_km') != SIGMA_KM
                or not s.get('sources') or not re.fullmatch(r'[a-f0-9]{64}',s.get('sha256',''))
                or not s.get('projection')):raise ValueError('Invalid native diagnostic provenance')
            pair.append(source)
        if frames['blend'+str(h)] != {'model':'blend','valid_time':valid,'sources':pair}:
            raise ValueError('Blend must retain both exact model sources')
    if utc(m['cycle']) != max(utc(c) for c in origins.values()):raise ValueError('Invalid reference cycle')
    expected = {name+'_'+frame for name in DEFINITIONS for frame in frames}
    if set(m.get('products',{})) != expected:raise ValueError('Incomplete forecast companion products')
    for key,p in m['products'].items():
        name,frame = key.split('_',1)
        if p != {'field':name,'frame':frame,'valid_time':frames[frame]['valid_time']}:
            raise ValueError('Misaligned forecast companion product')
    if not assets:return
    if (m.get('crs') != 'EPSG:3857' or [m.get('width'),m.get('height')] != [2400,1360]
        or m.get('bounds') != [[24,-125],[50,-66]] or m.get('resampling') != 'masked_bilinear'
        or not re.fullmatch(r'\d{10}-[a-f0-9]{12}-v1',m.get('generation',''))
        or set(m.get('assets',{})) != expected):raise ValueError('Invalid forecast companion export')
    for key,a in m['assets'].items():
        if a.get('path') != f"generations/{m['generation']}/{key}.png" or not re.fullmatch(r'[a-f0-9]{64}',a.get('sha256','')):
            raise ValueError('Unsafe forecast companion asset')
