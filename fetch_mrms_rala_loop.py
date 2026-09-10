#!/usr/bin/env python3
"""Build a rolling six-hour / 10-minute NOAA MRMS RALA archive for the WPC dashboard.

The source remains native NOAA MRMS Reflectivity at Lowest Altitude (RALA):
  * NCEP MRMS HTTPS is preferred for timestamps available on both feeds.
  * NOAA NODD/AWS is the fallback and normally provides the deeper inventory.

The published dashboard archive is intentionally sampled to a stable 10-minute
cadence.  It retains up to six hours (37 nominal slots) while the browser defaults
to the latest two hours and can expose four or six hours on demand.  The operational
workflow restores the previous data-branch package as a rolling PNG cache; cached
frames can also fill historical nominal slots when one live source inventory is
shallower than six hours.  No temporal interpolation or averaging is performed.
"""
from __future__ import annotations

import argparse
import json
import math
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
from PIL import Image

import fetch_mrms_rala as rala

MANIFEST_NAME = "mrms_rala_loop_manifest.json"
FRAMES_DIR_NAME = "frames"
METADATA_MODE = "mrms_rala_loop_manifest_v2"
GENERATOR_REVISION = "rala_loop_v2_11_10min_windows"
DEFAULT_ARCHIVE_MINUTES = 360
DEFAULT_CADENCE_MINUTES = 10
DEFAULT_SLOT_TOLERANCE_MINUTES = 4.5
DEFAULT_DASHBOARD_WINDOW_MINUTES = 120
DASHBOARD_WINDOW_OPTIONS_MINUTES = (120, 240, 360)
UTC = timezone.utc


@dataclass(frozen=True)
class SlotSelection:
    nominal_time: datetime
    candidate: rala.SourceCandidate
    cached_item: dict | None
    cached_path: Path | None
    selected_from: str  # "live" or "cache-fallback"


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def floor_to_cadence(value: datetime, cadence_minutes: int) -> datetime:
    seconds = cadence_minutes * 60
    stamp = math.floor(value.timestamp() / seconds) * seconds
    return datetime.fromtimestamp(stamp, tz=UTC)


def nominal_slots(latest_live_time: datetime, loop_minutes: int, cadence_minutes: int) -> list[datetime]:
    latest_slot = floor_to_cadence(latest_live_time, cadence_minutes)
    count = loop_minutes // cadence_minutes + 1
    return [
        latest_slot - timedelta(minutes=cadence_minutes * offset)
        for offset in range(count - 1, -1, -1)
    ]


def merge_live_candidates(ncep, nodd, source_mode: str):
    """Return timestamp-deduplicated live candidates; NCEP wins equal timestamps."""
    by_timestamp = {}
    if source_mode in ("auto", "nodd"):
        for item in nodd:
            by_timestamp[item.timestamp] = item
    if source_mode in ("auto", "ncep"):
        for item in ncep:
            by_timestamp[item.timestamp] = item
    if not by_timestamp:
        raise RuntimeError(f"No MRMS RALA candidates found for source mode {source_mode!r}.")
    return [by_timestamp[key] for key in sorted(by_timestamp)]


def load_cached_manifest(cache_dir: Path) -> dict | None:
    path = cache_dir / MANIFEST_NAME
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    # Keep the v2 manifest contract so the first v2.11 deployment can reuse the
    # prior v2.x two-minute package as a seed cache.
    return value if value.get("metadata_mode") == METADATA_MODE else None


def cached_inventory(cache_dir: Path, cached_manifest: dict | None) -> list[tuple[datetime, dict, Path]]:
    inventory = []
    for item in (cached_manifest or {}).get("frames", []):
        try:
            stamp = parse_time(item["valid_time_utc"])
            rel = item["png"]
        except Exception:
            continue
        path = cache_dir / rel
        if path.exists() and path.stat().st_size >= 10_000:
            inventory.append((stamp, item, path))
    inventory.sort(key=lambda row: row[0])
    return inventory


