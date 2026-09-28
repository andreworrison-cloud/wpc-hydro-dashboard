#!/usr/bin/env python3
"""Build guarded CONUS display derivatives from NASA NLDAS-3 static classes.

The NASA NetCDF is the scientific source. Output PNGs are browser display
derivatives only and must never be used as hydrologic-model inputs.
"""

from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
import s3fs
import xarray as xr
from PIL import Image
from rasterio.crs import CRS
from rasterio.transform import from_bounds
from rasterio.warp import Resampling, reproject, transform_bounds

UTC = timezone.utc
SOURCE_KEY = "nasa-waterinsight/NLDAS3/static/NLDAS-3_dominant-soil-vegetation.nc"
SOURCE_URL = f"s3://{SOURCE_KEY}"
TARGET_CRS = "EPSG:3857"
SOURCE_CRS = "EPSG:4326"
DEFAULT_EXTENT = (-125.0, -66.5, 23.0, 50.5)  # west, east, south, north
DEFAULT_WIDTH = 9000
MISSING = -9999.0

SOIL_CLASSES = {
    1: "Sand",
    2: "Loamy Sand",
    3: "Sandy Loam",
    4: "Silt Loam",
    5: "Silt",
    6: "Loam",
    7: "Sandy Clay Loam",
    8: "Silty Clay Loam",
    9: "Clay Loam",
    10: "Sandy Clay",
    11: "Silty Clay",
    12: "Clay",
    13: "Organic Material",
    14: "Water",
    15: "Bedrock",
    16: "Other (Land Ice)",
}

LANDCOVER_CLASSES = {
    1: "Evergreen Needleleaf Forest",
    2: "Evergreen Broadleaf Forest",
    3: "Deciduous Needleleaf Forest",
    4: "Deciduous Broadleaf Forest",
    5: "Mixed Forests",
    6: "Closed Shrublands",
    7: "Open Shrublands",
    8: "Woody Savannas",
    9: "Savannas",
    10: "Grasslands",
    11: "Permanent Wetland",
    12: "Croplands",
    13: "Urban and Built-Up",
    14: "Cropland/Natural Vegetation Mosaic",
    15: "Snow and Ice",
    16: "Barren or Sparsely Vegetated",
    17: "Ocean",
    18: "Wooded Tundra",
    19: "Mixed Tundra",
    20: "Bare Ground Tundra",
    21: "Open Water (LIS template surface)",
}

# Dashboard visualization palettes only; not claimed to be official NASA colors.
SOIL_COLORS = {
    1: "#f6e8c3", 2: "#dfc27d", 3: "#d8b365", 4: "#c2a67d",
    5: "#b9a37a", 6: "#a98f6a", 7: "#d95f0e", 8: "#e34a33",
    9: "#cb181d", 10: "#a50f15", 11: "#99000d", 12: "#67000d",
    13: "#5b3a29", 14: "#000000", 15: "#7f7f7f", 16: "#d9d9d9",
}
LANDCOVER_COLORS = {
    1: "#05450a", 2: "#086a10", 3: "#54a708", 4: "#78d203",
    5: "#009900", 6: "#c6b044", 7: "#dcd159", 8: "#dade48",
    9: "#fbff13", 10: "#b6ff05", 11: "#27ff87", 12: "#c24f44",
    13: "#a5a5a5", 14: "#ff6d4c", 15: "#69fff8", 16: "#f9ffa4",
    17: "#000000", 18: "#6b7d2a", 19: "#8f9a4d", 20: "#c2b280",
    21: "#000000",
}


def rgb(hex_color: str) -> tuple[int, int, int]:
    value = hex_color.lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def validate_regular_axis(
    values: np.ndarray,
    name: str,
    expected_step: float,
) -> float:
    values = np.asarray(values, dtype=np.float64)
    if values.ndim != 1 or values.size < 2:
        raise RuntimeError(f"{name} must be a 1-D regular coordinate")
    diffs = np.diff(values)
    if not np.all(np.isfinite(diffs)):
        raise RuntimeError(f"{name} contains non-finite coordinate spacing")
    if not np.isfinite(expected_step) or expected_step <= 0:
        raise RuntimeError(f"{name}: missing/invalid NASA grid spacing attribute")
    step = float(np.median(diffs))
    # Coordinates are stored as float32. Validate against NASA's stated DX/DY,
    # allowing only the expected representation jitter at large coordinate values.
    if not np.allclose(diffs, expected_step, rtol=0.0, atol=1.5e-5):
        raise RuntimeError(
            f"{name} spacing departs from NASA grid attribute: "
            f"median={step:.10f}, expected={expected_step:.10f}"
        )
    return step


