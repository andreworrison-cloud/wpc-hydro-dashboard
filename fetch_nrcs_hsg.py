#!/usr/bin/env python3
"""
NRCS Hydrologic Soil Group (HSG) — Dashboard Phase H1 native-30m publication helper.

This repository helper publishes the browser-facing categorical HSG layer from the
*retained scientific Phase H1 analysis*, rather than rebuilding the national soil
analysis from raw SSURGO/gNATSGO sources inside the dashboard repository.

Authoritative Phase H1 science contract
---------------------------------------
* Source geometry: FY2026 gNATSGO MUKEY grid, native 30 m, EPSG:5070.
* Source attributes: USDA-NRCS Soil Data Access.
* Map-unit representation: ``muaggatt.hydgrpdcd`` (Hydrologic Group - Dominant
  Conditions).
* Scientific analysis grid: 1 km equal-area EPSG:5070.
* Seven distinct classes are preserved: A, B, C, D, A/D, B/D, C/D.
* No Gaussian, bilinear, cubic, or other smoothing is used for categorical HSG.
* The dashboard PNG is a display derivative only. Future hydrologic calculations
  must use the retained scientific GeoTIFF products, not the PNG.

The full native-30 m national build is maintained separately in the WPC Hydrologic
Response Project. This script intentionally takes the validated 1-km map-unit
Dominant Condition GeoTIFF plus its analysis metadata and produces only the static
repository assets used by the dashboard.
"""

from __future__ import annotations

import argparse
import json
import math
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from PIL import Image
from rasterio.crs import CRS
from rasterio.transform import from_bounds
from rasterio.warp import Resampling, reproject, transform_bounds

UTC = timezone.utc

METADATA_MODE = "nrcs_hsg_dashboard_h1_native30m_v2"
ANALYSIS_METADATA_MODE = "nrcs_hsg_native30m_analysis_v2_3"
RENDER_REVISION = "nrcs-hsg-native30m-h1-v2-3"
EXPECTED_SOURCE_VINTAGE = "FY2026"
EXPECTED_SOURCE_NATIVE_RESOLUTION_M = 30
EXPECTED_ANALYSIS_RESOLUTION_M = 1000
EXPECTED_ANALYSIS_CRS = "EPSG:5070"
TARGET_CRS = "EPSG:3857"
DEFAULT_OUTPUT_WIDTH = 10000
DEFAULT_EXTENT = (-125.0, -66.5, 23.0, 50.5)  # west, east, south, north
MINIMUM_CLASSIFIED_COVERAGE = 0.25

OUTPUT_IMAGE = "nrcs_hydrologic_soil_group.png"
OUTPUT_METADATA = "nrcs_hydrologic_soil_group_metadata.json"

HSG_CLASSES = {
    "A": {"code": 1, "color": "#2c7bb6"},
    "B": {"code": 2, "color": "#abd9e9"},
    "C": {"code": 3, "color": "#fdae61"},
    "D": {"code": 4, "color": "#d7191c"},
    "A/D": {"code": 5, "color": "#c2a5cf"},
    "B/D": {"code": 6, "color": "#9970ab"},
    "C/D": {"code": 7, "color": "#762a83"},
}
EXPECTED_CLASS_ORDER = list(HSG_CLASSES)


def hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    if len(value) != 6:
        raise ValueError(f"Expected #RRGGBB color, got {value!r}")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def mercator_grid(extent, output_width: int):
    west, east, south, north = map(float, extent)
    if not (-180 <= west < east <= 180 and -85 < south < north < 85):
        raise ValueError(f"Invalid geographic extent: {extent}")
    if output_width < 500:
        raise ValueError("output_width must be at least 500 pixels")

    left, bottom, right, top = transform_bounds(
        "EPSG:4326", TARGET_CRS, west, south, east, north, densify_pts=21
    )
    projected_width = right - left
    projected_height = top - bottom
    output_height = max(1, int(round(output_width * projected_height / projected_width)))
    transform = from_bounds(left, bottom, right, top, output_width, output_height)
    return output_height, transform, (left, bottom, right, top)


