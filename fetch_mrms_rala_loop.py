#!/usr/bin/env python3
"""Build a rolling two-hour NOAA MRMS RALA loop for the WPC dashboard.

The loop uses only official MRMS dissemination:
  * NCEP MRMS HTTPS (preferred when the same timestamp exists on both feeds)
  * NOAA NODD/AWS (fallback)

The operational workflow restores the previous data-branch package as a cache.
Only new MRMS frames are downloaded/decoded/reprojected; still-valid cached PNGs
are reused.  The output directory contains timestamped transparent PNG frames and
one manifest consumed directly by the dashboard.
"""
from __future__ import annotations

import argparse
import json
import math
import shutil
import tempfile
from datetime import timedelta
from pathlib import Path

import numpy as np
from PIL import Image

import fetch_mrms_rala as rala

MANIFEST_NAME = "mrms_rala_loop_manifest.json"
FRAMES_DIR_NAME = "frames"
METADATA_MODE = "mrms_rala_loop_manifest_v2"


def choose_loop_candidates(ncep, nodd, source_mode: str, loop_minutes: int, max_frames: int):
    """Return chronological, timestamp-deduplicated candidates for the loop.

    In auto mode NCEP wins when the same timestamp is available from both feeds;
    NODD remains a true fallback for timestamps absent from NCEP.
    """
    by_timestamp = {}
    if source_mode in ("auto", "nodd"):
        for item in nodd:
            by_timestamp[item.timestamp] = item
    if source_mode in ("auto", "ncep"):
        for item in ncep:
            by_timestamp[item.timestamp] = item
    if not by_timestamp:
        raise RuntimeError(f"No MRMS RALA candidates found for source mode {source_mode!r}.")

    latest_time = max(by_timestamp)
    cutoff = latest_time - timedelta(minutes=float(loop_minutes))
    selected = [by_timestamp[t] for t in sorted(by_timestamp) if t >= cutoff]
    if max_frames > 0 and len(selected) > max_frames:
        selected = selected[-max_frames:]
    return selected


def frame_filename(candidate) -> str:
    return f"mrms_rala_{candidate.timestamp:%Y%m%dT%H%M%SZ}.png"


def load_cached_manifest(cache_dir: Path) -> dict | None:
    path = cache_dir / MANIFEST_NAME
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return value if value.get("metadata_mode") == METADATA_MODE else None


def cached_frame_path(cache_dir: Path, candidate) -> Path:
    return cache_dir / FRAMES_DIR_NAME / frame_filename(candidate)


