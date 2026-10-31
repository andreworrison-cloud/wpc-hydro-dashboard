"""Publish companion fields for the exact RAP GDI cycle selected by its producer."""
import argparse
import datetime as dt
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from dynamics import RECIPE, SIGMA_KM
from dynamics_contract import DEFINITIONS


def build(cycle, work, public):
    c = dt.datetime.strptime(cycle,'%Y%m%d%H').replace(tzinfo=dt.timezone.utc)
    now = dt.datetime.now(dt.timezone.utc)
    if c > now or now >= c+dt.timedelta(hours=6):raise ValueError('Requested RAP cycle is expired or in the future')
    work,public = Path(work),Path(public)
    root = work/cycle
    root.mkdir(parents=True,exist_ok=True)
    prior = public/'metadata.json'
    if prior.exists():
        m = json.loads(prior.read_text())
        if m['cycle'] > c.isoformat():
            print('Newer dynamics retained');return
    sources = []
    for lead in (0,3):
        p = root/f'f{lead:02d}.npz'
        meta = p.with_suffix('.json')
        cached = json.loads(meta.read_text()) if p.exists() and meta.exists() else {}
        if (cached.get('recipe') != RECIPE or cached.get('cycle') != c.isoformat() or cached.get('lead') != lead
            or cached.get('sha256') != hashlib.sha256(p.read_bytes()).hexdigest()):
            subprocess.run([sys.executable,str(Path(__file__).with_name('decode_dynamics.py')),
                            '--cycle',cycle,'--lead',str(lead),'--out',str(p),'--cache',str(work/'cache')],check=True)
            cached = json.loads(meta.read_text())
        sources.append(cached)
    if sources[0]['grid_md5'] != sources[1]['grid_md5']:raise ValueError('Dynamics grids differ across hours')
    spec = {'schema':'gdi_dynamics_suite_v1','recipe':RECIPE,'model':'rap','cycle':c.isoformat(),
            'expires_at':(c+dt.timedelta(hours=6)).isoformat(),'built_at':now.isoformat(),
            'smoothing_sigma_km':SIGMA_KM,'definitions':DEFINITIONS,'source_metadata':sources,
            'products':{f'{name}_{lead}':{'field':name,'cycle':c.isoformat(),'lead':lead,
                         'valid_time':(c+dt.timedelta(hours=lead)).isoformat()} for name in DEFINITIONS for lead in (0,3)}}
    (root/'suite.json').write_text(json.dumps(spec,indent=2))
    # Keep the GRIB native decoder and graphics libraries in separate processes,
    # as in the established RAP GDI producer. A failed export is never published.
    subprocess.run([sys.executable,str(Path(__file__).with_name('render_dynamics.py')),
                    '--input',str(root),'--public',str(public)],check=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--cycle',required=True)
    p.add_argument('--work',default='run/rap-dynamics')
    p.add_argument('--public',required=True)
    a = p.parse_args()
    build(a.cycle,a.work,a.public)
