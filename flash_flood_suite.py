#!/usr/bin/env python3
"""RRFS and pooled HRRR/RRFS flash-flood products using the shared V3.3 science.

Operational deterministic fields only; never substitute REFS, parallel RRFS,
missing hours, a different grid, or a single model for a 50/50 blend.
Raw/decoded checkpoints are runner-local and are never published to Git.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import gc
import hashlib
import json
from pathlib import Path
import re
import shutil
import tempfile

import numpy as np
from PIL import Image
from pyproj import Transformer

import fetch_hrrr_tle as science
from cam_member_io import Sources, Grid, member_urls, qpf_entry, grib_framing, atomic_npz
import eccodes as ec
import rasterio
import requests

UTC = timezone.utc
SCHEMA = "wpc-flash-flood-suite-v1"
MAX_PACKAGE_BYTES = 32 * 1024**2  # 20 PNGs plus two JSON files, per family
SUITES = {"rrfs": ("RRFS",), "hrrr_rrfs": ("HRRR", "RRFS")}
LAYER_KEYS = tuple(science.LAYER_FILES)


def iso(dt):
    return dt.replace(tzinfo=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def utc(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def layer_files(suite):
    return {k: v.replace("hrrr_", suite + "_", 1) for k, v in science.LAYER_FILES.items()}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def member(family, lag=0):
    return {"id": f"{family.lower()}_lag{lag}", "family": family,
            "lag_hours": lag, "forecast_horizon_hours": 18}


class OperationalSources(Sources):
    def __init__(self, cache_dir, workers=4):
        super().__init__(cache_dir, workers, value_reader=read_native_precip,
                         decode_version='flash-flood-eccodes-v1')

    def probe_index(self, url):
        if url not in self._indexes:
            with requests.get(url+'.idx', timeout=(8,15), stream=True) as response:
                response.raise_for_status()
                raw = bytearray()
                for chunk in response.iter_content(64*1024):
                    raw.extend(chunk)
                    if len(raw) > 2_000_000: raise ValueError('Unbounded discovery index')
                self._indexes[url] = bytes(raw).decode()
        return self._indexes[url]

    def index(self, url):
        if "/para/" in url:
            raise ValueError("Parallel RRFS is excluded from operational products")
        return super().index(url)

    def fetch_cumulative(self, init, fxx):
        path = self.cache/'rrfs-subh-endpoint-v2'/init.strftime('%Y%m%d%H')/f'f{fxx:03d}.npz'
        if path.is_file():
            with np.load(path, allow_pickle=False) as z:
                values, meta = z['values'], json.loads(str(z['metadata'].item()))
            self.admit_grid(meta['grid'])
            if meta['init_utc'] != init.isoformat() or meta['fxx'] != fxx:
                raise ValueError('Cumulative checkpoint identity mismatch')
            return values, meta
        errors = []
        for url in subhourly_urls(init, fxx):
            temporary = None
            try:
                byte_range = cumulative_entry(self.index(url), init, fxx)
                raw, transfer = self.get(url, max_bytes=16_000_000, byte_range=byte_range)
                if grib_framing(raw) != 1:
                    raise ValueError('Expected one cumulative endpoint message')
                with tempfile.NamedTemporaryFile(dir=self.cache, suffix='.grib2', delete=False) as f:
                    f.write(raw); temporary = Path(f.name)
                with self._decode_lock:
                    with open(temporary, 'rb') as f:
                        gid = ec.codes_grib_new_from_file(f)
                        try:
                            expected = {'dataDate':int(init.strftime('%Y%m%d')), 'dataTime':init.hour*100,
                                        'discipline':0, 'parameterCategory':1, 'parameterNumber':8,
                                        'stepType':'accum', 'typeOfLevel':'surface',
                                        'typeOfGeneratingProcess':2, 'generatingProcessIdentifier':134}
                            observed = {k:ec.codes_get(gid,k) for k in expected}
                            unit = ec.codes_get(gid,'stepUnits')
                            factor = {0:60,1:3600,13:1}.get(unit)
                            if observed != expected or factor is None or ec.codes_get(gid,'startStep')*factor != 0 or ec.codes_get(gid,'endStep')*factor != fxx*3600 or ec.codes_get(gid,'units') not in ('kg m**-2','mm'):
                                raise ValueError('Cumulative RRFS GRIB identity or exact interval mismatch')
                            quantum = 2.**ec.codes_get(gid,'binaryScaleFactor') * 10.**(-ec.codes_get(gid,'decimalScaleFactor'))
                            observed.update(start_seconds=0,end_seconds=fxx*3600,packing_quantum_mm=quantum)
                        finally: ec.codes_release(gid)
                    with rasterio.open(temporary) as src:
                        if src.count != 1 or src.driver != 'GRIB' or src.tags(1).get('GRIB_UNIT') != '[kg/(m^2)]':
                            raise ValueError('Unexpected cumulative precipitation raster')
                        grid = Grid.from_source(src)
                        if self.grid is None: self.grid = grid
                        if not self.grid.matches(src): raise ValueError('RRFS native grid differs')
                        values = read_native_precip(temporary)
                        if not np.isfinite(values).all() or np.any(values < 0) or np.any(values > 4000):
                            raise ValueError('Invalid cumulative rainfall values')
                meta = {'init_utc':init.isoformat(), 'fxx':fxx, 'source':transfer,
                        'validated_grib':observed, 'grid':self.grid.metadata()}
                atomic_npz(path, values=values, metadata=np.array(json.dumps(meta)))
                return values, meta
            except Exception as exc:
                errors.append(f'{url}: {exc}')
            finally:
                if temporary is not None: temporary.unlink(missing_ok=True)
        raise RuntimeError('Cumulative RRFS endpoint unavailable: '+'; '.join(errors))

    def admit_grid(self, meta):
        grid = Grid(tuple(meta['shape']), meta['crs_wkt'], tuple(meta['affine']))
        with self._decode_lock:
            if self.grid is None: self.grid = grid
            elif self.grid.identifier != grid.identifier: raise ValueError('Checkpoint native grid differs')

    def fetch_hour(self, identity, reference_init, valid_end):
        init = reference_init-timedelta(hours=identity['lag_hours'])
        if identity['family'] != 'RRFS' or init.hour % 3 == 0:
            return super().fetch_hour(identity, reference_init, valid_end)
        fxx = int((valid_end-init).total_seconds()/3600)
        current, cm = self.fetch_cumulative(init, fxx)
        previous, pm = (self.fetch_cumulative(init, fxx-1) if fxx > 1 else (np.zeros_like(current), None))
        quantum = cm['validated_grib']['packing_quantum_mm'] + (pm['validated_grib']['packing_quantum_mm'] if pm else 0)
        values, roundoff = cumulative_difference(previous, current, quantum + 1e-6)
        meta = {'decode_version':'rrfs-subh-hourly-v1', 'family':'RRFS', 'perturbation':'control',
                'init_utc':init.isoformat(), 'native_forecast_hour':fxx,
                'valid_start_utc':(valid_end-timedelta(hours=1)).isoformat(), 'valid_end_utc':valid_end.isoformat(),
                'units':'mm', 'grid':self.grid.metadata(), 'source':cm['source'],
                'validated_grib':cm['validated_grib'], 'hourly_method':'checked difference of exact whole-hour cumulative endpoints',
                'cumulative_endpoints':[pm, cm], 'packing_roundoff':roundoff}
        return values, meta


def subhourly_urls(init, fxx):
    relative = f'rrfs.{init:%Y%m%d}/{init:%H}/rrfs.t{init:%H}z.2dfld.3km.subh.f{fxx:03d}.conus.grib2'
    return ['https://noaa-rrfs-ops-pds.s3.amazonaws.com/'+relative,
            'https://nomads.ncep.noaa.gov/pub/data/nccf/com/rrfs/prod/'+relative]


def read_native_precip(path):
    """Match the original cfgrib/ecCodes float32 reader, in north-up order.

    GDAL and ecCodes can round a decoded packed depth by a float32 ULP.
    Use the original HRRR decoder for both models; no depth interpolation.
    """
    with open(path,'rb') as stream:
        gid = ec.codes_grib_new_from_file(stream)
        try:
            if any(ec.codes_get(gid,k) for k in ('iScansNegatively','jPointsAreConsecutive','alternativeRowScanning')):
                raise ValueError('Unqualified precipitation grid scan order')
            shape = (ec.codes_get(gid,'Nj'),ec.codes_get(gid,'Ni'))
            values = ec.codes_get_values(gid).reshape(shape).astype('float32')
            if ec.codes_get(gid,'jScansPositively'): values = values[::-1].copy()
            return values
        finally: ec.codes_release(gid)


def cumulative_entry(text, init, fxx):
    # Select only the exact whole-hour endpoint, excluding the three quarter-
    # hour records in the same file and excluding instantaneous rain rates.
    rows = []
    for line in text.splitlines():
        parts = line.split(':')
        if len(parts) >= 6 and parts[1].isdigit(): rows.append((int(parts[1]), parts))
    matches = []
    for i,(start,parts) in enumerate(rows[:-1]):
        if not {'APCP','surface',f'd={init:%Y%m%d%H}'}.issubset(parts): continue
        match = re.fullmatch(r'0-(\d+) (hour|min) acc fcst', parts[5])
        if match and int(match[1]) * (60 if match[2] == 'hour' else 1) == fxx*60:
            matches.append((start, rows[i+1][0]-1))
    if len(matches) != 1 or matches[0][1] < matches[0][0]:
        raise ValueError('Missing or ambiguous exact cumulative whole-hour APCP endpoint')
    return matches[0]


def cumulative_difference(previous, current, tolerance):
    if previous.shape != current.shape or not np.isfinite(previous).all() or not np.isfinite(current).all():
        raise ValueError('Both cumulative endpoints must be complete on the identical native grid')
    delta = current.astype('float64')-previous.astype('float64')
    if np.any(delta < -tolerance) or np.any(delta > 1000):
        raise ValueError('Cumulative rainfall reset or invalid one-hour increment')
    negatives = delta < 0
    evidence = {'negative_cells':int(negatives.sum()), 'minimum_increment_mm':float(delta.min()),
                'permitted_packing_error_mm':float(tolerance), 'rule':'only negatives within summed endpoint quantization steps become zero; larger decreases are rejected'}
    return np.maximum(delta,0).astype('float32'), evidence


def ready(sources, family, cycle, fxx):
    # Discovery uses the same exact one-hour selector as the actual transfer.
    subh = family == 'RRFS' and cycle.hour % 3 != 0
    for url in subhourly_urls(cycle,fxx) if subh else member_urls(member(family), cycle, fxx):
        if "/para/" in url:
            continue
        try:
            (cumulative_entry if subh else qpf_entry)(sources.probe_index(url), cycle, fxx)
            return True
        except Exception:
            pass
    return False


def find_cycle(sources, families, tle, now=None, lookback=8):
    now = (now or datetime.now(UTC)).replace(minute=0, second=0, microsecond=0)
    # A six-run TLE must contain only operational RRFS cycles after implementation.
    operational_start = datetime(2026, 11, 3, 12, tzinfo=UTC)
    for hours in range(lookback + 1):
        anchor = now - timedelta(hours=hours)
        print(f"Checking {'/'.join(families)} {'TLE' if tle else 'diagnostics'} {iso(anchor)}", flush=True)
        identities = [(f, lag) for f in families for lag in range(6 if tle else 1)]
        if "RRFS" in families and anchor-timedelta(hours=5 if tle else 0) < operational_start:
            continue
        with ThreadPoolExecutor(max_workers=4) as pool:
            flags = list(pool.map(lambda item: ready(sources, item[0], anchor-timedelta(hours=item[1]), 12+item[1]), identities))
        if all(flags):
            print(f"{'/'.join(families)} {'TLE' if tle else 'diagnostics'} anchor {iso(anchor)}", flush=True)
            return anchor
    raise RuntimeError(f"No complete {'/'.join(families)} {'TLE' if tle else 'diagnostic'} cycle within {lookback} hours")


def grid_coordinates(grid):
    rows, cols = grid.shape
    a, b, c, d, e, f = grid.affine
    if b or d or abs(a-3000) > 0.1 or abs(abs(e)-3000) > 0.1:
        raise ValueError("V3.3 neighborhood requires a matching native 3-km grid")
    x, y = np.meshgrid(c+(np.arange(cols)+0.5)*a, f+(np.arange(rows)+0.5)*e)
    lon, lat = Transformer.from_crs(grid.crs, "EPSG:4326", always_xy=True).transform(x, y)
    return lat, lon


def fetch_member(sources, family, anchor, lag=0):
    identity = member(family, lag)
    times = [anchor+timedelta(hours=h) for h in range(1, 13)]
    with ThreadPoolExecutor(max_workers=sources.workers) as pool:
        rows = list(pool.map(lambda t: sources.fetch_hour(identity, anchor, t), times))
    arrays, evidence = zip(*rows)
    qpf = (np.stack(arrays).astype(np.float64) / 25.4).astype(np.float32)
    # CONUS has no missing hourly rainfall cells. Treat a missing decoded cell
    # as an incomplete member rather than a dry event in the consensus.
    if qpf.shape[0] != 12 or not np.isfinite(qpf).all() or np.any(qpf < 0):
        raise ValueError("Incomplete or invalid hourly QPF member; no zero fill permitted")
    return {"family": family, "run_dt": anchor-timedelta(hours=lag),
            "lag_hours": lag, "fxx": science.aligned_member_fxx(lag), "qpf": qpf,
            "sources": [dict(m, member=identity["id"]) for m in evidence]}


def diagnostic_fields(qpfs, ffg):
    if len(qpfs) not in (1, 2) or any(q.shape != qpfs[0].shape for q in qpfs):
        raise ValueError("Diagnostics require one or two matching complete models")
    qpf = qpfs[0] if len(qpfs) == 1 else (qpfs[0]+qpfs[1])*np.float32(0.5)
    ratios = science.compute_run_ratio_fields(qpf, *ffg)
    events = (np.isfinite(ratios["combined"]) & (ratios["combined"] >= 1)).astype(np.float32)
    return {"hrrr_max_ratio": science.neighborhood_max(ratios["combined"]).astype(np.float32),
            "hrrr_ffg_coverage": science.neighborhood_coverage_fraction(events).astype(np.float32)}


def compute_fields(records, ffg):
    families = sorted(set(r["family"] for r in records))
    if len(records) != 6*len(families) or families not in (["RRFS"], ["HRRR", "RRFS"]):
        raise ValueError("Expected six complete cycles per model")
    for family in families:
        if sorted(r["lag_hours"] for r in records if r["family"] == family) != list(range(6)):
            raise ValueError("Each model must contribute exactly lags zero through five")
    for r in records:
        r["ratios"] = {k: np.asarray(v, dtype=np.float32) for k, v in
                       science.compute_run_ratio_fields(r["qpf"], *ffg).items()}
    latest = [i for i, r in enumerate(records) if r["lag_hours"] < 3]
    prior = [i for i, r in enumerate(records) if r["lag_hours"] >= 3]
    fields = science.compute_tle_fields(records, ffg, latest, prior)
    # The shared aggregation retains hourly events for HRRR compatibility;
    # release them here before the high-resolution raster rendering stage.
    for r in records:
        r.pop("hourly_neigh_ffg_event", None)
        r.pop("ratios", None)
    return fields


def render_style(key, count):
    if key in ("hrrr_max_ratio", "median_ratio"):
        return science.RATIO_LEVELS, science.RATIO_COLORS, 0.75
    if key == "hrrr_ffg_coverage":
        return science.COVERAGE_LEVELS, science.COVERAGE_COLORS, 1.0
    if key == "run_change":
        return [0.5, 1.5, 2.5, 3.5], science.RUN_CHANGE_COLORS, 0.5
    group = key in ("prior3", "latest3")
    n = count//2 if group else count
    minimum = n//3 if key.startswith("evolution_") else 1
    # Repeat each original hue for two adjacent 1/12 bins. Six colors retain
    # the established visual language; the legend shows the exact count ranges.
    colors = (science.FREQ_COLORS_3 if group else science.FREQ_COLORS_6)
    if count == 12:
        colors = [c for c in colors for _ in (0, 1)]
    return science.frequency_levels(n, minimum), colors[minimum-1:], 100*minimum/n-0.1


def retained_current(root, suite, anchor, diag):
    try:
        validate_package(root, suite, datetime.now(UTC))
        m = json.loads((root/f"{suite}_tle_manifest.json").read_text())
        return m["latest_cycle_utc"] == iso(anchor) and m["diagnostic_cycle_utc"] == iso(diag)
    except (ValueError, OSError, KeyError):
        return False


def build_suite(root, suite, sources, force=False):
    families = SUITES[suite]
    anchor = find_cycle(sources, families, tle=True)
    diag = find_cycle(sources, families, tle=False)
    if not force and retained_current(root, suite, anchor, diag):
        print(f"{suite}: complete current package retained without churn", flush=True)
        return
    first = fetch_member(sources, families[0], anchor)
    lat, lon = grid_coordinates(sources.grid)
    science.lats, science.lons = lat, lon
    ffg_result = science.fetch_and_align_ffg(anchor.replace(tzinfo=None), lat, lon)
    ffg, ffg_dt = ffg_result[:3], ffg_result[3]
    diag_ffg_result = (ffg_result if diag == anchor else
                       science.fetch_and_align_ffg(diag.replace(tzinfo=None), lat, lon))
    diagnostic_members = [first if family == families[0] and diag == anchor else
                          fetch_member(sources, family, diag) for family in families]
    fields = diagnostic_fields([r["qpf"] for r in diagnostic_members], diag_ffg_result[:3])
    diag_sources = [row for r in diagnostic_members for row in r["sources"]]
    del diagnostic_members
    records = []
    for family in families:
        for lag in range(6):
            rec = first if family == families[0] and lag == 0 else fetch_member(sources, family, anchor, lag)
            records.append(rec)
    fields.update(compute_fields(records, ffg))
    count = len(records)
    # Source hashes, valid intervals, encoded identity and download receipts are
    # retained in metadata; raw rainfall is a temporary execution checkpoint.
    evidence = [row for r in records for row in r["sources"]]
    identity = [{"family": r["family"], "cycle_utc": iso(r["run_dt"]),
                 "lag_hours": r["lag_hours"], "fxx_start": r["fxx"][0],
                 "fxx_end": r["fxx"][-1]} for r in records]
    del records, first
    gc.collect()
    files = layer_files(suite)
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f"{suite}-stage-", dir=root.parent) as tmp:
        staging = Path(tmp)
        for key, filename in files.items():
            levels, colors, minimum = render_style(key, count)
            science.render_overlay(fields.pop(key), staging/filename, levels, colors, mask_below=minimum)
            print(f"{suite}: rendered {filename}", flush=True)
            gc.collect()
        layers = {k: {"file": name, "sha256": sha(staging/name)} for k, name in files.items()}
        meta = {
            "schema": SCHEMA, "suite": suite, "algorithm_version": "3.3",
            "experimental": True, "complete": True,
            "latest_cycle_utc": iso(anchor), "common_valid_start_utc": iso(anchor),
            "common_valid_end_utc": iso(anchor+timedelta(hours=12)),
            "diagnostic_cycle_utc": iso(diag), "diagnostic_valid_start_utc": iso(diag),
            "diagnostic_valid_end_utc": iso(diag+timedelta(hours=12)),
            "diagnostic_ffg_analysis_utc": iso(diag_ffg_result[3]),
            "ffg_analysis_utc": iso(ffg_dt), "ffg_age_hours": (anchor.replace(tzinfo=None)-ffg_dt).total_seconds()/3600,
            "diagnostic_ffg_age_hours": (diag.replace(tzinfo=None)-diag_ffg_result[3]).total_seconds()/3600,
            "families": list(families), "family_weights": {f: 1/len(families) for f in families},
            "members_available": count, "cycles_per_family": 6, "members": identity,
            "latest_group_members": count//2, "prior_group_members": count//2,
            "run_change_minimum_members": 2*count//6,
            "evolution_minimum_members": count//3,
            "diagnostic_method": "hourly RRFS QPF" if count == 6 else "50/50 mean of same-cycle, same-hour HRRR/RRFS QPF before V3.3 diagnostics",
            "rrfs_hourly_input_policy": "Direct incremental APCP at three-hourly cycles; exact whole-hour cumulative endpoint differences from subh files at other hourly cycles. Only negative increments within the summed endpoint packing quantum are zeroed; larger decreases fail.",
            "tle_method": "equal member weights; six complete hourly cycles per family; no averaging of member rainfall",
            "member_frequency_note": "Member frequency / consensus; NOT calibrated probability.",
            "neighborhood_km": science.NEIGHBORHOOD_KM,
            "grid": sources.grid.metadata(), "grid_id": sources.grid.identifier,
            "bounds": science.LEAFLET_BOUNDS, "image_crs": "EPSG:3857",
            "render_width_px": science.RENDER_WIDTH_PX,
            "render_height_px": science._mercator_render_geometry()[1],
            "render_dpi": science.RENDER_DPI, "display_render_version": science.DISPLAY_RENDER_VERSION,
            "display_field_smoothing": False, "generated_utc": iso(datetime.now(UTC)),
            "sources": {"tle_member_hours": evidence, "diagnostic_member_hours": diag_sources},
            "ffg_files": [{"nominal_analysis_utc":iso(dt),
                           "file":f"5kmffg_{dt:%Y%m%d%H}.grib2",
                           "sha256":sha(science.FFG_CACHE/f"{dt:%Y%m%d}"/f"5kmffg_{dt:%Y%m%d%H}.grib2")}
                          for dt in sorted(set((ffg_dt,diag_ffg_result[3])))],
            "layers": layers,
        }
        science.write_json(staging/f"{suite}_tle_metadata.json", meta)
        manifest = {k: v for k, v in meta.items() if k not in ("sources", "grid", "members", "ffg_files")}
        manifest.update(metadata_file=f"{suite}_tle_metadata.json", metadata_sha256=sha(staging/f"{suite}_tle_metadata.json"))
        science.write_json(staging/f"{suite}_tle_manifest.json", manifest)
        validate_package(staging, suite, datetime.now(UTC))
        for path in staging.iterdir():
            shutil.copy2(path, root/path.name)
    print(f"{suite}: complete {count}-member package ready", flush=True)


def validate_package(root, suite, now=None):
    root = Path(root)
    now = now or datetime.now(UTC)
    try:
        manifest = json.loads((root/f"{suite}_tle_manifest.json").read_text())
        meta_path = root/f"{suite}_tle_metadata.json"
        meta = json.loads(meta_path.read_text())
        count = len(SUITES[suite])*6
        required = ("schema", "suite", "algorithm_version", "latest_cycle_utc", "diagnostic_cycle_utc", "common_valid_start_utc", "common_valid_end_utc", "diagnostic_valid_start_utc", "diagnostic_valid_end_utc", "generated_utc", "layers")
        if any(meta.get(k) != manifest.get(k) for k in required) or manifest.get("metadata_sha256") != sha(meta_path):
            raise ValueError("Mixed metadata/manifest generation or checksum mismatch")
        if meta.get("schema") != SCHEMA or meta.get("suite") != suite or meta.get("algorithm_version") != "3.3" or meta.get("complete") is not True:
            raise ValueError("Unexpected experimental suite contract")
        anchor, diag = utc(meta["latest_cycle_utc"]), utc(meta["diagnostic_cycle_utc"])
        if anchor > now+timedelta(minutes=15) or diag > now+timedelta(minutes=15):
            raise ValueError("Forecast cycle is in the future")
        if (utc(meta["common_valid_start_utc"]) != anchor or utc(meta["common_valid_end_utc"]) != anchor+timedelta(hours=12)
                or utc(meta["diagnostic_valid_start_utc"]) != diag or utc(meta["diagnostic_valid_end_utc"]) != diag+timedelta(hours=12)):
            raise ValueError("Incorrect 12-hour valid interval")
        if now >= min(utc(meta["common_valid_end_utc"]), utc(meta["diagnostic_valid_end_utc"])):
            raise ValueError("Retained package has expired")
        expected = {(f, lag) for f in SUITES[suite] for lag in range(6)}
        if (meta.get("families") != list(SUITES[suite]) or meta.get("family_weights") != {f:1/len(SUITES[suite]) for f in SUITES[suite]}
                or meta.get("run_change_minimum_members") != count//3 or meta.get("evolution_minimum_members") != count//3
                or meta.get("render_width_px") != 6000 or meta.get("render_dpi") != 600 or meta.get("neighborhood_km") != 40):
            raise ValueError("Incorrect weights, thresholds or shared science/render settings")
        for key, ref in (("ffg_analysis_utc",anchor),("diagnostic_ffg_analysis_utc",diag)):
            if not timedelta(0) <= ref-utc(meta[key]) < timedelta(hours=48):
                raise ValueError("FFG must come from the unchanged V3.3 at-or-before-reference policy")
        members = meta.get("members", [])
        if meta.get("members_available") != count or len(members) != count or {(r["family"], r["lag_hours"]) for r in members} != expected:
            raise ValueError("Missing or unbalanced model membership")
        for r in members:
            if utc(r["cycle_utc"]) != anchor-timedelta(hours=r["lag_hours"]) or r["fxx_start"] != 1+r["lag_hours"] or r["fxx_end"] != 12+r["lag_hours"]:
                raise ValueError("Member valid-time alignment failed")
        for label, ref in (("tle", anchor), ("diagnostic", diag)):
            rows = meta["sources"][f"{label}_member_hours"]
            expected_hours = {(f, lag, h) for f in SUITES[suite] for lag in range(6 if label == "tle" else 1) for h in range(1, 13)}
            actual = set()
            for row in rows:
                cycle = utc(row["init_utc"])
                lag = int((ref-cycle).total_seconds()/3600)
                hour = row["native_forecast_hour"]-lag
                actual.add((row["family"], lag, hour))
                if (utc(row["valid_end_utc"]) != ref+timedelta(hours=hour)
                        or utc(row["valid_start_utc"]) != ref+timedelta(hours=hour-1)
                        or row["grid"] != meta["grid"] or row["units"] != "mm"
                        or row["validated_grib"]["generatingProcessIdentifier"] != {"HRRR":83,"RRFS":134}[row["family"]]
                        or "/para/" in row["source"]["url"] or not re.fullmatch('[0-9a-f]{64}',row["source"]["sha256"])):
                    raise ValueError("Invalid precipitation provenance or time interval")
            if len(rows) != len(expected_hours) or actual != expected_hours:
                raise ValueError("Incomplete source hour inventory")
        if set(meta["layers"]) != set(LAYER_KEYS):
            raise ValueError("Expected all 20 synchronized overlays")
        for key, filename in layer_files(suite).items():
            item = meta["layers"][key]
            if item["file"] != filename or sha(root/filename) != item["sha256"]:
                raise ValueError(f"Incorrect raster or checksum: {key}")
            with Image.open(root/filename) as image:
                if image.size != science._mercator_render_geometry()[:2] or image.mode != "RGBA":
                    raise ValueError(f"Incorrect render contract: {key}")
                image.verify()
            with Image.open(root/filename) as image:
                image.load()
        paths = [root/name for name in layer_files(suite).values()] + [meta_path, root/f"{suite}_tle_manifest.json"]
        if sum(p.stat().st_size for p in paths) > MAX_PACKAGE_BYTES:
            raise ValueError("Suite exceeds 32-MiB published payload budget")
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Incomplete {suite} package: {exc}") from exc
    return meta


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=(*SUITES, "all"), default="all")
    parser.add_argument("--output-dir", type=Path, default=Path("static"))
    parser.add_argument("--cache-dir", type=Path, default=Path(".cache/flash_flood"))
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    sources = OperationalSources(args.cache_dir, workers=4)
    for suite in SUITES if args.suite == "all" else (args.suite,):
        if not args.validate_only:
            build_suite(args.output_dir, suite, sources, args.force)
        meta = validate_package(args.output_dir, suite)
        print(f"{suite} PASS: {meta['members_available']} members; valid through {meta['common_valid_end_utc']}", flush=True)


if __name__ == "__main__":
    main()
