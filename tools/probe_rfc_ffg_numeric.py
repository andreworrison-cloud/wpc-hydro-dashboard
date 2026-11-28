#!/usr/bin/env python3
"""Validate WPC hourly numerical FFG snapshots; diagnostic outputs only.

Requires numpy and rasterio. Saves original GRIBs, native numerical GeoTIFFs,
preview PNGs, and a machine-readable evidence report in a unique directory.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import time
from urllib.request import Request, urlopen

import numpy as np
import rasterio
from rasterio.transform import from_bounds
from rasterio.warp import reproject, transform, Resampling
from probe_rfc_ffg import POINTS

SOURCE = 'https://ftp-wpc.ncep.noaa.gov/workoff/ffg/'
HOURS = (1, 3, 6)


def now():
    return datetime.now(timezone.utc)


def download(url):
    for attempt in range(3):
        try:
            with urlopen(Request(url, headers={'User-Agent': 'WPC-Hydro-H5-Numeric-Probe/0.2'}), timeout=40) as response:
                raw = response.read(25_000_001)
                if len(raw) > 25_000_000:
                    raise ValueError('Source exceeds diagnostic size limit')
                return raw, {'url': url, 'retrieved_at': now().isoformat(),
                             'http_last_modified': response.headers.get('Last-Modified'),
                             'http_etag': response.headers.get('ETag'),
                             'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}
        except Exception:
            if attempt == 2:
                raise
            time.sleep(attempt + 1)


def snapshot_names(html, current):
    names = set(re.findall(r'href="(5kmffg_\d{10}\.g2)"', html))
    return sorted(n for n in names if datetime.strptime(n[7:17], '%Y%m%d%H').replace(tzinfo=timezone.utc) <= current)


def validate_grib(raw):
    """Require complete concatenated GRIB2 messages, not HTML/partial downloads."""
    offset = 0
    messages = 0
    while offset < len(raw):
        if raw[offset:offset+4] != b'GRIB' or len(raw) - offset < 20 or raw[offset+7] != 2:
            raise ValueError('Not a complete GRIB2 stream')
        size = int.from_bytes(raw[offset+8:offset+16], 'big')
        if size < 20 or offset + size > len(raw) or raw[offset+size-4:offset+size] != b'7777':
            raise ValueError('Truncated or invalid GRIB2 message')
        offset += size
        messages += 1
    if not messages:
        raise ValueError('Empty GRIB2 stream')
    return messages


def band_contract(tags):
    """Validate semantics before selecting a duration; never rely on band order."""
    if tags.get('GRIB_ELEMENT') != 'FFLDG' or tags.get('GRIB_UNIT') != '[kg/(m^2)]':
        raise ValueError('Unexpected quantity or units')
    if 'CENTER=7(US-NCEP)' not in tags.get('GRIB_IDS', '') or not re.search(r'\bSUBCENTER=(?:5\(|255\b)', tags.get('GRIB_IDS', '')):
        raise ValueError('Unexpected originating center')
    if tags.get('GRIB_PDS_PDTN') != '8':
        raise ValueError('Unvalidated GRIB template')
    p = [int(x) for x in tags['GRIB_PDS_TEMPLATE_ASSEMBLED_VALUES'].split()]
    if len(p) != 29 or p[21] != 1 or p[25] != 1:
        raise ValueError('Unvalidated time range specification')
    hours = p[26]
    ref, end = int(tags['GRIB_REF_TIME']), int(tags['GRIB_VALID_TIME'])
    if int(tags['GRIB_FORECAST_SECONDS']) != 0 or end - ref != hours * 3600:
        raise ValueError('Duration and timestamps disagree')
    return hours, ref, end


def checked_array(array):
    mask = np.ma.getmaskarray(array)
    values = array.compressed()
    if not len(values) or not np.isfinite(values).all() or np.any(values <= 0):
        raise ValueError('Missing, nonfinite, zero or negative FFG values')
    return np.ma.array(np.asarray(array), mask=mask)


def preview(array, crs, affine, path, width=1500, height=650, target_crs="EPSG:4326"):
    """Display only: nearest-neighbor geographic derivative; no invented values."""
    dest = np.full((height, width), np.nan, dtype='float32')
    from rasterio.warp import transform_bounds
    if target_crs not in ("EPSG:4326", "EPSG:3857"):
        raise ValueError("Unsupported display projection")
    projected_bounds = transform_bounds("EPSG:4326", target_crs, -126, 24, -66, 50)
    out_transform = from_bounds(*projected_bounds, width, height)
    reproject(array.filled(np.nan).astype('float32'), dest, src_transform=affine,
              src_crs=crs, src_nodata=np.nan, dst_transform=out_transform,
              dst_crs=target_crs, dst_nodata=np.nan, resampling=Resampling.nearest)
    # Diagnostic palette: lower rainfall thresholds are warmer. Not a final UI legend.
    edges = np.array([0.25, .5, .75, 1, 1.5, 2, 2.5, 3, 4, 5])
    colors = np.array([[128,0,38],[189,0,38],[227,26,28],[252,78,42],
        [253,141,60],[254,178,76],[254,217,118],[255,237,160],
        [161,217,155],[65,182,196],[44,127,184]],dtype='uint8')
    valid = np.isfinite(dest)
    rgba = np.zeros((4, *dest.shape), dtype='uint8')
    idx = np.searchsorted(edges, np.nan_to_num(dest / 25.4), side='right')
    rgba[:3] = colors[idx].transpose(2,0,1)
    rgba[:3, ~valid] = 0
    rgba[3] = valid * 255
    with rasterio.open(path, 'w', driver='PNG', width=dest.shape[1], height=dest.shape[0], count=4, dtype='uint8', crs=target_crs, transform=out_transform) as out:
        out.write(rgba)
    return {'bounds_wsen': [-126,24,-66,50], 'crs': target_crs, 'projected_bounds': list(projected_bounds), 'units': 'inches',
            'class_upper_edges': edges.tolist(), 'colors_rgb': colors.tolist(),
            'role': 'diagnostic_display_only', 'resampling': 'nearest'}


def inspect(path, folder):
    fields, summary = {}, {}
    with rasterio.open(path) as src:
        if src.driver != 'GRIB' or src.crs is None:
            raise ValueError('Missing numerical GRIB grid or CRS')
        summary.update({'shape': list(src.shape), 'crs_wkt': src.crs.to_wkt(),
                        'affine': list(src.transform)[:6], 'nodata': src.nodata,
                        'nominal_product_resolution': '5 km',
                        'projected_spacing_metres': [abs(src.transform.a), abs(src.transform.e)],
                        'grid_has_individual_rfc_issue_times': False, 'bands': {},
                        'subcenter_note': 'Hourly g2 uses missing subcenter 255; cycle grb2 uses WPC/HPC subcenter 5.'})
        for band in src.indexes:
            tags = src.tags(band)
            hours, ref, end = band_contract(tags)
            if hours not in HOURS:
                continue
            if hours in fields:
                raise ValueError('Duplicate duration')
            a = checked_array(src.read(band, masked=True))
            fields[hours] = a
            xs, ys = transform('EPSG:4326', src.crs, *zip(*POINTS.values()))
            samples = {}
            for name, x, y in zip(POINTS, xs, ys):
                row, col = src.index(x, y)
                value = None
                if 0 <= row < src.height and 0 <= col < src.width and not np.ma.is_masked(a[row,col]):
                    value = float(a[row,col])
                samples[name] = {'mm': value, 'inches': None if value is None else value / 25.4}
            summary['bands'][str(hours)] = {'source_band': band, 'tags': tags,
                'reference_time': datetime.fromtimestamp(ref, timezone.utc).isoformat(),
                'encoded_period_end': datetime.fromtimestamp(end, timezone.utc).isoformat(),
                'reference_age_hours_at_inspection': (now().timestamp() - ref) / 3600,
                'valid_cells': int(a.count()), 'grid_valid_fraction': float(a.count()/a.size),
                'min_mm': float(a.min()), 'max_mm': float(a.max()), 'samples': samples}
        if set(fields) != set(HOURS):
            raise ValueError('Missing required 1/3/6-hour fields')
        if len({x['reference_time'] for x in summary['bands'].values()}) != 1:
            raise ValueError('Mixed reference cycles')
        # Controlled native numerical derivative: no spatial resampling, mm units.
        numerical = folder / (path.stem + '_native_mm.tif')
        with rasterio.open(numerical, 'w', driver='GTiff', width=src.width, height=src.height,
                           count=3, dtype='float64', crs=src.crs, transform=src.transform,
                           nodata=9999.0, compress='deflate') as out:
            for b, h in enumerate(HOURS, 1):
                out.write(fields[h].filled(9999), b)
                out.set_band_description(b, f'{h}-hour RFC FFG (mm)')
                out.update_tags(b, duration_hours=str(h), units='mm',
                                reference_time=summary['bands'][str(h)]['reference_time'])
        # Verify numerical round trip, including every no-data cell.
        with rasterio.open(numerical) as out:
            for b, h in enumerate(HOURS, 1):
                restored = out.read(b, masked=True)
                if not np.array_equal(restored.mask, fields[h].mask) or not np.array_equal(restored.compressed(), fields[h].compressed()):
                    raise ValueError('Native numerical derivative changed values or mask')
        summary['native_roundtrip_exact'] = True
        summary['preview'] = preview(fields[3], src.crs, src.transform, folder / (path.stem + '_3h_preview.png'))
    return summary, fields


def compare(old_summary, old, new_summary, new):
    if old_summary['shape'] != new_summary['shape'] or old_summary['crs_wkt'] != new_summary['crs_wkt'] or old_summary['affine'] != new_summary['affine']:
        raise ValueError('Cannot compare different numerical grids')
    result = {}
    for h in HOURS:
        a,b = old[h],new[h]
        common = ~(np.ma.getmaskarray(a) | np.ma.getmaskarray(b))
        result[str(h)] = {'mask_changed_cells': int(np.count_nonzero(a.mask != b.mask)),
                         'value_changed_cells': int(np.count_nonzero(a.data[common] != b.data[common])),
                         'max_abs_difference_mm': float(np.max(np.abs(a.data[common] - b.data[common]))) if common.any() else None}
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output-dir', type=Path, required=True)
    ap.add_argument('--snapshot', help='UTC YYYYMMDDHH; otherwise latest listed hourly snapshot')
    args = ap.parse_args()
    folder = args.output_dir / now().strftime('%Y%m%dT%H%M%S%fZ')
    folder.mkdir(parents=True, exist_ok=False)
    report = {'revision': 'h5-numeric-v0.2', 'started_at': now().isoformat(),
              'production_ready': False, 'source': SOURCE, 'snapshots': {}, 'errors': []}
    try:
        raw, meta = download(SOURCE)
        report['directory_request'] = meta
        names = snapshot_names(raw.decode(), now())
        if args.snapshot:
            wanted = '5kmffg_' + datetime.strptime(args.snapshot, '%Y%m%d%H').strftime('%Y%m%d%H') + '.g2'
            names = [n for n in names if n <= wanted]
            if not names or names[-1] != wanted:
                raise ValueError('Requested snapshot is not listed')
        if len(names) < 2:
            raise ValueError('Need at least two listed snapshots for comparison')
        previous = None
        for name in names[-2:]:
            print(f'Downloading numerical snapshot {name}', flush=True)
            raw, request = download(SOURCE + name)
            request['grib_message_count'] = validate_grib(raw)
            path = folder / name
            path.write_bytes(raw)
            summary, fields = inspect(path, folder)
            summary['request'] = request
            summary['snapshot_hour_from_filename'] = name[7:17]
            report['snapshots'][name] = summary
            if previous:
                report['between_snapshots'] = compare(previous[0], previous[1], summary, fields)
            previous = summary, fields
        report['numerical_access_verified'] = True
        report['units_verified'] = 'kg m-2 = mm water; inches = mm / 25.4'
    except Exception as exc:
        report['errors'].append(str(exc))
        report['numerical_access_verified'] = False
    report['completed_at'] = now().isoformat()
    (folder / 'numeric_report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'report': str(folder / 'numeric_report.json'),
                      'numerical_access_verified': report['numerical_access_verified'],
                      'errors': report['errors']}, indent=2), flush=True)
    return 1 if report['errors'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
