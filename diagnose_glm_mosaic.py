#!/usr/bin/env python3
"""Artifact-only GOES GLM controlled CONUS mosaic diagnostic.

This script reads public NOAA GLM-L2-LCFA files from the GOES-19 and
GOES-18 AWS Open Data buckets. It processes one synchronized rolling hour
per satellite and derives 5-, 30-, and 60-minute LCFA-based lightning
fields.

The two satellite views are combined with an exclusive source-ownership
mask. Each native 0.02-degree grid cell is assigned to the satellite whose
sub-satellite point has the smaller spherical central angle to that cell.
The selected values are copied into the mosaic without summing, averaging,
blending, or secondary-source gap filling.

The diagnostic writes three controlled-mosaic GeoTIFF/PNG/metadata sets, a
source-ownership mask, a seam-comparison summary, and a self-contained HTML
preview that also embeds the separate GOES-19 and GOES-18 reference layers.
It does not modify or publish dashboard repository products.
"""

from __future__ import annotations

import argparse
import base64
import csv
import json
import math
import re
import shutil
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Sequence

import boto3
import numpy as np
import xarray as xr
from botocore import UNSIGNED
from botocore.config import Config
from PIL import Image
from rasterio import open as rio_open
from rasterio.enums import Resampling
from rasterio.transform import array_bounds, from_origin
from rasterio.warp import calculate_default_transform, reproject, transform_bounds

UTC = timezone.utc
PRODUCT_PREFIX = "GLM-L2-LCFA"
SATELLITES = {
    "G19": {
        "bucket": "noaa-goes19",
        "label": "GOES-19 (East)",
        "subsatellite_longitude": -75.2,
        "source_code": 19,
    },
    "G18": {
        "bucket": "noaa-goes18",
        "label": "GOES-18 (West)",
        "subsatellite_longitude": -137.0,
        "source_code": 18,
    },
}

WEST = -130.0
EAST = -60.0
SOUTH = 20.0
NORTH = 55.0
DEFAULT_RESOLUTION_DEGREES = 0.02
WINDOWS_MINUTES = (5, 30, 60)
MAX_WINDOW_MINUTES = max(WINDOWS_MINUTES)
CANDIDATE_STEP_MINUTES = 5
LCFA_FILES_PER_MINUTE = 3
DEFAULT_SEAM_BAND_DEGREES = 5.0

FIVE_MIN_BINS = [1, 2, 4, 8, 16, 32, 64, 128]
FIVE_MIN_LABELS = [
    "1",
    "2–3",
    "4–7",
    "8–15",
    "16–31",
    "32–63",
    "64–127",
    "≥128",
]
FIVE_MIN_RGBA = [
    (0, 255, 255, 210),
    (0, 255, 0, 210),
    (255, 255, 0, 220),
    (255, 153, 0, 225),
    (255, 0, 0, 230),
    (255, 0, 255, 235),
    (199, 125, 255, 240),
    (255, 255, 255, 248),
]

ROLLING_BINS = [1, 2, 4, 8, 16, 32, 64, 128, 256, 512]
ROLLING_LABELS = [
    "1",
    "2–3",
    "4–7",
    "8–15",
    "16–31",
    "32–63",
    "64–127",
    "128–255",
    "256–511",
    "≥512",
]
ROLLING_RGBA = [
    (0, 255, 255, 210),
    (0, 255, 0, 210),
    (255, 255, 0, 220),
    (255, 153, 0, 225),
    (255, 0, 0, 230),
    (255, 0, 255, 235),
    (199, 125, 255, 240),
    (0, 102, 255, 242),
    (102, 204, 255, 246),
    (255, 255, 255, 250),
]

SOURCE_RGBA = {
    18: (0, 153, 255, 92),
    19: (255, 196, 0, 92),
}

FILENAME_TIME_RE = re.compile(r"_s(?P<start>\d{13,16})_e(?P<end>\d{13,16})_")


@dataclass(frozen=True)
class GridSpec:
    west: float = WEST
    east: float = EAST
    south: float = SOUTH
    north: float = NORTH
    resolution: float = DEFAULT_RESOLUTION_DEGREES

    @property
    def width(self) -> int:
        return int(round((self.east - self.west) / self.resolution))

    @property
    def height(self) -> int:
        return int(round((self.north - self.south) / self.resolution))

    @property
    def transform(self):
        return from_origin(self.west, self.north, self.resolution, self.resolution)

    def center_coordinates(self) -> tuple[np.ndarray, np.ndarray]:
        lon = self.west + (np.arange(self.width, dtype=np.float64) + 0.5) * self.resolution
        lat = self.north - (np.arange(self.height, dtype=np.float64) + 0.5) * self.resolution
        return np.meshgrid(lon, lat)


@dataclass
class FileStats:
    file_name: str
    file_start_utc: str
    flashes_quality_controlled: int
    events_mapped_to_good_flashes: int
    events_in_domain: int
    flash_cell_contributions: int
    included_5min: bool
    included_30min: bool
    included_60min: bool


@dataclass
class SatelliteWindowStats:
    satellite: str
    satellite_label: str
    window_minutes: int
    window_start_utc: str
    window_end_utc: str
    expected_files: int
    listed_files: int
    processed_files: int
    completeness_fraction: float
    quality_controlled_flash_records: int
    events_mapped_to_good_flashes: int
    events_in_domain: int
    flash_cell_contributions: int
    nonzero_grid_cells: int
    maximum_value: int


@dataclass
class SatelliteAggregate:
    satellite: str
    arrays: dict[int, np.ndarray]
    stats: dict[int, SatelliteWindowStats]


@dataclass
class MosaicResult:
    window_minutes: int
    product_kind: str
    display_label: str
    window_start_utc: str
    window_end_utc: str
    maximum_value: int
    nonzero_grid_cells: int
    flash_cell_contributions: int
    source_g18_owned_cells: int
    source_g19_owned_cells: int
    source_g18_nonzero_cells: int
    source_g19_nonzero_cells: int
    native_geotiff: str
    leaflet_png: str
    metadata_json: str
    image_crs: str
    leaflet_bounds: list[list[float]]
    rendered_shape: list[int]
    legend_id: str


def utc_now() -> datetime:
    return datetime.now(UTC)


