#!/usr/bin/env python3
"""Recreate one synchronized MRMS FLASH Flash Flood Detector analysis."""

from __future__ import annotations

import argparse
import gzip
import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import requests
import xarray as xr
from affine import Affine
from PIL import Image
import rasterio
from rasterio.crs import CRS
from rasterio.transform import array_bounds, from_origin
from rasterio.warp import (
    Resampling,
    calculate_default_transform,
    reproject,
    transform_bounds,
)
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

IEM_ROOT = "https://mtarchive.geol.iastate.edu"
DEFAULT_OUTPUT_DIR = Path("diagnostic_output")
PREVIEW_MAX_DIMENSION = 3200
DEFAULT_LOOKBACK_MINUTES = 360

PRODUCTS = {
    "crest": ("CREST_MAXUNITSTREAMFLOW", "CREST_MAXUNITSTREAMFLOW"),
    "sac": ("SAC_MAXUNITSTREAMFLOW", "SAC_MAXUNITSTREAMFLOW"),
    "ffg": ("QPE_FFGMAX", "QPE_FFGMAX"),
    "ari": ("QPE_ARIMAX", "QPE_ARIMAX"),
}

CATEGORY_NAMES = {
    0: "None",
    1: "Monitor",
    2: "Flood Advisory",
    3: "FFW Base",
    4: "FFW Considerable",
    5: "FFW Catastrophic",
}

CATEGORY_RGBA = {
    0: (0, 0, 0, 0),
    1: (0, 255, 0, 165),
    2: (255, 255, 0, 180),
    3: (255, 170, 0, 190),
    4: (255, 0, 0, 200),
    5: (255, 0, 255, 215),
}

UNITQ_BINS = np.array(
    [0.25, 1.0, 1.5, 2.0, 3.0, 4.0, 5.0, 6.0, 8.5, 10.0, 15.0, 20.0],
    dtype=np.float32,
)
UNITQ_COLORS = np.array(
    [
        (210, 210, 210, 80),
        (170, 220, 170, 120),
        (0, 255, 0, 145),
        (255, 255, 0, 155),
        (255, 200, 0, 170),
        (255, 140, 0, 180),
        (255, 70, 0, 190),
        (255, 0, 0, 200),
        (190, 0, 190, 210),
        (100, 0, 190, 220),
        (0, 80, 255, 225),
        (0, 0, 130, 230),
    ],
    dtype=np.uint8,
)


@dataclass
class GridField:
    key: str
    source_url: str
    source_filename: str
    data: np.ndarray
    latitudes: np.ndarray
    longitudes: np.ndarray
    variable_name: str
    variable_attributes: dict[str, Any]
    dataset_attributes: dict[str, Any]


def build_session() -> requests.Session:
    retry = Retry(
        total=5,
        connect=5,
        read=5,
        backoff_factor=2.0,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET", "HEAD"}),
        raise_on_status=False,
    )
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": (
                "WPC-Hydrometeorological-Dashboard/1.0 "
                "(MRMS FLASH diagnostic; GitHub Actions)"
            )
        }
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session


