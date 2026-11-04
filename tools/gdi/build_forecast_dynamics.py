"""Build companions from the actual published GDI selection, never a new run pick."""
import argparse
import datetime as dt
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from dynamics import SIGMA_KM
from dynamics_contract import DEFINITIONS
from forecast_dynamics_contract import RECIPE,SCHEMA,contexts,verify_metadata
from guidance_contract import verify_spec


def frame(model, source, work):
    cycle = dt.datetime.fromisoformat(source['cycle']).strftime('%Y%m%d%H')
    lead = source['lead']
    p = work/'native'/model/cycle/f'F{lead:03d}.npz'
    meta = p.with_suffix('.json')
    cached = {}
    if p.exists() and meta.exists():
        try:cached = json.loads(meta.read_text())
        except (OSError,ValueError):pass
    if not (cached.get('model') == model and cached.get('recipe') == RECIPE
            and cached.get('cycle') == source['cycle'] and cached.get('lead') == lead
            and cached.get('grid_md5') == source['grid_md5'] and cached.get('smoothing_sigma_km') == SIGMA_KM
            and cached.get('sha256') == hashlib.sha256(p.read_bytes()).hexdigest()):
        subprocess.run([sys.executable,str(Path(__file__).with_name('decode_dynamics.py')),
                        '--model',model,'--cycle',cycle,'--lead',str(lead),
                        '--out',str(p),'--cache',str(work/'raw')],check=True,timeout=600)
        cached = json.loads(meta.read_text())
    if cached['grid_md5'] != source['grid_md5']:raise ValueError('Diagnostic grid differs from published GDI')
    return cached


def build(base_path, work, public):
    base = json.loads(Path(base_path).read_text())
    verify_spec(base,'forecast')
    if base.get('schema') != 'gdi_named_suite_v1' or not base.get('selection_signature'):
        raise ValueError('Use a complete published GDI forecast package')
    now = dt.datetime.now(dt.timezone.utc)
    if now >= dt.datetime.fromisoformat(base['expires_at']):raise ValueError('Base forecast expired')
    work,public = Path(work),Path(public)
    previous = public/'metadata.json'
    if previous.exists():
        old = json.loads(previous.read_text())
        if old.get('base_selection_signature') == base['selection_signature']:
            print('Matching complete companion selection already published');return
        if old['window_start'] > base['window_start']:raise ValueError('Refusing to regress dynamics window')
    def one_model(run):
        # One decoder process per model at a time. Native ecCodes always runs
        # on each subprocess's main thread; at most eight HTTP prefetches total.
        return [frame(run['model'],s,work) for s in run['samples']]
    with ThreadPoolExecutor(max_workers=2) as pool:
        sources = [s for group in pool.map(one_model,base['source_metadata']) for s in group]
    frames = contexts(base)
    spec = {'schema':SCHEMA,'recipe':RECIPE,'model':'hrrr_rrfs','cycle':base['cycle'],
            'window_start':base['window_start'],'window_end':base['window_end'],
            'expires_at':base['expires_at'],'sample_times':base['sample_times'],
            'base_selection_signature':base['selection_signature'],'base_generation':base['generation'],
            'built_at':now.isoformat(),'smoothing_sigma_km':SIGMA_KM,'definitions':DEFINITIONS,
            'frame_contexts':frames,'source_metadata':sources,
            'blend_method':'Equal model mean of separately calculated filtered diagnostics; both models required',
            'products':{name+'_'+key:{'field':name,'frame':key,'valid_time':c['valid_time']}
                        for name in DEFINITIONS for key,c in frames.items()}}
    verify_metadata(spec,assets=False)
    target = work/'render'
    target.mkdir(parents=True,exist_ok=True)
    (target/'suite.json').write_text(json.dumps(spec,indent=2))
    subprocess.run([sys.executable,str(Path(__file__).with_name('render_forecast_dynamics.py')),
                    '--input',str(target),'--native',str(work/'native'),'--public',str(public)],check=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--base',required=True)
    p.add_argument('--work',default='run/cam-dynamics')
    p.add_argument('--public',required=True)
    a = p.parse_args()
    build(a.base,a.work,a.public)
