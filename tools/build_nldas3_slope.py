#!/usr/bin/env python3
"""Build a guarded CONUS display derivative for NASA NLDAS-3 / MERIT slope.

This creates a descriptive percent-slope map only. The bins are display ranges,
not runoff-risk or flash-flood-risk classes, and the browser PNG must never be
used as a scientific input to future hourly-FFG calculations.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import rasterio
import s3fs
import xarray as xr
from PIL import Image
from rasterio.crs import CRS
from rasterio.transform import from_bounds
from rasterio.warp import Resampling, reproject, transform_bounds

UTC = timezone.utc

SOURCE_KEY = "nasa-waterinsight/NLDAS3/static/lis_input.nldas3.noahmp401.1km.hymap.nc"
SOURCE_URL = f"s3://{SOURCE_KEY}"
VARIABLE = "SLOPE"
SOURCE_CRS = "EPSG:4326"
TARGET_CRS = "EPSG:3857"
DEFAULT_EXTENT = (-125.0, -66.5, 23.0, 50.5)  # west, east, south, north
DEFAULT_WIDTH = 9000
MISSING = -9999.0

# Descriptive terrain-slope ranges only. These are not hydrologic-risk classes.
SLOPE_BINS = [
    {"code": 1, "min": 0.0,  "max": 1.0,  "label": "0–1%",   "color": "#f7f4ea"},
    {"code": 2, "min": 1.0,  "max": 2.0,  "label": "1–2%",   "color": "#e9dfc5"},
    {"code": 3, "min": 2.0,  "max": 5.0,  "label": "2–5%",   "color": "#d7c29a"},
    {"code": 4, "min": 5.0,  "max": 10.0, "label": "5–10%",  "color": "#c0a36f"},
    {"code": 5, "min": 10.0, "max": 20.0, "label": "10–20%", "color": "#a8844d"},
    {"code": 6, "min": 20.0, "max": 30.0, "label": "20–30%", "color": "#89643a"},
    {"code": 7, "min": 30.0, "max": 45.0, "label": "30–45%", "color": "#6b472b"},
    {"code": 8, "min": 45.0, "max": 60.0, "label": "45–60%", "color": "#4c301f"},
    {"code": 9, "min": 60.0, "max": None, "label": "≥60%",   "color": "#2f1d13"},
]


def hex_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return tuple(int(value[i:i+2], 16) for i in (0, 2, 4))


def index_bounds(extent, sw_lon, sw_lat, dx, dy, nx, ny):
    west, east, south, north = map(float, extent)
    x0 = max(0, int(np.floor((west - sw_lon) / dx)) - 2)
    x1 = min(nx, int(np.ceil((east - sw_lon) / dx)) + 3)
    y0 = max(0, int(np.floor((south - sw_lat) / dy)) - 2)
    y1 = min(ny, int(np.ceil((north - sw_lat) / dy)) + 3)
    if x1 <= x0 or y1 <= y0:
        raise RuntimeError("Requested extent does not intersect NLDAS-3 grid")
    return slice(y0, y1), slice(x0, x1)


def source_transform(ys: slice, xs: slice, sw_lon: float, sw_lat: float, dx: float, dy: float):
    west_center = sw_lon + xs.start * dx
    east_center = sw_lon + (xs.stop - 1) * dx
    south_center = sw_lat + ys.start * dy
    north_center = sw_lat + (ys.stop - 1) * dy
    west = west_center - dx / 2.0
    east = east_center + dx / 2.0
    south = south_center - dy / 2.0
    north = north_center + dy / 2.0
    width = xs.stop - xs.start
    height = ys.stop - ys.start
    return from_bounds(west, south, east, north, width, height), (west, south, east, north)


def target_grid(extent, width: int):
    west, east, south, north = map(float, extent)
    left, bottom, right, top = transform_bounds(
        SOURCE_CRS, TARGET_CRS, west, south, east, north, densify_pts=21
    )
    height = max(1, int(round(width * (top - bottom) / (right - left))))
    return height, from_bounds(left, bottom, right, top, width, height)


def classify(percent: np.ndarray, valid: np.ndarray) -> np.ndarray:
    codes = np.zeros(percent.shape, dtype=np.uint8)
    for item in SLOPE_BINS:
        lo = float(item["min"])
        hi = item["max"]
        mask = valid & (percent >= lo)
        if hi is not None:
            mask &= percent < float(hi)
        codes[mask] = int(item["code"])
    if np.any(valid & (codes == 0)):
        raise RuntimeError("Some valid slope cells were not assigned a display bin")
    return codes


def write_png(codes: np.ndarray, path: Path):
    palette = [0] * (256 * 3)
    for item in SLOPE_BINS:
        r, g, b = hex_rgb(item["color"])
        code = int(item["code"])
        palette[3*code:3*code+3] = [r, g, b]
    image = Image.fromarray(codes, mode="P")
    image.putpalette(palette)
    transparency = bytes([0] + [235] * 255)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, format="PNG", optimize=True, compress_level=9, transparency=transparency)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=Path("nldas3_slope_build"))
    parser.add_argument("--width", type=int, default=DEFAULT_WIDTH)
    parser.add_argument(
        "--extent", type=float, nargs=4,
        metavar=("WEST", "EAST", "SOUTH", "NORTH"),
        default=DEFAULT_EXTENT,
    )
    args = parser.parse_args()

    if args.width < 1000:
        raise SystemExit("--width must be at least 1000")

    s3 = s3fs.S3FileSystem(anon=True, client_kwargs={"region_name": "us-west-2"})
    print(f"Opening {SOURCE_URL}", flush=True)
    with s3.open(SOURCE_KEY, "rb") as fh:
        ds = xr.open_dataset(
            fh, engine="h5netcdf", decode_times=False,
            mask_and_scale=False, chunks=None,
        )
        if VARIABLE not in ds.variables:
            raise RuntimeError(f"Missing {VARIABLE} in source file")

        dx = float(ds.attrs["DX"])
        dy = float(ds.attrs["DY"])
        sw_lat = float(ds.attrs["SOUTH_WEST_CORNER_LAT"])
        sw_lon = float(ds.attrs["SOUTH_WEST_CORNER_LON"])
        ny = int(ds.sizes["north_south"])
        nx = int(ds.sizes["east_west"])
        ys, xs = index_bounds(args.extent, sw_lon, sw_lat, dx, dy, nx, ny)

        da = ds[VARIABLE]
        attrs = {str(k): str(v) for k, v in da.attrs.items()}
        if str(attrs.get("standard_name", "")) != "MERIT '1K' slope":
            raise RuntimeError(f"Unexpected SLOPE standard_name: {attrs.get('standard_name')}")
        raw = np.asarray(da.isel(north_south=ys, east_west=xs).load().values, dtype=np.float64)
        source_history = str(ds.attrs.get("history", "Unknown"))
        ds.close()

    valid = np.isfinite(raw) & (raw != MISSING)
    values = raw[valid]
    if values.size == 0:
        raise RuntimeError("No valid slope cells")
    if np.any(values < 0):
        raise RuntimeError("Negative slope values encountered")
    if float(values.max()) > 2.0:
        raise RuntimeError(
            f"Unexpectedly large dimensionless slope={values.max():.3f}; review units before publishing"
        )

    percent = raw * 100.0
    src_codes = classify(percent, valid)

    src_transform, subset_bounds = source_transform(ys, xs, sw_lon, sw_lat, dx, dy)
    # Source rows increase northward; rasterio expects row zero at the north edge.
    src_codes = np.flipud(src_codes)

    height, dst_transform = target_grid(args.extent, args.width)
    dst = np.zeros((height, args.width), dtype=np.uint8)
    reproject(
        source=src_codes,
        destination=dst,
        src_transform=src_transform,
        src_crs=CRS.from_epsg(4326),
        src_nodata=0,
        dst_transform=dst_transform,
        dst_crs=CRS.from_epsg(3857),
        dst_nodata=0,
        resampling=Resampling.nearest,
        init_dest_nodata=True,
        num_threads=2,
    )

    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    image_path = output_dir / "nldas3_slope_percent.png"
    metadata_path = output_dir / "nldas3_slope_metadata.json"
    write_png(dst, image_path)

    counts = np.bincount(dst.ravel(), minlength=10)
    visible_total = int(counts[1:10].sum())
    display_bins = []
    for item in SLOPE_BINS:
        code = int(item["code"])
        count = int(counts[code])
        display_bins.append({
            **item,
            "display_pixel_count": count,
            "display_fraction": float(count / visible_total) if visible_total else 0.0,
        })

    west, east, south, north = map(float, args.extent)
    stats = {
        "min_percent": float(np.min(values) * 100.0),
        "median_percent": float(np.percentile(values, 50) * 100.0),
        "p90_percent": float(np.percentile(values, 90) * 100.0),
        "p95_percent": float(np.percentile(values, 95) * 100.0),
        "p99_percent": float(np.percentile(values, 99) * 100.0),
        "max_percent": float(np.max(values) * 100.0),
    }
    metadata = {
        "metadata_mode": "nldas3_static_slope_dashboard_v1",
        "render_revision": "nldas3-merit-slope-phase1b-v1",
        "generated_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": SOURCE_URL,
        "source_history": source_history,
        "source_variable": VARIABLE,
        "source_standard_name": attrs.get("standard_name"),
        "source_units_attribute": attrs.get("units"),
        "physical_interpretation": "surface slope expressed as dimensionless rise/run; dashboard labels convert to percent slope",
        "domain": "CONUS dashboard extent",
        "bounds": [[south, west], [north, east]],
        "image": "nldas3_slope_percent.png",
        "image_crs": TARGET_CRS,
        "image_width": int(args.width),
        "image_height": int(height),
        "source_grid": {
            "dx_deg": dx,
            "dy_deg": dy,
            "subset_source_bounds": list(subset_bounds),
        },
        "display": {
            "categorical_descriptive_bins": True,
            "display_resampling": "nearest-neighbor",
            "smoothing": False,
            "transparent_missing_water": True,
            "bins": display_bins,
        },
        "source_stats": stats,
        "science_safeguards": [
            "Percent-slope bins are descriptive terrain ranges, not runoff-risk classes.",
            "The browser PNG is a display derivative only.",
            "Future hourly-FFG calculations must use retained source/scientific arrays, not this PNG.",
            "No infiltration or flash-flood threshold is inferred from slope alone.",
        ],
    }
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(json.dumps(stats, indent=2), flush=True)
    print(f"Wrote {image_path} ({image_path.stat().st_size / 1024 / 1024:.2f} MiB)", flush=True)
    print(f"Wrote {metadata_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
