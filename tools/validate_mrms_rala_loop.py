#!/usr/bin/env python3
"""Validate the dashboard-ready rolling MRMS RALA loop package."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

UTC = timezone.utc


def parse_time(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("output_dir", nargs="?", default="mrms_rala_loop_publish")
    p.add_argument("--minimum-frames", type=int, default=45)
    args = p.parse_args()

    root = Path(args.output_dir)
    manifest_path = root / "mrms_rala_loop_manifest.json"
    errors = []
    if not manifest_path.exists():
        errors.append(f"Missing manifest: {manifest_path}")
    else:
        m = json.loads(manifest_path.read_text(encoding="utf-8"))
        if m.get("metadata_mode") != "mrms_rala_loop_manifest_v2":
            errors.append("Unexpected MRMS RALA loop metadata_mode")
        if m.get("product") != "ReflectivityAtLowestAltitude" or m.get("units") != "dBZ":
            errors.append("Unexpected MRMS RALA product/units")
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
        times = []
        for item in frames:
            try:
                times.append(parse_time(item["valid_time_utc"]))
            except Exception:
                errors.append(f"Invalid frame time: {item.get('valid_time_utc')}")
                continue
            path = root / item.get("png", "")
            if not path.exists() or path.stat().st_size < 10_000:
                errors.append(f"Missing/implausible frame: {path}")
                continue
        if times and times != sorted(times):
            errors.append("Loop frame times are not chronological")
        if times and len(set(times)) != len(times):
            errors.append("Loop contains duplicate valid times")
        if len(times) >= 2:
            span = (times[-1] - times[0]).total_seconds() / 60.0
            if span < 100:
                errors.append(f"Loop spans only {span:.1f} minutes")
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
    print("MRMS RALA loop validation PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