def parse_utc_time(value: str) -> datetime:
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def floor_to_ten_minutes(value: datetime) -> datetime:
    return value.replace(
        minute=(value.minute // 10) * 10,
        second=0,
        microsecond=0,
    )


def product_url(product_key: str, valid_time: datetime) -> str:
    directory, prefix = PRODUCTS[product_key]
    date_path = valid_time.strftime("%Y/%m/%d")
    timestamp = valid_time.strftime("%Y%m%d-%H%M%S")
    filename = f"{prefix}_00.00_{timestamp}.grib2.gz"
    return (
        f"{IEM_ROOT}/{date_path}/mrms/ncep/FLASH/"
        f"{directory}/{filename}"
    )


def remote_exists(session: requests.Session, url: str) -> bool:
    try:
        response = session.head(url, timeout=(15, 45), allow_redirects=True)
        if response.status_code == 200:
            return True
        if response.status_code not in (403, 405):
            return False
    except requests.RequestException:
        pass

    try:
        response = session.get(
            url,
            headers={"Range": "bytes=0-0"},
            stream=True,
            timeout=(15, 45),
        )
        return response.status_code in (200, 206)
    except requests.RequestException:
        return False


def find_synchronized_time(
    session: requests.Session,
    requested_time: datetime,
    lookback_minutes: int,
) -> tuple[datetime, dict[str, str], list[dict[str, Any]]]:
    candidate = floor_to_ten_minutes(requested_time)
    attempts: list[dict[str, Any]] = []

    for lag in range(0, lookback_minutes + 10, 10):
        valid_time = candidate - timedelta(minutes=lag)
        urls = {key: product_url(key, valid_time) for key in PRODUCTS}
        availability = {
            key: remote_exists(session, url)
            for key, url in urls.items()
        }
        attempts.append(
            {
                "valid_time": valid_time.isoformat().replace("+00:00", "Z"),
                "availability": availability,
            }
        )
        print(
            f"Checking {valid_time:%Y-%m-%d %H:%MZ}: "
            f"{availability}"
        )
        if all(availability.values()):
            return valid_time, urls, attempts

    raise RuntimeError(
        "No synchronized CREST, SAC, QPE_FFGMAX, and QPE_ARIMAX "
        f"analysis was found during the previous {lookback_minutes} minutes."
    )


def stream_download(session: requests.Session, url: str, output_path: Path) -> None:
    temporary = output_path.with_suffix(output_path.suffix + ".part")
    with session.get(url, stream=True, timeout=(20, 300)) as response:
        response.raise_for_status()
        with temporary.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    handle.write(chunk)
    temporary.replace(output_path)


def decompress_gzip(source: Path, destination: Path) -> None:
    with gzip.open(source, "rb") as compressed:
        with destination.open("wb") as uncompressed:
            shutil.copyfileobj(compressed, uncompressed)


def json_value(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    return str(value)


def choose_data_variable(dataset: xr.Dataset) -> str:
    candidates = [
        name for name, variable in dataset.data_vars.items()
        if variable.ndim >= 2
    ]
    if not candidates:
        raise RuntimeError(
            f"No 2-D data variable found; data variables={list(dataset.data_vars)}"
        )
    return candidates[0]


def coordinate_name(dataset: xr.Dataset, candidates: tuple[str, ...]) -> str:
    lookup = {name.lower(): name for name in dataset.coords}
    for candidate in candidates:
        if candidate.lower() in lookup:
            return lookup[candidate.lower()]
    raise RuntimeError(
        f"Could not find {candidates} among coordinates {list(dataset.coords)}"
    )


def open_grib_field(
    product_key: str,
    grib_path: Path,
    source_url: str,
) -> GridField:
    backend_kwargs = {"indexpath": ""}
    try:
        dataset = xr.open_dataset(
            grib_path,
            engine="cfgrib",
            backend_kwargs=backend_kwargs,
        )
    except Exception as first_error:
        try:
            import cfgrib

            datasets = cfgrib.open_datasets(
                grib_path,
                backend_kwargs=backend_kwargs,
            )
            if not datasets:
                raise RuntimeError("cfgrib returned no datasets")
            dataset = datasets[0]
        except Exception as second_error:
            raise RuntimeError(
                f"Could not decode {grib_path.name}. "
                f"Primary error: {first_error}; fallback: {second_error}"
            ) from second_error

    try:
        variable_name = choose_data_variable(dataset)
        variable = dataset[variable_name].squeeze(drop=True)
        lat_name = coordinate_name(dataset, ("latitude", "lat", "y"))
        lon_name = coordinate_name(dataset, ("longitude", "lon", "x"))

        data = np.asarray(variable.values, dtype=np.float32)
        latitudes = np.asarray(dataset[lat_name].values, dtype=np.float64)
        longitudes = np.asarray(dataset[lon_name].values, dtype=np.float64)

        if latitudes.ndim == 2:
            if np.allclose(latitudes, latitudes[:, :1], equal_nan=True):
                latitudes = latitudes[:, 0]
            else:
                raise RuntimeError("Curvilinear latitude grid is unsupported in v1")
        if longitudes.ndim == 2:
            if np.allclose(longitudes, longitudes[:1, :], equal_nan=True):
                longitudes = longitudes[0, :]
            else:
                raise RuntimeError("Curvilinear longitude grid is unsupported in v1")

        if data.ndim != 2:
            raise RuntimeError(f"Expected 2-D data; found {data.shape}")
        if data.shape == (longitudes.size, latitudes.size):
            data = data.T
        if data.shape != (latitudes.size, longitudes.size):
            raise RuntimeError(
                f"Data shape {data.shape} does not match coordinates "
                f"{(latitudes.size, longitudes.size)}"
            )

        longitudes = longitudes.copy()
        longitudes[longitudes > 180.0] -= 360.0

        if latitudes[0] < latitudes[-1]:
            latitudes = latitudes[::-1]
            data = data[::-1, :]
        if longitudes[0] > longitudes[-1]:
            longitudes = longitudes[::-1]
            data = data[:, ::-1]

        data[~np.isfinite(data)] = np.nan
        data[data < 0.0] = np.nan

        return GridField(
            key=product_key,
            source_url=source_url,
            source_filename=grib_path.name,
            data=data,
            latitudes=latitudes,
            longitudes=longitudes,
            variable_name=variable_name,
            variable_attributes={
                str(key): json_value(value)
                for key, value in variable.attrs.items()
            },
            dataset_attributes={
                str(key): json_value(value)
                for key, value in dataset.attrs.items()
            },
        )
    finally:
        dataset.close()


def validate_alignment(fields: dict[str, GridField]) -> None:
    reference = fields["crest"]
    for key, field in fields.items():
        if field.data.shape != reference.data.shape:
            raise RuntimeError(
                f"Shape mismatch: CREST={reference.data.shape}, "
                f"{key}={field.data.shape}"
            )
        if not np.allclose(field.latitudes, reference.latitudes, atol=1e-6):
            raise RuntimeError(f"Latitude mismatch for {key}")
        if not np.allclose(field.longitudes, reference.longitudes, atol=1e-6):
            raise RuntimeError(f"Longitude mismatch for {key}")


def calculate_ffd_categories(
    ffg_percent: np.ndarray,
    ari_years: np.ndarray,
    crest_unitq: np.ndarray,
    sac_unitq: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    unitq = np.fmax(crest_unitq, sac_unitq)
    category = np.zeros(ffg_percent.shape, dtype=np.uint8)

    monitor = (
        (ffg_percent >= 50.0)
        | (ari_years >= 5.0)
        | (crest_unitq >= 1.5)
        | (sac_unitq >= 1.5)
    )
    category[monitor] = 1

    advisory = (
        ((ffg_percent >= 50.0) & (unitq >= 5.0))
        | ((ffg_percent >= 60.0) & (unitq >= 4.0))
        | ((ffg_percent >= 70.0) & (ari_years >= 2.0) & (unitq >= 1.0))
        | ((ffg_percent >= 80.0) & (ari_years >= 1.5) & (unitq >= 1.0))
        | ((ffg_percent >= 90.0) & (unitq >= 1.0))
    )
    category[advisory] = 2

    base = (
        ((ffg_percent >= 50.0) & (ari_years >= 2.0) & (unitq >= 6.0))
        | ((ffg_percent >= 60.0) & (unitq >= 5.0))
        | ((ffg_percent >= 70.0) & (unitq >= 4.5))
        | ((ffg_percent >= 80.0) & (ari_years >= 10.0) & (unitq >= 3.0))
        | ((ffg_percent >= 90.0) & (ari_years >= 8.0) & (unitq >= 2.0))
        | ((ffg_percent >= 100.0) & (unitq >= 4.0))
    )
    category[base] = 3

    considerable = (
        ((ffg_percent >= 100.0) & (unitq >= 8.5))
        | ((ffg_percent >= 120.0) & (ari_years >= 75.0) & (unitq >= 7.0))
        | ((ffg_percent >= 140.0) & (ari_years >= 50.0) & (unitq >= 6.0))
        | ((ffg_percent >= 160.0) & (unitq >= 6.0))
    )
    category[considerable] = 4

    catastrophic = (
        ((ffg_percent >= 200.0) & (ari_years >= 200.0) & (unitq >= 10.0))
        | ((ffg_percent >= 250.0) & (ari_years >= 125.0) & (unitq >= 10.0))
        | ((ffg_percent >= 300.0) & (unitq >= 10.0))
    )
    category[catastrophic] = 5

    all_missing = (
        ~np.isfinite(ffg_percent)
        & ~np.isfinite(ari_years)
        & ~np.isfinite(crest_unitq)
        & ~np.isfinite(sac_unitq)
    )
    category[all_missing] = 0
    return category, unitq


def run_self_test() -> None:
    cases = [
        (49.0, 4.9, 1.4, 1.4, 0),
        (50.0, 0.0, 0.0, 0.0, 1),
        (0.0, 5.0, 0.0, 0.0, 1),
        (50.0, 0.0, 5.0, 0.0, 2),
        (70.0, 2.0, 1.0, 0.0, 2),
        (60.0, 0.0, 5.0, 0.0, 3),
        (80.0, 10.0, 3.0, 0.0, 3),
        (100.0, 0.0, 8.5, 0.0, 4),
        (120.0, 75.0, 7.0, 0.0, 4),
        (200.0, 200.0, 10.0, 0.0, 5),
        (300.0, 0.0, 10.0, 0.0, 5),
        (100.0, 0.0, 1.0, 8.5, 4),
    ]
    inputs = [
        np.asarray([case[index] for case in cases], dtype=np.float32)
        for index in range(4)
    ]
    expected = np.asarray([case[4] for case in cases], dtype=np.uint8)
    actual, _ = calculate_ffd_categories(*inputs)
    if not np.array_equal(actual, expected):
        raise AssertionError(
            f"Self-test failed: expected {expected.tolist()}, "
            f"found {actual.tolist()}"
        )
    print("FFD threshold algorithm self-test passed.")


def source_transform(field: GridField) -> Affine:
    dx = float(np.median(np.diff(field.longitudes)))
    dy = float(abs(np.median(np.diff(field.latitudes))))
    if dx <= 0.0 or dy <= 0.0:
        raise RuntimeError(f"Invalid grid resolution dx={dx}, dy={dy}")
    west = float(field.longitudes[0] - dx / 2.0)
    north = float(field.latitudes[0] + dy / 2.0)
    return from_origin(west, north, dx, dy)


def write_geotiff(
    output_path: Path,
    data: np.ndarray,
    transform: Affine,
    dtype: str,
    nodata: float | int,
) -> None:
    array = np.asarray(data).copy()
    if np.issubdtype(np.dtype(dtype), np.floating):
        array = np.where(np.isfinite(array), array, nodata)
    array = array.astype(dtype)
    with rasterio.open(
        output_path,
        "w",
        driver="GTiff",
        height=array.shape[0],
        width=array.shape[1],
        count=1,
        dtype=dtype,
        crs="EPSG:4326",
        transform=transform,
        nodata=nodata,
        compress="DEFLATE",
        tiled=True,
        blockxsize=256,
        blockysize=256,
    ) as destination:
        destination.write(array, 1)


def project_preview(
    data: np.ndarray,
    transform: Affine,
    resampling: Resampling,
    nodata: float,
) -> tuple[np.ndarray, list[list[float]]]:
    source_crs = CRS.from_epsg(4326)
    destination_crs = CRS.from_epsg(3857)
    height, width = data.shape
    west, south, east, north = array_bounds(height, width, transform)
    destination_transform, destination_width, destination_height = (
        calculate_default_transform(
            source_crs,
            destination_crs,
            width,
            height,
            west,
            south,
            east,
            north,
        )
    )

    scale = max(
        destination_width / PREVIEW_MAX_DIMENSION,
        destination_height / PREVIEW_MAX_DIMENSION,
        1.0,
    )
    if scale > 1.0:
        reduced_width = max(1, int(round(destination_width / scale)))
        reduced_height = max(1, int(round(destination_height / scale)))
        destination_transform = destination_transform * Affine.scale(
            destination_width / reduced_width,
            destination_height / reduced_height,
        )
        destination_width = reduced_width
        destination_height = reduced_height

    source = np.where(np.isfinite(data), data, nodata).astype(np.float32)
    destination = np.full(
        (destination_height, destination_width),
        nodata,
        dtype=np.float32,
    )
    reproject(
        source=source,
        destination=destination,
        src_transform=transform,
        src_crs=source_crs,
        src_nodata=nodata,
        dst_transform=destination_transform,
        dst_crs=destination_crs,
        dst_nodata=nodata,
        resampling=resampling,
        init_dest_nodata=True,
        num_threads=2,
    )

    projected_bounds = array_bounds(
        destination_height,
        destination_width,
        destination_transform,
    )
    lonlat = transform_bounds(
        destination_crs,
        source_crs,
        *projected_bounds,
        densify_pts=21,
    )
    p_west, p_south, p_east, p_north = lonlat
    leaflet_bounds = [
        [float(p_south), float(p_west)],
        [float(p_north), float(p_east)],
    ]
    return destination, leaflet_bounds


def colorize_ffd(data: np.ndarray, nodata: float) -> np.ndarray:
    categories = np.rint(data).astype(np.int16)
    rgba = np.zeros((*categories.shape, 4), dtype=np.uint8)
    valid = data != nodata
    for category, color in CATEGORY_RGBA.items():
        rgba[valid & (categories == category)] = color
    return rgba


def colorize_unitq(data: np.ndarray, nodata: float) -> np.ndarray:
    rgba = np.zeros((*data.shape, 4), dtype=np.uint8)
    valid = (data != nodata) & np.isfinite(data) & (data >= UNITQ_BINS[0])
    if np.any(valid):
        indices = np.digitize(data[valid], UNITQ_BINS, right=False) - 1
        indices = np.clip(indices, 0, len(UNITQ_COLORS) - 1)
        rgba[valid] = UNITQ_COLORS[indices]
    return rgba


def save_png(path: Path, rgba: np.ndarray) -> None:
    Image.fromarray(rgba, mode="RGBA").save(
        path,
        optimize=True,
        compress_level=9,
    )


def statistics(data: np.ndarray) -> dict[str, Any]:
    valid = data[np.isfinite(data)]
    if valid.size == 0:
        return {
            "valid_count": 0,
            "minimum": None,
            "maximum": None,
            "mean": None,
            "percentiles": {},
        }
    return {
        "valid_count": int(valid.size),
        "minimum": float(np.min(valid)),
        "maximum": float(np.max(valid)),
        "mean": float(np.mean(valid)),
        "percentiles": {
            "50": float(np.percentile(valid, 50)),
            "90": float(np.percentile(valid, 90)),
            "95": float(np.percentile(valid, 95)),
            "99": float(np.percentile(valid, 99)),
            "99.9": float(np.percentile(valid, 99.9)),
        },
    }


def category_statistics(category: np.ndarray) -> dict[str, Any]:
    counts = {
        name: int(np.count_nonzero(category == value))
        for value, name in CATEGORY_NAMES.items()
    }
    total = int(category.size)
    percentages = {
        name: (100.0 * count / total if total else 0.0)
        for name, count in counts.items()
    }
    return {
        "total_grid_cells": total,
        "counts": counts,
        "percentages": percentages,
    }


def write_leaflet_html(
    path: Path,
    bounds: list[list[float]],
    valid_time: datetime,
) -> None:
    bounds_json = json.dumps(bounds)
    valid_label = valid_time.strftime("%Y-%m-%d %H:%M UTC")
    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>MRMS FLASH FFD Diagnostic</title>
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
  <style>
    html, body, #map {{ height: 100%; margin: 0; }}
    .info {{ background: rgba(0,0,0,.78); color: white; padding: 8px 12px;
             border-radius: 5px; font: 13px/1.35 Arial, sans-serif; }}
    .legend-row {{ display:flex; align-items:center; margin:3px 0; }}
    .swatch {{ width:15px; height:15px; margin-right:7px; border:1px solid #333; }}
  </style>
</head>
<body>
<div id="map"></div>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
const bounds = {bounds_json};
const map = L.map('map', {{preferCanvas: true}});
const osm = L.tileLayer(
  'https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png',
  {{maxZoom: 19, attribution: '&copy; OpenStreetMap contributors'}}
).addTo(map);
const dark = L.tileLayer(
  'https://{{s}}.basemaps.cartocdn.com/dark_all/{{z}}/{{x}}/{{y}}{{r}}.png',
  {{maxZoom: 20, attribution: '&copy; OpenStreetMap &copy; CARTO'}}
);
const ffd = L.imageOverlay('mrms_ffd_category.png', bounds, {{opacity: 0.82}}).addTo(map);
const crest = L.imageOverlay('mrms_crest_unitq.png', bounds, {{opacity: 0.82}});
L.control.layers(
  {{'OpenStreetMap': osm, 'Dark': dark}},
  {{'FFD category': ffd, 'CREST Unit Q': crest}},
  {{collapsed: false}}
).addTo(map);
map.fitBounds(bounds);

const info = L.control({{position: 'topright'}});
info.onAdd = function() {{
  const div = L.DomUtil.create('div', 'info');
  div.innerHTML = '<strong>MRMS FLASH Diagnostic</strong><br>{valid_label}<br>' +
    'Toggle the FFD and CREST layers.';
  return div;
}};
info.addTo(map);

const legend = L.control({{position: 'bottomright'}});
legend.onAdd = function() {{
  const div = L.DomUtil.create('div', 'info');
  div.innerHTML = '<strong>FFD Categories</strong>' +
    '<div class="legend-row"><span class="swatch" style="background:#00ff00"></span>Monitor</div>' +
    '<div class="legend-row"><span class="swatch" style="background:#ffff00"></span>Flood Advisory</div>' +
    '<div class="legend-row"><span class="swatch" style="background:#ffaa00"></span>FFW Base</div>' +
    '<div class="legend-row"><span class="swatch" style="background:#ff0000"></span>FFW Considerable</div>' +
    '<div class="legend-row"><span class="swatch" style="background:#ff00ff"></span>FFW Catastrophic</div>';
  return div;
}};
legend.addTo(map);
</script>
</body>
</html>
"""
    path.write_text(html, encoding="utf-8")


def run_diagnostic(args: argparse.Namespace) -> None:
    run_self_test()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    session = build_session()
    generated_time = datetime.now(timezone.utc)
    requested_time = (
        parse_utc_time(args.analysis_time)
        if args.analysis_time
        else generated_time - timedelta(minutes=20)
    )
    selected_time, urls, attempts = find_synchronized_time(
        session,
        requested_time,
        args.lookback_minutes,
    )
    print(f"Selected synchronized analysis: {selected_time:%Y-%m-%d %H:%MZ}")

    fields: dict[str, GridField] = {}
    sources: dict[str, Any] = {}

    with tempfile.TemporaryDirectory(prefix="mrms_ffd_") as temp_name:
        temp_dir = Path(temp_name)
        for key, url in urls.items():
            gz_path = temp_dir / Path(url).name
            grib_path = gz_path.with_suffix("")
            print(f"Downloading {key}: {url}")
            stream_download(session, url, gz_path)
            decompress_gzip(gz_path, grib_path)
            field = open_grib_field(key, grib_path, url)
            fields[key] = field
            sources[key] = {
                "url": url,
                "compressed_filename": gz_path.name,
                "compressed_size_bytes": int(gz_path.stat().st_size),
                "grib_size_bytes": int(grib_path.stat().st_size),
                "variable_name": field.variable_name,
                "variable_attributes": field.variable_attributes,
                "dataset_attributes": field.dataset_attributes,
                "raw_statistics": statistics(field.data),
            }

    validate_alignment(fields)
    reference = fields["crest"]
    transform = source_transform(reference)

    # QPE_FFGMAX is a non-dimensional ratio. The documented DVD thresholds
    # use percentage values, so ratio 0.50 becomes 50 percent.
    ffg_percent = fields["ffg"].data * 100.0
    ari_years = fields["ari"].data
    crest_unitq = fields["crest"].data
    sac_unitq = fields["sac"].data

    ffd_category, combined_unitq = calculate_ffd_categories(
        ffg_percent,
        ari_years,
        crest_unitq,
        sac_unitq,
    )

    write_geotiff(
        output_dir / "mrms_crest_unitq_native.tif",
        crest_unitq,
        transform,
        "float32",
        -9999.0,
    )
    write_geotiff(
        output_dir / "mrms_ffd_category_native.tif",
        ffd_category,
        transform,
        "uint8",
        0,
    )

    nodata = -9999.0
    crest_projected, bounds = project_preview(
        crest_unitq,
        transform,
        Resampling.nearest,
        nodata,
    )
    ffd_projected, ffd_bounds = project_preview(
        ffd_category.astype(np.float32),
        transform,
        Resampling.nearest,
        nodata,
    )
    if not np.allclose(np.asarray(bounds), np.asarray(ffd_bounds), atol=1e-5):
        raise RuntimeError("CREST and FFD projected bounds differ")

    save_png(
        output_dir / "mrms_crest_unitq.png",
        colorize_unitq(crest_projected, nodata),
    )
    save_png(
        output_dir / "mrms_ffd_category.png",
        colorize_ffd(ffd_projected, nodata),
    )
    write_leaflet_html(
        output_dir / "mrms_ffd_diagnostic.html",
        bounds,
        selected_time,
    )

    west, south, east, north = array_bounds(
        reference.data.shape[0],
        reference.data.shape[1],
        transform,
    )
    dx = float(np.median(np.diff(reference.longitudes)))
    dy = float(abs(np.median(np.diff(reference.latitudes))))

    metadata = {
        "diagnostic_version": "mrms-ffd-single-time-v1",
        "generated_time_utc": generated_time.isoformat().replace("+00:00", "Z"),
        "requested_time_utc": requested_time.isoformat().replace("+00:00", "Z"),
        "selected_analysis_time_utc": selected_time.isoformat().replace(
            "+00:00", "Z"
        ),
        "source_records": sources,
        "synchronization_attempts": attempts,
        "grid": {
            "shape": [int(value) for value in reference.data.shape],
            "crs": "EPSG:4326",
            "longitude_resolution_degrees": dx,
            "latitude_resolution_degrees": dy,
            "native_bounds": [
                float(west),
                float(south),
                float(east),
                float(north),
            ],
            "leaflet_bounds": bounds,
        },
        "transformations": {
            "ffg": "raw non-dimensional QPE/FFG ratio multiplied by 100",
            "hydrologic_input": "pixelwise maximum of CREST and SAC Unit Q",
            "preview_resampling": "nearest",
            "preview_max_dimension": PREVIEW_MAX_DIMENSION,
        },
        "derived_statistics": {
            "ffg_percent": statistics(ffg_percent),
            "ari_years": statistics(ari_years),
            "crest_unitq": statistics(crest_unitq),
            "sac_unitq": statistics(sac_unitq),
            "combined_unitq": statistics(combined_unitq),
            "ffd_categories": category_statistics(ffd_category),
        },
        "category_names": {
            str(key): value for key, value in CATEGORY_NAMES.items()
        },
        "outputs": {
            "interactive_preview": "mrms_ffd_diagnostic.html",
            "ffd_png": "mrms_ffd_category.png",
            "crest_png": "mrms_crest_unitq.png",
            "ffd_native_geotiff": "mrms_ffd_category_native.tif",
            "crest_native_geotiff": "mrms_crest_unitq_native.tif",
        },
    }
    (output_dir / "mrms_ffd_diagnostic_metadata.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    counts = metadata["derived_statistics"]["ffd_categories"]["counts"]
    lines = [
        "MRMS FLASH / FFD single-time diagnostic",
        "=======================================",
        f"Requested time: {requested_time:%Y-%m-%d %H:%MZ}",
        f"Selected time:  {selected_time:%Y-%m-%d %H:%MZ}",
        f"Grid shape:     {reference.data.shape}",
        f"Native bounds:  {west:.4f}, {south:.4f}, {east:.4f}, {north:.4f}",
        "",
        "FFD category counts:",
    ]
    for name in CATEGORY_NAMES.values():
        lines.append(f"  {name:18s}: {counts[name]:,}")
    lines.extend(
        [
            "",
            "Open mrms_ffd_diagnostic.html after extracting the artifact.",
        ]
    )
    summary = "\n".join(lines) + "\n"
    (output_dir / "mrms_ffd_diagnostic_summary.txt").write_text(
        summary,
        encoding="utf-8",
    )
    print(summary)
    print(f"Outputs written to {output_dir.resolve()}")


def argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Retrieve synchronized MRMS FLASH grids from IEM and recreate "
            "one Flash Flood Detector analysis."
        )
    )
    parser.add_argument(
        "--analysis-time",
        default=os.environ.get("ANALYSIS_TIME", "").strip(),
        help=(
            "UTC time such as 2025-07-03T00:20:00Z. Blank selects the "
            "newest synchronized 10-minute analysis."
        ),
    )
    parser.add_argument(
        "--lookback-minutes",
        type=int,
        default=DEFAULT_LOOKBACK_MINUTES,
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
    )
    parser.add_argument("--self-test", action="store_true")
    return parser


def main() -> None:
    parser = argument_parser()
    args = parser.parse_args()
    if args.self_test:
        run_self_test()
        return
    if args.lookback_minutes < 0:
        parser.error("--lookback-minutes must be non-negative")
    run_diagnostic(args)


if __name__ == "__main__":
    main()
