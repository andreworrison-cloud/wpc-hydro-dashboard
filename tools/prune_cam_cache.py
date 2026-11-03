"""Keep only the current verified CAM suite in an Actions checkpoint upload."""
import json
from pathlib import Path
import sys
from datetime import datetime


def prune(manifest_path, cache_root):
    root = Path(cache_root).resolve()
    manifest = json.loads(Path(manifest_path).read_text())
    keep = set()
    for row in manifest['spc_member_hours']:
        init = datetime.fromisoformat(row['init_utc']).strftime('%Y%m%d%H')
        identity = row['family']+'_'+row['perturbation']
        keep.add(root/'day1-native-qpf-v0.1'/identity/init/f"f{row['native_forecast_hour']:03d}.npz")
    for row in manifest['omd_fields']:
        init = datetime.fromisoformat(row['init_utc']).strftime('%Y%m%d%H')
        signature = '-'.join(str(d) for d in row['durations_hours']) if row['product'] == 'ffri' else 'hourly4'
        path = root/'omd-native-v1'/init/f"{row['product']}_f{row['forecast_hour']:02d}_{signature}.grib2"
        keep.update((path, path.with_suffix('.json')))
    init = datetime.fromisoformat(manifest['init_utc'].replace('Z', '+00:00')).strftime('%Y%m%d%H')
    keep.update((root/'cycle-ffg-v2'/init/'ffg.npz', root/'cycle-ffg-v2'/init/'metadata.json'))
    raw = Path(manifest['ffg'].get('source_file', '')).resolve()
    if raw.is_relative_to(root):
        keep.add(raw)
    removed = 0
    if root.exists():
        for path in root.rglob('*'):
            if path.is_file() and path.resolve() not in keep:
                path.unlink(); removed += 1
    size = sum(p.stat().st_size for p in root.rglob('*') if p.is_file())
    print(f'Native cache bounded to verified suite: {size/1024**2:.1f} MiB; {removed} obsolete files removed')
    return removed, size


if __name__ == '__main__':
    prune(sys.argv[1], sys.argv[2])