def build_palette() -> list[int]:
    palette = [0] * (256 * 3)
    for info in HSG_CLASSES.values():
        code = int(info["code"])
        r, g, b = hex_to_rgb(info["color"])
        palette[3 * code: 3 * code + 3] = [r, g, b]
    return palette


def write_indexed_png(codes: np.ndarray, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.fromarray(codes.astype(np.uint8, copy=False), mode="P")
    image.putpalette(build_palette())
    transparency = bytes([0] + [255] * 255)
    image.info["transparency"] = transparency
    image.save(path, format="PNG", optimize=True, compress_level=9, transparency=transparency)


def load_analysis_metadata(path: Path) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("metadata_mode") != ANALYSIS_METADATA_MODE:
        raise RuntimeError(
            f"Expected analysis metadata_mode={ANALYSIS_METADATA_MODE!r}; "
            f"found {data.get('metadata_mode')!r}."
        )
    if data.get("domain") != "CONUS":
        raise RuntimeError(f"Expected CONUS analysis; found {data.get('domain')!r}.")

    source = data.get("source_geometry") or {}
    grid = data.get("analysis_grid") or {}
    representation = (data.get("representations") or {}).get("mapunit_dominant_condition") or {}

    if source.get("vintage") != EXPECTED_SOURCE_VINTAGE:
        raise RuntimeError(
            f"Expected source vintage {EXPECTED_SOURCE_VINTAGE}; found {source.get('vintage')!r}."
        )
    if int(source.get("native_resolution_m", -1)) != EXPECTED_SOURCE_NATIVE_RESOLUTION_M:
        raise RuntimeError("Unexpected native gNATSGO source resolution in analysis metadata.")
    if str(source.get("crs", "")).upper() != EXPECTED_ANALYSIS_CRS:
        raise RuntimeError("Unexpected source CRS in analysis metadata.")
    if int(grid.get("resolution_m", -1)) != EXPECTED_ANALYSIS_RESOLUTION_M:
        raise RuntimeError("Unexpected Phase H1 scientific analysis resolution.")
    if str(grid.get("crs", "")).upper() != EXPECTED_ANALYSIS_CRS:
        raise RuntimeError("Unexpected Phase H1 scientific analysis CRS.")
    if representation.get("field") != "muaggatt.hydgrpdcd":
        raise RuntimeError("Phase H1 analysis metadata does not preserve muaggatt.hydgrpdcd.")
    if list(data.get("hsg_classes") or []) != EXPECTED_CLASS_ORDER:
        raise RuntimeError("Phase H1 HSG class order changed; review before publishing.")

    safeguards = set(data.get("scientific_safeguards") or [])
    required_safeguards = {
        "No Gaussian, bilinear, or cubic smoothing of categorical HSG source classes.",
        "Area aggregation is performed in EPSG:5070.",
        "A, B, C, D, A/D, B/D, and C/D remain separate.",
        "No empirical runoff-risk weights are assigned in Phase H1.",
        "Dashboard display PNG is not an analysis input.",
    }
    missing = required_safeguards - safeguards
    if missing:
        raise RuntimeError(f"Analysis metadata is missing Phase H1 safeguards: {sorted(missing)}")

    return data


def validate_dominant_raster(path: Path, analysis_metadata: dict[str, Any]) -> dict[str, Any]:
    grid = analysis_metadata["analysis_grid"]
    with rasterio.open(path) as src:
        if src.count != 1:
            raise RuntimeError(f"Expected one-band HSG dominant raster; found {src.count} bands.")
        if src.crs != CRS.from_epsg(5070):
            raise RuntimeError(f"Expected EPSG:5070 HSG analysis raster; found {src.crs}.")
        if src.dtypes[0] != "uint8":
            raise RuntimeError(f"Expected uint8 HSG codes; found {src.dtypes[0]!r}.")
        if src.nodata not in (0, 0.0):
            raise RuntimeError(f"Expected HSG nodata=0; found {src.nodata!r}.")
        if src.width != int(grid["width"]) or src.height != int(grid["height"]):
            raise RuntimeError(
                "HSG dominant raster dimensions do not match the retained analysis metadata."
            )
        if not math.isclose(abs(src.transform.a), EXPECTED_ANALYSIS_RESOLUTION_M, abs_tol=1e-6):
            raise RuntimeError("HSG dominant raster x resolution is not 1 km.")
        if not math.isclose(abs(src.transform.e), EXPECTED_ANALYSIS_RESOLUTION_M, abs_tol=1e-6):
            raise RuntimeError("HSG dominant raster y resolution is not 1 km.")

        tags = src.tags()
        if tags.get("source_vintage") != EXPECTED_SOURCE_VINTAGE:
            raise RuntimeError("HSG dominant raster source_vintage tag does not match FY2026.")
        if int(tags.get("source_native_resolution_m", -1)) != EXPECTED_SOURCE_NATIVE_RESOLUTION_M:
            raise RuntimeError("HSG dominant raster native-source-resolution tag is not 30 m.")
        if int(tags.get("analysis_resolution_m", -1)) != EXPECTED_ANALYSIS_RESOLUTION_M:
            raise RuntimeError("HSG dominant raster analysis-resolution tag is not 1 km.")
        minimum_coverage = float(tags.get("minimum_classified_coverage", "nan"))
        if not math.isclose(minimum_coverage, MINIMUM_CLASSIFIED_COVERAGE, abs_tol=1e-9):
            raise RuntimeError(
                "HSG dominant raster minimum-classified-coverage tag changed; review science first."
            )

        values = np.unique(src.read(1, out_shape=(min(src.height, 1200), min(src.width, 1800))))
        invalid = values[(values < 0) | (values > 7)]
        if invalid.size:
            raise RuntimeError(f"Unexpected HSG class codes in dominant raster: {invalid.tolist()}")

        return {
            "crs": src.crs.to_string(),
            "width": src.width,
            "height": src.height,
            "transform": tuple(src.transform),
            "tags": tags,
        }


def render_dashboard_codes(dominant_raster: Path, output_width: int, extent) -> tuple[np.ndarray, tuple]:
    output_height, dst_transform, projected_bounds = mercator_grid(extent, output_width)
    destination = np.zeros((output_height, output_width), dtype=np.uint8)

    with rasterio.open(dominant_raster) as src:
        reproject(
            source=rasterio.band(src, 1),
            destination=destination,
            src_transform=src.transform,
            src_crs=src.crs,
            src_nodata=0,
            dst_transform=dst_transform,
            dst_crs=TARGET_CRS,
            dst_nodata=0,
            resampling=Resampling.nearest,
            num_threads=2,
            init_dest_nodata=True,
        )

    invalid = np.unique(destination[(destination < 0) | (destination > 7)])
    if invalid.size:
        raise RuntimeError(f"Rendered PNG grid contains invalid HSG codes: {invalid.tolist()}")
    return destination, projected_bounds


def build(
    dominant_raster: Path,
    analysis_metadata_path: Path,
    output_dir: Path,
    output_width: int = DEFAULT_OUTPUT_WIDTH,
    extent=DEFAULT_EXTENT,
):
    dominant_raster = Path(dominant_raster)
    analysis_metadata_path = Path(analysis_metadata_path)
    output_dir = Path(output_dir)

    if not dominant_raster.exists():
        raise FileNotFoundError(dominant_raster)
    if not analysis_metadata_path.exists():
        raise FileNotFoundError(analysis_metadata_path)

    analysis = load_analysis_metadata(analysis_metadata_path)
    validate_dominant_raster(dominant_raster, analysis)
    hsg_codes, projected_bounds = render_dashboard_codes(dominant_raster, output_width, extent)

    image_path = output_dir / OUTPUT_IMAGE
    metadata_path = output_dir / OUTPUT_METADATA
    write_indexed_png(hsg_codes, image_path)

    counts = np.bincount(hsg_codes.ravel(), minlength=8)
    rated_count = int(counts[1:8].sum())
    total_count = int(hsg_codes.size)

    category_stats = []
    for name, info in HSG_CLASSES.items():
        code = int(info["code"])
        count = int(counts[code])
        category_stats.append({
            "name": name,
            "code": code,
            "color": info["color"],
            "display_pixel_count": count,
            "rated_display_fraction": (count / rated_count if rated_count else 0.0),
        })

    source = analysis["source_geometry"]
    grid = analysis["analysis_grid"]
    west, east, south, north = map(float, extent)
    generated = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    metadata = {
        "metadata_mode": METADATA_MODE,
        "render_revision": RENDER_REVISION,
        "product": "NRCS Hydrologic Soil Group (A-D / Dual)",
        "domain": "CONUS",
        "source": (
            f"{source['vintage']} gNATSGO native {source['native_resolution_m']}m MUKEY geometry + "
            "USDA-NRCS Soil Data Access muaggatt.hydgrpdcd"
        ),
        "source_geometry_vintage": source["vintage"],
        "source_native_resolution_m": int(source["native_resolution_m"]),
        "scientific_analysis_resolution_m": int(grid["resolution_m"]),
        "attribute": "hydgrpdcd",
        "attribute_label": "Hydrologic Group - Dominant Conditions",
        "classes": category_stats,
        "image": f"static/{OUTPUT_IMAGE}",
        "image_crs": TARGET_CRS,
        "bounds": [[south, west], [north, east]],
        "image_width": int(output_width),
        "image_height": int(hsg_codes.shape[0]),
        "display_resampling": "nearest-neighbor",
        "smoothing": False,
        "categorical": True,
        "rated_display_fraction": (rated_count / total_count if total_count else 0.0),
        "dual_group_note": "A/D, B/D and C/D are preserved. Drainage state is not inferred by H1.",
        "palette_note": (
            "Colors are a WPC dashboard visualization palette and are not claimed to be "
            "an NRCS official color standard."
        ),
        "analysis_source_note": (
            "The PNG is a display derivative of the 1km equal-area DCD analysis. Future "
            "hydrologic calculations must use the scientific GeoTIFFs, not this PNG."
        ),
        "generated_utc": generated,
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    print(
        "Validated Phase H1 science:",
        f"{source['vintage']} native {source['native_resolution_m']}m gNATSGO -> "
        f"{grid['resolution_m']}m EPSG:5070 DCD analysis"
    )
    print(f"Wrote {image_path} ({image_path.stat().st_size / 1024 / 1024:.2f} MiB)")
    print(f"Wrote {metadata_path}")
    print(f"Rated display coverage: {100.0 * metadata['rated_display_fraction']:.2f}%")
    return metadata


def self_test() -> None:
    """Controlled publication test for the retained 1-km Phase H1 contract."""
    with tempfile.TemporaryDirectory(prefix="nrcs_hsg_h1_publish_selftest_") as td:
        root = Path(td)
        tif = root / "nrcs_hsg_mapunit_dominant_1km_fy2026.tif"
        analysis_json = root / "nrcs_hsg_analysis_metadata_fy2026.json"
        out = root / "static"

        width, height = 12, 8
        left, bottom = -6000.0, 1800000.0
        right = left + width * EXPECTED_ANALYSIS_RESOLUTION_M
        top = bottom + height * EXPECTED_ANALYSIS_RESOLUTION_M
        transform = from_bounds(left, bottom, right, top, width, height)
        west, south, east, north = transform_bounds(
            EXPECTED_ANALYSIS_CRS, 'EPSG:4326', left, bottom, right, top, densify_pts=21
        )
        test_extent = (west, east, south, north)
        data = np.zeros((height, width), dtype=np.uint8)
        for idx, code in enumerate(range(1, 8)):
            data[:, idx:idx + 1] = code

        with rasterio.open(
            tif,
            "w",
            driver="GTiff",
            width=width,
            height=height,
            count=1,
            dtype="uint8",
            crs=EXPECTED_ANALYSIS_CRS,
            transform=transform,
            nodata=0,
        ) as dst:
            dst.write(data, 1)
            dst.update_tags(
                source_vintage=EXPECTED_SOURCE_VINTAGE,
                source_native_resolution_m=str(EXPECTED_SOURCE_NATIVE_RESOLUTION_M),
                analysis_resolution_m=str(EXPECTED_ANALYSIS_RESOLUTION_M),
                minimum_classified_coverage=str(MINIMUM_CLASSIFIED_COVERAGE),
            )

        analysis = {
            "metadata_mode": ANALYSIS_METADATA_MODE,
            "domain": "CONUS",
            "source_geometry": {
                "dataset": "gNATSGO MUKEY grid via SoilWeb WCS",
                "vintage": EXPECTED_SOURCE_VINTAGE,
                "native_resolution_m": EXPECTED_SOURCE_NATIVE_RESOLUTION_M,
                "crs": EXPECTED_ANALYSIS_CRS,
            },
            "analysis_grid": {
                "crs": EXPECTED_ANALYSIS_CRS,
                "resolution_m": EXPECTED_ANALYSIS_RESOLUTION_M,
                "width": width,
                "height": height,
            },
            "hsg_classes": EXPECTED_CLASS_ORDER,
            "representations": {
                "mapunit_dominant_condition": {"field": "muaggatt.hydgrpdcd"}
            },
            "scientific_safeguards": [
                "No Gaussian, bilinear, or cubic smoothing of categorical HSG source classes.",
                "Area aggregation is performed in EPSG:5070.",
                "A, B, C, D, A/D, B/D, and C/D remain separate.",
                "No empirical runoff-risk weights are assigned in Phase H1.",
                "Dashboard display PNG is not an analysis input.",
            ],
        }
        analysis_json.write_text(json.dumps(analysis, indent=2), encoding="utf-8")

        metadata = build(
            tif,
            analysis_json,
            out,
            output_width=700,
            extent=test_extent,
        )
        assert metadata["metadata_mode"] == METADATA_MODE
        assert metadata["render_revision"] == RENDER_REVISION
        assert metadata["source_geometry_vintage"] == EXPECTED_SOURCE_VINTAGE
        assert metadata["source_native_resolution_m"] == 30
        assert metadata["scientific_analysis_resolution_m"] == 1000
        assert metadata["attribute"] == "hydgrpdcd"
        assert metadata["display_resampling"] == "nearest-neighbor"
        assert metadata["smoothing"] is False
        assert metadata["categorical"] is True
        assert (out / OUTPUT_IMAGE).exists()
        assert (out / OUTPUT_METADATA).exists()

        with Image.open(out / OUTPUT_IMAGE) as image:
            assert image.mode == "P"
            used = set(np.unique(np.asarray(image)).tolist())
            assert used.intersection(set(range(1, 8)))

    print("NRCS HSG Phase H1 native30m v2.3 publication self-test: PASS")


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dominant-raster",
        type=Path,
        help="Validated Phase H1 1-km map-unit dominant-condition GeoTIFF",
    )
    parser.add_argument(
        "--analysis-metadata",
        type=Path,
        help="Validated Phase H1 national scientific analysis metadata JSON",
    )
    parser.add_argument("--output-dir", type=Path, default=Path("static"))
    parser.add_argument("--output-width", type=int, default=DEFAULT_OUTPUT_WIDTH)
    parser.add_argument(
        "--extent",
        type=float,
        nargs=4,
        metavar=("WEST", "EAST", "SOUTH", "NORTH"),
        default=DEFAULT_EXTENT,
        help="Geographic display extent; default is the CONUS dashboard extent",
    )
    parser.add_argument("--self-test", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.self_test:
        self_test()
        return 0
    if args.dominant_raster is None or args.analysis_metadata is None:
        raise SystemExit(
            "--dominant-raster and --analysis-metadata are required unless --self-test is used"
        )

    build(
        args.dominant_raster,
        args.analysis_metadata,
        args.output_dir,
        output_width=args.output_width,
        extent=args.extent,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
