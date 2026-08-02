#!/usr/bin/env python3
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
CYCLE_MINUTES = 10
DEFAULT_HOURS = 24
DEFAULT_LOOKBACK_MINUTES = 360
DEFAULT_MINIMUM_COMPLETENESS = 0.85
MAX_RENDER_DIMENSION = 8000
NODATA_FLOAT = -9999.0


@dataclass
class GridField:
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
        backoff_factor=1.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET", "HEAD"}),
        raise_on_status=False,
    )
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": (
                "WPC-Hydrometeorological-Dashboard/1.0 "
                "(MRMS FLASH rolling maximum; GitHub Actions)"
            )
        }
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session


def parse_utc_time(value: str) -> datetime:
    normalized = value.strip().strip('"').strip("'")

    # Be forgiving when a workflow input is pasted as:
    #   end_time = 2025-07-03T00:20:00Z
    # rather than only the ISO timestamp.
    if "=" in normalized:
        key, candidate = normalized.split("=", 1)
        if key.strip().lower() in {
            "end_time",
            "analysis_time",
            "time",
        }:
            normalized = candidate.strip().strip('"').strip("'")

    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"

    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as error:
        raise ValueError(
            "Invalid UTC time. Enter only an ISO timestamp such as "
            "2025-07-03T00:20:00Z."
        ) from error

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def floor_to_cycle(value: datetime) -> datetime:
    return value.replace(
        minute=(value.minute // CYCLE_MINUTES) * CYCLE_MINUTES,
        second=0,
        microsecond=0,
    )


def iso_z(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def product_url(product: str, valid_time: datetime) -> str:
    date_path = valid_time.strftime("%Y/%m/%d")
    timestamp = valid_time.strftime("%Y%m%d-%H%M%S")
    filename = f"{product}_00.00_{timestamp}.grib2.gz"
    return (
        f"{IEM_ROOT}/{date_path}/mrms/ncep/FLASH/"
        f"{product}/{filename}"
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


def stream_download(
    session: requests.Session,
    url: str,
    output_path: Path,
) -> None:
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


def serialize_json_value(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    return str(value)


def select_data_variable(dataset: xr.Dataset) -> str:
    candidates = [
        name
        for name, variable in dataset.data_vars.items()
        if variable.ndim >= 2
    ]
    if not candidates:
        raise RuntimeError(
            f"No two-dimensional GRIB variable found: "
            f"{list(dataset.data_vars)}"
        )
    return candidates[0]


def find_coordinate_name(
    dataset: xr.Dataset,
    candidates: tuple[str, ...],
) -> str:
    lookup = {name.lower(): name for name in dataset.coords}
    for candidate in candidates:
        if candidate.lower() in lookup:
            return lookup[candidate.lower()]
    raise RuntimeError(
        f"Could not find {candidates} in coordinates "
        f"{list(dataset.coords)}"
    )


def open_grib_field(grib_path: Path) -> GridField:
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
                f"Primary error: {first_error}; "
                f"fallback error: {second_error}"
            ) from second_error

    try:
        variable_name = select_data_variable(dataset)
        variable = dataset[variable_name].squeeze(drop=True)
        latitude_name = find_coordinate_name(
            dataset,
            ("latitude", "lat", "y"),
        )
        longitude_name = find_coordinate_name(
            dataset,
            ("longitude", "lon", "x"),
        )

        data = np.asarray(variable.values, dtype=np.float32)
        latitudes = np.asarray(
            dataset[latitude_name].values,
            dtype=np.float64,
        )
        longitudes = np.asarray(
            dataset[longitude_name].values,
            dtype=np.float64,
        )

        if latitudes.ndim == 2:
            if np.allclose(
                latitudes,
                latitudes[:, :1],
                equal_nan=True,
            ):
                latitudes = latitudes[:, 0]
            else:
                raise RuntimeError(
                    "Curvilinear latitude grid is unsupported."
                )
        if longitudes.ndim == 2:
            if np.allclose(
                longitudes,
                longitudes[:1, :],
                equal_nan=True,
            ):
                longitudes = longitudes[0, :]
            else:
                raise RuntimeError(
                    "Curvilinear longitude grid is unsupported."
                )

        if data.shape == (longitudes.size, latitudes.size):
            data = data.T
        if data.shape != (latitudes.size, longitudes.size):
            raise RuntimeError(
                f"Data shape {data.shape} does not match "
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
            data=data,
            latitudes=latitudes,
            longitudes=longitudes,
            variable_name=variable_name,
            variable_attributes={
                str(key): serialize_json_value(value)
                for key, value in variable.attrs.items()
            },
            dataset_attributes={
                str(key): serialize_json_value(value)
                for key, value in dataset.attrs.items()
            },
        )
    finally:
        dataset.close()


def download_and_decode(
    session: requests.Session,
    product: str,
    valid_time: datetime,
    temporary_dir: Path,
) -> tuple[GridField, dict[str, Any]]:
    url = product_url(product, valid_time)
    gzip_path = temporary_dir / Path(url).name
    grib_path = gzip_path.with_suffix("")

    stream_download(session, url, gzip_path)
    decompress_gzip(gzip_path, grib_path)
    field = open_grib_field(grib_path)

    record = {
        "product": product,
        "valid_time_utc": iso_z(valid_time),
        "url": url,
        "compressed_size_bytes": int(gzip_path.stat().st_size),
        "grib_size_bytes": int(grib_path.stat().st_size),
        "variable_name": field.variable_name,
    }

    gzip_path.unlink(missing_ok=True)
    grib_path.unlink(missing_ok=True)
    return field, record


def validate_alignment(
    reference: GridField,
    candidate: GridField,
    product: str,
) -> None:
    if candidate.data.shape != reference.data.shape:
        raise RuntimeError(
            f"{product} shape {candidate.data.shape} differs from "
            f"reference {reference.data.shape}"
        )
    if not np.allclose(
        candidate.latitudes,
        reference.latitudes,
        rtol=0.0,
        atol=1.0e-6,
    ):
        raise RuntimeError(
            f"{product} latitude coordinates do not align."
        )
    if not np.allclose(
        candidate.longitudes,
        reference.longitudes,
        rtol=0.0,
        atol=1.0e-6,
    ):
        raise RuntimeError(
            f"{product} longitude coordinates do not align."
        )


def grid_transform(field: GridField) -> Affine:
    x_resolution = float(np.median(np.diff(field.longitudes)))
    y_resolution = float(
        abs(np.median(np.diff(field.latitudes)))
    )
    if x_resolution <= 0.0 or y_resolution <= 0.0:
        raise RuntimeError(
            f"Invalid grid resolution: {x_resolution}, {y_resolution}"
        )
    west = float(field.longitudes[0] - x_resolution / 2.0)
    north = float(field.latitudes[0] + y_resolution / 2.0)
    return from_origin(
        west,
        north,
        x_resolution,
        y_resolution,
    )


def expected_cycle_times(
    end_time: datetime,
    hours: int,
) -> list[datetime]:
    count = hours * (60 // CYCLE_MINUTES)
    start_time = end_time - timedelta(
        minutes=CYCLE_MINUTES * (count - 1)
    )
    return [
        start_time + timedelta(minutes=CYCLE_MINUTES * index)
        for index in range(count)
    ]


def write_geotiff(
    output_path: Path,
    data: np.ndarray,
    transform: Affine,
    dtype: str,
    nodata: float | int,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if np.issubdtype(np.dtype(dtype), np.floating):
        write_data = np.where(
            np.isfinite(data),
            data,
            nodata,
        ).astype(dtype)
    else:
        write_data = np.asarray(data, dtype=dtype)

    with rasterio.open(
        output_path,
        "w",
        driver="GTiff",
        height=write_data.shape[0],
        width=write_data.shape[1],
        count=1,
        dtype=dtype,
        crs="EPSG:4326",
        transform=transform,
        nodata=nodata,
        compress="DEFLATE",
        predictor=(
            2
            if np.issubdtype(np.dtype(dtype), np.floating)
            else 1
        ),
        tiled=True,
        blockxsize=256,
        blockysize=256,
    ) as destination:
        destination.write(write_data, 1)


def reproject_for_dashboard(
    data: np.ndarray,
    source_transform: Affine,
    source_nodata: float,
) -> tuple[np.ndarray, list[list[float]], Affine]:
    source_crs = CRS.from_epsg(4326)
    destination_crs = CRS.from_epsg(3857)
    height, width = data.shape
    west, south, east, north = array_bounds(
        height,
        width,
        source_transform,
    )

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
        destination_width / MAX_RENDER_DIMENSION,
        destination_height / MAX_RENDER_DIMENSION,
        1.0,
    )
    if scale > 1.0:
        reduced_width = max(
            1,
            int(round(destination_width / scale)),
        )
        reduced_height = max(
            1,
            int(round(destination_height / scale)),
        )
        destination_transform = (
            destination_transform
            * Affine.scale(
                destination_width / reduced_width,
                destination_height / reduced_height,
            )
        )
        destination_width = reduced_width
        destination_height = reduced_height

    destination = np.full(
        (destination_height, destination_width),
        source_nodata,
        dtype=np.float32,
    )
    source = np.where(
        np.isfinite(data),
        data,
        source_nodata,
    ).astype(np.float32)

    reproject(
        source=source,
        destination=destination,
        src_transform=source_transform,
        src_crs=source_crs,
        src_nodata=source_nodata,
        dst_transform=destination_transform,
        dst_crs=destination_crs,
        dst_nodata=source_nodata,
        resampling=Resampling.nearest,
        init_dest_nodata=True,
        num_threads=2,
    )

    projected_bounds = array_bounds(
        destination_height,
        destination_width,
        destination_transform,
    )
    p_west, p_south, p_east, p_north = projected_bounds
    l_west, l_south, l_east, l_north = transform_bounds(
        destination_crs,
        source_crs,
        p_west,
        p_south,
        p_east,
        p_north,
        densify_pts=21,
    )
    bounds = [
        [float(l_south), float(l_west)],
        [float(l_north), float(l_east)],
    ]

    print(
        "Dashboard render: "
        f"{width}x{height} native -> "
        f"{destination_width}x{destination_height} EPSG:3857"
    )
    return destination, bounds, destination_transform


def save_rgba_png(
    output_path: Path,
    rgba: np.ndarray,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(
        rgba.astype(np.uint8),
        mode="RGBA",
    ).save(
        output_path,
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


def resolve_end_time(
    session: requests.Session,
    requested: str,
    required_products: tuple[str, ...],
    lookback_minutes: int,
) -> tuple[datetime, list[dict[str, Any]]]:
    base = (
        parse_utc_time(requested)
        if requested.strip()
        else datetime.now(timezone.utc) - timedelta(minutes=20)
    )
    candidate = floor_to_cycle(base)
    attempts: list[dict[str, Any]] = []

    for lag in range(0, lookback_minutes + CYCLE_MINUTES, CYCLE_MINUTES):
        valid_time = candidate - timedelta(minutes=lag)
        availability = {
            product: remote_exists(
                session,
                product_url(product, valid_time),
            )
            for product in required_products
        }
        attempts.append(
            {
                "valid_time_utc": iso_z(valid_time),
                "availability": availability,
            }
        )
        print(
            f"Checking end cycle {valid_time:%Y-%m-%d %H:%MZ}: "
            f"{availability}"
        )
        if all(availability.values()):
            return valid_time, attempts

    raise RuntimeError(
        "Could not find a complete ending analysis during the "
        f"previous {lookback_minutes} minutes."
    )


def completeness_check(
    used_count: int,
    expected_count: int,
    minimum_fraction: float,
) -> None:
    fraction = (
        used_count / expected_count
        if expected_count
        else 0.0
    )
    print(
        f"Window completeness: {used_count}/{expected_count} "
        f"({fraction:.1%})"
    )
    if fraction < minimum_fraction:
        raise RuntimeError(
            f"Window completeness {fraction:.1%} is below the "
            f"required {minimum_fraction:.1%}."
        )


PRODUCT = "CREST_MAXUNITSTREAMFLOW"
DEFAULT_OUTPUT_DIR = Path("mrms_crest_24h_output")
DISPLAY_MINIMUM = 1.0

UNITQ_BINS = np.array(
    [1.0, 1.5, 2.0, 3.0, 4.0, 5.0, 6.0, 8.5, 10.0, 15.0, 20.0],
    dtype=np.float32,
)
UNITQ_COLORS = np.array(
    [
        (0, 255, 0, 150),
        (255, 255, 0, 160),
        (255, 200, 0, 170),
        (255, 140, 0, 180),
        (255, 70, 0, 190),
        (255, 0, 0, 200),
        (190, 0, 190, 210),
        (100, 0, 190, 220),
        (0, 80, 255, 225),
        (0, 0, 180, 230),
        (0, 0, 100, 235),
    ],
    dtype=np.uint8,
)


def colorize_unitq(data: np.ndarray) -> np.ndarray:
    rgba = np.zeros((*data.shape, 4), dtype=np.uint8)
    valid = (
        np.isfinite(data)
        & (data != NODATA_FLOAT)
        & (data >= DISPLAY_MINIMUM)
    )
    if not np.any(valid):
        return rgba
    indices = np.digitize(
        data[valid],
        UNITQ_BINS,
        right=False,
    ) - 1
    indices = np.clip(
        indices,
        0,
        len(UNITQ_COLORS) - 1,
    )
    rgba[valid] = UNITQ_COLORS[indices]
    return rgba


def write_html(
    output_path: Path,
    bounds: list[list[float]],
    window_start: datetime,
    window_end: datetime,
) -> None:
    bounds_json = json.dumps(bounds)
    title = (
        f"{window_start:%Y-%m-%d %H:%MZ} to "
        f"{window_end:%Y-%m-%d %H:%MZ}"
    )
    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>MRMS CREST Unit Q 24-Hour Maximum</title>
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
  <style>
    html, body, #map {{height:100%; margin:0;}}
    .info {{background:rgba(0,0,0,.78); color:white; padding:8px 12px;
            border-radius:5px; font:13px/1.35 Arial,sans-serif;}}
  </style>
</head>
<body>
<div id="map"></div>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
const bounds = {bounds_json};
const map = L.map('map', {{preferCanvas:true}});
L.tileLayer(
  'https://{{s}}.basemaps.cartocdn.com/dark_all/{{z}}/{{x}}/{{y}}{{r}}.png',
  {{maxZoom:20, attribution:'&copy; OpenStreetMap &copy; CARTO'}}
).addTo(map);
L.imageOverlay(
  'mrms_crest_unitq_max24h.png',
  bounds,
  {{opacity:0.86}}
).addTo(map);
map.fitBounds(bounds);
const info = L.control({{position:'topright'}});
info.onAdd = function() {{
  const div = L.DomUtil.create('div','info');
  div.innerHTML =
    '<strong>MRMS FLASH CREST Unit Q</strong><br>' +
    'Rolling 24-Hour Maximum<br>{title}<br>' +
    'Units: m&sup3; s<sup>-1</sup> km<sup>-2</sup>';
  return div;
}};
info.addTo(map);
</script>
</body>
</html>
"""
    output_path.write_text(html, encoding="utf-8")


def run(args: argparse.Namespace) -> None:
    session = build_session()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    end_time, end_attempts = resolve_end_time(
        session,
        args.end_time,
        (PRODUCT,),
        args.lookback_minutes,
    )
    cycle_times = expected_cycle_times(
        end_time,
        args.hours,
    )
    expected_count = len(cycle_times)

    maximum: np.ndarray | None = None
    reference: GridField | None = None
    used_times: list[str] = []
    missing_times: list[str] = []
    source_records: list[dict[str, Any]] = []

    with tempfile.TemporaryDirectory(
        prefix="mrms_crest_24h_"
    ) as temporary:
        temporary_dir = Path(temporary)
        for index, valid_time in enumerate(cycle_times, start=1):
            url = product_url(PRODUCT, valid_time)
            if not remote_exists(session, url):
                missing_times.append(iso_z(valid_time))
                print(
                    f"[{index}/{expected_count}] Missing CREST "
                    f"{valid_time:%Y-%m-%d %H:%MZ}"
                )
                continue

            print(
                f"[{index}/{expected_count}] Processing CREST "
                f"{valid_time:%Y-%m-%d %H:%MZ}"
            )
            try:
                field, record = download_and_decode(
                    session,
                    PRODUCT,
                    valid_time,
                    temporary_dir,
                )
            except Exception as error:
                print(f"Cycle failed: {error}")
                missing_times.append(iso_z(valid_time))
                continue

            if reference is None:
                reference = field
                maximum = field.data.copy()
            else:
                validate_alignment(
                    reference,
                    field,
                    PRODUCT,
                )
                np.fmax(
                    maximum,
                    field.data,
                    out=maximum,
                )

            used_times.append(iso_z(valid_time))
            source_records.append(record)

    completeness_check(
        len(used_times),
        expected_count,
        args.minimum_completeness,
    )
    if reference is None or maximum is None:
        raise RuntimeError("No CREST grids were processed.")

    transform = grid_transform(reference)
    window_start = cycle_times[0]

    geotiff_name = "mrms_crest_unitq_max24h_native.tif"
    png_name = "mrms_crest_unitq_max24h.png"
    metadata_name = "mrms_crest_unitq_max24h_metadata.json"
    summary_name = "mrms_crest_unitq_max24h_summary.txt"
    html_name = "mrms_crest_unitq_max24h.html"

    if not args.dashboard_only:
        write_geotiff(
            output_dir / geotiff_name,
            maximum,
            transform,
            "float32",
            NODATA_FLOAT,
        )
    projected, bounds, projected_transform = (
        reproject_for_dashboard(
            maximum,
            transform,
            NODATA_FLOAT,
        )
    )
    save_rgba_png(
        output_dir / png_name,
        colorize_unitq(projected),
    )
    if not args.dashboard_only:
        write_html(
            output_dir / html_name,
            bounds,
            window_start,
            end_time,
        )

    output_manifest = {
        "png": png_name,
        "metadata": metadata_name,
    }
    if not args.dashboard_only:
        output_manifest.update(
            {
                "native_geotiff": geotiff_name,
                "summary": summary_name,
                "interactive_preview": html_name,
            }
        )

    metadata = {
        "product": "MRMS FLASH CREST Maximum Unit Streamflow",
        "product_key": PRODUCT,
        "aggregation": (
            "pixelwise maximum of successive CREST "
            "MAXUNITSTREAMFLOW analyses"
        ),
        "units": "m^3 s^-1 km^-2",
        "window_start_utc": iso_z(window_start),
        "window_end_utc": iso_z(end_time),
        "window_hours": args.hours,
        "expected_cycles": expected_count,
        "processed_cycles": len(used_times),
        "completeness_fraction": (
            len(used_times) / expected_count
        ),
        "missing_times_utc": missing_times,
        "metadata_mode": (
            "dashboard_compact"
            if args.dashboard_only
            else "diagnostic_full"
        ),
        "grid": {
            "shape": list(reference.data.shape),
            "crs": "EPSG:4326",
            "native_transform": list(transform)[:6],
            "leaflet_bounds": bounds,
            "image_crs": "EPSG:3857",
            "rendered_shape": list(projected.shape),
            "rendered_transform": list(
                projected_transform
            )[:6],
        },
        "rendering": {
            "resampling": "nearest",
            "display_minimum": DISPLAY_MINIMUM,
            "maximum_render_dimension": MAX_RENDER_DIMENSION,
        },
        "statistics": statistics(maximum),
        "generated_time_utc": iso_z(
            datetime.now(timezone.utc)
        ),
        "outputs": output_manifest,
    }

    if not args.dashboard_only:
        metadata.update(
            {
                "used_times_utc": used_times,
                "end_time_search_attempts": end_attempts,
                "source_records": source_records,
            }
        )
    (output_dir / metadata_name).write_text(
        json.dumps(metadata, indent=2),
        encoding="utf-8",
    )

    summary = "\n".join(
        [
            "MRMS FLASH CREST Unit Q Rolling Maximum",
            "=======================================",
            f"Window: {window_start:%Y-%m-%d %H:%MZ} to "
            f"{end_time:%Y-%m-%d %H:%MZ}",
            f"Processed cycles: {len(used_times)}/{expected_count}",
            f"Missing cycles: {len(missing_times)}",
            f"Maximum Unit Q: "
            f"{metadata['statistics']['maximum']}",
            f"Native grid: {reference.data.shape}",
            f"Rendered grid: {projected.shape}",
            "",
        ]
    )
    if not args.dashboard_only:
        (output_dir / summary_name).write_text(
            summary,
            encoding="utf-8",
        )
    print(summary)
    print(f"Outputs written to {output_dir.resolve()}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Calculate the true rolling maximum of MRMS FLASH "
            "CREST Maximum Unit Streamflow analyses."
        )
    )
    parser.add_argument(
        "--end-time",
        default=os.environ.get("END_TIME", "").strip(),
        help=(
            "UTC ending analysis, e.g. 2025-07-03T00:20:00Z. "
            "Blank selects the newest available cycle."
        ),
    )
    parser.add_argument(
        "--hours",
        type=int,
        default=DEFAULT_HOURS,
    )
    parser.add_argument(
        "--lookback-minutes",
        type=int,
        default=DEFAULT_LOOKBACK_MINUTES,
    )
    parser.add_argument(
        "--minimum-completeness",
        type=float,
        default=DEFAULT_MINIMUM_COMPLETENESS,
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
    )
    parser.add_argument(
        "--dashboard-only",
        action="store_true",
        help=(
            "Write only the compact dashboard PNG and metadata JSON. "
            "Skip GeoTIFF, HTML, and summary files."
        ),
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
    )
    return parser


def self_test() -> None:
    end = datetime(
        2025,
        7,
        3,
        0,
        20,
        tzinfo=timezone.utc,
    )
    times = expected_cycle_times(end, 24)
    assert len(times) == 144
    assert times[0] == datetime(
        2025,
        7,
        2,
        0,
        30,
        tzinfo=timezone.utc,
    )
    assert times[-1] == end
    print("CREST 24-hour window self-test passed.")


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    if args.hours <= 0:
        parser.error("--hours must be positive")
    if not 0.0 < args.minimum_completeness <= 1.0:
        parser.error(
            "--minimum-completeness must be in (0, 1]"
        )
    run(args)


if __name__ == "__main__":
    main()
