#!/usr/bin/env python3
"""Build diagnostic-only 10/15 dBZ transparency variants from the selected RALA frame.

These previews do not alter mrms_rala_conus_latest.png or the dashboard metadata.
They are only for deciding whether weak-echo clutter at the current 5 dBZ cutoff
is desirable for the WPC dashboard presentation.
"""
from __future__ import annotations

import argparse
import gzip
import json
import tempfile
from datetime import datetime
from pathlib import Path
import sys

# When a script is launched as ``python tools/<script>.py``, Python places the
# tools directory (not the repository root) on sys.path.  Add the repository
# root explicitly so the shared MRMS backend module can be imported reliably
# both in GitHub Actions and during local diagnostic runs.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import numpy as np
from PIL import Image

import fetch_mrms_rala as rala


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("output_dir", nargs="?", default="diagnostics/mrms_rala")
    args = p.parse_args()
    root = Path(args.output_dir)
    meta = json.loads((root / "mrms_rala_metadata.json").read_text(encoding="utf-8"))
    url = meta["source_url"]
    timestamp = datetime.fromisoformat(meta["source_valid_time_utc"].replace("Z", "+00:00"))
    candidate = rala.SourceCandidate(
        provider=meta["source_provider"], timestamp=timestamp,
        url=url, key=meta["source_key"],
    )
    width = int(meta["display"]["image_width_px"])

    session = rala.make_session()
    with tempfile.TemporaryDirectory(prefix="rala_threshold_") as td:
        td = Path(td)
        gz_path = td / "rala.grib2.gz"
        grib_path = td / "rala.grib2"
        rala.download_file(session, candidate, gz_path)
        rala.gunzip_file(gz_path, grib_path)
        data, src_transform, _ = rala.decode_grib(grib_path)
        projected, _, _ = rala.reproject_dbz(data, src_transform, width)

    base = rala.colorize(projected)
    counts = {}
    for threshold in (5.0, 10.0, 15.0):
        rgba = base.copy()
        rgba[~np.isfinite(projected) | (projected < threshold), 3] = 0
        out = root / f"mrms_rala_threshold_{int(threshold):02d}dbz.png"
        Image.fromarray(rgba, mode="RGBA").save(out, format="PNG", compress_level=6)
        counts[str(int(threshold))] = int(np.count_nonzero(rgba[..., 3]))
        print(f"Threshold {threshold:.0f} dBZ: {counts[str(int(threshold))]:,} visible pixels -> {out.name}")

    summary = {
        "source_valid_time_utc": meta["source_valid_time_utc"],
        "source_provider": meta["source_provider"],
        "purpose": "diagnostic-only weak-echo cutoff comparison; production PNG unchanged",
        "visible_pixel_counts": counts,
    }
    (root / "mrms_rala_threshold_preview_summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    print("MRMS threshold preview generation PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
