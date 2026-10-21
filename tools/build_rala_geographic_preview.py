#!/usr/bin/env python3
"""Create a diagnostic-only geographic reference preview for a RALA PNG.

The dashboard PNG itself remains untouched.  This preview overlays coastlines,
country borders, U.S. state boundaries, and a lat/lon grid solely to verify that
Web-Mercator placement is correct before dashboard integration.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from PIL import Image
from mpl_toolkits.basemap import Basemap


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("output_dir", nargs="?", default="diagnostics/mrms_rala")
    args = p.parse_args()
    root = Path(args.output_dir)
    png_path = root / "mrms_rala_conus_latest.png"
    meta_path = root / "mrms_rala_metadata.json"
    preview_path = root / "mrms_rala_geographic_preview.png"

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    (south, west), (north, east) = meta["display"]["leaflet_bounds"]
    image = np.asarray(Image.open(png_path).convert("RGBA"))

    fig, ax = plt.subplots(figsize=(16, 10))
    m = Basemap(
        epsg=3857,
        llcrnrlon=west, llcrnrlat=south,
        urcrnrlon=east, urcrnrlat=north,
        resolution="l", ax=ax,
    )
    ax.set_facecolor("white")
    ax.imshow(
        image, origin="upper",
        extent=[m.xmin, m.xmax, m.ymin, m.ymax],
        interpolation="nearest", zorder=1,
    )
    m.drawcoastlines(linewidth=0.85, zorder=3)
    m.drawcountries(linewidth=0.8, zorder=3)
    m.drawstates(linewidth=0.45, zorder=3)
    m.drawparallels(np.arange(20, 56, 5), labels=[1, 0, 0, 0], linewidth=0.2, zorder=2)
    m.drawmeridians(np.arange(-130, -59, 10), labels=[0, 0, 0, 1], linewidth=0.2, zorder=2)

    valid = meta.get("source_valid_time_utc", "unknown")
    provider = meta.get("source_provider", "unknown")
    cutoff = meta.get("display", {}).get("visible_minimum_dbz", "?")
    ax.set_title(
        f"MRMS Reflectivity at Lowest Altitude — Geographic Placement Check\n"
        f"Valid {valid} | {provider} | transparent below {cutoff} dBZ",
        fontsize=13,
    )
    fig.savefig(preview_path, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)

    if preview_path.stat().st_size < 50_000:
        raise SystemExit("Geographic preview is implausibly small")
    print(f"MRMS geographic preview PASS: {preview_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
