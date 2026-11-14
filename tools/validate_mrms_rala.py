#!/usr/bin/env python3
"""Validate a generated MRMS RALA diagnostic package."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from PIL import Image
import numpy as np


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output_dir", nargs="?", default="diagnostics/mrms_rala")
    parser.add_argument("--allow-stale", action="store_true")
    args = parser.parse_args()
    root = Path(args.output_dir)
    errors = []

    png = root / "mrms_rala_conus_latest.png"
    metadata_path = root / "mrms_rala_metadata.json"
    manifest_path = root / "mrms_rala_manifest.json"
    diagnostics_path = root / "mrms_rala_source_diagnostics.json"
    for path in (png, metadata_path, manifest_path, diagnostics_path):
        if not path.exists():
            errors.append(f"Missing output: {path}")

    if not errors:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if metadata.get("metadata_mode") != "mrms_rala_dashboard_v1":
            errors.append("Unexpected RALA metadata_mode")
        if metadata.get("product") != "ReflectivityAtLowestAltitude":
            errors.append("Unexpected MRMS product")
        if metadata.get("units") != "dBZ":
            errors.append("RALA units are not dBZ")
        if manifest.get("metadata_mode") != "mrms_rala_dashboard_manifest_v1":
            errors.append("Unexpected RALA manifest contract")
        if manifest.get("png") != png.name or manifest.get("metadata") != metadata_path.name:
            errors.append("Manifest file references do not match expected names")
        bounds = manifest.get("bounds")
        if not (isinstance(bounds, list) and len(bounds) == 2 and all(len(row) == 2 for row in bounds)):
            errors.append("Manifest Leaflet bounds are invalid")
        if not metadata.get("fresh", False) and not args.allow_stale:
            errors.append("Generated RALA source is stale")

        with Image.open(png) as image:
            if image.mode != "RGBA":
                errors.append(f"PNG mode is {image.mode}, expected RGBA")
            if image.width < 4000 or image.height < 1800:
                errors.append(f"PNG dimensions are too small: {image.size}")
            alpha = np.asarray(image.getchannel("A"))
            visible = int(np.count_nonzero(alpha))
            transparent = int(alpha.size - visible)
            if visible < 100:
                errors.append("PNG has too few visible radar pixels")
            if transparent < 100:
                errors.append("PNG does not preserve transparent no-echo/background pixels")

    if errors:
        print("MRMS RALA validation FAILED:")
        for error in errors:
            print(f" - {error}")
        return 1
    print("MRMS RALA validation PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