def candidate_from_cached(stamp: datetime, item: dict) -> rala.SourceCandidate:
    return rala.SourceCandidate(
        provider=str(item.get("source_provider") or "Prior NOAA MRMS rolling cache"),
        timestamp=stamp,
        url=str(item.get("source_url") or ""),
        key=str(item.get("source_key") or ""),
    )


def _nearest_live_candidate(live_candidates, slot: datetime, tolerance_minutes: float, used_times: set[datetime]):
    tolerance_seconds = tolerance_minutes * 60.0
    eligible = [
        item for item in live_candidates
        if item.timestamp not in used_times
        and abs((item.timestamp - slot).total_seconds()) <= tolerance_seconds
    ]
    if not eligible:
        return None
    # Nearest timestamp wins.  If equally close, prefer the earlier observation
    # so a nominal slot never depends on a later file merely because of a tie.
    return min(
        eligible,
        key=lambda item: (
            abs((item.timestamp - slot).total_seconds()),
            1 if item.timestamp > slot else 0,
            item.timestamp,
        ),
    )


def _nearest_cached_candidate(cache_rows, slot: datetime, tolerance_minutes: float, used_times: set[datetime]):
    tolerance_seconds = tolerance_minutes * 60.0
    eligible = [
        row for row in cache_rows
        if row[0] not in used_times
        and abs((row[0] - slot).total_seconds()) <= tolerance_seconds
    ]
    if not eligible:
        return None
    return min(
        eligible,
        key=lambda row: (
            abs((row[0] - slot).total_seconds()),
            1 if row[0] > slot else 0,
            row[0],
        ),
    )


def choose_slot_selections(
    live_candidates,
    cache_rows,
    loop_minutes: int,
    cadence_minutes: int,
    slot_tolerance_minutes: float,
):
    """Select one real MRMS frame per nominal slot without interpolation/averaging.

    Live NOAA inventory is preferred.  A previously published NOAA PNG can fill a
    historical slot only when the live inventory has no acceptable frame near that
    slot.  This makes the rolling cache useful during shallow/transient listings,
    which the previous implementation did not do.
    """
    if not live_candidates:
        raise RuntimeError("No live MRMS RALA candidates are available.")

    slots = nominal_slots(live_candidates[-1].timestamp, loop_minutes, cadence_minutes)
    used_times: set[datetime] = set()
    selections: list[SlotSelection] = []
    missing_slots: list[datetime] = []

    cache_by_time = {row[0]: row for row in cache_rows}
    for slot in slots:
        live = _nearest_live_candidate(live_candidates, slot, slot_tolerance_minutes, used_times)
        if live is not None:
            cached = cache_by_time.get(live.timestamp)
            selections.append(
                SlotSelection(
                    nominal_time=slot,
                    candidate=live,
                    cached_item=cached[1] if cached else None,
                    cached_path=cached[2] if cached else None,
                    selected_from="live",
                )
            )
            used_times.add(live.timestamp)
            continue

        cached = _nearest_cached_candidate(cache_rows, slot, slot_tolerance_minutes, used_times)
        if cached is not None:
            stamp, item, path = cached
            selections.append(
                SlotSelection(
                    nominal_time=slot,
                    candidate=candidate_from_cached(stamp, item),
                    cached_item=item,
                    cached_path=path,
                    selected_from="cache-fallback",
                )
            )
            used_times.add(stamp)
            continue

        missing_slots.append(slot)

    selections.sort(key=lambda item: item.nominal_time)
    return selections, slots, missing_slots


def frame_filename(candidate) -> str:
    return f"mrms_rala_{candidate.timestamp:%Y%m%dT%H%M%SZ}.png"


