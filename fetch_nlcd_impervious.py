#!/usr/bin/env python3
"""Publish the validated WPC Phase H2 Annual NLCD dashboard derivative.

This is a publication helper, not the national native-30m build. It consumes
the retained, QA-approved Phase H2 v1.1 GeoTIFF science and recreates the static
dashboard PNG + metadata. Future H4/dynamic calculations must use the retained
GeoTIFF science, never this PNG.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import rasterio
from PIL import Image
from pyproj import Transformer
from rasterio.crs import CRS
from rasterio.enums import Resampling
from rasterio.transform import from_bounds
from rasterio.warp import reproject

METADATA_MODE = "usgs_nlcd_fractional_impervious_h2_dashboard_v1_1_final"
ANALYSIS_METADATA_MODE = "annual_nlcd_fractional_impervious_h2_v1_1"
RENDER_REVISION = "annual-nlcd-fctimp-2025-h2-v1-1-final"

EXPECTED_SOURCE = "USGS Annual NLCD Collection 1.2 Fractional Impervious Surface"
EXPECTED_SOURCE_PRODUCT = "FctImp"
EXPECTED_MAP_YEAR = 2025
EXPECTED_SOURCE_NATIVE_RESOLUTION_M = 30
EXPECTED_ANALYSIS_RESOLUTION_M = 1000
EXPECTED_ANALYSIS_CRS = "EPSG:5070"
EXPECTED_GRID_WIDTH = 4621
EXPECTED_GRID_HEIGHT = 2913

TARGET_CRS = "EPSG:3857"
DISPLAY_BOUNDS = (-125.0, 23.0, -66.5, 50.5)
DEFAULT_OUTPUT_WIDTH = 9000
MINIMUM_VALID_COVERAGE = 0.25

OUTPUT_IMAGE = "usgs_nlcd_fractional_impervious_2025.png"
OUTPUT_METADATA = "usgs_nlcd_fractional_impervious_2025_metadata.json"

DISPLAY_BINS = [
    {"min": 0.0, "max": 5.0, "color": "#ffffcc", "label": ">0–5%"},
    {"min": 5.0, "max": 10.0, "color": "#ffeda0", "label": "5–10%"},
    {"min": 10.0, "max": 20.0, "color": "#fed976", "label": "10–20%"},
    {"min": 20.0, "max": 40.0, "color": "#feb24c", "label": "20–40%"},
    {"min": 40.0, "max": 60.0, "color": "#fd8d3c", "label": "40–60%"},
    {"min": 60.0, "max": 80.0, "color": "#f03b20", "label": "60–80%"},
    {"min": 80.0, "max": 100.0001, "color": "#bd0026", "label": "80–100%"},
]


def hex_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    if len(value) != 6:
        raise ValueError(f"Expected #RRGGBB color, got {value!r}")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def load_analysis_metadata(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("mode") != ANALYSIS_METADATA_MODE:
        raise ValueError(f"Unexpected analysis mode: {data.get('mode')!r}")
    if data.get("revision") != "native30m_conus_v1_1_final":
        raise ValueError(f"Unexpected analysis revision: {data.get('revision')!r}")

    source = data.get("source") or {}
    analysis = data.get("analysis") or {}
    repair = data.get("v1_1_repair") or {}

    if source.get("dataset") != EXPECTED_SOURCE:
        raise ValueError("Annual NLCD source dataset changed.")
    if source.get("product_code") != EXPECTED_SOURCE_PRODUCT:
        raise ValueError("Annual NLCD product code changed.")
    if int(source.get("map_year", -1)) != EXPECTED_MAP_YEAR:
        raise ValueError("Annual NLCD map year changed.")
    if int(source.get("native_resolution_m", -1)) != EXPECTED_SOURCE_NATIVE_RESOLUTION_M:
        raise ValueError("Annual NLCD native source resolution changed.")
    if str(source.get("native_crs", "")).upper() != EXPECTED_ANALYSIS_CRS:
        raise ValueError("Annual NLCD source CRS changed.")

    if int(analysis.get("resolution_m", -1)) != EXPECTED_ANALYSIS_RESOLUTION_M:
        raise ValueError("Annual NLCD analysis resolution changed.")
    if str(analysis.get("crs", "")).upper() != EXPECTED_ANALYSIS_CRS:
        raise ValueError("Annual NLCD analysis CRS changed.")
    if int(analysis.get("width", -1)) != EXPECTED_GRID_WIDTH or int(analysis.get("height", -1)) != EXPECTED_GRID_HEIGHT:
        raise ValueError("Annual NLCD retained analysis grid dimensions changed.")
    if repair.get("final_qa_status") != "PASS":
        raise ValueError("Phase H2 v1.1 final coverage QA is not PASS.")
    if repair.get("final_qa_file") != "nlcd_h2_v1_1_final_coverage_qa.json":
        raise ValueError("Phase H2 final QA provenance changed.")
    return data


def load_final_qa(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("status") != "PASS":
        raise ValueError("Final H2 coverage QA is not PASS.")
    gates = data.get("gates") or {}
    required = {
        "all_major_retrieval_holes_reduced_ge_99pct",
        "no_large_rectangular_residual_cluster",
        "all_residual_clusters_ge25_have_persistent_source_evidence",
        "artifact_fraction_within_0_1",
        "grid_shape_preserved",
        "grid_alignment_preserved",
    }
    if set(gates) != required or not all(gates.values()):
        raise ValueError("Final H2 coverage QA gates are incomplete or not all PASS.")
    return data


def validate_science_raster(path: Path, *, kind: str):
    with rasterio.open(path) as src:
        if src.crs != CRS.from_epsg(5070):
            raise ValueError(f"{path.name}: expected EPSG:5070, found {src.crs}")
        if (src.width, src.height) != (EXPECTED_GRID_WIDTH, EXPECTED_GRID_HEIGHT):
            raise ValueError(f"{path.name}: unexpected shape {src.width}x{src.height}")
        if src.count != 1 or src.dtypes[0] != "float32":
            raise ValueError(f"{path.name}: expected one float32 band")
        arr = src.read(1).astype(np.float32)
        if src.nodata is not None:
            arr[arr == src.nodata] = np.nan
        profile = src.profile.copy()

    finite = np.isfinite(arr)
    if finite.any():
        low = float(np.nanmin(arr))
        high = float(np.nanmax(arr))
        if kind == "mean" and (low < -1e-4 or high > 100.0001):
            raise ValueError(f"{path.name}: impervious percentage outside 0..100")
        if kind == "coverage" and (low < -1e-6 or high > 1.000001):
            raise ValueError(f"{path.name}: coverage outside 0..1")
    return profile, arr


def publish(mean_tif: Path, coverage_tif: Path, analysis_metadata: Path,
            final_qa: Path, output_dir: Path,
            output_width: int = DEFAULT_OUTPUT_WIDTH) -> dict:
    load_analysis_metadata(analysis_metadata)
    load_final_qa(final_qa)

    mean_profile, mean = validate_science_raster(mean_tif, kind="mean")
    coverage_profile, coverage = validate_science_raster(coverage_tif, kind="coverage")
    if mean_profile["transform"] != coverage_profile["transform"]:
        raise ValueError("Mean and coverage rasters are not exactly aligned.")

    west, south, east, north = DISPLAY_BOUNDS
    to_3857 = Transformer.from_crs(4326, 3857, always_xy=True)
    xmin, ymin = to_3857.transform(west, south)
    xmax, ymax = to_3857.transform(east, north)
    output_height = int(round(output_width * (ymax - ymin) / (xmax - xmin)))
    dst_transform = from_bounds(xmin, ymin, xmax, ymax, output_width, output_height)

    mean_display = np.full((output_height, output_width), np.nan, dtype=np.float32)
    cov_display = np.zeros((output_height, output_width), dtype=np.float32)

    reproject(
        source=mean, destination=mean_display,
        src_transform=mean_profile["transform"], src_crs=mean_profile["crs"],
        src_nodata=np.nan, dst_transform=dst_transform, dst_crs=TARGET_CRS,
        dst_nodata=np.nan, resampling=Resampling.nearest, num_threads=4,
    )
    reproject(
        source=coverage, destination=cov_display,
        src_transform=coverage_profile["transform"], src_crs=coverage_profile["crs"],
        src_nodata=np.nan, dst_transform=dst_transform, dst_crs=TARGET_CRS,
        dst_nodata=0.0, resampling=Resampling.nearest, num_threads=4,
    )

    rgba = np.zeros((output_height, output_width, 4), dtype=np.uint8)
    valid = (
        np.isfinite(mean_display)
        & (mean_display > 0.0)
        & (cov_display >= MINIMUM_VALID_COVERAGE)
    )

    for item in DISPLAY_BINS:
        lo = float(item["min"])
        hi = float(item["max"])
        mask = (
            valid & (mean_display > 0.0) & (mean_display < hi)
            if lo == 0.0
            else valid & (mean_display >= lo) & (mean_display < hi)
        )
        r, g, b = hex_rgb(item["color"])
        rgba[mask, 0] = r
        rgba[mask, 1] = g
        rgba[mask, 2] = b
        rgba[mask, 3] = 235

    output_dir.mkdir(parents=True, exist_ok=True)
    image_path = output_dir / OUTPUT_IMAGE
    metadata_path = output_dir / OUTPUT_METADATA

    Image.fromarray(rgba, mode="RGBA").save(
        image_path, format="PNG", optimize=False, compress_level=7
    )

    metadata = {
        "metadata_mode": METADATA_MODE,
        "render_revision": RENDER_REVISION,
        "product": "USGS Annual NLCD Fractional Impervious Surface (%)",
        "source": "USGS Annual NLCD Collection 1.2",
        "source_product": EXPECTED_SOURCE_PRODUCT,
        "source_map_year": EXPECTED_MAP_YEAR,
        "source_native_resolution_m": EXPECTED_SOURCE_NATIVE_RESOLUTION_M,
        "scientific_analysis_resolution_m": EXPECTED_ANALYSIS_RESOLUTION_M,
        "scientific_analysis_crs": EXPECTED_ANALYSIS_CRS,
        "scientific_input": "nlcd_fractional_impervious_mean_1km_2025.tif",
        "scientific_coverage_input": "nlcd_fractional_impervious_valid_coverage_1km_2025.tif",
        "final_coverage_qa": "nlcd_h2_v1_1_final_coverage_qa.json",
        "image": f"static/{OUTPUT_IMAGE}",
        "image_crs": TARGET_CRS,
        "leaflet_bounds": [[south, west], [north, east]],
        "image_width": int(output_width),
        "image_height": int(output_height),
        "display_resampling": "nearest-neighbor",
        "smoothing": False,
        "display_min_valid_coverage_fraction": MINIMUM_VALID_COVERAGE,
        "display_bins": DISPLAY_BINS,
        "zero_percent_display": "transparent",
        "persistent_source_nodata_display": "transparent",
        "dynamic_model_use_note": (
            "Future H4/dynamic calculations must use v1.1 scientific GeoTIFFs "
            "and coverage/QA fields, never this PNG."
        ),
    }
    metadata_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    return metadata


def self_test() -> None:
    assert METADATA_MODE == "usgs_nlcd_fractional_impervious_h2_dashboard_v1_1_final"
    assert ANALYSIS_METADATA_MODE == "annual_nlcd_fractional_impervious_h2_v1_1"
    assert RENDER_REVISION == "annual-nlcd-fctimp-2025-h2-v1-1-final"
    assert EXPECTED_MAP_YEAR == 2025
    assert EXPECTED_SOURCE_NATIVE_RESOLUTION_M == 30
    assert EXPECTED_ANALYSIS_RESOLUTION_M == 1000
    assert EXPECTED_ANALYSIS_CRS == "EPSG:5070"
    assert DEFAULT_OUTPUT_WIDTH == 9000
    assert MINIMUM_VALID_COVERAGE == 0.25
    assert len(DISPLAY_BINS) == 7
    print("Annual NLCD Phase H2 v1.1 final publication self-test: PASS")


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mean-tif", type=Path)
    parser.add_argument("--coverage-tif", type=Path)
    parser.add_argument("--analysis-metadata", type=Path)
    parser.add_argument("--final-qa", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("static"))
    parser.add_argument("--output-width", type=int, default=DEFAULT_OUTPUT_WIDTH)
    parser.add_argument("--self-test", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.self_test:
        self_test()
        return 0
    required = {
        "--mean-tif": args.mean_tif,
        "--coverage-tif": args.coverage_tif,
        "--analysis-metadata": args.analysis_metadata,
        "--final-qa": args.final_qa,
    }
    missing = [flag for flag, value in required.items() if value is None]
    if missing:
        raise SystemExit("Missing required arguments: " + ", ".join(missing))
    publish(
        args.mean_tif, args.coverage_tif, args.analysis_metadata,
        args.final_qa, args.output_dir, args.output_width
    )
    print(f"Wrote {args.output_dir / OUTPUT_IMAGE}")
    print(f"Wrote {args.output_dir / OUTPUT_METADATA}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