def iso_z(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_utc(value: str) -> datetime:
    text = value.strip()
    if not text:
        raise ValueError("Empty UTC time")
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def floor_to_candidate(value: datetime) -> datetime:
    value = value.astimezone(UTC).replace(second=0, microsecond=0)
    return value.replace(minute=(value.minute // CANDIDATE_STEP_MINUTES) * CANDIDATE_STEP_MINUTES)


def expected_files(window_minutes: int) -> int:
    return window_minutes * LCFA_FILES_PER_MINUTE


def parse_goes_timestamp(digits: str) -> datetime:
    if len(digits) < 13:
        raise ValueError(f"Invalid GOES timestamp: {digits}")
    base = datetime.strptime(digits[:13], "%Y%j%H%M%S").replace(tzinfo=UTC)
    fractional = digits[13:]
    if fractional:
        base += timedelta(seconds=int(fractional) / (10 ** len(fractional)))
    return base


def key_start_time(key: str) -> datetime | None:
    match = FILENAME_TIME_RE.search(Path(key).name)
    if not match:
        return None
    return parse_goes_timestamp(match.group("start"))


def build_s3_client():
    return boto3.client(
        "s3",
        config=Config(
            signature_version=UNSIGNED,
            retries={"max_attempts": 10, "mode": "standard"},
        ),
    )


def hour_starts(window_start: datetime, window_end: datetime) -> Iterable[datetime]:
    cursor = window_start.replace(minute=0, second=0, microsecond=0)
    final = (window_end - timedelta(microseconds=1)).replace(
        minute=0, second=0, microsecond=0
    )
    while cursor <= final:
        yield cursor
        cursor += timedelta(hours=1)


def list_prefix_keys(client, bucket: str, prefix: str) -> list[str]:
    keys: list[str] = []
    continuation: str | None = None
    while True:
        kwargs = {"Bucket": bucket, "Prefix": prefix, "MaxKeys": 1000}
        if continuation:
            kwargs["ContinuationToken"] = continuation
        response = client.list_objects_v2(**kwargs)
        keys.extend(
            item["Key"]
            for item in response.get("Contents", [])
            if item.get("Key", "").endswith(".nc")
        )
        if not response.get("IsTruncated"):
            break
        continuation = response.get("NextContinuationToken")
        if not continuation:
            break
    return keys


def list_window_keys(
    client,
    bucket: str,
    window_start: datetime,
    window_end: datetime,
) -> list[str]:
    candidates: list[str] = []
    for hour in hour_starts(window_start, window_end):
        prefix = (
            f"{PRODUCT_PREFIX}/{hour.year}/"
            f"{hour.timetuple().tm_yday:03d}/{hour.hour:02d}/"
        )
        candidates.extend(list_prefix_keys(client, bucket, prefix))

    selected: list[tuple[datetime, str]] = []
    for key in candidates:
        start = key_start_time(key)
        if start is not None and window_start <= start < window_end:
            selected.append((start, key))
    selected.sort(key=lambda item: item[0])
    return [key for _, key in selected]


def count_keys_in_window(keys: Sequence[str], start: datetime, end: datetime) -> int:
    return sum(
        1
        for key in keys
        if (key_time := key_start_time(key)) is not None and start <= key_time < end
    )


def resolve_common_end_time(
    client,
    requested_end: str,
    lookback_minutes: int,
    minimum_completeness: float,
) -> tuple[datetime, dict[str, list[str]]]:
    if requested_end.strip():
        candidates = [floor_to_candidate(parse_utc(requested_end))]
    else:
        newest = floor_to_candidate(utc_now())
        candidates = [
            newest - timedelta(minutes=offset)
            for offset in range(0, lookback_minutes + 1, CANDIDATE_STEP_MINUTES)
        ]

    attempts: list[str] = []
    for end in candidates:
        full_start = end - timedelta(minutes=MAX_WINDOW_MINUTES)
        keys_by_satellite: dict[str, list[str]] = {}
        complete = True
        detail_parts: list[str] = []

        for satellite, config in SATELLITES.items():
            keys = list_window_keys(client, config["bucket"], full_start, end)
            keys_by_satellite[satellite] = keys
            counts = []
            for window_minutes in WINDOWS_MINUTES:
                start = end - timedelta(minutes=window_minutes)
                listed = count_keys_in_window(keys, start, end)
                minimum = math.ceil(expected_files(window_minutes) * minimum_completeness)
                counts.append(f"{window_minutes}m={listed}/{expected_files(window_minutes)}")
                if listed < minimum:
                    complete = False
            detail_parts.append(f"{satellite} " + ", ".join(counts))

        attempts.append(f"end {iso_z(end)} ({'; '.join(detail_parts)})")
        if complete:
            print(f"Resolved common GLM mosaic end time: {attempts[-1]}")
            return end, keys_by_satellite

        if requested_end.strip():
            break

    detail = "\n  ".join(attempts[:12])
    raise RuntimeError(
        "Could not find a common GOES-19/GOES-18 set of 5-, 30-, and "
        f"60-minute windows meeting minimum completeness {minimum_completeness:.0%}.\n"
        f"Recent attempts:\n  {detail}"
    )


def download_keys(
    client,
    bucket: str,
    keys: Sequence[str],
    destination: Path,
    workers: int,
) -> list[Path]:
    destination.mkdir(parents=True, exist_ok=True)

    def download_one(key: str) -> Path:
        target = destination / Path(key).name
        client.download_file(bucket, key, str(target))
        return target

    completed: list[Path] = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        future_map = {executor.submit(download_one, key): key for key in keys}
        for future in as_completed(future_map):
            key = future_map[future]
            try:
                completed.append(future.result())
            except Exception as error:
                print(f"WARNING: failed to download {key}: {error}", file=sys.stderr)
    completed.sort(key=lambda path: key_start_time(path.name) or datetime.min.replace(tzinfo=UTC))
    return completed


def _unsigned_requested(variable: xr.DataArray) -> bool:
    return str(variable.attrs.get("_Unsigned", "false")).strip().lower() == "true"


def _reinterpret_unsigned(raw: np.ndarray, variable: xr.DataArray) -> np.ndarray:
    if _unsigned_requested(variable) and raw.dtype.kind == "i":
        return raw.view(np.dtype(f"u{raw.dtype.itemsize}"))
    return raw


def _missing_mask(raw: np.ndarray, variable: xr.DataArray) -> np.ndarray:
    mask = np.zeros(raw.shape, dtype=bool)
    if raw.dtype.kind == "f":
        mask |= ~np.isfinite(raw)
    for key in ("_FillValue", "missing_value"):
        if key not in variable.attrs:
            continue
        for candidate in np.asarray(variable.attrs[key]).reshape(-1):
            try:
                mask |= raw == candidate
            except (TypeError, ValueError):
                pass
    return mask


def science_values(dataset: xr.Dataset, name: str) -> np.ndarray:
    if name not in dataset.variables:
        raise KeyError(f"Required LCFA variable missing: {name}")
    variable = dataset[name]
    raw = np.asarray(variable.values)
    missing = _missing_mask(raw, variable)
    unpacked = _reinterpret_unsigned(raw, variable).astype(np.float64, copy=False)
    scale = float(np.asarray(variable.attrs.get("scale_factor", 1.0)).reshape(-1)[0])
    offset = float(np.asarray(variable.attrs.get("add_offset", 0.0)).reshape(-1)[0])
    decoded = np.asarray(unpacked * scale + offset, dtype=np.float64)
    decoded[missing] = np.nan
    return decoded


def identifier_values(dataset: xr.Dataset, name: str) -> np.ndarray:
    if name not in dataset.variables:
        raise KeyError(f"Required LCFA variable missing: {name}")
    variable = dataset[name]
    raw = np.asarray(variable.values)
    return _reinterpret_unsigned(raw, variable).astype(np.int64, copy=False)


def quality_mask(dataset: xr.Dataset, name: str, length: int) -> np.ndarray:
    if name not in dataset.variables:
        return np.ones(length, dtype=bool)
    raw = identifier_values(dataset, name).reshape(-1)
    if raw.size != length:
        raise ValueError(f"{name} length {raw.size} does not match expected {length}")
    return raw == 0


def map_events_to_flashes(dataset: xr.Dataset) -> tuple[np.ndarray, np.ndarray, np.ndarray, int]:
    event_lat = science_values(dataset, "event_lat").reshape(-1)
    event_lon = science_values(dataset, "event_lon").reshape(-1)
    event_parent_group = identifier_values(dataset, "event_parent_group_id").reshape(-1)

    group_id = identifier_values(dataset, "group_id").reshape(-1)
    group_parent_flash = identifier_values(dataset, "group_parent_flash_id").reshape(-1)
    flash_id = identifier_values(dataset, "flash_id").reshape(-1)

    flash_good = quality_mask(dataset, "flash_quality_flag", flash_id.size)
    group_good = quality_mask(dataset, "group_quality_flag", group_id.size)
    valid_flash_ids = flash_id[flash_good]

    group_good &= np.isin(group_parent_flash, valid_flash_ids)
    valid_group_id = group_id[group_good]
    valid_group_flash = group_parent_flash[group_good]

    if valid_group_id.size == 0 or event_parent_group.size == 0:
        return event_lat[:0], event_lon[:0], event_parent_group[:0], int(valid_flash_ids.size)

    order = np.argsort(valid_group_id)
    sorted_group_id = valid_group_id[order]
    sorted_group_flash = valid_group_flash[order]
    positions = np.searchsorted(sorted_group_id, event_parent_group)
    matches = positions < sorted_group_id.size
    safe_positions = np.minimum(positions, sorted_group_id.size - 1)
    matches &= sorted_group_id[safe_positions] == event_parent_group

    mapped_lat = event_lat[matches]
    mapped_lon = event_lon[matches]
    mapped_flash = sorted_group_flash[safe_positions[matches]]

    if valid_flash_ids.size and mapped_lat.size == 0:
        raise ValueError(
            "Quality-controlled flashes were present, but no events could be linked "
            "through the event/group/flash identifiers."
        )

    finite = np.isfinite(mapped_lat) & np.isfinite(mapped_lon)
    plausible = (
        finite
        & (mapped_lat >= -90.0)
        & (mapped_lat <= 90.0)
        & (mapped_lon >= -180.0)
        & (mapped_lon <= 180.0)
    )
    if mapped_lat.size and not np.any(plausible):
        raise ValueError(
            "Decoded event coordinates are outside geographic latitude/longitude "
            "ranges. Check _Unsigned, scale_factor, and add_offset handling."
        )

    return (
        mapped_lat[plausible],
        mapped_lon[plausible],
        mapped_flash[plausible],
        int(valid_flash_ids.size),
    )


def accumulate_file_fed(path: Path, grid: GridSpec) -> tuple[np.ndarray, tuple[int, int, int, int]]:
    counts = np.zeros((grid.height, grid.width), dtype=np.uint32)
    with xr.open_dataset(
        path,
        engine="netcdf4",
        decode_times=False,
        mask_and_scale=False,
    ) as dataset:
        event_lat, event_lon, event_flash, good_flash_count = map_events_to_flashes(dataset)

    mapped_event_count = int(event_lat.size)
    in_domain = (
        np.isfinite(event_lat)
        & np.isfinite(event_lon)
        & (event_lon >= grid.west)
        & (event_lon < grid.east)
        & (event_lat >= grid.south)
        & (event_lat < grid.north)
    )
    event_lat = event_lat[in_domain]
    event_lon = event_lon[in_domain]
    event_flash = event_flash[in_domain]

    if event_lat.size == 0:
        return counts, (good_flash_count, mapped_event_count, 0, 0)

    columns = np.floor((event_lon - grid.west) / grid.resolution).astype(np.int64)
    rows = np.floor((grid.north - event_lat) / grid.resolution).astype(np.int64)
    valid_cells = (
        (rows >= 0)
        & (rows < grid.height)
        & (columns >= 0)
        & (columns < grid.width)
    )
    rows = rows[valid_cells]
    columns = columns[valid_cells]
    event_flash = event_flash[valid_cells]

    cell_index = rows * grid.width + columns
    unique_flashes, local_flash_index = np.unique(event_flash, return_inverse=True)
    multiplier = max(1, unique_flashes.size)
    combined = cell_index.astype(np.int64) * multiplier + local_flash_index.astype(np.int64)
    unique_pairs = np.unique(combined)
    unique_cells = unique_pairs // multiplier
    flat_counts = np.bincount(unique_cells, minlength=grid.height * grid.width)
    counts = flat_counts.reshape(grid.height, grid.width).astype(np.uint32, copy=False)

    return counts, (
        good_flash_count,
        mapped_event_count,
        int(event_lat.size),
        int(unique_pairs.size),
    )


def legend_for_window(window_minutes: int) -> tuple[list[int], list[str], list[tuple[int, int, int, int]], str]:
    if window_minutes == 5:
        return FIVE_MIN_BINS, FIVE_MIN_LABELS, FIVE_MIN_RGBA, "five-minute"
    return ROLLING_BINS, ROLLING_LABELS, ROLLING_RGBA, "rolling"


def product_text(window_minutes: int) -> tuple[str, str, str]:
    if window_minutes == 5:
        return (
            "five-minute flash extent density",
            "GOES GLM Controlled Mosaic — Latest 5-Minute FED",
            "flashes per 0.02-degree grid cell per five minutes",
        )
    return (
        f"rolling {window_minutes}-minute flash extent accumulation",
        f"GOES GLM Controlled Mosaic — Rolling {window_minutes}-Minute Accumulation",
        f"flash extent contributions per 0.02-degree grid cell per {window_minutes} minutes",
    )


def build_source_ownership(grid: GridSpec) -> tuple[np.ndarray, dict[str, float]]:
    lon, lat = grid.center_coordinates()
    lat_rad = np.deg2rad(lat)
    lon_rad = np.deg2rad(lon)

    scores: dict[str, np.ndarray] = {}
    for satellite, config in SATELLITES.items():
        sub_lon_rad = math.radians(float(config["subsatellite_longitude"]))
        # Cosine of spherical central angle to the sub-satellite point at 0° latitude.
        scores[satellite] = np.cos(lat_rad) * np.cos(lon_rad - sub_lon_rad)

    owner = np.where(
        scores["G18"] > scores["G19"],
        SATELLITES["G18"]["source_code"],
        SATELLITES["G19"]["source_code"],
    ).astype(np.uint8)

    midpoint = (
        float(SATELLITES["G18"]["subsatellite_longitude"])
        + float(SATELLITES["G19"]["subsatellite_longitude"])
    ) / 2.0
    return owner, {
        "g18_subsatellite_longitude": float(SATELLITES["G18"]["subsatellite_longitude"]),
        "g19_subsatellite_longitude": float(SATELLITES["G19"]["subsatellite_longitude"]),
        "nominal_equal_angle_seam_longitude": midpoint,
    }


def build_controlled_mosaic(
    g18: np.ndarray,
    g19: np.ndarray,
    owner: np.ndarray,
) -> np.ndarray:
    if g18.shape != g19.shape or g18.shape != owner.shape:
        raise ValueError("Satellite arrays and source ownership mask must have identical shapes")
    return np.where(owner == 18, g18, g19).astype(np.uint32, copy=False)


def write_native_geotiff(
    array: np.ndarray,
    grid: GridSpec,
    output_path: Path,
    product: str,
    units: str,
    dtype: str = "uint16",
) -> None:
    if dtype == "uint8":
        safe = array.astype(np.uint8, copy=False)
        predictor = 1
    else:
        safe = np.minimum(array, np.iinfo(np.uint16).max).astype(np.uint16)
        predictor = 2
    with rio_open(
        output_path,
        "w",
        driver="GTiff",
        height=grid.height,
        width=grid.width,
        count=1,
        dtype=dtype,
        crs="EPSG:4326",
        transform=grid.transform,
        compress="deflate",
        predictor=predictor,
        tiled=True,
        blockxsize=512,
        blockysize=512,
    ) as destination:
        destination.write(safe, 1)
        destination.update_tags(product=product, units=units)


def web_mercator_geometry(
    grid: GridSpec,
    maximum_dimension: int,
):
    dst_transform, dst_width, dst_height = calculate_default_transform(
        "EPSG:4326",
        "EPSG:3857",
        grid.width,
        grid.height,
        grid.west,
        grid.south,
        grid.east,
        grid.north,
    )
    largest = max(dst_width, dst_height)
    if largest > maximum_dimension:
        scale = largest / maximum_dimension
        dst_width = max(1, int(round(dst_width / scale)))
        dst_height = max(1, int(round(dst_height / scale)))
        left, bottom, right, top = transform_bounds(
            "EPSG:4326",
            "EPSG:3857",
            grid.west,
            grid.south,
            grid.east,
            grid.north,
            densify_pts=21,
        )
        dst_transform = from_origin(
            left,
            top,
            (right - left) / dst_width,
            (top - bottom) / dst_height,
        )
    return dst_transform, dst_width, dst_height


def reproject_nearest(
    array: np.ndarray,
    grid: GridSpec,
    maximum_dimension: int,
    dtype: np.dtype,
) -> tuple[np.ndarray, list[list[float]], list[int], dict[str, float]]:
    dst_transform, dst_width, dst_height = web_mercator_geometry(grid, maximum_dimension)
    destination = np.zeros((dst_height, dst_width), dtype=dtype)
    reproject(
        source=array.astype(dtype, copy=False),
        destination=destination,
        src_transform=grid.transform,
        src_crs="EPSG:4326",
        dst_transform=dst_transform,
        dst_crs="EPSG:3857",
        resampling=Resampling.nearest,
    )
    mercator_bounds = array_bounds(dst_height, dst_width, dst_transform)
    west, south, east, north = transform_bounds(
        "EPSG:3857", "EPSG:4326", *mercator_bounds, densify_pts=21
    )
    leaflet_bounds = [[south, west], [north, east]]
    transform_values = {
        "a": float(dst_transform.a),
        "b": float(dst_transform.b),
        "c": float(dst_transform.c),
        "d": float(dst_transform.d),
        "e": float(dst_transform.e),
        "f": float(dst_transform.f),
    }
    return destination, leaflet_bounds, [dst_height, dst_width], transform_values


def render_lightning_png(
    array: np.ndarray,
    grid: GridSpec,
    output_path: Path,
    maximum_dimension: int,
    bins: Sequence[int],
    rgba_values: Sequence[tuple[int, int, int, int]],
) -> tuple[list[list[float]], list[int], dict[str, float]]:
    destination, leaflet_bounds, shape, transform_values = reproject_nearest(
        np.minimum(array, np.iinfo(np.uint16).max),
        grid,
        maximum_dimension,
        np.uint16,
    )
    rgba = np.zeros((shape[0], shape[1], 4), dtype=np.uint8)
    for index, lower in enumerate(bins):
        upper = bins[index + 1] if index + 1 < len(bins) else None
        mask = destination >= lower
        if upper is not None:
            mask &= destination < upper
        rgba[mask] = rgba_values[index]
    Image.fromarray(rgba, mode="RGBA").save(output_path, optimize=True)
    return leaflet_bounds, shape, transform_values


def render_source_mask_png(
    owner: np.ndarray,
    grid: GridSpec,
    output_path: Path,
    maximum_dimension: int,
) -> tuple[list[list[float]], list[int], dict[str, float]]:
    destination, leaflet_bounds, shape, transform_values = reproject_nearest(
        owner,
        grid,
        maximum_dimension,
        np.uint8,
    )
    rgba = np.zeros((shape[0], shape[1], 4), dtype=np.uint8)
    for code, color in SOURCE_RGBA.items():
        rgba[destination == code] = color
    Image.fromarray(rgba, mode="RGBA").save(output_path, optimize=True)
    return leaflet_bounds, shape, transform_values


def nonzero_percentiles(array: np.ndarray) -> dict[str, float]:
    values = array[array > 0]
    names = ("p50", "p75", "p90", "p95", "p99", "p99_5", "p99_9")
    if values.size == 0:
        return {name: 0.0 for name in names}
    requested = [50, 75, 90, 95, 99, 99.5, 99.9]
    computed = np.percentile(values.astype(np.float64), requested)
    return {name: float(value) for name, value in zip(names, computed)}


def bin_counts(array: np.ndarray, bins: Sequence[int], labels: Sequence[str]) -> dict[str, int]:
    result: dict[str, int] = {}
    for index, lower in enumerate(bins):
        upper = bins[index + 1] if index + 1 < len(bins) else None
        mask = array >= lower
        if upper is not None:
            mask &= array < upper
        result[labels[index]] = int(np.count_nonzero(mask))
    return result


def seam_statistics(
    g18: np.ndarray,
    g19: np.ndarray,
    owner: np.ndarray,
    grid: GridSpec,
    seam_longitude: float,
    half_width_degrees: float,
) -> dict[str, float | int]:
    lon_centers = grid.west + (np.arange(grid.width, dtype=np.float64) + 0.5) * grid.resolution
    seam_columns = np.abs(lon_centers - seam_longitude) <= half_width_degrees
    band = np.broadcast_to(seam_columns, g18.shape)

    west_positive = (g18 > 0) & band
    east_positive = (g19 > 0) & band
    both = west_positive & east_positive
    g18_only = west_positive & ~east_positive
    g19_only = east_positive & ~west_positive
    both_zero = band & ~west_positive & ~east_positive

    primary = np.where(owner == 18, g18, g19)
    secondary = np.where(owner == 18, g19, g18)
    primary_zero_secondary_positive = band & (primary == 0) & (secondary > 0)

    if np.any(both):
        g18_both = g18[both].astype(np.float64)
        g19_both = g19[both].astype(np.float64)
        absolute_difference = np.abs(g18_both - g19_both)
        ratio = np.maximum(g18_both, g19_both) / np.minimum(g18_both, g19_both)
        median_abs_difference = float(np.median(absolute_difference))
        p90_abs_difference = float(np.percentile(absolute_difference, 90))
        within_factor_two_fraction = float(np.mean(ratio <= 2.0))
        correlation = (
            float(np.corrcoef(g18_both, g19_both)[0, 1])
            if g18_both.size >= 2 and np.std(g18_both) > 0 and np.std(g19_both) > 0
            else 0.0
        )
    else:
        median_abs_difference = 0.0
        p90_abs_difference = 0.0
        within_factor_two_fraction = 0.0
        correlation = 0.0

    return {
        "seam_band_half_width_degrees": float(half_width_degrees),
        "seam_band_grid_cells": int(np.count_nonzero(band)),
        "both_satellites_nonzero_cells": int(np.count_nonzero(both)),
        "g18_only_nonzero_cells": int(np.count_nonzero(g18_only)),
        "g19_only_nonzero_cells": int(np.count_nonzero(g19_only)),
        "both_satellites_zero_cells": int(np.count_nonzero(both_zero)),
        "primary_zero_secondary_nonzero_cells": int(np.count_nonzero(primary_zero_secondary_positive)),
        "median_absolute_difference_when_both_nonzero": median_abs_difference,
        "p90_absolute_difference_when_both_nonzero": p90_abs_difference,
        "within_factor_two_fraction_when_both_nonzero": within_factor_two_fraction,
        "pearson_correlation_when_both_nonzero": correlation,
    }


def png_data_uri(path: Path) -> str:
    return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def compact_json(value) -> str:
    return json.dumps(value, separators=(",", ":"))


def legend_payload(
    bins: Sequence[int],
    labels: Sequence[str],
    colors: Sequence[tuple[int, int, int, int]],
    title: str,
) -> dict:
    return {
        "title": title,
        "bins": list(bins),
        "labels": list(labels),
        "rgba": [list(color) for color in colors],
    }


def process_satellite(
    client,
    satellite: str,
    keys: Sequence[str],
    end_time: datetime,
    working_dir: Path,
    grid: GridSpec,
    workers: int,
    minimum_completeness: float,
) -> SatelliteAggregate:
    config = SATELLITES[satellite]
    satellite_dir = working_dir / satellite.lower()
    downloaded = download_keys(client, config["bucket"], keys, satellite_dir, workers)
    if not downloaded:
        raise RuntimeError(f"No {satellite} LCFA files downloaded")

    aggregates = {
        window: np.zeros((grid.height, grid.width), dtype=np.uint32)
        for window in WINDOWS_MINUTES
    }
    file_stats: list[FileStats] = []

    for index, path in enumerate(downloaded, start=1):
        file_start = key_start_time(path.name)
        if file_start is None:
            print(f"WARNING: [{satellite}] cannot parse time from {path.name}", file=sys.stderr)
            continue
        print(f"[{satellite}] Processing {index}/{len(downloaded)}: {path.name}")
        try:
            contribution, stats_tuple = accumulate_file_fed(path, grid)
        except Exception as error:
            print(f"WARNING: [{satellite}] skipping unreadable file {path.name}: {error}", file=sys.stderr)
            continue

        included = {
            window: end_time - timedelta(minutes=window) <= file_start < end_time
            for window in WINDOWS_MINUTES
        }
        for window, is_included in included.items():
            if is_included:
                aggregates[window] += contribution

        good_flashes, mapped_events, domain_events, contributions = stats_tuple
        file_stats.append(
            FileStats(
                file_name=path.name,
                file_start_utc=iso_z(file_start),
                flashes_quality_controlled=good_flashes,
                events_mapped_to_good_flashes=mapped_events,
                events_in_domain=domain_events,
                flash_cell_contributions=contributions,
                included_5min=included[5],
                included_30min=included[30],
                included_60min=included[60],
            )
        )

    if not file_stats:
        raise RuntimeError(f"No usable {satellite} LCFA files were processed")

    inclusion_field = {5: "included_5min", 30: "included_30min", 60: "included_60min"}
    stats_by_window: dict[int, SatelliteWindowStats] = {}
    for window in WINDOWS_MINUTES:
        start_time = end_time - timedelta(minutes=window)
        included_stats = [stats for stats in file_stats if getattr(stats, inclusion_field[window])]
        expected = expected_files(window)
        processed_files = len(included_stats)
        completeness = processed_files / expected
        if completeness < minimum_completeness:
            raise RuntimeError(
                f"{satellite} {window}-minute processed completeness "
                f"{processed_files}/{expected} ({completeness:.1%}) is below "
                f"the required {minimum_completeness:.1%}."
            )
        aggregate = aggregates[window]
        stats_by_window[window] = SatelliteWindowStats(
            satellite=satellite,
            satellite_label=config["label"],
            window_minutes=window,
            window_start_utc=iso_z(start_time),
            window_end_utc=iso_z(end_time),
            expected_files=expected,
            listed_files=count_keys_in_window(keys, start_time, end_time),
            processed_files=processed_files,
            completeness_fraction=completeness,
            quality_controlled_flash_records=sum(stats.flashes_quality_controlled for stats in included_stats),
            events_mapped_to_good_flashes=sum(stats.events_mapped_to_good_flashes for stats in included_stats),
            events_in_domain=sum(stats.events_in_domain for stats in included_stats),
            flash_cell_contributions=sum(stats.flash_cell_contributions for stats in included_stats),
            nonzero_grid_cells=int(np.count_nonzero(aggregate)),
            maximum_value=int(aggregate.max(initial=0)),
        )

    return SatelliteAggregate(satellite=satellite, arrays=aggregates, stats=stats_by_window)


def write_interactive_html(
    output_path: Path,
    mosaic_results: Sequence[MosaicResult],
    reference_pngs: dict[str, Path],
    source_mask_png: Path,
    source_mask_bounds: list[list[float]],
    satellite_stats: dict[str, dict[int, SatelliteWindowStats]],
    geometry: dict[str, float],
    generated_time: str,
    seam_band_degrees: float,
) -> None:
    legends = {
        "five-minute": legend_payload(
            FIVE_MIN_BINS,
            FIVE_MIN_LABELS,
            FIVE_MIN_RGBA,
            "Flashes per 0.02° grid cell / 5 minutes",
        ),
        "rolling": legend_payload(
            ROLLING_BINS,
            ROLLING_LABELS,
            ROLLING_RGBA,
            "Flash extent contributions per 0.02° grid cell",
        ),
    }

    layers = []
    for result in mosaic_results:
        layers.append(
            {
                "id": f"mosaic-{result.window_minutes}",
                "family": "Mosaic",
                "windowMinutes": result.window_minutes,
                "name": result.display_label,
                "dataUri": png_data_uri(output_path.parent / result.leaflet_png),
                "bounds": result.leaflet_bounds,
                "legendId": result.legend_id,
                "metadata": asdict(result),
            }
        )

    for satellite in ("G19", "G18"):
        for window in WINDOWS_MINUTES:
            stats = satellite_stats[satellite][window]
            product_kind, _, _ = product_text(window)
            label = "Latest 5-Minute FED" if window == 5 else f"Rolling {window}-Minute Accumulation"
            reference_id = f"{satellite.lower()}-{window}"
            layers.append(
                {
                    "id": reference_id,
                    "family": stats.satellite_label,
                    "windowMinutes": window,
                    "name": f"{stats.satellite_label} — {label}",
                    "dataUri": png_data_uri(reference_pngs[reference_id]),
                    "bounds": mosaic_results[0].leaflet_bounds,
                    "legendId": "five-minute" if window == 5 else "rolling",
                    "metadata": {
                        **asdict(stats),
                        "product_kind": product_kind,
                        "display_label": f"{stats.satellite_label} — {label}",
                    },
                }
            )

    seam_lon = geometry["nominal_equal_angle_seam_longitude"]
    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>GOES GLM Controlled Mosaic Diagnostic</title>
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
  <style>
    html, body, #map {{ height: 100%; margin: 0; }}
    body {{ font-family: Arial, Helvetica, sans-serif; background: #111; }}
    .leaflet-control {{ font-family: Arial, Helvetica, sans-serif; }}
    .panel {{ background: rgba(21,26,33,.95); color: #f4f7fa; padding: 10px 12px; border: 1px solid rgba(255,255,255,.16); border-radius: 7px; box-shadow: 0 2px 10px rgba(0,0,0,.48); line-height: 1.35; }}
    .title {{ max-width: 480px; }}
    .title h2 {{ margin: 0 0 4px; font-size: 17px; }}
    .title p {{ margin: 3px 0; font-size: 11px; color: #d5dbe3; }}
    .selector {{ width: 370px; max-height: 57vh; overflow-y: auto; }}
    .selector h3 {{ margin: 0 0 7px; font-size: 14px; }}
    .family {{ margin: 9px 0 4px; font-size: 12px; font-weight: 700; color: #9fc6ff; }}
    .choice {{ display: block; margin: 4px 0; cursor: pointer; font-size: 12px; }}
    .choice input {{ margin-right: 6px; }}
    .controls {{ border-top: 1px solid rgba(255,255,255,.16); margin-top: 9px; padding-top: 8px; font-size: 11px; }}
    .controls button {{ margin: 3px 4px 2px 0; padding: 5px 8px; cursor: pointer; }}
    .controls input[type=range] {{ width: 180px; vertical-align: middle; }}
    .metadata {{ width: 440px; max-width: calc(100vw - 40px); }}
    .metadata h3 {{ margin: 0 0 5px; font-size: 14px; }}
    .metadata table {{ width: 100%; border-collapse: collapse; font-size: 11px; }}
    .metadata td {{ padding: 3px 4px; border-top: 1px solid rgba(255,255,255,.12); vertical-align: top; }}
    .metadata td:first-child {{ color: #a9c9ff; width: 126px; white-space: nowrap; }}
    .warning {{ color: #ffd166; font-weight: 700; font-size: 11px; margin-top: 7px; }}
    .legend {{ max-width: 740px; }}
    .legend-title {{ font-size: 11px; font-weight: 700; margin-bottom: 5px; }}
    .legend-row {{ display: flex; flex-wrap: nowrap; border: 1px solid #333; }}
    .legend-bin {{ min-width: 48px; padding: 4px 5px; text-align: center; color: #111; font-size: 10px; font-weight: 700; }}
    .source-key {{ display:flex; gap:10px; margin-top:6px; }}
    .source-swatch {{ display:inline-block; width:16px; height:11px; margin-right:4px; vertical-align:-1px; }}
    @media (max-width: 760px) {{ .title {{ max-width:72vw; }} .selector {{ width:72vw; max-height:42vh; }} .metadata {{ width:78vw; }} .legend {{ max-width:78vw; overflow-x:auto; }} }}
  </style>
</head>
<body>
<div id="map"></div>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
const layers = {compact_json(layers)};
const legends = {compact_json(legends)};
const sourceMaskUri = {json.dumps(png_data_uri(source_mask_png))};
const sourceMaskBounds = {compact_json(source_mask_bounds)};
const seamLongitude = {seam_lon:.6f};
const seamBand = {float(seam_band_degrees):.3f};

const map = L.map('map', {{ center:[38.5,-97], zoom:4, preferCanvas:true }});
map.createPane('glmRaster'); map.getPane('glmRaster').style.zIndex = 350;
map.createPane('sourceMask'); map.getPane('sourceMask').style.zIndex = 360; map.getPane('sourceMask').style.pointerEvents = 'none';
map.createPane('seam'); map.getPane('seam').style.zIndex = 425; map.getPane('seam').style.pointerEvents = 'none';
map.createPane('stateLines'); map.getPane('stateLines').style.zIndex = 430; map.getPane('stateLines').style.pointerEvents = 'none';

const dark = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{{z}}/{{y}}/{{x}}', {{ maxZoom:16, attribution:'Tiles © Esri' }}).addTo(map);
const darkLabels = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Reference/MapServer/tile/{{z}}/{{y}}/{{x}}', {{ maxZoom:16, pane:'overlayPane' }}).addTo(map);
const light = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{{z}}/{{y}}/{{x}}', {{ maxZoom:16, attribution:'Tiles © Esri' }});
const lightLabels = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Reference/MapServer/tile/{{z}}/{{y}}/{{x}}', {{ maxZoom:16, pane:'overlayPane' }});
const topo = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{{z}}/{{y}}/{{x}}', {{ maxZoom:19, attribution:'Tiles © Esri' }});
const imagery = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{{z}}/{{y}}/{{x}}', {{ maxZoom:19, attribution:'Tiles © Esri' }});
const osm = L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{ maxZoom:19, attribution:'© OpenStreetMap contributors' }});
L.control.layers({{'Esri Dark Gray':dark,'Esri Light Gray':light,'Esri Topographic':topo,'Esri Imagery':imagery,'OpenStreetMap':osm}}, null, {{collapsed:false}}).addTo(map);
map.on('baselayerchange', e => {{ [darkLabels,lightLabels].forEach(l=>{{if(map.hasLayer(l))map.removeLayer(l);}}); if(e.name==='Esri Dark Gray')darkLabels.addTo(map); if(e.name==='Esri Light Gray')lightLabels.addTo(map); }});

const rasterLayers = new Map();
layers.forEach(item => rasterLayers.set(item.id, L.imageOverlay(item.dataUri, item.bounds, {{opacity:.9, interactive:false, pane:'glmRaster'}})));
const sourceMask = L.imageOverlay(sourceMaskUri, sourceMaskBounds, {{opacity:.72, interactive:false, pane:'sourceMask'}});
const seamLine = L.polyline([[{SOUTH},seamLongitude],[{NORTH},seamLongitude]], {{pane:'seam', color:'#ffffff', weight:2, opacity:.95, dashArray:'7 5'}}).addTo(map);
const seamWest = L.polyline([[{SOUTH},seamLongitude-seamBand],[{NORTH},seamLongitude-seamBand]], {{pane:'seam', color:'#bbbbbb', weight:1, opacity:.55, dashArray:'3 6'}});
const seamEast = L.polyline([[{SOUTH},seamLongitude+seamBand],[{NORTH},seamLongitude+seamBand]], {{pane:'seam', color:'#bbbbbb', weight:1, opacity:.55, dashArray:'3 6'}});

let currentId = 'mosaic-5';
let currentOpacity = .90;
function selectedItem() {{ return layers.find(item => item.id === currentId); }}
function selectLayer(id) {{
  rasterLayers.forEach(layer => {{ if(map.hasLayer(layer)) map.removeLayer(layer); }});
  currentId = id;
  rasterLayers.get(id).setOpacity(currentOpacity).addTo(map);
  document.querySelectorAll('input[name=glm-layer]').forEach(input => input.checked = input.value === id);
  updateMetadata(); updateLegend();
}}

const titleControl = L.control({{position:'topleft'}});
titleControl.onAdd = () => {{ const d=L.DomUtil.create('div','panel title'); d.innerHTML='<h2>GOES GLM Controlled CONUS Mosaic</h2><p>Exclusive lower-view-angle source ownership. No summation, averaging, blending, or secondary-source gap filling.</p><p>Nominal seam: '+seamLongitude.toFixed(1)+'°W; comparison band: ±'+seamBand.toFixed(1)+'°.</p>'; return d; }};
titleControl.addTo(map);

const selectorControl = L.control({{position:'topleft'}});
selectorControl.onAdd = () => {{
  const d=L.DomUtil.create('div','panel selector'); L.DomEvent.disableClickPropagation(d); L.DomEvent.disableScrollPropagation(d);
  let content='<h3>Lightning layer</h3>';
  [...new Set(layers.map(item=>item.family))].forEach(family => {{
    content += `<div class="family">${{family}}</div>`;
    layers.filter(item=>item.family===family).forEach(item => {{ content += `<label class="choice"><input type="radio" name="glm-layer" value="${{item.id}}">${{item.name}}</label>`; }});
  }});
  content += `<div class="controls"><label><input id="sourceToggle" type="checkbox"> Show source ownership</label><br><label><input id="bandToggle" type="checkbox"> Show ±${{seamBand.toFixed(1)}}° seam band</label><br><label>Opacity <input id="opacity" type="range" min="0.25" max="1" step="0.05" value="0.90"> <span id="opacityValue">90%</span></label><br><button id="fitButton">Fit domain</button><button id="hideButton">Hide lightning</button><div class="source-key"><span><i class="source-swatch" style="background:rgba(0,153,255,.55)"></i>GOES-18</span><span><i class="source-swatch" style="background:rgba(255,196,0,.55)"></i>GOES-19</span></div></div>`;
  d.innerHTML=content;
  setTimeout(()=>{{
    d.querySelectorAll('input[name=glm-layer]').forEach(input=>input.addEventListener('change',()=>selectLayer(input.value)));
    d.querySelector('#sourceToggle').addEventListener('change',e=>{{if(e.target.checked)sourceMask.addTo(map);else map.removeLayer(sourceMask);}});
    d.querySelector('#bandToggle').addEventListener('change',e=>{{if(e.target.checked){{seamWest.addTo(map);seamEast.addTo(map);}}else{{map.removeLayer(seamWest);map.removeLayer(seamEast);}}}});
    d.querySelector('#opacity').addEventListener('input',e=>{{currentOpacity=Number(e.target.value);rasterLayers.forEach(layer=>layer.setOpacity(currentOpacity));d.querySelector('#opacityValue').textContent=Math.round(currentOpacity*100)+'%';}});
    d.querySelector('#fitButton').addEventListener('click',()=>map.fitBounds(layers[0].bounds));
    d.querySelector('#hideButton').addEventListener('click',()=>rasterLayers.forEach(layer=>{{if(map.hasLayer(layer))map.removeLayer(layer);}}));
  }},0);
  return d;
}};
selectorControl.addTo(map);

const metadataControl = L.control({{position:'topright'}});
metadataControl.onAdd = () => {{ const d=L.DomUtil.create('div','panel metadata'); d.id='metadataPanel'; L.DomEvent.disableClickPropagation(d); return d; }};
metadataControl.addTo(map);
function updateMetadata() {{
  const item=selectedItem(); const m=item.metadata; const isMosaic=item.family==='Mosaic';
  const label=m.window_minutes===5?'Maximum FED':'Maximum accumulation';
  let extra='';
  if(isMosaic) extra=`<tr><td>GOES-18 cells</td><td>${{m.source_g18_owned_cells.toLocaleString()}} owned / ${{m.source_g18_nonzero_cells.toLocaleString()}} nonzero</td></tr><tr><td>GOES-19 cells</td><td>${{m.source_g19_owned_cells.toLocaleString()}} owned / ${{m.source_g19_nonzero_cells.toLocaleString()}} nonzero</td></tr>`;
  else extra=`<tr><td>LCFA files</td><td>${{m.processed_files}} / ${{m.expected_files}} processed (${{(m.completeness_fraction*100).toFixed(0)}}%)</td></tr><tr><td>QC flashes</td><td>${{m.quality_controlled_flash_records.toLocaleString()}}</td></tr>`;
  document.getElementById('metadataPanel').innerHTML=`<h3>${{item.name}}</h3><table><tr><td>Valid window</td><td>${{m.window_start_utc}} through ${{m.window_end_utc}}</td></tr>${{extra}}<tr><td>Nonzero cells</td><td>${{m.nonzero_grid_cells.toLocaleString()}}</td></tr><tr><td>${{label}}</td><td>${{(m.maximum_value??0).toLocaleString()}}</td></tr></table><div class="warning">The mosaic copies one satellite value per grid cell. It never adds East and West detections.</div><div style="font-size:10px;color:#cfd5dd;margin-top:5px">Generated: {generated_time}</div>`;
}}

const legendControl=L.control({{position:'bottomright'}});
legendControl.onAdd=()=>{{const d=L.DomUtil.create('div','panel legend');d.id='legendPanel';return d;}};
legendControl.addTo(map);
function updateLegend() {{ const item=selectedItem(); const legend=legends[item.legendId]; const blocks=legend.labels.map((label,i)=>{{const c=legend.rgba[i];return `<span class="legend-bin" style="background:rgba(${{c[0]}},${{c[1]}},${{c[2]}},${{c[3]/255}})">${{label}}</span>`;}}).join(''); document.getElementById('legendPanel').innerHTML=`<div class="legend-title">${{legend.title}}</div><div class="legend-row">${{blocks}}</div>`; }}

fetch('https://raw.githubusercontent.com/PublicaMundi/MappingAPI/master/data/geojson/us-states.json').then(r=>r.json()).then(data=>L.geoJSON(data,{{pane:'stateLines',style:{{color:'#fff',weight:1,opacity:.72,fillOpacity:0}},interactive:false}}).addTo(map)).catch(error=>console.warn('State boundary overlay unavailable:',error));
selectLayer(currentId); map.fitBounds(layers[0].bounds);
</script>
</body>
</html>
"""
    output_path.write_text(html, encoding="utf-8")


def self_test() -> None:
    grid = GridSpec(west=-120.0, east=-90.0, south=30.0, north=40.0, resolution=1.0)
    owner, geometry = build_source_ownership(grid)
    seam = geometry["nominal_equal_angle_seam_longitude"]
    assert abs(seam - (-106.1)) < 0.01
    lon, _ = grid.center_coordinates()
    assert np.all(owner[lon < seam] == 18)
    assert np.all(owner[lon > seam] == 19)

    g18 = np.arange(grid.height * grid.width, dtype=np.uint32).reshape(grid.height, grid.width)
    g19 = g18 + 1000
    mosaic = build_controlled_mosaic(g18, g19, owner)
    assert np.all(mosaic[owner == 18] == g18[owner == 18])
    assert np.all(mosaic[owner == 19] == g19[owner == 19])

    simple_owner = np.array([[18, 18, 19, 19]], dtype=np.uint8)
    simple_g18 = np.array([[1, 0, 8, 9]], dtype=np.uint32)
    simple_g19 = np.array([[5, 6, 7, 0]], dtype=np.uint32)
    simple = build_controlled_mosaic(simple_g18, simple_g19, simple_owner)
    assert np.array_equal(simple, np.array([[1, 0, 7, 0]], dtype=np.uint32))

    five = np.array([[0, 1, 2, 4, 8, 16, 32, 64, 128]], dtype=np.uint16)
    counts = bin_counts(five, FIVE_MIN_BINS, FIVE_MIN_LABELS)
    assert counts["1"] == 1 and counts["≥128"] == 1
    assert expected_files(5) == 15 and expected_files(30) == 90 and expected_files(60) == 180
    print("GLM controlled-mosaic ownership, no-sum, and legend self-test passed.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--analysis-time",
        default="",
        help=(
            "UTC ending time shared by the 5-, 30-, and 60-minute windows, "
            "e.g. 2026-07-21T21:00:00Z. Blank selects the newest common end time."
        ),
    )
    parser.add_argument("--lookback-minutes", type=int, default=180)
    parser.add_argument("--minimum-completeness", type=float, default=0.80)
    parser.add_argument("--resolution-degrees", type=float, default=DEFAULT_RESOLUTION_DEGREES)
    parser.add_argument("--download-workers", type=int, default=10)
    parser.add_argument("--maximum-render-dimension", type=int, default=6000)
    parser.add_argument("--seam-band-degrees", type=float, default=DEFAULT_SEAM_BAND_DEGREES)
    parser.add_argument("--output-dir", default="glm_mosaic_diagnostic_output")
    parser.add_argument("--keep-downloads", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.self_test:
        self_test()
        return 0
    if not (0 < args.minimum_completeness <= 1):
        raise SystemExit("--minimum-completeness must be within (0, 1]")
    if args.lookback_minutes < 0:
        raise SystemExit("--lookback-minutes must be nonnegative")
    if args.resolution_degrees <= 0:
        raise SystemExit("--resolution-degrees must be positive")
    if args.seam_band_degrees <= 0:
        raise SystemExit("--seam-band-degrees must be positive")

    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    grid = GridSpec(resolution=args.resolution_degrees)
    print(f"Mosaic diagnostic grid: {grid.height} rows × {grid.width} columns")

    client = build_s3_client()
    end_time, keys_by_satellite = resolve_common_end_time(
        client,
        args.analysis_time,
        args.lookback_minutes,
        args.minimum_completeness,
    )

    temporary_root = Path(tempfile.mkdtemp(prefix="glm_mosaic_diagnostic_"))
    try:
        aggregates: dict[str, SatelliteAggregate] = {}
        for satellite in ("G19", "G18"):
            aggregates[satellite] = process_satellite(
                client=client,
                satellite=satellite,
                keys=keys_by_satellite[satellite],
                end_time=end_time,
                working_dir=temporary_root,
                grid=grid,
                workers=args.download_workers,
                minimum_completeness=args.minimum_completeness,
            )

        owner, geometry = build_source_ownership(grid)
        seam_longitude = geometry["nominal_equal_angle_seam_longitude"]
        print(
            "Controlled mosaic ownership: "
            f"GOES-18 west of approximately {seam_longitude:.2f}°, "
            "GOES-19 east of the seam; no blending or summation."
        )

        source_tif = output_dir / "glm_mosaic_source_ownership.tif"
        source_png = output_dir / "glm_mosaic_source_ownership.png"
        source_metadata_path = output_dir / "glm_mosaic_source_ownership_metadata.json"
        write_native_geotiff(
            owner,
            grid,
            source_tif,
            "GOES GLM controlled-mosaic source ownership",
            "18=GOES-18 West, 19=GOES-19 East",
            dtype="uint8",
        )
        source_bounds, source_shape, source_transform = render_source_mask_png(
            owner,
            grid,
            source_png,
            args.maximum_render_dimension,
        )
        source_metadata = {
            "product": "GOES GLM controlled-mosaic source ownership mask",
            "methodology": (
                "Each cell is assigned to the satellite with the smaller spherical "
                "central angle to its sub-satellite point. The mask is exclusive."
            ),
            "source_codes": {"18": "GOES-18 (West)", "19": "GOES-19 (East)"},
            "satellite_geometry": geometry,
            "owned_cell_counts": {
                "G18": int(np.count_nonzero(owner == 18)),
                "G19": int(np.count_nonzero(owner == 19)),
            },
            "grid": {
                **asdict(grid),
                "shape": [grid.height, grid.width],
                "crs": "EPSG:4326",
                "image_crs": "EPSG:3857",
                "leaflet_bounds": source_bounds,
                "rendered_shape": source_shape,
                "rendered_transform": source_transform,
            },
            "generated_time_utc": iso_z(utc_now()),
        }
        source_metadata_path.write_text(json.dumps(source_metadata, indent=2), encoding="utf-8")

        mosaic_results: list[MosaicResult] = []
        summary_rows: list[dict] = []
        reference_pngs: dict[str, Path] = {}
        reference_dir = temporary_root / "reference_pngs"
        reference_dir.mkdir(parents=True, exist_ok=True)

        for satellite in ("G19", "G18"):
            for window in WINDOWS_MINUTES:
                bins, _, colors, _ = legend_for_window(window)
                reference_path = reference_dir / f"{satellite.lower()}_{window}min.png"
                render_lightning_png(
                    aggregates[satellite].arrays[window],
                    grid,
                    reference_path,
                    args.maximum_render_dimension,
                    bins,
                    colors,
                )
                reference_pngs[f"{satellite.lower()}-{window}"] = reference_path

        for window in WINDOWS_MINUTES:
            g18 = aggregates["G18"].arrays[window]
            g19 = aggregates["G19"].arrays[window]
            mosaic = build_controlled_mosaic(g18, g19, owner)
            bins, labels, colors, legend_id = legend_for_window(window)
            product_kind, display_label, units = product_text(window)
            start_time = end_time - timedelta(minutes=window)
            stem = f"glm_conus_mosaic_{window}min"
            geotiff_path = output_dir / f"{stem}.tif"
            png_path = output_dir / f"{stem}.png"
            metadata_path = output_dir / f"{stem}_metadata.json"

            write_native_geotiff(
                mosaic,
                grid,
                geotiff_path,
                f"LCFA-derived GOES GLM controlled mosaic {product_kind}",
                units,
            )
            leaflet_bounds, rendered_shape, rendered_transform = render_lightning_png(
                mosaic,
                grid,
                png_path,
                args.maximum_render_dimension,
                bins,
                colors,
            )

            source_g18_owned = int(np.count_nonzero(owner == 18))
            source_g19_owned = int(np.count_nonzero(owner == 19))
            source_g18_nonzero = int(np.count_nonzero((owner == 18) & (mosaic > 0)))
            source_g19_nonzero = int(np.count_nonzero((owner == 19) & (mosaic > 0)))
            result = MosaicResult(
                window_minutes=window,
                product_kind=product_kind,
                display_label=display_label,
                window_start_utc=iso_z(start_time),
                window_end_utc=iso_z(end_time),
                maximum_value=int(mosaic.max(initial=0)),
                nonzero_grid_cells=int(np.count_nonzero(mosaic)),
                flash_cell_contributions=int(mosaic.sum(dtype=np.uint64)),
                source_g18_owned_cells=source_g18_owned,
                source_g19_owned_cells=source_g19_owned,
                source_g18_nonzero_cells=source_g18_nonzero,
                source_g19_nonzero_cells=source_g19_nonzero,
                native_geotiff=geotiff_path.name,
                leaflet_png=png_path.name,
                metadata_json=metadata_path.name,
                image_crs="EPSG:3857",
                leaflet_bounds=leaflet_bounds,
                rendered_shape=rendered_shape,
                legend_id=legend_id,
            )

            seam = seam_statistics(
                g18,
                g19,
                owner,
                grid,
                seam_longitude,
                args.seam_band_degrees,
            )
            metadata = {
                **asdict(result),
                "product": f"Diagnostic LCFA-derived GOES GLM controlled mosaic {product_kind}",
                "source_product": PRODUCT_PREFIX,
                "mosaic_method": {
                    "name": "exclusive lower-view-angle source ownership",
                    "description": (
                        "Each native grid cell is assigned to the satellite whose "
                        "sub-satellite point has the smaller spherical central angle. "
                        "The selected satellite value is copied directly."
                    ),
                    "summation": False,
                    "averaging": False,
                    "blending": False,
                    "secondary_source_gap_fill": False,
                    "satellite_geometry": geometry,
                },
                "satellite_inputs": {
                    "G18": asdict(aggregates["G18"].stats[window]),
                    "G19": asdict(aggregates["G19"].stats[window]),
                },
                "seam_diagnostics": seam,
                "units": units,
                "nonzero_percentiles": nonzero_percentiles(mosaic),
                "render_bin_counts": bin_counts(mosaic, bins, labels),
                "grid": {
                    **asdict(grid),
                    "shape": [grid.height, grid.width],
                    "crs": "EPSG:4326",
                    "image_crs": "EPSG:3857",
                    "leaflet_bounds": leaflet_bounds,
                    "rendered_shape": rendered_shape,
                    "rendered_transform": rendered_transform,
                },
                "rendering": {
                    "resampling": "nearest",
                    "bins": list(bins),
                    "labels": list(labels),
                    "rgba": [list(color) for color in colors],
                },
                "generated_time_utc": iso_z(utc_now()),
            }
            metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
            mosaic_results.append(result)

            summary_rows.append(
                {
                    "window_minutes": window,
                    "window_start_utc": iso_z(start_time),
                    "window_end_utc": iso_z(end_time),
                    "g18_processed_files": aggregates["G18"].stats[window].processed_files,
                    "g18_expected_files": aggregates["G18"].stats[window].expected_files,
                    "g18_maximum": aggregates["G18"].stats[window].maximum_value,
                    "g19_processed_files": aggregates["G19"].stats[window].processed_files,
                    "g19_expected_files": aggregates["G19"].stats[window].expected_files,
                    "g19_maximum": aggregates["G19"].stats[window].maximum_value,
                    "mosaic_maximum": result.maximum_value,
                    "mosaic_nonzero_grid_cells": result.nonzero_grid_cells,
                    "mosaic_flash_cell_contributions": result.flash_cell_contributions,
                    "g18_owned_cells": source_g18_owned,
                    "g19_owned_cells": source_g19_owned,
                    **seam,
                }
            )

        summary_path = output_dir / "glm_mosaic_summary.csv"
        with summary_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(summary_rows[0].keys()))
            writer.writeheader()
            writer.writerows(summary_rows)

        generated_time = iso_z(utc_now())
        html_path = output_dir / "glm_mosaic_diagnostic.html"
        write_interactive_html(
            html_path,
            mosaic_results,
            reference_pngs,
            source_png,
            source_bounds,
            {sat: aggregates[sat].stats for sat in aggregates},
            geometry,
            generated_time,
            args.seam_band_degrees,
        )

        manifest = {
            "product": "GOES GLM controlled CONUS mosaic diagnostic package",
            "window_end_utc": iso_z(end_time),
            "windows_minutes": list(WINDOWS_MINUTES),
            "mosaic_method": {
                "name": "exclusive lower-view-angle source ownership",
                "summation": False,
                "averaging": False,
                "blending": False,
                "secondary_source_gap_fill": False,
                "satellite_geometry": geometry,
            },
            "mosaic_products": [asdict(result) for result in mosaic_results],
            "source_ownership": {
                "native_geotiff": source_tif.name,
                "leaflet_png": source_png.name,
                "metadata_json": source_metadata_path.name,
            },
            "summary_csv": summary_path.name,
            "interactive_html": html_path.name,
            "generated_time_utc": generated_time,
            "publishing_mode": "artifact-only; no repository files modified",
        }
        (output_dir / "glm_mosaic_manifest.json").write_text(
            json.dumps(manifest, indent=2), encoding="utf-8"
        )

        print("\nControlled-mosaic outputs:")
        for path in sorted(output_dir.iterdir()):
            if path.is_file():
                print(f"  {path.name}: {path.stat().st_size:,} bytes")
        return 0
    finally:
        if args.keep_downloads:
            retained = output_dir / "downloaded_lcfa_files"
            if retained.exists():
                shutil.rmtree(retained)
            shutil.move(str(temporary_root), str(retained))
            print(f"Retained downloaded LCFA files under {retained}")
        else:
            shutil.rmtree(temporary_root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
