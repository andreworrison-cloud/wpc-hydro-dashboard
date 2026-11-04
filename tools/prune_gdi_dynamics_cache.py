"""Bound disposable derived GDI checkpoints to the current 14 input frames."""
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path

MAX_CACHE_BYTES = 1024**3


def prune(base_path, cache_root, budget=MAX_CACHE_BYTES):
    root = Path(cache_root).resolve()
    if root.name != 'native' or root.parent.name != 'cam-dynamics':
        raise ValueError('Expected only the runner-local cam-dynamics/native cache')
    base = json.loads(Path(base_path).read_text())
    runs = base.get('source_metadata') or []
    if len(runs) != 2 or {r.get('model') for r in runs} != {'hrrr','rrfs'}:
        raise ValueError('A complete paired GDI selection is required')
    keep = set()
    # Validate every needed checkpoint before removing an obsolete cache file.
    for run in runs:
        samples = run.get('samples') or []
        if len(samples) != 7:
            raise ValueError('Seven current samples per model are required')
        for row in samples:
            lead = row['lead']
            if not isinstance(lead,int) or not 0 <= lead <= 84:
                raise ValueError('Invalid current forecast lead')
            cycle = datetime.fromisoformat(row['cycle']).strftime('%Y%m%d%H')
            path = root/run['model']/cycle/f'F{lead:03d}.npz'
            stamp_path = path.with_suffix('.json')
            if path.is_symlink() or stamp_path.is_symlink() or not path.resolve().is_relative_to(root):
                raise ValueError('Unsafe cache checkpoint path')
            stamp = json.loads(stamp_path.read_text())
            if (stamp.get('model') != run['model'] or stamp.get('cycle') != row['cycle']
                    or stamp.get('lead') != lead or stamp.get('grid_md5') != row['grid_md5']
                    or stamp.get('recipe') != 'cam_gdi_dynamics_v1'
                    or stamp.get('sha256') != hashlib.sha256(path.read_bytes()).hexdigest()):
                raise ValueError('Current checkpoint identity or checksum is incomplete')
            keep.update((path,stamp_path))
    if len(keep) != 28:
        raise ValueError('The paired selection must identify 14 distinct frames')
    removed = 0
    for model in ('hrrr','rrfs'):
        for path in (root/model).rglob('*'):
            if path.is_file() and path.suffix in ('.npz','.json') and path not in keep:
                if path.is_symlink() or not path.resolve().is_relative_to(root):
                    raise ValueError('Unsafe obsolete checkpoint path')
                path.unlink();removed += 1
    size = sum(p.stat().st_size for p in root.rglob('*') if p.is_file())
    return {'save_cache':size <= budget,'bytes':size,'removed_files':removed,'retained_frames':14}


if __name__ == '__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base',required=True,type=Path)
    parser.add_argument('--cache',type=Path,default=Path('run/cam-dynamics/native'))
    args=parser.parse_args()
    try: result=prune(args.base,args.cache)
    except (ValueError,KeyError,OSError) as exc:
        result={'save_cache':False,'reason':str(exc)}
    print('Derived GDI cache budget:',json.dumps(result),flush=True)
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'],'a') as stream:
            stream.write('save_cache='+str(result['save_cache']).lower()+'\n')