def save_rgba_png(rgba: np.ndarray, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(rgba, mode="RGBA").save(
        destination,
        format="PNG",
        optimize=True,
        compress_level=9,
    )
    if destination.stat().st_size < 10_000:
        raise RuntimeError(f"Rendered loop frame is implausibly small: {destination}")


def render_candidate(session, candidate, destination: Path, output_width: int):
    with tempfile.TemporaryDirectory(prefix="mrms_rala_loop_frame_") as td:
        td = Path(td)
        gz_path = td / "frame.grib2.gz"
        grib_path = td / "frame.grib2"
        gzip_bytes = rala.download_file(session, candidate, gz_path)
        grib_bytes = rala.gunzip_file(gz_path, grib_path)
        data, src_transform, decode_meta = rala.decode_grib(grib_path)
        projected, _dst_transform, bounds_3857 = rala.reproject_dbz(
            data, src_transform, output_width
        )
        rgba = rala.colorize(projected)
        visible = int(np.count_nonzero(rgba[..., 3]))
        if visible < 100:
            raise RuntimeError(
                f"{candidate.iso()} rendered only {visible} visible radar pixels."
            )
        save_rgba_png(rgba, destination)
        return {
            "bounds": rala.leaflet_bounds_from_mercator(bounds_3857),
            "width": int(rgba.shape[1]),
            "height": int(rgba.shape[0]),
            "visible_pixels": visible,
            "decode": decode_meta,
            "gzip_bytes": gzip_bytes,
            "grib2_bytes": grib_bytes,
        }


def build(args) -> int:
    now = rala.utc_now()
    session = rala.make_session()
    ncep = []
    nodd = []
    discovery_errors = []

    if args.source_mode in ("auto", "ncep"):
        try:
            ncep = rala.discover_ncep(session)
        except Exception as exc:
            discovery_errors.append(f"NCEP discovery failed: {type(exc).__name__}: {exc}")
            if args.source_mode == "ncep":
                raise
    if args.source_mode in ("auto", "nodd"):
        try:
            nodd = rala.discover_nodd(session, now)
        except Exception as exc:
            discovery_errors.append(f"NODD discovery failed: {type(exc).__name__}: {exc}")
            if args.source_mode == "nodd":
                raise

    candidates = choose_loop_candidates(
        ncep, nodd, args.source_mode, args.loop_minutes, args.max_frames
    )
    latest = candidates[-1]
    latest_age = (now - latest.timestamp).total_seconds() / 60.0
    if latest_age > args.freshness_minutes:
        raise RuntimeError(
            f"Newest MRMS RALA frame is {latest_age:.1f} minutes old; "
            f"maximum allowed is {args.freshness_minutes:.1f} minutes."
        )

    output_dir = Path(args.output_dir)
    cache_dir = Path(args.cache_dir) if args.cache_dir else Path("__no_cache__")
    output_frames = output_dir / FRAMES_DIR_NAME
    output_dir.mkdir(parents=True, exist_ok=True)
    output_frames.mkdir(parents=True, exist_ok=True)

    cached_manifest = load_cached_manifest(cache_dir)
    cached_frames_by_time = {
        item.get("valid_time_utc"): item
        for item in (cached_manifest or {}).get("frames", [])
        if item.get("valid_time_utc") and item.get("png")
    }

    common_display = None
    frames = []
    reused = 0
    built = 0

    for index, candidate in enumerate(candidates, start=1):
        name = frame_filename(candidate)
        destination = output_frames / name
        cached = cached_frame_path(cache_dir, candidate)
        cached_item = cached_frames_by_time.get(candidate.iso())

        if cached.exists() and cached.stat().st_size >= 10_000 and cached_item:
            shutil.copy2(cached, destination)
            reused += 1
            if common_display is None:
                common_display = (cached_manifest or {}).get("display")
            frame_meta = {
                "valid_time_utc": candidate.iso(),
                "png": f"{FRAMES_DIR_NAME}/{name}",
                "source_provider": candidate.provider,
                "source_key": candidate.key,
                "source_url": candidate.url,
                "visible_pixels": cached_item.get("visible_pixels"),
                "reused_from_previous_package": True,
            }
            print(f"[{index:02d}/{len(candidates):02d}] reuse {candidate.iso()} -> {name}")
        else:
            print(f"[{index:02d}/{len(candidates):02d}] build {candidate.iso()} from {candidate.provider}")
            rendered = render_candidate(session, candidate, destination, args.output_width)
            built += 1
            display = {
                "projection": "EPSG:3857",
                "leaflet_bounds": rendered["bounds"],
                "image_width_px": rendered["width"],
                "image_height_px": rendered["height"],
                "visible_minimum_dbz": rala.MIN_VISIBLE_DBZ,
                "resampling": "nearest-neighbor",
                "smoothing": False,
                "color_table": [
                    {"threshold_dbz": threshold, "color": color}
                    for threshold, color in rala.RADAR_COLOR_TABLE
                ],
            }
            if common_display is None:
                common_display = display
            else:
                if common_display.get("leaflet_bounds") != display.get("leaflet_bounds"):
                    raise RuntimeError("MRMS loop frame bounds changed inside one package.")
                if int(common_display.get("image_width_px", 0)) != display["image_width_px"]:
                    raise RuntimeError("MRMS loop frame width changed inside one package.")
                if int(common_display.get("image_height_px", 0)) != display["image_height_px"]:
                    raise RuntimeError("MRMS loop frame height changed inside one package.")
            frame_meta = {
                "valid_time_utc": candidate.iso(),
                "png": f"{FRAMES_DIR_NAME}/{name}",
                "source_provider": candidate.provider,
                "source_key": candidate.key,
                "source_url": candidate.url,
                "visible_pixels": rendered["visible_pixels"],
                "reused_from_previous_package": False,
            }
        frames.append(frame_meta)

    if not common_display:
        raise RuntimeError("No usable MRMS display metadata was produced.")

    intervals = []
    for a, b in zip(candidates, candidates[1:]):
        intervals.append((b.timestamp - a.timestamp).total_seconds() / 60.0)
    median_interval = float(np.median(intervals)) if intervals else math.nan

    manifest = {
        "metadata_mode": METADATA_MODE,
        "generator_revision": "rala_loop_v2",
        "product": rala.PRODUCT,
        "region": rala.REGION,
        "field_height_km": rala.FIELD_HEIGHT_KM,
        "units": "dBZ",
        "latest_valid_time_utc": latest.iso(),
        "generated_utc": rala.iso_z(rala.utc_now()),
        "freshness_limit_minutes": float(args.freshness_minutes),
        "latest_age_minutes_at_build": round(latest_age, 2),
        "loop_window_minutes": int(args.loop_minutes),
        "frame_count": len(frames),
        "median_frame_spacing_minutes": (
            round(median_interval, 3) if math.isfinite(median_interval) else None
        ),
        "source_mode": args.source_mode,
        "source_policy": (
            "Official NOAA MRMS only. NCEP MRMS HTTPS is preferred for matching "
            "timestamps; NOAA NODD/AWS supplies fallback frames when needed."
        ),
        "discovery": {
            "ncep_candidate_count": len(ncep),
            "nodd_candidate_count": len(nodd),
            "errors": discovery_errors,
        },
        "display": common_display,
        "frames": frames,
        "build_efficiency": {
            "reused_cached_frames": reused,
            "new_frames_rendered": built,
        },
    }
    (output_dir / MANIFEST_NAME).write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )

    print(
        f"MRMS RALA loop PASS: {len(frames)} frames spanning "
        f"{frames[0]['valid_time_utc']} -> {frames[-1]['valid_time_utc']}; "
        f"reused={reused}, built={built}."
    )
    return 0


def parse_args():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output-dir", default="mrms_rala_loop_publish")
    p.add_argument("--cache-dir", default="")
    p.add_argument("--source-mode", choices=("auto", "ncep", "nodd"), default="auto")
    p.add_argument("--loop-minutes", type=int, default=120)
    p.add_argument("--max-frames", type=int, default=75)
    p.add_argument("--freshness-minutes", type=float, default=20.0)
    p.add_argument("--output-width", type=int, default=7000)
    return p.parse_args()


def main() -> int:
    args = parse_args()
    if args.loop_minutes < 30 or args.loop_minutes > 360:
        raise SystemExit("--loop-minutes must be between 30 and 360")
    if args.max_frames < 2 or args.max_frames > 180:
        raise SystemExit("--max-frames must be between 2 and 180")
    if args.output_width < 4000 or args.output_width > 9000:
        raise SystemExit("--output-width must be between 4000 and 9000")
    try:
        return build(args)
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
