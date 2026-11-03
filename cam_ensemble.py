"""SPC REFS / OMD REFS dashboard CAM products, common checked windows.

SPC REFS is WPC experimental processing of the ten-member SPC configuration.
OMD REFS retains the native producer neighborhood probabilities. The two
configurations share members and are not independent ensembles.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import gc
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import shutil
import tempfile
import time

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import BoundaryNorm, ListedColormap
import numpy as np
from pyproj import Transformer
from rasterio.transform import xy

from cam_member_io import Sources, Grid, atomic_json, atomic_npz, load_ffg, ffg_on_member_grid
from cam_omd import OMDReader
from cam_probability import WindowAccumulator, expected_ffg_durations, blend_maxima

UTC = timezone.utc
LOG = logging.getLogger(__name__)
SCHEMA = "wpc-spc-omd-cam-v1"
QPF_IN = (.5, 1, 2, 3)
PROBABILITY_LEVELS = (10, 30, 50, 70, 90, 100.0001)
QPF_COLORS = ("#ffffcc", "#a1dab4", "#41b6c4", "#2c7fb8", "#253494")
FFG_COLORS = ("#ffffb2", "#fecc5c", "#fd8d3c", "#f03b20", "#bd0026")


def iso(value):
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def windows_for(kind, init):
    if init.tzinfo is None or init.utcoffset() != timedelta(0) or init.hour not in (0, 6, 12, 18) or any((init.minute, init.second, init.microsecond)):
        raise ValueError("Use a whole 00/06/12/18Z UTC initialization")
    if kind == "cam":
        return {"3h_to_9h": (3, 9), "9h_to_15h": (9, 15)}
    if kind != "ero":
        raise ValueError("Unknown CAM product")
    start = max(0, 12-init.hour)
    end = 36-init.hour
    return {"ero": (start, end)}


def read_members():
    p = Path(__file__).with_name("cam_spc_members.json")
    profile = json.loads(p.read_text())
    members = profile["members"]
    identity = [(m["family"], m["perturbation"], m["lag_hours"]) for m in members]
    expected = {("HRRR", "control", h) for h in (0, 6, 12)} | {
        ("RRFS", "control", h) for h in (0, 6, 12)} | {
        ("RRFS_ENS", f"m{n:03d}", 0) for n in (1, 2, 3, 5)}
    if len(identity) != 10 or set(identity) != expected or any(m["weight"] != 1 for m in members):
        raise ValueError("The initial dashboard contract requires the documented ten equal-weight SPC members")
    return members


def load_cycle_ffg(sources, init):
    """Freeze the freshest official FFG actually published at/before model init.

    A nominal 12Z filename posted at 12:38Z is not an as-of-12Z input. The
    older 11Z snapshot is eligible if its publication and reference are fresh.
    The notebook's checked duration/value decoder is reused unchanged.
    """
    folder = sources.cache / "cycle-ffg-v1" / init.strftime("%Y%m%d%H")
    path, meta_path = folder / "ffg.npz", folder / "metadata.json"
    if path.exists() and meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text())
            if meta["asof_model_init_utc"] != iso(init):
                raise ValueError("Cycle FFG cache identity mismatch")
            published = parsedate_to_datetime(meta["source"]["http_last_modified"]).astimezone(UTC)
            snapshot = datetime.fromisoformat(meta["snapshot_time_utc"])
            reference = datetime.fromisoformat(meta["reference_time_utc"])
            if published > init or not timedelta(0) <= init-snapshot < timedelta(hours=3) or not timedelta(0) <= init-reference < timedelta(hours=9):
                raise ValueError("Unqualified cached FFG timing")
            with np.load(path, allow_pickle=False) as z:
                fields = {d: z[f"ffg_{d}"] for d in (1, 3, 6)}
            g = meta["grid"]
            grid = Grid(tuple(g["shape"]), g["crs_wkt"], tuple(g["affine"]))
            if any(a.shape != grid.shape or np.isinf(a).any() or not np.isfinite(a).any() or np.any(a[np.isfinite(a)] <= 0)
                   for a in fields.values()):
                raise ValueError("Invalid cached FFG values")
            meta["from_cycle_cache"] = True
            return fields, grid, meta
        except Exception as exc:
            LOG.warning("Discarding unusable cycle FFG checkpoint: %s", exc)
    errors = []
    for lag in range(3):
        snapshot = (init-timedelta(hours=lag)).strftime("%Y%m%d%H")
        try:
            fields, grid, meta = load_ffg(sources, init, snapshot=snapshot)
            modified = meta["source"].get("http_last_modified")
            if not modified or parsedate_to_datetime(modified).astimezone(UTC) > init:
                raise ValueError("FFG publication was later than model initialization, or cannot be verified")
            meta.update(asof_model_init_utc=iso(init), from_cycle_cache=False,
                        policy="fresh official snapshot demonstrably published by model initialization; frozen for this cycle")
            folder.mkdir(parents=True, exist_ok=True)
            atomic_npz(path, **{f"ffg_{d}": a for d, a in fields.items()})
            atomic_json(meta_path, meta)
            return fields, grid, meta
        except Exception as exc:
            errors.append(f"{snapshot}: {exc}")
    raise RuntimeError("No qualified cycle-time FFG snapshot: " + "; ".join(errors))


def select_cycle(kind, sources, omd, members, now, pinned=None):
    newest = pinned or now.replace(hour=now.hour//6*6, minute=0, second=0, microsecond=0)
    errors = []
    for lag in range(1 if pinned else 4):
        init = newest-timedelta(hours=lag*6)
        windows = windows_for(kind, init)
        start = min(a for a, b in windows.values()); end = max(b for a, b in windows.values())
        if init+timedelta(hours=end) <= now:
            continue
        try:
            # Sources.preflight checks every member's native lead/horizon and
            # terminal APCP identity. All interior hours are checked in the run.
            class Period:
                pass
            period = Period(); period.end = init+timedelta(hours=end)
            omd_probe = omd.probe(init, end)
            preflight = sources.preflight(members, init, period)
            LOG.info("Selected aligned SPC/OMD suite %s; all %d member terminal hours present", iso(init), len(members))
            return init, windows, {"spc": preflight, "omd": omd_probe}
        except Exception as exc:
            errors.append(f"{iso(init)}: {exc}")
            LOG.warning("Suite not ready: %s", errors[-1])
    raise RuntimeError("No complete aligned SPC/OMD suite: " + " | ".join(errors))


def update_peak(peak, complete, value):
    if peak is None:
        peak = np.asarray(value, np.float32).copy()
        complete = np.isfinite(value)
    else:
        np.fmax(peak, value, out=peak)
        complete &= np.isfinite(value)
    return peak, complete


def compact_hour(member, meta):
    return {"member": member["id"], "family": meta["family"],
            "perturbation": meta["perturbation"], "init_utc": meta["init_utc"],
            "native_forecast_hour": meta["native_forecast_hour"],
            "valid_start_utc": meta["valid_start_utc"], "valid_end_utc": meta["valid_end_utc"],
            "url": meta["source"]["url"], "sha256": meta["source"]["sha256"],
            "from_cache": meta["from_cache"], "transferred_bytes": meta["transferred_bytes"]}


def compute(kind, init, windows, sources, omd, members, native_ffg, ffg_grid):
    results, hourly_sources, contracts = {}, [], {}
    weights = [m["weight"] for m in members]
    grid = None
    for label, (start, end) in windows.items():
        LOG.info("Calculating %s: %s to %s", label, iso(init+timedelta(hours=start)), iso(init+timedelta(hours=end)))
        acc = None; omd_qpf = omd_ffg = q_known = f_known = None
        with ThreadPoolExecutor(max_workers=sources.workers) as pool:
            for fxx in range(start+1, end+1):
                valid_end = init+timedelta(hours=fxx)
                fetched = list(pool.map(lambda m: sources.fetch_hour(m, init, valid_end), members))
                values = []
                for member, (qpf, meta) in zip(members, fetched):
                    if (meta["valid_start_utc"], meta["valid_end_utc"]) != (
                        (valid_end-timedelta(hours=1)).isoformat(), valid_end.isoformat()):
                        raise ValueError("Cached member valid-hour mismatch")
                    hourly_sources.append(compact_hour(member, meta)); values.append(qpf)
                if grid is None:
                    grid = sources.grid
                    mapped_ffg = ffg_on_member_grid(native_ffg, ffg_grid, grid)
                if acc is None:
                    acc = WindowAccumulator(start, end, weights, mapped_ffg, grid.spacing)
                acc.add(fxx, np.stack(values))
                del fetched, values, qpf
                prob, _ = omd.fetch(init, fxx, "prob", grid=grid)
                cube = np.stack([prob[mm] for mm in (12.7, 25.4, 50.8, 76.2)])
                omd_qpf, q_known = update_peak(omd_qpf, q_known, cube)
                durations = expected_ffg_durations(fxx, start)
                ffg, _ = omd.fetch(init, fxx, "ffri", durations, grid)
                for d in durations:
                    omd_ffg, f_known = update_peak(omd_ffg, f_known, ffg[d])
                del prob, cube, ffg
                LOG.info("%s f%02d checked: 10/10 hourly members; OMD QPF + FFG %s", label, fxx, durations)
        spc = acc.finish(); del acc
        omd_qpf[~q_known] = np.nan; omd_ffg[~f_known] = np.nan
        native = {"QPF": omd_qpf, "FFG_MAX": omd_ffg}
        results[label] = {"spc_refs": spc, "omd_refs": native,
                          "super": {key: blend_maxima(spc[key], native[key]) for key in spc}}
        contracts[label] = {"valid_start_utc": iso(init+timedelta(hours=start)),
                            "valid_end_utc": iso(init+timedelta(hours=end)),
                            "forecast_hours": list(range(start+1, end+1)),
                            "ffg_slots": [{"forecast_hour": f, "duration_hours": d}
                                          for f in range(start+1, end+1)
                                          for d in expected_ffg_durations(f, start)]}
        gc.collect()
    return results, grid, hourly_sources, contracts


def projected_coordinates(grid):
    rows, cols = np.indices(grid.shape)
    xx = grid.affine[0]*(cols+.5)+grid.affine[2]
    yy = grid.affine[4]*(rows+.5)+grid.affine[5]
    lon, lat = Transformer.from_crs(grid.crs, "EPSG:4326", always_xy=True).transform(xx, yy)
    xw, yw = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True).transform(lon, lat)
    bounds = [[float(np.nanmin(lat)), float(np.nanmin(lon))],
              [float(np.nanmax(lat)), float(np.nanmax(lon))]]
    return xw, yw, bounds


def render(kind, products, grid, folder, dpi=600):
    xw, yw, bounds = projected_coordinates(grid)
    extents = (np.nanmin(xw), np.nanmax(xw), np.nanmin(yw), np.nanmax(yw))
    files = []
    for label, suites in products.items():
        for model, values in suites.items():
            specs = [("FFG_MAX", None, values["FFG_MAX"], FFG_COLORS)] + [
                ("QPF", q, values["QPF"][i], QPF_COLORS) for i, q in enumerate(QPF_IN)]
            for parameter, threshold, data, colors in specs:
                if kind == "cam":
                    name = (f"cam_ffg_{label}_{model}.png" if parameter == "FFG_MAX" else
                            f"cam_qpf_{label}_{threshold:g}_inch_{model}.png")
                else:
                    name = (f"ero_ffg_{model}.png" if parameter == "FFG_MAX" else
                            f"ero_qpf_{threshold:g}_inch_{model}.png")
                fig = plt.figure(figsize=(10, 6), dpi=dpi, frameon=False)
                ax = fig.add_axes([0, 0, 1, 1]); ax.set_axis_off()
                cmap = ListedColormap(colors)
                masked = np.ma.masked_invalid(np.where(data >= 10, data, np.nan))
                ax.contourf(xw, yw, masked, levels=PROBABILITY_LEVELS,
                            cmap=cmap, norm=BoundaryNorm(PROBABILITY_LEVELS, 5),
                            alpha=.65, antialiased=True)
                ax.set_xlim(extents[:2]); ax.set_ylim(extents[2:])
                fig.savefig(folder/name, transparent=True, dpi=dpi)
                plt.close(fig); files.append(name)
    return bounds, files


def remove_legacy_images(output, prefix):
    for path in output.glob(prefix + "*.png"):
        if path.name.endswith("_href.png") or (
            path.name.endswith("_refs.png") and not path.name.endswith(("_spc_refs.png", "_omd_refs.png"))
        ):
            path.unlink()


def run(kind, *, cache=Path("grib_cache_cam_members"), output=Path("static"), pinned=None, workers=2, dpi=600):
    began = time.monotonic(); now = datetime.now(UTC)
    sources = Sources(cache, workers); omd = OMDReader(sources); members = read_members()
    init, windows, preflight = select_cycle(kind, sources, omd, members, now, pinned)
    ffg, ffg_grid, ffg_meta = load_cycle_ffg(sources, init)
    products, grid, hourly_sources, contracts = compute(kind, init, windows, sources, omd, members, ffg, ffg_grid)
    expected = len(members)*sum(b-a for a, b in windows.values())
    if len(hourly_sources) != expected or len({(r["member"], r["valid_end_utc"]) for r in hourly_sources}) != expected:
        raise ValueError("Member-hour population is incomplete or duplicated")
    start = min(a for a, b in windows.values()); end = max(b for a, b in windows.values())
    if datetime.now(UTC) >= init+timedelta(hours=end):
        raise ValueError("Selected valid period expired during calculation")
    meta = {"schema": SCHEMA, "generated_at_utc": iso(datetime.now(UTC)),
            "valid_time": f"{'Day 1 ERO' if kind == 'ero' else 'Ensemble Nowcast'} (SPC REFS {init:%HZ} | OMD REFS {init:%HZ})",
            "spc_refs_init_utc": iso(init), "omd_refs_init_utc": iso(init),
            "valid_start_utc": iso(init+timedelta(hours=start)), "valid_end_utc": iso(init+timedelta(hours=end)),
            "window_contract": contracts, "members": members, "spc_member_count": 10,
            "ffg": ffg_meta, "hourly_qpf_thresholds_in": list(QPF_IN), "ffg_durations_hours": [1, 3, 6],
            "method": {"probability": "maximum of individual rolling-window neighborhood member frequencies",
                       "ffg_combination": "maximum across duration-specific probabilities and eligible times; no duration/time event union",
                       "spc_neighborhood_radius_km": 40, "extra_neighborhood_or_smoothing": False,
                       "ffg_cadence": "1h hourly; 3h/6h at forecast hours divisible by 3; entire accumulation inside selected window",
                       "spc_ffg_baseline": "official numerical FFG published by model initialization, frozen per cycle",
                       "omd_ffg_baseline": "native producer FFG baseline; raw producer snapshot identity is not published in this GRIB",
                       "omd_processing": "native producer neighborhood probabilities (generating process 194); no additional dilation",
                       "blend": "50% SPC suite maximum + 50% OMD suite maximum on identical native grids and valid periods; both required",
                       "shared_members": True, "independent_ensemble_samples": False,
                       "spc_status": "WPC experimental calculation using SPC member roster"},
            "preflight": preflight, "source_completeness_contract": "all ten SPC members, every selected hour, and every OMD probability slot required",
            "rendering": {"revision": SCHEMA, "map_dpi": dpi, "map_pixel_dimensions": [10*dpi, 6*dpi],
                          "probability_levels": [10, 30, 50, 70, 90, 100],
                          "qpf_colors": list(QPF_COLORS), "ffg_colors": list(FFG_COLORS), "rainfall_regridding": "none"}}
    if kind == "ero":
        a, b = init+timedelta(hours=start), init+timedelta(hours=end)
        meta.update(ero_start_utc=iso(a), ero_end_utc=iso(b), ero_coverage_hours=end-start,
                    ero_window_type="18z_update" if init.hour == 18 else "full_day1",
                    ero_window_str=f"{a:%HZ %b %d} &mdash; {b:%HZ %b %d}")
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="cam-stage-", dir=output.parent) as temp:
        stage = Path(temp)
        bounds, files = render(kind, products, grid, stage, dpi)
        meta.update(bounds=bounds, expected_files=files, elapsed_seconds=round(time.monotonic()-began, 2))
        source_name = "cam_sources.json" if kind == "cam" else "ero_cam_sources.json"
        atomic_json(stage/source_name, {"schema": SCHEMA, "init_utc": iso(init), "analysis_grid": grid.metadata(),
                                      "spc_member_hours": hourly_sources, "omd_fields": omd.records,
                                      "ffg": ffg_meta, "expected_spc_member_hours": expected})
        meta["file_sha256"] = {name: hashlib.sha256((stage/name).read_bytes()).hexdigest()
                               for name in [*files, source_name]}
        for name in [*files, source_name]:
            os.replace(stage/name, output/name)
        # Explicit new names prevent any archived HREF image from being
        # relabeled SPC REFS, even during the transition's first publication.
        prefix = "cam_" if kind == "cam" else "ero_"
        remove_legacy_images(output, prefix)
        meta_name = "cam_metadata.json" if kind == "cam" else "ero_cam_metadata.json"
        atomic_json(output/meta_name, meta)
    LOG.info("Complete %s package: %d PNGs, %d/%d SPC member-hours, %.1f seconds", kind, len(files), len(hourly_sources), expected, time.monotonic()-began)
    return meta


def main(kind):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--init", help="Pin YYYYMMDDHH UTC; default latest aligned complete suite")
    parser.add_argument("--cache", type=Path, default=Path("grib_cache_cam_members"))
    parser.add_argument("--output", type=Path, default=Path("static"))
    parser.add_argument("--workers", type=int, choices=range(1, 5), default=2)
    parser.add_argument("--dpi", type=int, default=600)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    pinned = datetime.strptime(args.init, "%Y%m%d%H").replace(tzinfo=UTC) if args.init else None
    try:
        run(kind, cache=args.cache, output=args.output, pinned=pinned, workers=args.workers, dpi=args.dpi)
    except Exception:
        LOG.exception("New %s package withheld; current files retained for independent freshness validation", kind)
        # The workflow validates the restored package next, including the new
        # schema and expiry. Legacy HREF packages cannot pass as SPC guidance.
        meta_path = args.output / ("cam_metadata.json" if kind == "cam" else "ero_cam_metadata.json")
        if meta_path.exists():
            try:
                if json.loads(meta_path.read_text()).get("schema") == SCHEMA:
                    return
            except (ValueError, OSError):
                pass
        raise
