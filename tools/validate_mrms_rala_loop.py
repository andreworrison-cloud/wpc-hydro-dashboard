#!/usr/bin/env python3
"""Validate the dashboard-ready rolling MRMS RALA 10-minute / six-hour package."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

UTC = timezone.utc
EXPECTED_METADATA_MODE = "mrms_rala_loop_manifest_v2"
EXPECTED_GENERATOR_REVISION = "rala_loop_v2_11_10min_windows"
EXPECTED_WINDOW_OPTIONS = [120, 240, 360]


def parse_time(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("output_dir", nargs="?", default="mrms_rala_loop_publish")
    p.add_argument("--minimum-frames", type=int, default=35)
    p.add_argument("--minimum-span-minutes", type=float, default=350.0)
    p.add_argument("--expected-cadence-minutes", type=float, default=10.0)
    p.add_argument("--max-gap-minutes", type=float, default=20.0)
    p.add_argument("--default-window-minutes", type=int, default=120)
    p.add_argument("--minimum-default-window-frames", type=int, default=12)
    args = p.parse_args()

    root = Path(args.output_dir)
    manifest_path = root / "mrms_rala_loop_manifest.json"
    errors = []
    if not manifest_path.exists():
        errors.append(f"Missing manifest: {manifest_path}")
    else:
        m = json.loads(manifest_path.read_text(encoding="utf-8"))
        if m.get("metadata_mode") != EXPECTED_METADATA_MODE:
            errors.append("Unexpected MRMS RALA loop metadata_mode")
        if m.get("generator_revision") != EXPECTED_GENERATOR_REVISION:
            errors.append(
                f"Unexpected MRMS RALA generator_revision: {m.get('generator_revision')!r}"
            )
        if m.get("product") != "ReflectivityAtLowestAltitude" or m.get("units") != "dBZ":
            errors.append("Unexpected MRMS RALA product/units")
        if m.get("region") != "CONUS":
            errors.append("Unexpected MRMS RALA region")

        if int(m.get("loop_window_minutes", -1)) != 360:
            errors.append("Published MRMS RALA archive is not configured for six hours")
        if float(m.get("target_frame_cadence_minutes", -1)) != args.expected_cadence_minutes:
            errors.append("Published MRMS RALA cadence is not the required 10 minutes")
        if int(m.get("default_dashboard_window_minutes", -1)) != args.default_window_minutes:
            errors.append("MRMS RALA default dashboard window is not two hours")
        if m.get("dashboard_window_options_minutes") != EXPECTED_WINDOW_OPTIONS:
            errors.append("MRMS RALA dashboard window options are not [120, 240, 360]")
        expected_count = int(360 / args.expected_cadence_minutes) + 1
        if int(m.get("expected_frame_count", -1)) != expected_count:
            errors.append(f"MRMS RALA expected_frame_count is not {expected_count}")

        display = m.get("display") or {}
        if str(display.get("projection", "")).upper() != "EPSG:3857":
            errors.append("Loop display is not EPSG:3857")
        if float(display.get("visible_minimum_dbz", -999)) != 5.0:
            errors.append("Loop must preserve the 5 dBZ visibility threshold")
        if display.get("resampling") != "nearest-neighbor" or display.get("smoothing") is not False:
            errors.append("Loop must preserve nearest-neighbor/no-smoothing rendering")

        frames = m.get("frames") or []
        if len(frames) < args.minimum_frames:
            errors.append(f"Loop has only {len(frames)} frames; expected at least {args.minimum_frames}")
        if int(m.get("frame_count", -1)) != len(frames):
            errors.append("Manifest frame_count does not match the frame inventory")

        actual_times = []
        nominal_times = []
        for item in frames:
            try:
                actual = parse_time(item["valid_time_utc"])
                nominal = parse_time(item["nominal_time_utc"])
                actual_times.append(actual)
                nominal_times.append(nominal)
            except Exception:
                errors.append(
                    f"Invalid frame/nominal time: {item.get('valid_time_utc')} / {item.get('nominal_time_utc')}"
                )
                continue

            offset = abs((actual - nominal).total_seconds()) / 60.0
            tolerance = float(m.get("slot_tolerance_minutes", 4.5))
            if offset > tolerance + 1e-6:
                errors.append(
                    f"Frame {item.get('valid_time_utc')} is {offset:.2f} min from its nominal slot"
                )

            path = root / item.get("png", "")
            if not path.exists() or path.stat().st_size < 10_000:
                errors.append(f"Missing/implausible frame: {path}")

        if actual_times and actual_times != sorted(actual_times):
            errors.append("Loop frame times are not chronological")
        if actual_times and len(set(actual_times)) != len(actual_times):
            errors.append("Loop contains duplicate valid times")
        if nominal_times and nominal_times != sorted(nominal_times):
            errors.append("Loop nominal slot times are not chronological")
        if nominal_times and len(set(nominal_times)) != len(nominal_times):
            errors.append("Loop contains duplicate nominal slots")

        if len(nominal_times) >= 2:
            nominal_gaps = [
                (b - a).total_seconds() / 60.0
                for a, b in zip(nominal_times, nominal_times[1:])
            ]
            for gap in nominal_gaps:
                # Missing slots are allowed, but any gap larger than the operational
                # ceiling is rejected.  A normal package has exactly 10-min gaps.
                if gap < args.expected_cadence_minutes - 0.01:
                    errors.append(f"Nominal MRMS cadence is too dense: {gap:.1f} minutes")
                    break
                if gap > args.max_gap_minutes + 0.01:
                    errors.append(f"MRMS archive contains a {gap:.1f}-minute nominal gap")
                    break

            span = (nominal_times[-1] - nominal_times[0]).total_seconds() / 60.0
            if span < args.minimum_span_minutes:
                errors.append(f"Loop spans only {span:.1f} nominal minutes")

            latest_nominal = nominal_times[-1]
            cutoff = latest_nominal.timestamp() - args.default_window_minutes * 60.0
            default_times = [item for item in nominal_times if item.timestamp() >= cutoff - 1e-6]
            if len(default_times) < args.minimum_default_window_frames:
                errors.append(
                    f"Default two-hour window has only {len(default_times)} frames; "
                    f"expected at least {args.minimum_default_window_frames}"
                )
            if len(default_times) >= 2:
                default_span = (default_times[-1] - default_times[0]).total_seconds() / 60.0
                if default_span < 110.0:
                    errors.append(f"Default two-hour window spans only {default_span:.1f} minutes")

        if frames:
            latest_path = root / frames[-1]["png"]
            if latest_path.exists():
                with Image.open(latest_path) as image:
                    rgba = image.convert("RGBA")
                    if rgba.width < 6000 or rgba.height < 3000:
                        errors.append(f"Latest frame dimensions are too small: {rgba.size}")
                    if rgba.getchannel("A").getbbox() is None:
                        errors.append("Latest frame has no visible radar pixels")

    if errors:
        print("MRMS RALA loop validation FAILED:")
        for error in errors:
            print(f" - {error}")
        return 1
    print("MRMS RALA loop validation PASS: six-hour archive, 10-minute cadence, two-hour default")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