def subset_slices(lat: np.ndarray, lon: np.ndarray, extent) -> tuple[slice, slice]:
    west, east, south, north = map(float, extent)
    lat_mask = np.where((lat >= south - 0.02) & (lat <= north + 0.02))[0]
    lon_mask = np.where((lon >= west - 0.02) & (lon <= east + 0.02))[0]
    if lat_mask.size == 0 or lon_mask.size == 0:
        raise RuntimeError("Requested CONUS extent does not intersect NLDAS-3 grid")
    return (
        slice(int(lat_mask.min()), int(lat_mask.max()) + 1),
        slice(int(lon_mask.min()), int(lon_mask.max()) + 1),
    )


def validate_categories(values: np.ndarray, allowed: set[int], product: str) -> np.ndarray:
    valid = np.isfinite(values) & (values != MISSING)
    observed = values[valid]
    if observed.size == 0:
        raise RuntimeError(f"{product}: no valid source cells found")
    rounded = np.rint(observed)
    if not np.allclose(observed, rounded, rtol=0.0, atol=1.0e-6):
        raise RuntimeError(f"{product}: encountered non-integer-like category values")
    codes = rounded.astype(np.int16)
    unexpected = sorted(set(np.unique(codes).tolist()) - allowed)
    if unexpected:
        raise RuntimeError(f"{product}: unexpected source class codes {unexpected}")
    return valid


def source_transform(
    lat: np.ndarray,
    lon: np.ndarray,
    expected_dy: float,
    expected_dx: float,
):
    lat_step = validate_regular_axis(lat, "latitude", expected_dy)
    lon_step = validate_regular_axis(lon, "longitude", expected_dx)
    if lon_step <= 0:
        raise RuntimeError("Expected NLDAS-3 longitude to increase eastward")

    data_flip = lat_step > 0
    lat_north = float(lat[-1] if data_flip else lat[0])
    lat_south = float(lat[0] if data_flip else lat[-1])
    west = float(lon[0] - lon_step / 2.0)
    east = float(lon[-1] + lon_step / 2.0)
    south = float(lat_south - abs(lat_step) / 2.0)
    north = float(lat_north + abs(lat_step) / 2.0)
    transform = from_bounds(west, south, east, north, lon.size, lat.size)
    return transform, data_flip, (west, south, east, north)


def target_grid(extent, width: int):
    west, east, south, north = map(float, extent)
    left, bottom, right, top = transform_bounds(
        SOURCE_CRS, TARGET_CRS, west, south, east, north, densify_pts=21
    )
    height = max(1, int(round(width * (top - bottom) / (right - left))))
    return height, from_bounds(left, bottom, right, top, width, height)


def reproject_codes(
    values: np.ndarray,
    valid_mask: np.ndarray,
    src_transform,
    flip_y: bool,
    extent,
    width: int,
    transparent_codes: set[int],
) -> np.ndarray:
    codes = np.zeros(values.shape, dtype=np.uint8)
    rounded = np.rint(values[valid_mask]).astype(np.int16)
    codes[valid_mask] = rounded.astype(np.uint8)
    for code in transparent_codes:
        codes[codes == code] = 0
    if flip_y:
        codes = np.flipud(codes)

    height, dst_transform = target_grid(extent, width)
    dst = np.zeros((height, width), dtype=np.uint8)
    reproject(
        source=codes,
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
    return dst


def write_indexed_png(
    codes: np.ndarray,
    path: Path,
    colors: dict[int, str],
) -> None:
    palette = [0] * (256 * 3)
    for code, color in colors.items():
        r, g, b = rgb(color)
        palette[3 * code:3 * code + 3] = [r, g, b]
    image = Image.fromarray(codes, mode="P")
    image.putpalette(palette)
    transparency = bytes([0] + [255] * 255)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, optimize=True, compress_level=9, transparency=transparency)