def save_rgba_png(rgba: np.ndarray, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(rgba, mode="RGBA").save(
        destination,
        format="PNG",
        optimize=False,
        compress_level=6,
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


def _display_contract(rendered: dict) -> dict:
    return {
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


def _validate_common_display(common_display: dict | None, display: dict) -> dict:
    if common_display is None:
        return display
    if common_display.get("leaflet_bounds") != display.get("leaflet_bounds"):
        raise RuntimeError("MRMS loop frame bounds changed inside one package.")
    if int(common_display.get("image_width_px", 0)) != int(display["image_width_px"]):
        raise RuntimeError("MRMS loop frame width changed inside one package.")
    if int(common_display.get("image_height_px", 0)) != int(display["image_height_px"]):
        raise RuntimeError("MRMS loop frame height changed inside one package.")
    return common_display


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

    live_candidates = merge_live_candidates(ncep, nodd, args.source_mode)
    newest_live = live_candidates[-1]
    newest_live_age = (now - newest_live.timestamp).total_seconds() / 60.0
    if newest_live_age > args.freshness_minutes:
        raise RuntimeError(
            f"Newest MRMS RALA source frame is {newest_live_age:.1f} minutes old; "
            f"maximum allowed is {args.freshness_minutes:.1f} minutes."
        )

    output_dir = Path(args.output_dir)
    cache_dir = Path(args.cache_dir) if args.cache_dir else Path("__no_cache__")
    output_frames = output_dir / FRAMES_DIR_NAME
    output_dir.mkdir(parents=True, exist_ok=True)
    output_frames.mkdir(parents=True, exist_ok=True)

    cached_manifest = load_cached_manifest(cache_dir)
    cache_rows = cached_inventory(cache_dir, cached_manifest)
    selections, slots, missing_slots = choose_slot_selections(
        live_candidates,
        cache_rows,
        args.loop_minutes,
        args.cadence_minutes,
        args.slot_tolerance_minutes,
    )
    if not selections:
        raise RuntimeError("No MRMS frames matched the requested 10-minute archive slots.")

    common_display = None
    frames = []
    reused = 0
    built = 0
    cached_fallback = 0
    live_selected = 0

    for index, selection in enumerate(selections, start=1):
        candidate = selection.candidate
        name = frame_filename(candidate)
        destination = output_frames / name
        cached_item = selection.cached_item
        cached_path = selection.cached_path

        if selection.selected_from == "live":
            live_selected += 1
        else:
            cached_fallback += 1

        if cached_path and cached_path.exists() and cached_path.stat().st_size >= 10_000 and cached_item:
            shutil.copy2(cached_path, destination)
            reused += 1
            if common_display is None:
                common_display = (cached_manifest or {}).get("display")
            frame_meta = {
                "nominal_time_utc": rala.iso_z(selection.nominal_time),
                "valid_time_utc": candidate.iso(),
                "slot_offset_minutes": round(
                    (candidate.timestamp - selection.nominal_time).total_seconds() / 60.0, 3
                ),
                "png": f"{FRAMES_DIR_NAME}/{name}",
                "source_provider": candidate.provider,
                "source_key": candidate.key,
                "source_url": candidate.url,
                "visible_pixels": cached_item.get("visible_pixels"),
                "reused_from_previous_package": True,
                "selection_source": selection.selected_from,
            }
            print(
                f"[{index:02d}/{len(selections):02d}] reuse {candidate.iso()} "
                f"for slot {rala.iso_z(selection.nominal_time)}"
            )
        else:
            if selection.selected_from != "live":
                raise RuntimeError(
                    f"Cached fallback frame disappeared before publication: {candidate.iso()}"
                )
            print(
                f"[{index:02d}/{len(selections):02d}] build {candidate.iso()} "
                f"for slot {rala.iso_z(selection.nominal_time)} from {candidate.provider}"
            )
            rendered = render_candidate(session, candidate, destination, args.output_width)
            built += 1
            display = _display_contract(rendered)
            common_display = _validate_common_display(common_display, display)
            frame_meta = {
                "nominal_time_utc": rala.iso_z(selection.nominal_time),
                "valid_time_utc": candidate.iso(),
                "slot_offset_minutes": round(
                    (candidate.timestamp - selection.nominal_time).total_seconds() / 60.0, 3
                ),
                "png": f"{FRAMES_DIR_NAME}/{name}",
                "source_provider": candidate.provider,
                "source_key": candidate.key,
                "source_url": candidate.url,
                "visible_pixels": rendered["visible_pixels"],
                "reused_from_previous_package": False,
                "selection_source": selection.selected_from,
            }
        frames.append(frame_meta)

    if not common_display:
        raise RuntimeError("No usable MRMS display metadata was produced.")

    actual_times = [parse_time(item["valid_time_utc"]) for item in frames]
    actual_intervals = [
        (b - a).total_seconds() / 60.0
        for a, b in zip(actual_times, actual_times[1:])
    ]
    median_interval = float(np.median(actual_intervals)) if actual_intervals else math.nan
    latest = actual_times[-1]
    latest_age = (now - latest).total_seconds() / 60.0
    if latest_age > args.freshness_minutes:
        raise RuntimeError(
            f"Newest published 10-minute MRMS RALA frame is {latest_age:.1f} minutes old; "
            f"maximum allowed is {args.freshness_minutes:.1f} minutes."
        )

    expected_frame_count = args.loop_minutes // args.cadence_minutes + 1
    manifest = {
        "metadata_mode": METADATA_MODE,
        "generator_revision": GENERATOR_REVISION,
        "product": rala.PRODUCT,
        "region": rala.REGION,
        "field_height_km": rala.FIELD_HEIGHT_KM,
        "units": "dBZ",
        "latest_valid_time_utc": frames[-1]["valid_time_utc"],
        "latest_nominal_time_utc": frames[-1]["nominal_time_utc"],
        "generated_utc": rala.iso_z(rala.utc_now()),
        "freshness_limit_minutes": float(args.freshness_minutes),
        "latest_age_minutes_at_build": round(latest_age, 2),
        "newest_live_source_age_minutes_at_build": round(newest_live_age, 2),
        "loop_window_minutes": int(args.loop_minutes),
        "target_frame_cadence_minutes": int(args.cadence_minutes),
        "slot_tolerance_minutes": float(args.slot_tolerance_minutes),
        "expected_frame_count": int(expected_frame_count),
        "frame_count": len(frames),
        "default_dashboard_window_minutes": DEFAULT_DASHBOARD_WINDOW_MINUTES,
        "dashboard_window_options_minutes": list(DASHBOARD_WINDOW_OPTIONS_MINUTES),
        "nominal_archive_start_utc": rala.iso_z(slots[0]),
        "nominal_archive_end_utc": rala.iso_z(slots[-1]),
        "actual_span_minutes": round(
            (actual_times[-1] - actual_times[0]).total_seconds() / 60.0, 3
        ) if len(actual_times) >= 2 else 0.0,
        "median_frame_spacing_minutes": (
            round(median_interval, 3) if math.isfinite(median_interval) else None
        ),
        "missing_nominal_slots_utc": [rala.iso_z(item) for item in missing_slots],
        "source_mode": args.source_mode,
        "source_policy": (
            "Official NOAA MRMS only. NCEP MRMS HTTPS is preferred for matching "
            "timestamps; NOAA NODD/AWS supplies fallback frames when needed. "
            "Published frames are real MRMS analyses sampled to nominal 10-minute "
            "slots; no temporal interpolation or averaging is performed."
        ),
        "discovery": {
            "ncep_candidate_count": len(ncep),
            "nodd_candidate_count": len(nodd),
            "merged_live_candidate_count": len(live_candidates),
            "errors": discovery_errors,
        },
        "display": common_display,
        "frames": frames,
        "build_efficiency": {
            "reused_cached_frames": reused,
            "new_frames_rendered": built,
            "cached_fallback_frames": cached_fallback,
            "live_selected_frames": live_selected,
        },
    }
    (output_dir / MANIFEST_NAME).write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )

    print(
        f"MRMS RALA loop PASS: {len(frames)}/{expected_frame_count} published frames; "
        f"nominal archive {manifest['nominal_archive_start_utc']} -> "
        f"{manifest['nominal_archive_end_utc']}; actual span={manifest['actual_span_minutes']:.1f} min; "
        f"reused={reused}, built={built}, cache_fallback={cached_fallback}, "
        f"missing_slots={len(missing_slots)}."
    )
    return 0


def self_test() -> int:
    base = datetime(2026, 9, 10, 18, 4, 42, tzinfo=UTC)
    live = [
        rala.SourceCandidate(
            provider="NCEP MRMS HTTPS",
            timestamp=base - timedelta(minutes=2 * i),
            url=f"https://example/{i}",
            key=f"live-{i}",
        )
        for i in range(0, 191)
    ]
    live = sorted(live, key=lambda item: item.timestamp)
    selections, slots, missing = choose_slot_selections(
        live, [], 360, 10, 4.5
    )
    assert len(slots) == 37
    assert len(selections) == 37
    assert not missing
    assert all(
        abs((item.candidate.timestamp - item.nominal_time).total_seconds()) <= 270
        for item in selections
    )

    # Regression for the production failure mode: pretend the live listing exposes
    # only ~98 minutes, while the rolling cache contains the prior six-hour archive.
    shallow_start = base - timedelta(minutes=98)
    shallow_live = [item for item in live if item.timestamp >= shallow_start]
    cache_rows = []
    for item in selections:
        cached_item = {
            "valid_time_utc": item.candidate.iso(),
            "png": f"frames/{frame_filename(item.candidate)}",
            "source_provider": item.candidate.provider,
            "source_key": item.candidate.key,
            "source_url": item.candidate.url,
        }
        # Path existence is not tested by choose_slot_selections itself; cached
        # inventory performs that filesystem check in production.
        cache_rows.append((item.candidate.timestamp, cached_item, Path(cached_item["png"])))
    recovered, slots2, missing2 = choose_slot_selections(
        shallow_live, cache_rows, 360, 10, 4.5
    )
    assert len(slots2) == 37
    assert len(recovered) == 37
    assert not missing2
    assert sum(item.selected_from == "cache-fallback" for item in recovered) > 20
    print("MRMS RALA v2.11 10-minute / 6-hour selection self-test PASS")
    return 0


def parse_args():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output-dir", default="mrms_rala_loop_publish")
    p.add_argument("--cache-dir", default="")
    p.add_argument("--source-mode", choices=("auto", "ncep", "nodd"), default="auto")
    p.add_argument("--loop-minutes", type=int, default=DEFAULT_ARCHIVE_MINUTES)
    p.add_argument("--cadence-minutes", type=int, default=DEFAULT_CADENCE_MINUTES)
    p.add_argument("--slot-tolerance-minutes", type=float, default=DEFAULT_SLOT_TOLERANCE_MINUTES)
    p.add_argument("--freshness-minutes", type=float, default=20.0)
    p.add_argument("--output-width", type=int, default=7000)
    p.add_argument("--self-test", action="store_true")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    if args.self_test:
        return self_test()
    if args.loop_minutes not in DASHBOARD_WINDOW_OPTIONS_MINUTES:
        raise SystemExit("--loop-minutes must be one of 120, 240, or 360")
    if args.cadence_minutes < 5 or args.cadence_minutes > 30:
        raise SystemExit("--cadence-minutes must be between 5 and 30")
    if args.loop_minutes % args.cadence_minutes != 0:
        raise SystemExit("--loop-minutes must be evenly divisible by --cadence-minutes")
    if args.slot_tolerance_minutes <= 0 or args.slot_tolerance_minutes >= args.cadence_minutes / 2:
        raise SystemExit("--slot-tolerance-minutes must be positive and less than half the cadence")
    if args.output_width < 4000 or args.output_width > 9000:
        raise SystemExit("--output-width must be between 4000 and 9000")
    if args.freshness_minutes <= 0:
        raise SystemExit("--freshness-minutes must be positive")
    try:
        return build(args)
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
