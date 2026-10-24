#!/usr/bin/env python3
"""
Generate operational NLDAS-2 Noah Relative Soil Moisture products for the
WPC Hydrometeorological Dashboard.

Outputs
-------
static/nldas_rsm_0_10cm.png
static/nldas_rsm_0_100cm.png
static/nldas_rsm_metadata.json

Definition
----------
Relative Soil Moisture (% of saturation) is calculated as:

    RSM = 100 * volumetric_soil_moisture / porosity

The operational NLDAS-2 Noah GRIB2 file provides column-integrated soil
moisture in kg m-2. Because 1 kg m-2 of water equals 1 mm of water depth:

    0-10 cm volumetric soil moisture  = CISOILM / 100 mm
    0-100 cm volumetric soil moisture = CISOILM / 1000 mm

The official NASA NLDAS Noah soil-parameter file provides the spatially
varying Noah_porosity field.

Important GRIB2 note
--------------------
The NOAA/NCEP NLDAS Noah file uses local GRIB2 table definitions. Some
ecCodes builds do not reliably expose the layer bounds for every local
record. The official, stable file inventory identifies:

    Record 25: CISOILM, 0-1.0 m below ground
    Record 26: CISOILM, 0-0.1 m below ground

This script extracts those exact records and applies strict grid, units,
value-range, and valid-time checks before producing any output.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import requests
import xarray as xr
from affine import Affine
from eccodes import (
    codes_get,
    codes_get_array,
    codes_grib_new_from_file,
    codes_release,
)
from PIL import Image
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


NLDAS_ROOT = (
    "https://nomads.ncep.noaa.gov/pub/data/nccf/com/nldas/prod"
)
NOAH_SOIL_PARAMETER_URL = (
    "https://ldas.gsfc.nasa.gov/sites/default/files/"
    "ldas/nldas/NLDAS_soil_Noah.nc4"
)

WORK_DIR = Path("nldas_rsm_work")
GRIB_FILE = WORK_DIR / "latest_nldas_noah.grib2"
SOIL_PARAMETER_FILE = WORK_DIR / "NLDAS_soil_Noah.nc4"

OUTPUT_0_10 = Path("static/nldas_rsm_0_10cm.png")
OUTPUT_0_100 = Path("static/nldas_rsm_0_100cm.png")
OUTPUT_METADATA = Path("static/nldas_rsm_metadata.json")

LOOKBACK_DAYS = 20
MAX_OUTPUT_DIMENSION = 1800
RENDER_UPSCALE_FACTOR = 3.0
RENDER_REVISION = "nldas-rsm-percent-saturation-v1.2"

EXPECTED_GRID = {
    "Ni": 464,
    "Nj": 224,
    "number_of_points": 103936,
}

PRODUCT_RECORDS = {
    "0_100cm": {
        "record_number": 25,
        "depth_label": "0-100 cm",
        "depth_m": 1.0,
        "depth_mm": 1000.0,
        "output": OUTPUT_0_100,
        "expected_discipline": 2,
        "expected_parameter_category": 3,
        "expected_parameter_number": 20,
        "authoritative_units": "kg m**-2",
    },
    "0_10cm": {
        "record_number": 26,
        "depth_label": "0-10 cm",
        "depth_m": 0.1,
        "depth_mm": 100.0,
        "output": OUTPUT_0_10,
        "expected_discipline": 2,
        "expected_parameter_category": 3,
        "expected_parameter_number": 20,
        "authoritative_units": "kg m**-2",
    },
}

HEADERS = {
    "User-Agent": (
        "WPC-Hydro-Dashboard/1.0 "
        "(GitHub Actions; NLDAS-2 Noah RSM retrieval)"
    ),
    "Accept": "text/html,application/octet-stream,*/*",
}


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
    session.headers.update(HEADERS)
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session


def fetch_text(
    session: requests.Session,
    url: str,
    timeout: tuple[int, int] = (20, 120),
) -> str:
    response = session.get(url, timeout=timeout)
    response.raise_for_status()
    return response.text


def stream_download(
    session: requests.Session,
    url: str,
    output_path: Path,
    timeout: tuple[int, int] = (20, 300),
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(output_path.suffix + ".part")

    with session.get(url, stream=True, timeout=timeout) as response:
        response.raise_for_status()
        with temporary.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    handle.write(chunk)

    temporary.replace(output_path)


def is_grib(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            return handle.read(4) == b"GRIB"
    except OSError:
        return False


def is_netcdf_or_hdf5(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            magic = handle.read(8)
        return (
            magic.startswith(b"CDF\x01")
            or magic.startswith(b"CDF\x02")
            or magic == b"\x89HDF\r\n\x1a\n"
        )
    except OSError:
        return False


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_available_dates(html: str) -> list[str]:
    return sorted(
        set(re.findall(r"nldas\.(20\d{6})/?", html)),
        reverse=True,
    )


def fallback_dates() -> list[str]:
    now = datetime.now(timezone.utc)
    return [
        (now - timedelta(days=lag)).strftime("%Y%m%d")
        for lag in range(LOOKBACK_DAYS + 1)
    ]


def parse_noah_files(html: str) -> list[tuple[int, str]]:
    pattern = re.compile(
        r'href=["\']([^"\']*noah\.t12z\.grbf(\d{2})'
        r'(?:\.grib2)?)(?:["\'])',
        re.IGNORECASE,
    )

    unique: dict[str, int] = {}

    for filename, forecast_hour in pattern.findall(html):
        name = Path(filename).name
        lowered = name.lower()

        if lowered.endswith((".idx", ".index", ".inv", ".part")):
            continue

        unique[name] = int(forecast_hour)

    return sorted(
        (
            (forecast_hour, filename)
            for filename, forecast_hour in unique.items()
        ),
        reverse=True,
    )


def locate_latest_noah_file(
    session: requests.Session,
) -> tuple[str, int, str, str]:
    try:
        root_html = fetch_text(session, f"{NLDAS_ROOT}/")
        dates = parse_available_dates(root_html)
    except requests.RequestException as error:
        print(f"NLDAS root listing failed: {error}")
        dates = []

    if not dates:
        dates = fallback_dates()

    for date_string in dates[: LOOKBACK_DAYS + 1]:
        directory_url = f"{NLDAS_ROOT}/nldas.{date_string}/"
        print(f"Checking {directory_url}")

        try:
            directory_html = fetch_text(session, directory_url)
        except requests.RequestException as error:
            print(f" -> unavailable: {error}")
            continue

        candidates = parse_noah_files(directory_html)

        if not candidates:
            print(" -> no Noah hourly files found")
            continue

        forecast_hour, filename = candidates[0]
        source_url = f"{directory_url}{filename}"

        print(
            "Selected newest posted NLDAS-2 Noah file: "
            f"{date_string}, f{forecast_hour:02d}, {filename}"
        )

        return (
            date_string,
            forecast_hour,
            filename,
            source_url,
        )

    raise RuntimeError(
        "No operational NLDAS-2 Noah file was found within "
        f"the last {LOOKBACK_DAYS} days."
    )


def safe_codes_get(
    gid: Any,
    key: str,
    default: Any = None,
) -> Any:
    try:
        return codes_get(gid, key)
    except Exception:
        return default


def parse_grib_valid_time(info: dict[str, Any]) -> datetime:
    date_value = int(info["validity_date"])
    time_value = int(info["validity_time"])

    return datetime.strptime(
        f"{date_value:08d}{time_value:04d}",
        "%Y%m%d%H%M",
    ).replace(tzinfo=timezone.utc)


def normalize_longitudes(longitudes: np.ndarray) -> np.ndarray:
    normalized = np.asarray(longitudes, dtype=np.float64).copy()
    normalized[normalized > 180.0] -= 360.0
    return normalized


def extract_required_grib_records(
    path: Path,
) -> tuple[dict[str, dict[str, Any]], int]:
    record_lookup = {
        config["record_number"]: product_key
        for product_key, config in PRODUCT_RECORDS.items()
    }

    selected: dict[str, dict[str, Any]] = {}
    message_number = 0

    with path.open("rb") as handle:
        while True:
            gid = codes_grib_new_from_file(handle)

            if gid is None:
                break

            message_number += 1

            try:
                product_key = record_lookup.get(message_number)

                if product_key is None:
                    continue

                info = {
                    "record_number": message_number,
                    "short_name": str(
                        safe_codes_get(gid, "shortName", "")
                    ),
                    "name": str(
                        safe_codes_get(gid, "name", "")
                    ),
                    "decoded_units": str(
                        safe_codes_get(gid, "units", "")
                    ),
                    "discipline": int(
                        safe_codes_get(gid, "discipline", -1)
                    ),
                    "parameter_category": int(
                        safe_codes_get(
                            gid,
                            "parameterCategory",
                            -1,
                        )
                    ),
                    "parameter_number": int(
                        safe_codes_get(
                            gid,
                            "parameterNumber",
                            -1,
                        )
                    ),
                    "type_of_level": str(
                        safe_codes_get(gid, "typeOfLevel", "")
                    ),
                    "Ni": int(
                        safe_codes_get(gid, "Ni", 0)
                    ),
                    "Nj": int(
                        safe_codes_get(gid, "Nj", 0)
                    ),
                    "number_of_points": int(
                        safe_codes_get(gid, "numberOfPoints", 0)
                    ),
                    "validity_date": int(
                        safe_codes_get(gid, "validityDate", 0)
                    ),
                    "validity_time": int(
                        safe_codes_get(gid, "validityTime", 0)
                    ),
                    "data_date": int(
                        safe_codes_get(gid, "dataDate", 0)
                    ),
                    "data_time": int(
                        safe_codes_get(gid, "dataTime", 0)
                    ),
                    "forecast_time": int(
                        safe_codes_get(gid, "forecastTime", 0)
                    ),
                }

                values = np.asarray(
                    codes_get_array(gid, "values"),
                    dtype=np.float64,
                )
                latitudes = np.asarray(
                    codes_get_array(gid, "latitudes"),
                    dtype=np.float64,
                )
                longitudes = normalize_longitudes(
                    codes_get_array(gid, "longitudes")
                )

                if not (
                    values.size
                    == latitudes.size
                    == longitudes.size
                    == info["number_of_points"]
                ):
                    raise RuntimeError(
                        f"Record {message_number} has inconsistent "
                        "data and coordinate array sizes."
                    )

                for key, expected in EXPECTED_GRID.items():
                    if info[key] != expected:
                        raise RuntimeError(
                            f"Record {message_number} has unexpected "
                            f"{key}={info[key]}; expected {expected}."
                        )

                config = PRODUCT_RECORDS[product_key]

                parameter_checks = {
                    "discipline": config["expected_discipline"],
                    "parameter_category": (
                        config["expected_parameter_category"]
                    ),
                    "parameter_number": (
                        config["expected_parameter_number"]
                    ),
                }

                for key, expected in parameter_checks.items():
                    if info[key] != expected:
                        raise RuntimeError(
                            f"Record {message_number} has unexpected "
                            f"{key}={info[key]}; expected {expected} "
                            "for CISOILM."
                        )

                decoded_units = info["decoded_units"].strip()
                normalized_units = decoded_units.lower()

                if normalized_units in {"", "unknown"}:
                    # ecCodes can report "unknown" for these NLDAS local
                    # GRIB2 records even though the official NOAA inventory
                    # defines CISOILM as kg m-2. Preserve both values in the
                    # metadata and use the authoritative inventory units.
                    info["units"] = config["authoritative_units"]
                    info["units_source"] = (
                        "NOAA/NCEP NLDAS Noah inventory"
                    )
                    print(
                        f"Record {message_number}: ecCodes returned "
                        f"{decoded_units or 'blank'} units; using "
                        f"authoritative CISOILM units "
                        f"{info['units']}."
                    )
                elif "kg" in normalized_units:
                    info["units"] = decoded_units
                    info["units_source"] = "ecCodes"
                else:
                    raise RuntimeError(
                        f"Record {message_number} has unexpected "
                        f"decoded units {decoded_units!r}; expected "
                        "CISOILM in kg m-2."
                    )

                selected[product_key] = {
                    "info": info,
                    "values": values,
                    "latitudes": latitudes,
                    "longitudes": longitudes,
                }

                print(
                    f"Extracted record {message_number} for "
                    f"{PRODUCT_RECORDS[product_key]['depth_label']}: "
                    f"{info['short_name']} | {info['name']} | "
                    f"{info['units']} "
                    f"(decoded={info['decoded_units']!r})"
                )

            finally:
                codes_release(gid)

    if message_number != 51:
        raise RuntimeError(
            "Unexpected NLDAS Noah record count: "
            f"{message_number}; expected 51."
        )

    missing = sorted(set(PRODUCT_RECORDS) - set(selected))

    if missing:
        raise RuntimeError(
            "Required NLDAS Noah records were not extracted: "
            + ", ".join(missing)
        )

    valid_times = {
        parse_grib_valid_time(item["info"])
        for item in selected.values()
    }

    if len(valid_times) != 1:
        raise RuntimeError(
            "The two NLDAS soil-moisture records have "
            "different valid times."
        )

    return selected, message_number


def load_noah_porosity(
    path: Path,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    with xr.open_dataset(
        path,
        engine="h5netcdf",
        mask_and_scale=True,
    ) as dataset:
        required = {"lat", "lon", "Noah_porosity"}

        if not required.issubset(dataset.variables):
            missing = sorted(required - set(dataset.variables))
            raise RuntimeError(
                "NASA Noah soil-parameter file is missing: "
                + ", ".join(missing)
            )

        latitudes = np.asarray(
            dataset["lat"].values,
            dtype=np.float64,
        )
        longitudes = normalize_longitudes(
            dataset["lon"].values
        )

        porosity_array = (
            dataset["Noah_porosity"]
            .squeeze(drop=True)
            .transpose("lat", "lon")
        )
        porosity = np.asarray(
            porosity_array.values,
            dtype=np.float64,
        )

    if latitudes.ndim != 1 or longitudes.ndim != 1:
        raise RuntimeError(
            "NASA porosity latitude/longitude coordinates "
            "are not one-dimensional."
        )

    if porosity.shape != (
        EXPECTED_GRID["Nj"],
        EXPECTED_GRID["Ni"],
    ):
        raise RuntimeError(
            "NASA Noah_porosity grid has unexpected shape "
            f"{porosity.shape}."
        )

    if not np.all(np.diff(latitudes) > 0.0):
        raise RuntimeError(
            "NASA porosity latitude coordinates are not increasing."
        )

    if not np.all(np.diff(longitudes) > 0.0):
        raise RuntimeError(
            "NASA porosity longitude coordinates are not increasing."
        )

    porosity[
        ~np.isfinite(porosity)
        | (porosity < 0.30)
        | (porosity > 0.60)
    ] = np.nan

    valid = porosity[np.isfinite(porosity)]

    if valid.size == 0:
        raise RuntimeError(
            "NASA Noah_porosity contains no valid land values."
        )

    print(
        "Noah_porosity range: "
        f"{float(np.nanmin(valid)):.3f} to "
        f"{float(np.nanmax(valid)):.3f}"
    )

    return latitudes, longitudes, porosity


def map_points_to_static_grid(
    values: np.ndarray,
    point_latitudes: np.ndarray,
    point_longitudes: np.ndarray,
    grid_latitudes: np.ndarray,
    grid_longitudes: np.ndarray,
) -> np.ndarray:
    lat_step = float(np.median(np.diff(grid_latitudes)))
    lon_step = float(np.median(np.diff(grid_longitudes)))

    lat_indices = np.rint(
        (point_latitudes - grid_latitudes[0]) / lat_step
    ).astype(np.int64)
    lon_indices = np.rint(
        (point_longitudes - grid_longitudes[0]) / lon_step
    ).astype(np.int64)

    inside = (
        np.isfinite(point_latitudes)
        & np.isfinite(point_longitudes)
        & (lat_indices >= 0)
        & (lat_indices < grid_latitudes.size)
        & (lon_indices >= 0)
        & (lon_indices < grid_longitudes.size)
    )

    if int(np.count_nonzero(inside)) != values.size:
        raise RuntimeError(
            "One or more GRIB points do not map onto the "
            "NASA static NLDAS grid."
        )

    mapped_latitudes = grid_latitudes[lat_indices]
    mapped_longitudes = grid_longitudes[lon_indices]

    coordinate_tolerance = max(
        abs(lat_step),
        abs(lon_step),
    ) * 0.05

    coordinate_error = np.maximum(
        np.abs(mapped_latitudes - point_latitudes),
        np.abs(mapped_longitudes - point_longitudes),
    )

    if float(np.nanmax(coordinate_error)) > coordinate_tolerance:
        raise RuntimeError(
            "GRIB coordinates do not align closely enough with "
            "the NASA static NLDAS grid."
        )

    flat_indices = (
        lat_indices * grid_longitudes.size + lon_indices
    )

    if np.unique(flat_indices).size != values.size:
        raise RuntimeError(
            "Duplicate GRIB points were found while mapping "
            "to the NASA static grid."
        )

    grid = np.full(
        (grid_latitudes.size, grid_longitudes.size),
        np.nan,
        dtype=np.float64,
    )
    grid[lat_indices, lon_indices] = values

    return grid


def calculate_rsm(
    storage_kg_m2: np.ndarray,
    porosity: np.ndarray,
    depth_mm: float,
) -> tuple[np.ndarray, dict[str, float]]:
    storage = np.asarray(storage_kg_m2, dtype=np.float64)

    storage[
        ~np.isfinite(storage)
        | (storage < 0.0)
        | (storage > depth_mm * 0.75)
    ] = np.nan

    volumetric_soil_moisture = storage / depth_mm

    with np.errstate(divide="ignore", invalid="ignore"):
        raw_rsm = (
            volumetric_soil_moisture / porosity * 100.0
        )

    # Values far above saturation are treated as missing because they
    # indicate fill values, a wrong record, or a grid mismatch. Small model
    # overshoots are clipped to the physical display range of 0-100%.
    raw_rsm[
        ~np.isfinite(raw_rsm)
        | (raw_rsm < 0.0)
        | (raw_rsm > 120.0)
    ] = np.nan

    clipped_count = int(
        np.count_nonzero(
            np.isfinite(raw_rsm) & (raw_rsm > 100.0)
        )
    )

    rsm = np.clip(raw_rsm, 0.0, 100.0)

    valid = rsm[np.isfinite(rsm)]

    if valid.size == 0:
        raise RuntimeError(
            "The calculated RSM field contains no valid values."
        )

    stats = {
        "minimum": round(float(np.nanmin(valid)), 2),
        "maximum": round(float(np.nanmax(valid)), 2),
        "mean": round(float(np.nanmean(valid)), 2),
        "percent_at_or_above_70": round(
            float(100.0 * np.mean(valid >= 70.0)),
            2,
        ),
        "percent_at_or_above_90": round(
            float(100.0 * np.mean(valid >= 90.0)),
            2,
        ),
        "clipped_above_100_count": clipped_count,
        "valid_grid_cells": int(valid.size),
    }

    return rsm.astype(np.float32), stats


def reproject_to_web_mercator(
    source_data: np.ndarray,
    latitudes: np.ndarray,
    longitudes: np.ndarray,
) -> tuple[np.ndarray, list[list[float]]]:
    latitude_step = float(np.median(np.diff(latitudes)))
    longitude_step = float(np.median(np.diff(longitudes)))

    if latitude_step <= 0.0 or longitude_step <= 0.0:
        raise RuntimeError(
            "Invalid NLDAS source-grid spacing."
        )

    # The NASA static grid is south-to-north. Rasterio expects row zero
    # at the northern edge, so the data are reversed vertically.
    north_up_data = source_data[::-1, :]

    source_transform = from_origin(
        west=float(longitudes[0] - longitude_step / 2.0),
        north=float(latitudes[-1] + latitude_step / 2.0),
        xsize=longitude_step,
        ysize=latitude_step,
    )

    source_crs = CRS.from_epsg(4326)
    destination_crs = CRS.from_epsg(3857)

    source_height, source_width = north_up_data.shape
    source_bounds = array_bounds(
        source_height,
        source_width,
        source_transform,
    )

    (
        destination_transform,
        destination_width,
        destination_height,
    ) = calculate_default_transform(
        source_crs,
        destination_crs,
        source_width,
        source_height,
        *source_bounds,
    )

    native_destination_width = destination_width
    native_destination_height = destination_height

    # The Web Mercator reprojection of the native 0.125-degree NLDAS grid
    # is only about 435 x 277 pixels over CONUS. Render at three times that
    # pixel density so Leaflet does not have to enlarge a small PNG across
    # the map. Nearest-neighbor resampling below preserves crisp native-grid
    # boundaries and does not invent additional meteorological resolution.
    upscale_factor = min(
        RENDER_UPSCALE_FACTOR,
        MAX_OUTPUT_DIMENSION / native_destination_width,
        MAX_OUTPUT_DIMENSION / native_destination_height,
    )
    upscale_factor = max(upscale_factor, 1.0)

    destination_width = max(
        1,
        int(round(native_destination_width * upscale_factor)),
    )
    destination_height = max(
        1,
        int(round(native_destination_height * upscale_factor)),
    )

    destination_transform = (
        destination_transform
        * Affine.scale(
            native_destination_width / destination_width,
            native_destination_height / destination_height,
        )
    )

    destination = np.full(
        (destination_height, destination_width),
        np.nan,
        dtype=np.float32,
    )
    destination_valid = np.zeros(
        (destination_height, destination_width),
        dtype=np.uint8,
    )
    source_valid = np.isfinite(north_up_data).astype(
        np.uint8
    )

    reproject(
        source=north_up_data,
        destination=destination,
        src_transform=source_transform,
        src_crs=source_crs,
        src_nodata=np.nan,
        dst_transform=destination_transform,
        dst_crs=destination_crs,
        dst_nodata=np.nan,
        resampling=Resampling.nearest,
        init_dest_nodata=True,
        num_threads=2,
    )

    reproject(
        source=source_valid,
        destination=destination_valid,
        src_transform=source_transform,
        src_crs=source_crs,
        src_nodata=0,
        dst_transform=destination_transform,
        dst_crs=destination_crs,
        dst_nodata=0,
        resampling=Resampling.nearest,
        init_dest_nodata=True,
        num_threads=2,
    )

    destination[destination_valid == 0] = np.nan
    destination[
        (destination < 0.0)
        | (destination > 100.0)
    ] = np.nan

    projected_bounds = array_bounds(
        destination_height,
        destination_width,
        destination_transform,
    )

    west, south, east, north = transform_bounds(
        destination_crs,
        CRS.from_epsg(4326),
        *projected_bounds,
        densify_pts=21,
    )

    leaflet_bounds = [
        [float(south), float(west)],
        [float(north), float(east)],
    ]

    print(
        "NLDAS RSM Web Mercator render: "
        f"{native_destination_width}x{native_destination_height} native "
        f"-> {destination_width}x{destination_height} output; "
        "nearest-neighbor resampling"
    )

    return destination, leaflet_bounds


def create_rsm_rgba(data: np.ndarray) -> np.ndarray:
    # Percent-of-saturation palette. Lower values remain visible but
    # increasingly transparent; the wet and near-saturated tail receives
    # the strongest color emphasis.
    palette = np.array(
        [
            [150, 110, 70, 105],   # 0-40
            [210, 190, 120, 125],  # 40-50
            [170, 215, 130, 150],  # 50-60
            [90, 190, 120, 175],   # 60-70
            [35, 185, 190, 205],   # 70-80
            [45, 125, 230, 225],   # 80-90
            [20, 50, 170, 245],    # 90-95
            [125, 0, 175, 255],    # 95-100
        ],
        dtype=np.uint8,
    )

    rgba = np.zeros(
        (data.shape[0], data.shape[1], 4),
        dtype=np.uint8,
    )
    valid = np.isfinite(data)

    class_index = np.digitize(
        data,
        bins=[40, 50, 60, 70, 80, 90, 95],
        right=False,
    )

    rgba[valid] = palette[class_index[valid]]
    return rgba


def atomic_save_png(
    rgba: np.ndarray,
    output_path: Path,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(
        output_path.suffix + ".tmp"
    )

    Image.fromarray(rgba).save(
        temporary,
        format="PNG",
        optimize=True,
    )
    temporary.replace(output_path)


def atomic_write_json(
    payload: dict[str, Any],
    output_path: Path,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(
        output_path.suffix + ".tmp"
    )
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    temporary.replace(output_path)


def load_existing_metadata() -> dict[str, Any] | None:
    try:
        return json.loads(
            OUTPUT_METADATA.read_text(encoding="utf-8")
        )
    except Exception:
        return None


def compatible_previous_outputs_exist() -> bool:
    metadata = load_existing_metadata()

    if metadata is None:
        return False

    return (
        OUTPUT_0_10.exists()
        and OUTPUT_0_100.exists()
        and str(metadata.get("image_crs", "")).upper()
        == "EPSG:3857"
        and metadata.get("render_revision")
        == RENDER_REVISION
    )


def source_is_unchanged(source_sha256: str) -> bool:
    metadata = load_existing_metadata()

    if metadata is None:
        return False

    return (
        compatible_previous_outputs_exist()
        and metadata.get("source_sha256") == source_sha256
    )


def cleanup_work_files() -> None:
    GRIB_FILE.unlink(missing_ok=True)
    SOIL_PARAMETER_FILE.unlink(missing_ok=True)


def main() -> int:
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    session = build_session()

    try:
        (
            directory_date,
            forecast_hour,
            source_filename,
            source_url,
        ) = locate_latest_noah_file(session)

        print(f"Downloading {source_url}")
        stream_download(session, source_url, GRIB_FILE)

        if not is_grib(GRIB_FILE):
            raise RuntimeError(
                "The downloaded NLDAS Noah file is not GRIB."
            )

        source_sha256 = sha256_file(GRIB_FILE)

        if source_is_unchanged(source_sha256):
            print(
                "The newest NLDAS source file is unchanged; "
                "keeping the existing RSM outputs."
            )
            return 0

        selected, total_records = extract_required_grib_records(
            GRIB_FILE
        )

        valid_time = parse_grib_valid_time(
            selected["0_100cm"]["info"]
        )

        print(
            "Downloading official NASA Noah soil parameters: "
            f"{NOAH_SOIL_PARAMETER_URL}"
        )
        stream_download(
            session,
            NOAH_SOIL_PARAMETER_URL,
            SOIL_PARAMETER_FILE,
        )

        if not is_netcdf_or_hdf5(SOIL_PARAMETER_FILE):
            raise RuntimeError(
                "The downloaded NASA Noah soil-parameter file "
                "is not NetCDF/HDF5."
            )

        soil_parameter_sha256 = sha256_file(
            SOIL_PARAMETER_FILE
        )

        (
            grid_latitudes,
            grid_longitudes,
            porosity,
        ) = load_noah_porosity(SOIL_PARAMETER_FILE)

        product_metadata: dict[str, Any] = {}
        common_bounds: list[list[float]] | None = None

        for product_key, config in PRODUCT_RECORDS.items():
            record = selected[product_key]

            storage_grid = map_points_to_static_grid(
                values=record["values"],
                point_latitudes=record["latitudes"],
                point_longitudes=record["longitudes"],
                grid_latitudes=grid_latitudes,
                grid_longitudes=grid_longitudes,
            )

            rsm, statistics = calculate_rsm(
                storage_kg_m2=storage_grid,
                porosity=porosity,
                depth_mm=float(config["depth_mm"]),
            )

            projected_rsm, leaflet_bounds = (
                reproject_to_web_mercator(
                    rsm,
                    grid_latitudes,
                    grid_longitudes,
                )
            )

            if common_bounds is None:
                common_bounds = leaflet_bounds
            elif not np.allclose(
                np.asarray(common_bounds),
                np.asarray(leaflet_bounds),
                atol=1.0e-6,
            ):
                raise RuntimeError(
                    "The two NLDAS RSM products produced "
                    "different map bounds."
                )

            rgba = create_rsm_rgba(projected_rsm)
            output_path = Path(config["output"])
            atomic_save_png(rgba, output_path)

            info = record["info"]

            product_metadata[product_key] = {
                "product": (
                    "NLDAS-2 Noah Relative Soil Moisture "
                    f"({config['depth_label']})"
                ),
                "depth": config["depth_label"],
                "units": "percent of saturation",
                "image": str(output_path).replace("\\", "/"),
                "record_number": int(
                    config["record_number"]
                ),
                "source_parameter": (
                    "CISOILM - Column-Integrated Soil Moisture"
                ),
                "source_units": info["units"],
                "layer_depth_mm": float(
                    config["depth_mm"]
                ),
                "rendered_width": int(projected_rsm.shape[1]),
                "rendered_height": int(projected_rsm.shape[0]),
                "resampling": "nearest",
                "statistics": statistics,
            }

            print(
                f"Wrote {output_path}; valid RSM range "
                f"{statistics['minimum']:.1f}-"
                f"{statistics['maximum']:.1f}%"
            )

        if common_bounds is None:
            raise RuntimeError(
                "No NLDAS RSM products were generated."
            )

        retrieval_time = datetime.now(timezone.utc)

        metadata = {
            "valid_time": valid_time.strftime(
                "NLDAS-2 Noah RSM: %b %d, %Y %HZ"
            ),
            "valid_time_iso": valid_time.strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),
            "retrieved_time": retrieval_time.strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),
            "data_age_hours": round(
                (
                    retrieval_time - valid_time
                ).total_seconds() / 3600.0,
                1,
            ),
            "bounds": common_bounds,
            "crs": "EPSG:3857",
            "image_crs": "EPSG:3857",
            "bounds_crs": "EPSG:4326",
            "render_revision": RENDER_REVISION,
            "units": "percent of saturation",
            "formula": (
                "100 * (CISOILM_kg_m-2 / layer_depth_mm) "
                "/ Noah_porosity"
            ),
            "display_scale": [
                "0-40",
                "40-50",
                "50-60",
                "60-70",
                "70-80",
                "80-90",
                "90-95",
                "95-100",
            ],
            "source": {
                "nldas_root": NLDAS_ROOT,
                "directory_date": directory_date,
                "forecast_hour": forecast_hour,
                "filename": source_filename,
                "url": source_url,
                "sha256": source_sha256,
                "record_count": total_records,
            },
            "source_sha256": source_sha256,
            "soil_parameters": {
                "url": NOAH_SOIL_PARAMETER_URL,
                "variable": "Noah_porosity",
                "sha256": soil_parameter_sha256,
            },
            "grid": {
                "Ni": EXPECTED_GRID["Ni"],
                "Nj": EXPECTED_GRID["Nj"],
                "resolution_degrees": 0.125,
            },
            "rendering": {
                "upscale_factor": RENDER_UPSCALE_FACTOR,
                "maximum_output_dimension": MAX_OUTPUT_DIMENSION,
                "resampling": "nearest",
                "purpose": (
                    "crisp display of native NLDAS grid cells; "
                    "no added meteorological resolution"
                ),
            },
            "products": product_metadata,
        }

        atomic_write_json(metadata, OUTPUT_METADATA)

        print(f"Wrote {OUTPUT_METADATA}")
        print(
            "NLDAS-2 Noah RSM products successfully "
            "generated in EPSG:3857."
        )
        return 0

    except Exception as error:
        print(f"WARNING: NLDAS-2 RSM update failed: {error}")

        if compatible_previous_outputs_exist():
            print(
                "Keeping the previous revision-compatible "
                "NLDAS-2 RSM outputs."
            )
            return 0

        print(
            "No compatible previous NLDAS-2 RSM outputs "
            "exist; the workflow must fail."
        )
        return 1

    finally:
        cleanup_work_files()


if __name__ == "__main__":
    sys.exit(main())