def class_metadata(classes: dict[int, str], colors: dict[int, str], counts: np.ndarray):
    out = []
    visible_total = int(counts[1:].sum())
    for code, label in classes.items():
        count = int(counts[code]) if code < counts.size else 0
        out.append({
            "code": code,
            "label": label,
            "color": colors[code],
            "display_pixel_count": count,
            "display_fraction": (count / visible_total if visible_total else 0.0),
        })
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=Path("nldas3_build"))
    parser.add_argument("--width", type=int, default=DEFAULT_WIDTH)
    parser.add_argument(
        "--extent",
        type=float,
        nargs=4,
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
            fh,
            engine="h5netcdf",
            decode_times=False,
            mask_and_scale=False,
            chunks=None,
        )
        required = {"lat", "lon", "Landcover_inst", "Soiltype_inst"}
        missing_vars = required - set(ds.variables)
        if missing_vars:
            raise RuntimeError(f"NLDAS-3 source missing required fields: {sorted(missing_vars)}")

        lat_full = np.asarray(ds["lat"].values, dtype=np.float64)
        lon_full = np.asarray(ds["lon"].values, dtype=np.float64)
        ys, xs = subset_slices(lat_full, lon_full, args.extent)
        lat = lat_full[ys]
        lon = lon_full[xs]

        land = np.asarray(ds["Landcover_inst"].isel(north_south=ys, east_west=xs).load().values)
        soil = np.asarray(ds["Soiltype_inst"].isel(north_south=ys, east_west=xs).load().values)
        source_history = str(ds.attrs.get("history", "Unknown"))
        source_dx = float(ds.attrs.get("DX", float("nan")))
        source_dy = float(ds.attrs.get("DY", float("nan")))
        ds.close()

    land_valid = validate_categories(land, set(LANDCOVER_CLASSES), "NLDAS-3 land cover")
    soil_valid = validate_categories(soil, set(SOIL_CLASSES), "NLDAS-3 soil texture")

    transform, flip_y, source_bounds = source_transform(
        lat, lon, expected_dy=source_dy, expected_dx=source_dx
    )
    land_png = reproject_codes(
        land, land_valid, transform, flip_y, args.extent, args.width, {17, 21}
    )
    soil_png = reproject_codes(
        soil, soil_valid, transform, flip_y, args.extent, args.width, {14}
    )

    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    soil_path = output_dir / "nldas3_soil_texture.png"
    land_path = output_dir / "nldas3_landcover.png"
    meta_path = output_dir / "nldas3_static_metadata.json"
    write_indexed_png(soil_png, soil_path, SOIL_COLORS)
    write_indexed_png(land_png, land_path, LANDCOVER_COLORS)

    soil_counts = np.bincount(soil_png.ravel(), minlength=256)
    land_counts = np.bincount(land_png.ravel(), minlength=256)
    west, east, south, north = map(float, args.extent)
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    metadata: dict[str, Any] = {
        "metadata_mode": "nldas3_static_dashboard_v1",
        "render_revision": "nldas3-static-phase1-v1",
        "generated_utc": now,
        "source": SOURCE_URL,
        "source_history": source_history,
        "source_grid": {
            "projection": "equidistant cylindrical / latitude-longitude",
            "native_dx_deg": float(abs(np.median(np.diff(lon)))),
            "native_dy_deg": float(abs(np.median(np.diff(lat)))),
            "subset_source_bounds": list(source_bounds),
        },
        "domain": "CONUS dashboard extent",
        "bounds": [[south, west], [north, east]],
        "image_crs": TARGET_CRS,
        "categorical": True,
        "display_resampling": "nearest-neighbor",
        "smoothing": False,
        "scientific_use_note": (
            "Dashboard PNGs are display derivatives only. Future infiltration/runoff/FFG "
            "calculations must use retained scientific NLDAS-3 source/analysis rasters."
        ),
        "soil_texture": {
            "source_variable": "Soiltype_inst",
            "classification": "STATSGO 16-class texture index",
            "water_code": 14,
            "water_display": "transparent",
            "image": "nldas3_soil_texture.png",
            "classes": class_metadata(SOIL_CLASSES, SOIL_COLORS, soil_counts),
        },
        "landcover": {
            "source_variable": "Landcover_inst",
            "classification": "IGBP/NCEP-modified 20-class land cover + LIS open-water surface type",
            "water_codes": [17, 21],
            "water_display": "transparent",
            "image": "nldas3_landcover.png",
            "classes": class_metadata(LANDCOVER_CLASSES, LANDCOVER_COLORS, land_counts),
        },
        "palette_note": "Colors are WPC dashboard visualization palettes, not official NASA colors.",
    }
    meta_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    print(f"Wrote {soil_path} ({soil_path.stat().st_size / 1024 / 1024:.2f} MiB)", flush=True)
    print(f"Wrote {land_path} ({land_path.stat().st_size / 1024 / 1024:.2f} MiB)", flush=True)
    print(f"Wrote {meta_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
