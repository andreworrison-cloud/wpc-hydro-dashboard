#!/usr/bin/env python3
"""Incremental operational GOES GLM controlled CONUS mosaic generator.

This is the drop-in incremental replacement for the existing Operational
Generator. It preserves the established dashboard-facing filenames and the
``glm_dashboard_v1`` metadata contract while replacing the expensive full-hour
LCFA rebuild with persistent sparse five-minute cache slots.

GOES-18 and GOES-19 are first calculated independently. The published CONUS
mosaic then uses the previously validated exclusive lower-view-angle ownership
mask: every grid cell has exactly one satellite source, with no summation,
averaging, blending, secondary-source gap filling, or cross-satellite flash
deduplication.

The script also writes artifact-only diagnostic layers and a self-contained
viewer using the same IEM NEXRAD WMS and ten-minute radar cadence used by the
WPC Hydrometeorological Dashboard. The GitHub workflow validates the full
staging package before copying only the established publication files to
``static/``.
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
SLOT_MINUTES = 5
CACHE_SLOT_COUNT = 12
DEFAULT_SEAM_BAND_DEGREES = 5.0
WINDOWS_MINUTES = (5, 30, 60)
LCFA_FILES_PER_MINUTE = 3
EXPECTED_FILES_PER_SLOT = SLOT_MINUTES * LCFA_FILES_PER_MINUTE
FILENAME_TIME_RE = re.compile(r"_s(?P<start>\d{13,16})_e(?P<end>\d{13,16})_")

FIVE_MIN_BINS = [1, 2, 4, 8, 16, 32, 64, 128]
FIVE_MIN_LABELS = ["1", "2–3", "4–7", "8–15", "16–31", "32–63", "64–127", "≥128"]
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
    "1", "2–3", "4–7", "8–15", "16–31", "32–63", "64–127",
    "128–255", "256–511", "≥512",
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

EVENT_DENSITY_BINS = [1, 4, 16, 64, 256, 1024]
EVENT_DENSITY_LABELS = ["1–3", "4–15", "16–63", "64–255", "256–1023", "≥1024"]
EVENT_DENSITY_RGBA = [
    (80, 180, 255, 160),
    (0, 255, 255, 180),
    (0, 255, 0, 195),
    (255, 255, 0, 210),
    (255, 128, 0, 225),
    (255, 0, 0, 240),
]

FOOTPRINT_BINS = [1]
FOOTPRINT_LABELS = ["Nonzero GLM footprint"]
FOOTPRINT_RGBA = [(255, 255, 255, 165)]

SOURCE_BINS = [18, 19]
SOURCE_LABELS = ["GOES-18 West ownership", "GOES-19 East ownership"]
SOURCE_RGBA = [
    (0, 153, 255, 92),
    (255, 196, 0, 92),
]


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
    def size(self) -> int:
        return self.width * self.height

    @property
    def transform(self):
        return from_origin(self.west, self.north, self.resolution, self.resolution)

    def center_coordinates(self) -> tuple[np.ndarray, np.ndarray]:
        lon = self.west + (np.arange(self.width, dtype=np.float64) + 0.5) * self.resolution
        lat = self.north - (np.arange(self.height, dtype=np.float64) + 0.5) * self.resolution
        return np.meshgrid(lon, lat)


@dataclass
class SlotMetadata:
    satellite: str
    satellite_label: str
    bucket: str
    slot_start_utc: str
    slot_end_utc: str
    expected_files: int
    listed_files: int
    processed_files: int
    completeness_fraction: float
    quality_controlled_flash_records: int
    events_mapped_to_good_flashes: int
    events_in_domain: int
    flash_cell_contributions: int
    nonzero_fed_cells: int
    maximum_fed: int
    nonzero_event_density_cells: int
    maximum_event_density: int
    event_sample_count: int
    flash_centroid_sample_count: int
    cache_npz: str
    generated_time_utc: str


@dataclass
class ProductResult:
    satellite: str
    satellite_label: str
    bucket: str
    window_minutes: int
    display_label: str
    product_kind: str
    units: str
    window_start_utc: str
    window_end_utc: str
    expected_slots: int
    available_slots: int
    slot_completeness_fraction: float
    expected_files: int
    processed_files: int
    file_completeness_fraction: float
    quality_controlled_flash_records: int
    events_mapped_to_good_flashes: int
    events_in_domain: int
    flash_cell_contributions: int
    nonzero_grid_cells: int
    maximum_value: int
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
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def floor_to_five_minutes(value: datetime) -> datetime:
    value = value.astimezone(UTC).replace(second=0, microsecond=0)
    return value.replace(minute=(value.minute // SLOT_MINUTES) * SLOT_MINUTES)


def floor_to_ten_minutes(value: datetime) -> datetime:
    value = value.astimezone(UTC).replace(second=0, microsecond=0)
    return value.replace(minute=(value.minute // 10) * 10)


def slot_token(end_time: datetime) -> str:
    return end_time.strftime("%Y%m%dT%H%MZ")


def parse_slot_token(token: str) -> datetime:
    return datetime.strptime(token, "%Y%m%dT%H%MZ").replace(tzinfo=UTC)


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
            connect_timeout=20,
            read_timeout=120,
        ),
    )


def hour_starts(window_start: datetime, window_end: datetime) -> Iterable[datetime]:
    cursor = window_start.replace(minute=0, second=0, microsecond=0)
    final = (window_end - timedelta(microseconds=1)).replace(minute=0, second=0, microsecond=0)
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


def list_window_keys(client, bucket: str, window_start: datetime, window_end: datetime) -> list[str]:
    candidates: list[str] = []
    for hour in hour_starts(window_start, window_end):
        prefix = f"{PRODUCT_PREFIX}/{hour.year}/{hour.timetuple().tm_yday:03d}/{hour.hour:02d}/"
        candidates.extend(list_prefix_keys(client, bucket, prefix))

    selected: list[tuple[datetime, str]] = []
    for key in candidates:
        start = key_start_time(key)
        if start is not None and window_start <= start < window_end:
            selected.append((start, key))
    selected.sort(key=lambda item: item[0])
    return [key for _, key in selected]


def resolve_target_end_time(
    client,
    requested_end: str,
    lookback_minutes: int,
    minimum_slot_completeness: float,
) -> tuple[datetime, dict[str, list[str]]]:
    minimum_files = math.ceil(EXPECTED_FILES_PER_SLOT * minimum_slot_completeness)
    if requested_end.strip():
        candidates = [floor_to_five_minutes(parse_utc(requested_end))]
    else:
        # The dashboard radar loop advances on 10-minute frames. Prefer GLM
        # windows ending on those same boundaries, while the cache still fills
        # both constituent five-minute slots needed by the rolling products.
        newest = floor_to_ten_minutes(utc_now())
        candidates = [
            newest - timedelta(minutes=offset)
            for offset in range(0, lookback_minutes + 1, 10)
        ]

    attempts: list[str] = []
    for end_time in candidates:
        start_time = end_time - timedelta(minutes=SLOT_MINUTES)
        keys_by_satellite: dict[str, list[str]] = {}
        detail: list[str] = []
        valid = True
        for satellite, config in SATELLITES.items():
            keys = list_window_keys(client, config["bucket"], start_time, end_time)
            keys_by_satellite[satellite] = keys
            detail.append(f"{satellite}={len(keys)}/{EXPECTED_FILES_PER_SLOT}")
            if len(keys) < minimum_files:
                valid = False
        attempts.append(f"{iso_z(end_time)} ({', '.join(detail)})")
        if valid:
            print(f"Resolved synchronized GLM slot: {attempts[-1]}")
            return end_time, keys_by_satellite
        if requested_end.strip():
            break

    raise RuntimeError(
        "No synchronized GOES-19/GOES-18 five-minute slot met the minimum "
        f"completeness of {minimum_slot_completeness:.0%}. Recent attempts: "
        + "; ".join(attempts[:12])
    )


def download_keys(client, bucket: str, keys: Sequence[str], destination: Path, workers: int) -> list[Path]:
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
        raise ValueError("Quality-controlled flashes were present but no events linked to them")

    plausible = (
        np.isfinite(mapped_lat)
        & np.isfinite(mapped_lon)
        & (mapped_lat >= -90.0)
        & (mapped_lat <= 90.0)
        & (mapped_lon >= -180.0)
        & (mapped_lon <= 180.0)
    )
    if mapped_lat.size and not np.any(plausible):
        raise ValueError("Decoded event coordinates are outside geographic ranges")

    return mapped_lat[plausible], mapped_lon[plausible], mapped_flash[plausible], int(valid_flash_ids.size)


def deterministic_sample(lat: np.ndarray, lon: np.ndarray, maximum: int) -> tuple[np.ndarray, np.ndarray]:
    if lat.size <= maximum:
        return lat.astype(np.float32, copy=False), lon.astype(np.float32, copy=False)
    indices = np.linspace(0, lat.size - 1, maximum, dtype=np.int64)
    return lat[indices].astype(np.float32), lon[indices].astype(np.float32)


def flash_centroids(lat: np.ndarray, lon: np.ndarray, flash_ids: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    if lat.size == 0:
        return lat.astype(np.float32), lon.astype(np.float32)
    order = np.argsort(flash_ids)
    sorted_ids = flash_ids[order]
    sorted_lat = lat[order]
    sorted_lon = lon[order]
    unique_ids, starts, counts = np.unique(sorted_ids, return_index=True, return_counts=True)
    del unique_ids
    centroid_lat = np.add.reduceat(sorted_lat, starts) / counts
    centroid_lon = np.add.reduceat(sorted_lon, starts) / counts
    return centroid_lat.astype(np.float32), centroid_lon.astype(np.float32)


def add_sparse(flat_array: np.ndarray, indices: np.ndarray, values: np.ndarray) -> None:
    if indices.size:
        np.add.at(flat_array, indices.astype(np.int64, copy=False), values)


def process_lcfa_file(
    path: Path,
    grid: GridSpec,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, tuple[int, int, int, int]]:
    with xr.open_dataset(
        path,
        engine="netcdf4",
        decode_times=False,
        mask_and_scale=False,
    ) as dataset:
        event_lat, event_lon, event_flash, good_flash_count = map_events_to_flashes(dataset)

    mapped_event_count = int(event_lat.size)
    in_domain = (
        (event_lon >= grid.west)
        & (event_lon < grid.east)
        & (event_lat >= grid.south)
        & (event_lat < grid.north)
    )
    event_lat = event_lat[in_domain]
    event_lon = event_lon[in_domain]
    event_flash = event_flash[in_domain]
    if event_lat.size == 0:
        empty_i = np.empty(0, dtype=np.int64)
        empty_v = np.empty(0, dtype=np.uint32)
        return empty_i, empty_v, empty_i, empty_v, (good_flash_count, mapped_event_count, 0, 0)

    columns = np.floor((event_lon - grid.west) / grid.resolution).astype(np.int64)
    rows = np.floor((grid.north - event_lat) / grid.resolution).astype(np.int64)
    valid = (rows >= 0) & (rows < grid.height) & (columns >= 0) & (columns < grid.width)
    event_lat = event_lat[valid]
    event_lon = event_lon[valid]
    event_flash = event_flash[valid]
    cell_index = rows[valid] * grid.width + columns[valid]

    event_cells, event_counts = np.unique(cell_index, return_counts=True)
    unique_flashes, local_flash_index = np.unique(event_flash, return_inverse=True)
    multiplier = max(1, unique_flashes.size)
    combined = cell_index.astype(np.int64) * multiplier + local_flash_index.astype(np.int64)
    unique_pairs = np.unique(combined)
    pair_cells = unique_pairs // multiplier
    fed_cells, fed_counts = np.unique(pair_cells, return_counts=True)

    return (
        fed_cells.astype(np.int64),
        fed_counts.astype(np.uint32),
        event_cells.astype(np.int64),
        event_counts.astype(np.uint32),
        (good_flash_count, mapped_event_count, int(event_lat.size), int(unique_pairs.size)),
    )


def slot_paths(cache_root: Path, satellite: str, end_time: datetime) -> tuple[Path, Path]:
    directory = cache_root / satellite.lower()
    directory.mkdir(parents=True, exist_ok=True)
    token = slot_token(end_time)
    return directory / f"{token}.npz", directory / f"{token}.json"


def slot_exists(cache_root: Path, satellite: str, end_time: datetime) -> bool:
    npz_path, json_path = slot_paths(cache_root, satellite, end_time)
    return npz_path.exists() and json_path.exists()


def build_satellite_slot(
    client,
    satellite: str,
    keys: Sequence[str],
    end_time: datetime,
    cache_root: Path,
    work_root: Path,
    grid: GridSpec,
    workers: int,
    minimum_slot_completeness: float,
    maximum_event_points: int,
    maximum_flash_centroids: int,
) -> tuple[Path, Path, SlotMetadata]:
    config = SATELLITES[satellite]
    start_time = end_time - timedelta(minutes=SLOT_MINUTES)
    download_dir = work_root / satellite.lower() / slot_token(end_time)
    downloaded = download_keys(client, config["bucket"], keys, download_dir, workers)
    minimum_processed = math.ceil(EXPECTED_FILES_PER_SLOT * minimum_slot_completeness)
    if len(downloaded) < minimum_processed:
        raise RuntimeError(
            f"{satellite} downloaded only {len(downloaded)}/{EXPECTED_FILES_PER_SLOT} files "
            f"for {iso_z(start_time)}–{iso_z(end_time)}"
        )

    fed_flat = np.zeros(grid.size, dtype=np.uint32)
    event_flat = np.zeros(grid.size, dtype=np.uint32)
    processed_files = 0
    qc_flashes = 0
    mapped_events = 0
    domain_events = 0
    contributions = 0
    event_lat_parts: list[np.ndarray] = []
    event_lon_parts: list[np.ndarray] = []
    centroid_lat_parts: list[np.ndarray] = []
    centroid_lon_parts: list[np.ndarray] = []

    for index, path in enumerate(downloaded, start=1):
        print(f"[{satellite}] slot {slot_token(end_time)} file {index}/{len(downloaded)}: {path.name}")
        try:
            with xr.open_dataset(path, engine="netcdf4", decode_times=False, mask_and_scale=False) as dataset:
                lat, lon, flash_ids, good_flash_count = map_events_to_flashes(dataset)
            mapped_event_count = int(lat.size)
            in_domain = (
                (lon >= grid.west) & (lon < grid.east)
                & (lat >= grid.south) & (lat < grid.north)
            )
            lat = lat[in_domain]
            lon = lon[in_domain]
            flash_ids = flash_ids[in_domain]

            if lat.size:
                columns = np.floor((lon - grid.west) / grid.resolution).astype(np.int64)
                rows = np.floor((grid.north - lat) / grid.resolution).astype(np.int64)
                valid = (rows >= 0) & (rows < grid.height) & (columns >= 0) & (columns < grid.width)
                lat = lat[valid]
                lon = lon[valid]
                flash_ids = flash_ids[valid]
                cells = rows[valid] * grid.width + columns[valid]

                event_cells, event_counts = np.unique(cells, return_counts=True)
                add_sparse(event_flat, event_cells, event_counts.astype(np.uint32))

                unique_flashes, local = np.unique(flash_ids, return_inverse=True)
                multiplier = max(1, unique_flashes.size)
                unique_pairs = np.unique(cells.astype(np.int64) * multiplier + local.astype(np.int64))
                pair_cells = unique_pairs // multiplier
                fed_cells, fed_counts = np.unique(pair_cells, return_counts=True)
                add_sparse(fed_flat, fed_cells, fed_counts.astype(np.uint32))

                sample_lat, sample_lon = deterministic_sample(lat, lon, max(1, maximum_event_points // max(1, len(downloaded))))
                event_lat_parts.append(sample_lat)
                event_lon_parts.append(sample_lon)
                c_lat, c_lon = flash_centroids(lat, lon, flash_ids)
                c_lat, c_lon = deterministic_sample(c_lat, c_lon, max(1, maximum_flash_centroids // max(1, len(downloaded))))
                centroid_lat_parts.append(c_lat)
                centroid_lon_parts.append(c_lon)
                contributions += int(unique_pairs.size)

            qc_flashes += good_flash_count
            mapped_events += mapped_event_count
            domain_events += int(lat.size)
            processed_files += 1
        except Exception as error:
            print(f"WARNING: [{satellite}] skipping {path.name}: {error}", file=sys.stderr)

    if processed_files < minimum_processed:
        raise RuntimeError(
            f"{satellite} processed only {processed_files}/{EXPECTED_FILES_PER_SLOT} usable files"
        )

    fed_indices = np.flatnonzero(fed_flat).astype(np.uint32)
    fed_values = fed_flat[fed_indices].astype(np.uint16)
    event_indices = np.flatnonzero(event_flat).astype(np.uint32)
    event_values = np.minimum(event_flat[event_indices], np.iinfo(np.uint16).max).astype(np.uint16)

    event_lat = np.concatenate(event_lat_parts) if event_lat_parts else np.empty(0, dtype=np.float32)
    event_lon = np.concatenate(event_lon_parts) if event_lon_parts else np.empty(0, dtype=np.float32)
    event_lat, event_lon = deterministic_sample(event_lat, event_lon, maximum_event_points)
    centroid_lat = np.concatenate(centroid_lat_parts) if centroid_lat_parts else np.empty(0, dtype=np.float32)
    centroid_lon = np.concatenate(centroid_lon_parts) if centroid_lon_parts else np.empty(0, dtype=np.float32)
    centroid_lat, centroid_lon = deterministic_sample(centroid_lat, centroid_lon, maximum_flash_centroids)

    final_npz, final_json = slot_paths(cache_root, satellite, end_time)
    temp_npz = final_npz.with_suffix(".npz.tmp")
    temp_json = final_json.with_suffix(".json.tmp")
    with temp_npz.open("wb") as handle:
        np.savez_compressed(
            handle,
            fed_indices=fed_indices,
            fed_values=fed_values,
            event_indices=event_indices,
            event_values=event_values,
            event_lat=event_lat,
            event_lon=event_lon,
            centroid_lat=centroid_lat,
            centroid_lon=centroid_lon,
        )

    metadata = SlotMetadata(
        satellite=satellite,
        satellite_label=config["label"],
        bucket=config["bucket"],
        slot_start_utc=iso_z(start_time),
        slot_end_utc=iso_z(end_time),
        expected_files=EXPECTED_FILES_PER_SLOT,
        listed_files=len(keys),
        processed_files=processed_files,
        completeness_fraction=processed_files / EXPECTED_FILES_PER_SLOT,
        quality_controlled_flash_records=qc_flashes,
        events_mapped_to_good_flashes=mapped_events,
        events_in_domain=domain_events,
        flash_cell_contributions=contributions,
        nonzero_fed_cells=int(fed_indices.size),
        maximum_fed=int(fed_values.max(initial=0)),
        nonzero_event_density_cells=int(event_indices.size),
        maximum_event_density=int(event_values.max(initial=0)),
        event_sample_count=int(event_lat.size),
        flash_centroid_sample_count=int(centroid_lat.size),
        cache_npz=final_npz.name,
        generated_time_utc=iso_z(utc_now()),
    )
    temp_json.write_text(json.dumps(asdict(metadata), indent=2), encoding="utf-8")
    temp_npz.replace(final_npz)
    temp_json.replace(final_json)
    return final_npz, final_json, metadata


def remove_slot(cache_root: Path, satellite: str, end_time: datetime) -> None:
    npz_path, json_path = slot_paths(cache_root, satellite, end_time)
    npz_path.unlink(missing_ok=True)
    json_path.unlink(missing_ok=True)


def build_slot_pair(
    client,
    end_time: datetime,
    keys_by_satellite: dict[str, list[str]],
    cache_root: Path,
    work_root: Path,
    grid: GridSpec,
    args: argparse.Namespace,
) -> None:
    built: list[str] = []
    try:
        for satellite in ("G19", "G18"):
            build_satellite_slot(
                client=client,
                satellite=satellite,
                keys=keys_by_satellite[satellite],
                end_time=end_time,
                cache_root=cache_root,
                work_root=work_root,
                grid=grid,
                workers=args.download_workers,
                minimum_slot_completeness=args.minimum_slot_completeness,
                maximum_event_points=args.maximum_event_points,
                maximum_flash_centroids=args.maximum_flash_centroids,
            )
            built.append(satellite)
    except Exception:
        for satellite in built:
            remove_slot(cache_root, satellite, end_time)
        raise


def cached_slot_times(cache_root: Path, satellite: str) -> set[datetime]:
    directory = cache_root / satellite.lower()
    if not directory.exists():
        return set()
    times: set[datetime] = set()
    for path in directory.glob("*.npz"):
        try:
            end_time = parse_slot_token(path.stem)
        except ValueError:
            continue
        if path.with_suffix(".json").exists():
            times.add(end_time)
    return times


def common_cached_slot_times(cache_root: Path) -> list[datetime]:
    common = cached_slot_times(cache_root, "G19") & cached_slot_times(cache_root, "G18")
    return sorted(common)


def prune_cache(cache_root: Path, keep_slot_count: int) -> None:
    common = common_cached_slot_times(cache_root)
    keep = set(common[-keep_slot_count:])
    for satellite in SATELLITES:
        for end_time in cached_slot_times(cache_root, satellite):
            if end_time not in keep:
                remove_slot(cache_root, satellite, end_time)


def load_slot_metadata(cache_root: Path, satellite: str, end_time: datetime) -> SlotMetadata:
    _, json_path = slot_paths(cache_root, satellite, end_time)
    return SlotMetadata(**json.loads(json_path.read_text(encoding="utf-8")))


def load_sparse_slot(cache_root: Path, satellite: str, end_time: datetime) -> dict[str, np.ndarray]:
    npz_path, _ = slot_paths(cache_root, satellite, end_time)
    with np.load(npz_path) as data:
        return {name: np.asarray(data[name]) for name in data.files}


def reconstruct_sparse(indices: np.ndarray, values: np.ndarray, grid: GridSpec, dtype=np.uint32) -> np.ndarray:
    flat = np.zeros(grid.size, dtype=dtype)
    flat[indices.astype(np.int64, copy=False)] = values.astype(dtype, copy=False)
    return flat.reshape(grid.height, grid.width)


def window_slot_times(end_time: datetime, window_minutes: int) -> list[datetime]:
    slot_count = window_minutes // SLOT_MINUTES
    return [end_time - timedelta(minutes=SLOT_MINUTES * offset) for offset in range(slot_count - 1, -1, -1)]


def legend_for_window(window_minutes: int):
    if window_minutes == 5:
        return FIVE_MIN_BINS, FIVE_MIN_LABELS, FIVE_MIN_RGBA, "five-minute"
    return ROLLING_BINS, ROLLING_LABELS, ROLLING_RGBA, "rolling"


def product_text(window_minutes: int) -> tuple[str, str, str]:
    if window_minutes == 5:
        return (
            "five-minute flash extent density",
            "Flash Extent Density — Latest 5 Minutes",
            "flashes per 0.02-degree grid cell per five minutes",
        )
    return (
        f"rolling {window_minutes}-minute flash extent accumulation",
        f"Flash Extent Accumulation — Rolling {window_minutes} Minutes",
        f"flash extent contributions per 0.02-degree grid cell per {window_minutes} minutes",
    )


def write_native_geotiff(array: np.ndarray, grid: GridSpec, output_path: Path, product: str, units: str) -> None:
    safe = np.minimum(array, np.iinfo(np.uint16).max).astype(np.uint16)
    with rio_open(
        output_path,
        "w",
        driver="GTiff",
        height=grid.height,
        width=grid.width,
        count=1,
        dtype="uint16",
        crs="EPSG:4326",
        transform=grid.transform,
        compress="deflate",
        predictor=2,
        tiled=True,
        blockxsize=512,
        blockysize=512,
    ) as destination:
        destination.write(safe, 1)
        destination.update_tags(product=product, units=units, zero_value="valid no-lightning value")


def render_web_mercator(
    array: np.ndarray,
    grid: GridSpec,
    output_path: Path,
    maximum_dimension: int,
    bins: Sequence[int],
    rgba_values: Sequence[tuple[int, int, int, int]],
) -> tuple[list[list[float]], list[int], dict[str, float]]:
    dst_transform, dst_width, dst_height = calculate_default_transform(
        "EPSG:4326", "EPSG:3857", grid.width, grid.height,
        grid.west, grid.south, grid.east, grid.north,
    )
    largest = max(dst_width, dst_height)
    if largest > maximum_dimension:
        scale = largest / maximum_dimension
        dst_width = max(1, int(round(dst_width / scale)))
        dst_height = max(1, int(round(dst_height / scale)))
        left, bottom, right, top = transform_bounds(
            "EPSG:4326", "EPSG:3857",
            grid.west, grid.south, grid.east, grid.north,
            densify_pts=21,
        )
        dst_transform = from_origin(left, top, (right - left) / dst_width, (top - bottom) / dst_height)

    destination = np.zeros((dst_height, dst_width), dtype=np.uint16)
    reproject(
        source=np.minimum(array, np.iinfo(np.uint16).max).astype(np.uint16),
        destination=destination,
        src_transform=grid.transform,
        src_crs="EPSG:4326",
        dst_transform=dst_transform,
        dst_crs="EPSG:3857",
        resampling=Resampling.nearest,
    )

    rgba = np.zeros((dst_height, dst_width, 4), dtype=np.uint8)
    for index, lower in enumerate(bins):
        upper = bins[index + 1] if index + 1 < len(bins) else None
        mask = destination >= lower
        if upper is not None:
            mask &= destination < upper
        rgba[mask] = rgba_values[index]
    Image.fromarray(rgba, mode="RGBA").save(output_path, optimize=True)

    mercator_bounds = array_bounds(dst_height, dst_width, dst_transform)
    west, south, east, north = transform_bounds("EPSG:3857", "EPSG:4326", *mercator_bounds, densify_pts=21)
    return (
        [[south, west], [north, east]],
        [dst_height, dst_width],
        {
            "a": float(dst_transform.a), "b": float(dst_transform.b), "c": float(dst_transform.c),
            "d": float(dst_transform.d), "e": float(dst_transform.e), "f": float(dst_transform.f),
        },
    )


def nonzero_percentiles(array: np.ndarray) -> dict[str, float]:
    values = array[array > 0]
    names = ("p50", "p75", "p90", "p95", "p99", "p99_5", "p99_9")
    if values.size == 0:
        return {name: 0.0 for name in names}
    computed = np.percentile(values.astype(np.float64), [50, 75, 90, 95, 99, 99.5, 99.9])
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


def create_product(
    satellite: str,
    window_minutes: int,
    end_time: datetime,
    available_times: set[datetime],
    cache_root: Path,
    output_dir: Path,
    grid: GridSpec,
    args: argparse.Namespace,
) -> tuple[ProductResult, np.ndarray]:
    desired = window_slot_times(end_time, window_minutes)
    selected = [value for value in desired if value in available_times]
    expected_slots = len(desired)
    minimum_slots = math.ceil(expected_slots * args.minimum_window_completeness)
    if len(selected) < minimum_slots:
        raise RuntimeError(
            f"{satellite} {window_minutes}-minute window has only {len(selected)}/{expected_slots} "
            "cached slots"
        )

    aggregate = np.zeros((grid.height, grid.width), dtype=np.uint32)
    slot_metadata: list[SlotMetadata] = []
    for slot_end in selected:
        slot = load_sparse_slot(cache_root, satellite, slot_end)
        flat = aggregate.reshape(-1)
        add_sparse(flat, slot["fed_indices"], slot["fed_values"].astype(np.uint32))
        slot_metadata.append(load_slot_metadata(cache_root, satellite, slot_end))

    config = SATELLITES[satellite]
    bins, labels, colors, legend_id = legend_for_window(window_minutes)
    product_kind, short_display, units = product_text(window_minutes)
    display_label = f"{config['label']} — {short_display}"
    stem = f"glm_{satellite.lower()}_fed_{window_minutes}min"
    geotiff_path = output_dir / f"{stem}.tif"
    png_path = output_dir / f"{stem}.png"
    metadata_path = output_dir / f"{stem}_metadata.json"

    write_native_geotiff(
        aggregate, grid, geotiff_path,
        f"Incremental LCFA-derived GLM {product_kind}", units,
    )
    leaflet_bounds, rendered_shape, rendered_transform = render_web_mercator(
        aggregate, grid, png_path, args.maximum_render_dimension, bins, colors,
    )

    processed_files = sum(item.processed_files for item in slot_metadata)
    expected_files = expected_slots * EXPECTED_FILES_PER_SLOT
    result = ProductResult(
        satellite=satellite,
        satellite_label=config["label"],
        bucket=config["bucket"],
        window_minutes=window_minutes,
        display_label=display_label,
        product_kind=product_kind,
        units=units,
        window_start_utc=iso_z(end_time - timedelta(minutes=window_minutes)),
        window_end_utc=iso_z(end_time),
        expected_slots=expected_slots,
        available_slots=len(selected),
        slot_completeness_fraction=len(selected) / expected_slots,
        expected_files=expected_files,
        processed_files=processed_files,
        file_completeness_fraction=processed_files / expected_files,
        quality_controlled_flash_records=sum(item.quality_controlled_flash_records for item in slot_metadata),
        events_mapped_to_good_flashes=sum(item.events_mapped_to_good_flashes for item in slot_metadata),
        events_in_domain=sum(item.events_in_domain for item in slot_metadata),
        flash_cell_contributions=int(aggregate.sum(dtype=np.uint64)),
        nonzero_grid_cells=int(np.count_nonzero(aggregate)),
        maximum_value=int(aggregate.max(initial=0)),
        native_geotiff=geotiff_path.name,
        leaflet_png=png_path.name,
        metadata_json=metadata_path.name,
        image_crs="EPSG:3857",
        leaflet_bounds=leaflet_bounds,
        rendered_shape=rendered_shape,
        legend_id=legend_id,
    )

    metadata = {
        **asdict(result),
        "metadata_mode": "glm_dashboard_v1",
        "product_role": "satellite_reference_debug",
        "product": f"Incremental LCFA-derived GLM {product_kind}",
        "source_product": PRODUCT_PREFIX,
        "listed_files": processed_files,
        "completeness_fraction": processed_files / expected_files,
        "default_opacity": 0.88,
        "option": "Separate satellite reference used by the controlled mosaic",
        "incremental_method": {
            "slot_minutes": SLOT_MINUTES,
            "requested_slot_end_times_utc": [iso_z(value) for value in desired],
            "used_slot_end_times_utc": [iso_z(value) for value in selected],
            "missing_slot_end_times_utc": [iso_z(value) for value in desired if value not in available_times],
            "cache_storage": "sparse nonzero grid indices and values in compressed NPZ files",
        },
        "methodology": (
            "Within each LCFA file, a quality-controlled flash contributes once to each 0.02-degree "
            "grid cell containing at least one constituent event. Five-minute cache slots are summed "
            "to form rolling 30- and 60-minute products."
        ),
        "quality_control": (
            "flash_quality_flag == 0 and group_quality_flag == 0 when present; packed event "
            "coordinates honor _Unsigned before scale_factor and add_offset"
        ),
        "important_note": (
            "This is an LCFA-derived diagnostic field, not NOAA's official gridded FED product. "
            "GOES-19 and GOES-18 remain separate and must not be added together."
        ),
        "nonzero_percentiles": nonzero_percentiles(aggregate),
        "render_bin_counts": bin_counts(aggregate, bins, labels),
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
    return result, aggregate



def build_source_ownership(grid: GridSpec) -> tuple[np.ndarray, dict[str, float]]:
    """Assign each grid cell exclusively to the lower-view-angle satellite."""
    lon, lat = grid.center_coordinates()
    lat_rad = np.deg2rad(lat)
    lon_rad = np.deg2rad(lon)
    scores: dict[str, np.ndarray] = {}
    for satellite, config in SATELLITES.items():
        sub_lon = math.radians(float(config["subsatellite_longitude"]))
        scores[satellite] = np.cos(lat_rad) * np.cos(lon_rad - sub_lon)
    owner = np.where(
        scores["G18"] > scores["G19"],
        SATELLITES["G18"]["source_code"],
        SATELLITES["G19"]["source_code"],
    ).astype(np.uint8)
    seam = (
        float(SATELLITES["G18"]["subsatellite_longitude"])
        + float(SATELLITES["G19"]["subsatellite_longitude"])
    ) / 2.0
    return owner, {
        "g18_subsatellite_longitude": float(SATELLITES["G18"]["subsatellite_longitude"]),
        "g19_subsatellite_longitude": float(SATELLITES["G19"]["subsatellite_longitude"]),
        "nominal_equal_angle_seam_longitude": seam,
    }


def build_controlled_mosaic(g18: np.ndarray, g19: np.ndarray, owner: np.ndarray) -> np.ndarray:
    if g18.shape != g19.shape or g18.shape != owner.shape:
        raise ValueError("Satellite arrays and ownership mask must have identical shapes")
    return np.where(owner == 18, g18, g19).astype(np.uint32, copy=False)


def compact_grid_metadata(
    grid: GridSpec,
    leaflet_bounds: list[list[float]],
    rendered_shape: list[int],
    rendered_transform: dict[str, float],
) -> dict:
    return {
        **asdict(grid),
        "shape": [grid.height, grid.width],
        "crs": "EPSG:4326",
        "image_crs": "EPSG:3857",
        "leaflet_bounds": leaflet_bounds,
        "rendered_shape": rendered_shape,
        "rendered_transform": rendered_transform,
    }


def result_input_payload(result: ProductResult) -> dict:
    """Return the exact completeness/statistics shape consumed by Option B."""
    return {
        "satellite": result.satellite,
        "satellite_label": result.satellite_label,
        "window_minutes": result.window_minutes,
        "window_start_utc": result.window_start_utc,
        "window_end_utc": result.window_end_utc,
        "expected_slots": result.expected_slots,
        "available_slots": result.available_slots,
        "slot_completeness_fraction": result.slot_completeness_fraction,
        "expected_files": result.expected_files,
        "listed_files": result.processed_files,
        "processed_files": result.processed_files,
        "completeness_fraction": result.file_completeness_fraction,
        "quality_controlled_flash_records": result.quality_controlled_flash_records,
        "events_mapped_to_good_flashes": result.events_mapped_to_good_flashes,
        "events_in_domain": result.events_in_domain,
        "flash_cell_contributions": result.flash_cell_contributions,
        "nonzero_grid_cells": result.nonzero_grid_cells,
        "maximum_value": result.maximum_value,
    }


def seam_statistics(
    g18: np.ndarray,
    g19: np.ndarray,
    owner: np.ndarray,
    grid: GridSpec,
    seam_longitude: float,
    seam_band_degrees: float,
) -> dict:
    lon, _ = grid.center_coordinates()
    band = np.abs(lon - seam_longitude) <= seam_band_degrees
    both_nonzero = band & (g18 > 0) & (g19 > 0)
    either_nonzero = band & ((g18 > 0) | (g19 > 0))
    difference = g19.astype(np.int64) - g18.astype(np.int64)
    selected = np.where(owner == 18, g18, g19)
    return {
        "seam_longitude": seam_longitude,
        "band_half_width_degrees": seam_band_degrees,
        "band_grid_cells": int(np.count_nonzero(band)),
        "either_satellite_nonzero_cells": int(np.count_nonzero(either_nonzero)),
        "both_satellites_nonzero_cells": int(np.count_nonzero(both_nonzero)),
        "g18_nonzero_cells": int(np.count_nonzero(band & (g18 > 0))),
        "g19_nonzero_cells": int(np.count_nonzero(band & (g19 > 0))),
        "selected_nonzero_cells": int(np.count_nonzero(band & (selected > 0))),
        "mean_g19_minus_g18_where_both_nonzero": (
            float(np.mean(difference[both_nonzero])) if np.any(both_nonzero) else 0.0
        ),
        "median_g19_minus_g18_where_both_nonzero": (
            float(np.median(difference[both_nonzero])) if np.any(both_nonzero) else 0.0
        ),
    }


def create_source_ownership_products(
    owner: np.ndarray,
    geometry: dict[str, float],
    grid: GridSpec,
    output_dir: Path,
    args: argparse.Namespace,
) -> dict:
    stem = "glm_mosaic_source_ownership"
    tif_path = output_dir / f"{stem}.tif"
    png_path = output_dir / f"{stem}.png"
    metadata_path = output_dir / f"{stem}_metadata.json"
    write_native_geotiff(
        owner.astype(np.uint32), grid, tif_path,
        "GOES GLM controlled-mosaic source ownership",
        "18=GOES-18 West, 19=GOES-19 East",
    )
    bounds, shape, transform = render_web_mercator(
        owner.astype(np.uint32), grid, png_path,
        args.maximum_render_dimension, SOURCE_BINS, SOURCE_RGBA,
    )
    metadata = {
        "metadata_mode": "glm_dashboard_v1",
        "product_role": "source_ownership_debug",
        "product": "GOES GLM controlled-mosaic source ownership mask",
        "display_label": "GOES GLM Mosaic — Satellite Source Ownership",
        "methodology": (
            "Each cell is assigned exclusively to the satellite with the smaller "
            "spherical central angle to its sub-satellite point."
        ),
        "source_codes": {"18": "GOES-18 (West)", "19": "GOES-19 (East)"},
        "satellite_geometry": geometry,
        "owned_cell_counts": {
            "G18": int(np.count_nonzero(owner == 18)),
            "G19": int(np.count_nonzero(owner == 19)),
        },
        "leaflet_png": png_path.name,
        "default_opacity": 0.42,
        "grid": compact_grid_metadata(grid, bounds, shape, transform),
        "rendering": {
            "resampling": "nearest",
            "bins": SOURCE_BINS,
            "labels": SOURCE_LABELS,
            "rgba": [list(value) for value in SOURCE_RGBA],
        },
        "generated_time_utc": iso_z(utc_now()),
    }
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return metadata


def create_controlled_mosaic_product(
    window_minutes: int,
    end_time: datetime,
    g18: np.ndarray,
    g19: np.ndarray,
    g18_result: ProductResult,
    g19_result: ProductResult,
    owner: np.ndarray,
    geometry: dict[str, float],
    grid: GridSpec,
    output_dir: Path,
    args: argparse.Namespace,
) -> tuple[dict, np.ndarray]:
    mosaic = build_controlled_mosaic(g18, g19, owner)
    bins, labels, colors, legend_id = legend_for_window(window_minutes)
    if window_minutes == 5:
        product_kind = "five-minute flash extent density"
        display_label = "GOES GLM Controlled Mosaic — Latest 5-Minute FED"
        units = "flashes per 0.02-degree grid cell per five minutes"
    else:
        product_kind = f"rolling {window_minutes}-minute flash extent accumulation"
        display_label = f"GOES GLM Controlled Mosaic — Rolling {window_minutes}-Minute Accumulation"
        units = f"flash extent contributions per 0.02-degree grid cell per {window_minutes} minutes"
    stem = f"glm_conus_mosaic_{window_minutes}min"
    tif_path = output_dir / f"{stem}.tif"
    png_path = output_dir / f"{stem}.png"
    metadata_path = output_dir / f"{stem}_metadata.json"
    write_native_geotiff(
        mosaic, grid, tif_path,
        f"Incremental LCFA-derived GOES GLM controlled mosaic {product_kind}", units,
    )
    bounds, shape, transform = render_web_mercator(
        mosaic, grid, png_path, args.maximum_render_dimension, bins, colors,
    )
    seam = seam_statistics(
        g18, g19, owner, grid,
        float(geometry["nominal_equal_angle_seam_longitude"]),
        args.seam_band_degrees,
    )
    metadata = {
        "metadata_mode": "glm_dashboard_v1",
        "product_role": "controlled_mosaic",
        "window_minutes": window_minutes,
        "product_kind": product_kind,
        "display_label": display_label,
        "window_start_utc": iso_z(end_time - timedelta(minutes=window_minutes)),
        "window_end_utc": iso_z(end_time),
        "maximum_value": int(mosaic.max(initial=0)),
        "nonzero_grid_cells": int(np.count_nonzero(mosaic)),
        "flash_cell_contributions": int(mosaic.sum(dtype=np.uint64)),
        "source_g18_owned_cells": int(np.count_nonzero(owner == 18)),
        "source_g19_owned_cells": int(np.count_nonzero(owner == 19)),
        "source_g18_nonzero_cells": int(np.count_nonzero((owner == 18) & (mosaic > 0))),
        "source_g19_nonzero_cells": int(np.count_nonzero((owner == 19) & (mosaic > 0))),
        "source_product": PRODUCT_PREFIX,
        "mosaic_method": {
            "name": "exclusive lower-view-angle source ownership",
            "summation": False,
            "averaging": False,
            "blending": False,
            "secondary_source_gap_fill": False,
            "satellite_geometry": geometry,
        },
        "satellite_inputs": {
            "G18": result_input_payload(g18_result),
            "G19": result_input_payload(g19_result),
        },
        "incremental_cache": {
            "slot_minutes": SLOT_MINUTES,
            "expected_slots": window_minutes // SLOT_MINUTES,
            "g18_available_slots": g18_result.available_slots,
            "g19_available_slots": g19_result.available_slots,
            "storage": "compressed sparse NPZ five-minute slots",
        },
        "seam_diagnostics": seam,
        "units": units,
        "legend_id": legend_id,
        "leaflet_png": png_path.name,
        "default_opacity": 0.88,
        "grid": compact_grid_metadata(grid, bounds, shape, transform),
        "rendering": {
            "resampling": "nearest",
            "bins": list(bins),
            "labels": list(labels),
            "rgba": [list(color) for color in colors],
        },
        "nonzero_percentiles": nonzero_percentiles(mosaic),
        "render_bin_counts": bin_counts(mosaic, bins, labels),
        "generated_time_utc": iso_z(utc_now()),
    }
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return metadata, mosaic

def points_geojson(lat: np.ndarray, lon: np.ndarray, kind: str, satellite: str) -> dict:
    features = []
    for index, (latitude, longitude) in enumerate(zip(lat.tolist(), lon.tolist())):
        features.append({
            "type": "Feature",
            "properties": {"kind": kind, "satellite": satellite, "sample_index": index},
            "geometry": {"type": "Point", "coordinates": [longitude, latitude]},
        })
    return {"type": "FeatureCollection", "features": features}


def build_debug_outputs(
    satellite: str,
    end_time: datetime,
    cache_root: Path,
    output_dir: Path,
    grid: GridSpec,
    args: argparse.Namespace,
) -> dict:
    slot = load_sparse_slot(cache_root, satellite, end_time)
    event_density = reconstruct_sparse(slot["event_indices"], slot["event_values"], grid)
    footprint = np.zeros((grid.height, grid.width), dtype=np.uint8)
    footprint.reshape(-1)[slot["fed_indices"].astype(np.int64)] = 1

    event_png = output_dir / f"glm_{satellite.lower()}_debug_event_density_5min.png"
    footprint_png = output_dir / f"glm_{satellite.lower()}_debug_footprint_5min.png"
    event_bounds, _, _ = render_web_mercator(
        event_density, grid, event_png, args.maximum_render_dimension,
        EVENT_DENSITY_BINS, EVENT_DENSITY_RGBA,
    )
    footprint_bounds, _, _ = render_web_mercator(
        footprint, grid, footprint_png, args.maximum_render_dimension,
        FOOTPRINT_BINS, FOOTPRINT_RGBA,
    )

    event_geojson_path = output_dir / f"glm_{satellite.lower()}_debug_event_sample_5min.geojson"
    centroid_geojson_path = output_dir / f"glm_{satellite.lower()}_debug_flash_centroids_5min.geojson"
    event_geojson = points_geojson(slot["event_lat"], slot["event_lon"], "event_sample", satellite)
    centroid_geojson = points_geojson(slot["centroid_lat"], slot["centroid_lon"], "flash_centroid", satellite)
    event_geojson_path.write_text(json.dumps(event_geojson), encoding="utf-8")
    centroid_geojson_path.write_text(json.dumps(centroid_geojson), encoding="utf-8")

    return {
        "satellite": satellite,
        "satelliteLabel": SATELLITES[satellite]["label"],
        "eventDensityPng": event_png.name,
        "eventDensityBounds": event_bounds,
        "footprintPng": footprint_png.name,
        "footprintBounds": footprint_bounds,
        "eventGeojson": event_geojson,
        "centroidGeojson": centroid_geojson,
        "eventPointCount": len(event_geojson["features"]),
        "centroidPointCount": len(centroid_geojson["features"]),
    }


def png_data_uri(path: Path) -> str:
    return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def compact_json(value) -> str:
    return json.dumps(value, separators=(",", ":"))


def write_debug_html(
    output_path: Path,
    results: Sequence[ProductResult],
    debug_payloads: Sequence[dict],
    generated_time: str,
    end_time: datetime,
) -> None:
    legends = {
        "five-minute": {
            "title": "Flashes per 0.02° grid cell / 5 minutes",
            "labels": FIVE_MIN_LABELS,
            "rgba": [list(value) for value in FIVE_MIN_RGBA],
        },
        "rolling": {
            "title": "Flash extent contributions per 0.02° grid cell",
            "labels": ROLLING_LABELS,
            "rgba": [list(value) for value in ROLLING_RGBA],
        },
    }
    overlays = []
    for result in results:
        overlays.append({
            "id": f"{result.satellite.lower()}-{result.window_minutes}",
            "satellite": result.satellite,
            "satelliteLabel": result.satellite_label,
            "windowMinutes": result.window_minutes,
            "name": result.display_label,
            "dataUri": png_data_uri(output_path.parent / result.leaflet_png),
            "bounds": result.leaflet_bounds,
            "legendId": result.legend_id,
            "metadata": asdict(result),
        })

    debug_layers = []
    for payload in debug_payloads:
        debug_layers.append({
            **payload,
            "eventDensityDataUri": png_data_uri(output_path.parent / payload["eventDensityPng"]),
            "footprintDataUri": png_data_uri(output_path.parent / payload["footprintPng"]),
        })

    radar_end = floor_to_ten_minutes(end_time)
    radar_times = [
        iso_z(radar_end - timedelta(minutes=10 * offset))
        for offset in range(12, -1, -1)
    ]
    timing = {
        "glmEndUtc": iso_z(end_time),
        "radarComparisonUtc": iso_z(radar_end),
        "radarOffsetMinutes": int((radar_end - end_time).total_seconds() / 60),
        "radarTimes": radar_times,
    }

    template = r'''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Incremental GOES GLM Option A Debug Viewer</title>
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/leaflet-timedimension@1.1.1/dist/leaflet.timedimension.control.min.css">
  <style>
    html, body, #map { height: 100%; margin: 0; }
    body { font-family: Arial, Helvetica, sans-serif; background: #111; }
    .panel { background: rgba(21,26,33,.96); color:#f4f7fa; padding:10px 11px; border:1px solid rgba(255,255,255,.16); border-radius:7px; box-shadow:0 2px 10px rgba(0,0,0,.48); line-height:1.35; }
    .title { max-width:460px; }
    .title h2 { margin:0 0 4px; font-size:17px; }
    .title p { margin:3px 0; font-size:11px; color:#d5dbe3; }
    .selector { width:380px; max-height:58vh; overflow:auto; }
    .selector h3 { margin:0 0 6px; font-size:14px; }
    .sat-heading { margin:8px 0 3px; font-size:12px; font-weight:700; color:#9fc6ff; }
    .choice { display:block; margin:3px 0; font-size:12px; cursor:pointer; }
    .controls { border-top:1px solid rgba(255,255,255,.16); margin-top:8px; padding-top:7px; font-size:11px; }
    .controls input[type=range] { width:175px; vertical-align:middle; }
    .controls button { margin:3px 4px 1px 0; padding:4px 7px; }
    .metadata { width:440px; max-width:calc(100vw - 40px); }
    .metadata h3 { margin:0 0 5px; font-size:14px; }
    .metadata table { width:100%; border-collapse:collapse; font-size:11px; }
    .metadata td { padding:3px 4px; border-top:1px solid rgba(255,255,255,.12); vertical-align:top; }
    .metadata td:first-child { color:#a9c9ff; width:135px; white-space:nowrap; }
    .warning { color:#ffd166; font-weight:700; margin-top:6px; font-size:11px; }
    .legend { max-width:720px; }
    .legend-title { font-size:11px; font-weight:700; margin-bottom:4px; }
    .legend-row { display:flex; flex-wrap:nowrap; border:1px solid #333; }
    .legend-bin { min-width:48px; padding:4px 5px; text-align:center; color:#111; font-size:10px; font-weight:700; }
    @media (max-width:760px) { .selector{width:74vw;max-height:42vh}.metadata{width:78vw}.title{max-width:72vw}.legend{max-width:78vw;overflow:auto} }
  </style>
</head>
<body>
<div id="map"></div>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script src="https://cdn.jsdelivr.net/npm/iso8601-js-period@0.2.1/iso8601.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/leaflet-timedimension@1.1.1/dist/leaflet.timedimension.min.js"></script>
<script>
const overlays = __OVERLAYS__;
const debugLayers = __DEBUG__;
const legends = __LEGENDS__;
const timing = __TIMING__;

const map = L.map('map', { center:[38.5,-97], zoom:4, preferCanvas:true, timeDimension:true, timeDimensionOptions:{ times:timing.radarTimes.join(',') }, timeDimensionControl:true, timeDimensionControlOptions:{ autoPlay:false, loopButton:true, timeSliderDragUpdate:true, playerOptions:{ transitionTime:900, loop:true } } });
map.timeDimension.setCurrentTime(Date.parse(timing.radarComparisonUtc));
map.createPane('radarPane'); map.getPane('radarPane').style.zIndex=320;
map.createPane('glmRaster'); map.getPane('glmRaster').style.zIndex=350;
map.createPane('debugRaster'); map.getPane('debugRaster').style.zIndex=390;
map.createPane('debugPoints'); map.getPane('debugPoints').style.zIndex=420;
map.createPane('stateLines'); map.getPane('stateLines').style.zIndex=440; map.getPane('stateLines').style.pointerEvents='none';

const dark=L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}',{maxZoom:16,attribution:'Tiles © Esri'}).addTo(map);
const darkLabels=L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Reference/MapServer/tile/{z}/{y}/{x}',{maxZoom:16}).addTo(map);
const light=L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}',{maxZoom:16,attribution:'Tiles © Esri'});
const topo=L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}',{maxZoom:19,attribution:'Tiles © Esri'});
const imagery=L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',{maxZoom:19,attribution:'Tiles © Esri'});
const osm=L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:19,attribution:'© OpenStreetMap contributors'});
L.control.layers({'Esri Dark Gray':dark,'Esri Light Gray':light,'Esri Topographic':topo,'Esri Imagery':imagery,'OpenStreetMap':osm},null,{collapsed:false}).addTo(map);

const radarWMS=L.tileLayer.wms('https://mesonet.agron.iastate.edu/cgi-bin/wms/nexrad/n0q-t.cgi',{format:'image/png',transparent:true,opacity:.58,layers:'nexrad-n0q-wmst',pane:'radarPane',attribution:'Radar © IEM'});
const radarTimeLayer=L.timeDimension.layer.wms(radarWMS,{updateTimeDimension:false,requestTimeFromCapabilities:false}).addTo(map);

const imageLayers=new Map();
overlays.forEach(item=>imageLayers.set(item.id,L.imageOverlay(item.dataUri,item.bounds,{opacity:.88,interactive:false,pane:'glmRaster'})));
const debugObjects={};
debugLayers.forEach(item=>{
  debugObjects[item.satellite]={
    eventDensity:L.imageOverlay(item.eventDensityDataUri,item.eventDensityBounds,{opacity:.72,interactive:false,pane:'debugRaster'}),
    footprint:L.imageOverlay(item.footprintDataUri,item.footprintBounds,{opacity:.70,interactive:false,pane:'debugRaster'}),
    events:L.geoJSON(item.eventGeojson,{pane:'debugPoints',pointToLayer:(f,ll)=>L.circleMarker(ll,{radius:2,color:'#00ffff',weight:1,fillColor:'#00ffff',fillOpacity:.45})}),
    centroids:L.geoJSON(item.centroidGeojson,{pane:'debugPoints',pointToLayer:(f,ll)=>L.circleMarker(ll,{radius:4,color:'#ffffff',weight:1.5,fillColor:'#ff00ff',fillOpacity:.70})})
  };
});

let currentId=overlays[0].id; let currentOpacity=.88;
function selectedItem(){return overlays.find(item=>item.id===currentId)}
function selectLayer(id){
  imageLayers.forEach(layer=>{if(map.hasLayer(layer))map.removeLayer(layer)});
  currentId=id; imageLayers.get(id).setOpacity(currentOpacity).addTo(map);
  document.querySelectorAll('input[name=glm-layer]').forEach(input=>input.checked=input.value===id);
  updateMetadata(); updateLegend();
}
function toggleDebug(satellite,key,enabled){const layer=debugObjects[satellite][key]; if(enabled)layer.addTo(map);else if(map.hasLayer(layer))map.removeLayer(layer)}

const title=L.control({position:'topleft'}); title.onAdd=()=>{const d=L.DomUtil.create('div','panel title');d.innerHTML=`<h2>Incremental GOES GLM Mosaic Diagnostics</h2><p>Separate GOES-19 East and GOES-18 West source fields behind the exclusive controlled mosaic; no cross-satellite summation.</p><p>Radar uses the dashboard's IEM NEXRAD WMS and 10-minute loop timing.</p>`;L.DomEvent.disableClickPropagation(d);return d};title.addTo(map);
const selector=L.control({position:'topleft'}); selector.onAdd=()=>{const d=L.DomUtil.create('div','panel selector');const sections=['G19','G18'].map(s=>{const items=overlays.filter(x=>x.satellite===s);return `<div class="sat-heading">${items[0].satelliteLabel}</div>`+items.map(x=>`<label class="choice"><input type="radio" name="glm-layer" value="${x.id}">${x.name.replace(x.satelliteLabel+' — ','')}</label>`).join('')+`<label class="choice"><input type="checkbox" data-sat="${s}" data-debug="eventDensity">Debug: raw event density</label><label class="choice"><input type="checkbox" data-sat="${s}" data-debug="footprint">Debug: nonzero FED footprint</label><label class="choice"><input type="checkbox" data-sat="${s}" data-debug="events">Debug: sampled event points</label><label class="choice"><input type="checkbox" data-sat="${s}" data-debug="centroids">Debug: sampled flash centroids</label>`}).join('');d.innerHTML=`<h3>GLM and debug layers</h3>${sections}<div class="controls"><label>GLM opacity <input id="opacity" type="range" min=".2" max="1" step=".05" value=".88"> <span id="opacityValue">88%</span></label><br><label>Radar opacity <input id="radarOpacity" type="range" min="0" max="1" step=".05" value=".58"> <span id="radarOpacityValue">58%</span></label><br><label class="choice"><input id="radarToggle" type="checkbox" checked> Dashboard NEXRAD 2-hour loop</label><button id="fit">Fit CONUS</button><button id="clearDebug">Clear debug</button></div>`;L.DomEvent.disableClickPropagation(d);setTimeout(()=>{d.querySelectorAll('input[name=glm-layer]').forEach(i=>i.addEventListener('change',()=>selectLayer(i.value)));d.querySelectorAll('input[data-debug]').forEach(i=>i.addEventListener('change',()=>toggleDebug(i.dataset.sat,i.dataset.debug,i.checked)));d.querySelector('#opacity').addEventListener('input',e=>{currentOpacity=Number(e.target.value);imageLayers.get(currentId).setOpacity(currentOpacity);d.querySelector('#opacityValue').textContent=`${Math.round(currentOpacity*100)}%`});d.querySelector('#radarOpacity').addEventListener('input',e=>{radarWMS.setOpacity(Number(e.target.value));d.querySelector('#radarOpacityValue').textContent=`${Math.round(Number(e.target.value)*100)}%`});d.querySelector('#radarToggle').addEventListener('change',e=>{if(e.target.checked)radarTimeLayer.addTo(map);else if(map.hasLayer(radarTimeLayer))map.removeLayer(radarTimeLayer)});d.querySelector('#fit').addEventListener('click',()=>map.fitBounds(selectedItem().bounds));d.querySelector('#clearDebug').addEventListener('click',()=>{d.querySelectorAll('input[data-debug]').forEach(i=>{i.checked=false;toggleDebug(i.dataset.sat,i.dataset.debug,false)})});selectLayer(currentId)},0);return d};selector.addTo(map);

const metadata=L.control({position:'topright'});metadata.onAdd=()=>{const d=L.DomUtil.create('div','panel metadata');d.id='metadataPanel';L.DomEvent.disableClickPropagation(d);return d};metadata.addTo(map);
function updateMetadata(){const x=selectedItem(),m=x.metadata;document.getElementById('metadataPanel').innerHTML=`<h3>${m.display_label}</h3><table><tr><td>GLM window</td><td>${m.window_start_utc} through ${m.window_end_utc}</td></tr><tr><td>Cached slots</td><td>${m.available_slots}/${m.expected_slots} (${(m.slot_completeness_fraction*100).toFixed(0)}%)</td></tr><tr><td>LCFA files</td><td>${m.processed_files}/${m.expected_files} (${(m.file_completeness_fraction*100).toFixed(0)}%)</td></tr><tr><td>QC flashes</td><td>${m.quality_controlled_flash_records.toLocaleString()}</td></tr><tr><td>Nonzero cells</td><td>${m.nonzero_grid_cells.toLocaleString()}</td></tr><tr><td>Maximum</td><td>${m.maximum_value.toLocaleString()}</td></tr><tr><td>Radar comparison</td><td>${timing.radarComparisonUtc} (${timing.radarOffsetMinutes} min from GLM end)</td></tr><tr><td>Source</td><td>${m.satellite_label} / GLM-L2-LCFA</td></tr></table><div class="warning">Compare GLM structure with radar, but do not add East and West values in their overlap.</div><div style="font-size:10px;color:#cfd5dd;margin-top:5px">Generated: __GENERATED__</div>`}
const legend=L.control({position:'bottomright'});legend.onAdd=()=>{const d=L.DomUtil.create('div','panel legend');d.id='legendPanel';return d};legend.addTo(map);
function updateLegend(){const x=selectedItem(),l=legends[x.legendId];document.getElementById('legendPanel').innerHTML=`<div class="legend-title">${l.title}</div><div class="legend-row">${l.labels.map((label,i)=>{const c=l.rgba[i];return `<span class="legend-bin" style="background:rgba(${c[0]},${c[1]},${c[2]},${c[3]/255})">${label}</span>`}).join('')}</div>`}
fetch('https://raw.githubusercontent.com/PublicaMundi/MappingAPI/master/data/geojson/us-states.json').then(r=>r.json()).then(data=>L.geoJSON(data,{pane:'stateLines',style:{color:'#fff',weight:1,opacity:.72,fillOpacity:0},interactive:false}).addTo(map)).catch(e=>console.warn(e));
selectLayer(currentId);map.fitBounds(overlays[0].bounds);
</script>
</body>
</html>'''

    html = (
        template
        .replace("__OVERLAYS__", compact_json(overlays))
        .replace("__DEBUG__", compact_json(debug_layers))
        .replace("__LEGENDS__", compact_json(legends))
        .replace("__TIMING__", compact_json(timing))
        .replace("__GENERATED__", generated_time)
    )
    output_path.write_text(html, encoding="utf-8")


def write_summary_csv(output_path: Path, results: Sequence[ProductResult]) -> None:
    rows = [asdict(result) for result in results]
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)



def self_test() -> None:
    grid = GridSpec(west=-120.0, east=-90.0, south=30.0, north=40.0, resolution=1.0)

    # Packed-coordinate and identifier decoding regression test.
    expected_lon = np.array([-99.95, -99.94, -99.85, -99.96], dtype=np.float64)
    expected_lat = np.array([30.95, 30.94, 30.95, 30.96], dtype=np.float64)
    scale = 0.002
    packed_lon_u16 = np.rint((expected_lon + 180.0) / scale).astype(np.uint16)
    packed_lat_u16 = np.rint((expected_lat + 90.0) / scale).astype(np.uint16)
    group_ids_u32 = np.array([0xF0000001, 0xF0000002, 0xF0000003], dtype=np.uint32)
    flash_ids_u32 = np.array([0xE0000001, 0xE0000002], dtype=np.uint32)
    dataset = xr.Dataset(data_vars={
        "event_lat": xr.DataArray(packed_lat_u16.view(np.int16), dims=("event",), attrs={"_Unsigned":"true","scale_factor":scale,"add_offset":-90.0}),
        "event_lon": xr.DataArray(packed_lon_u16.view(np.int16), dims=("event",), attrs={"_Unsigned":"true","scale_factor":scale,"add_offset":-180.0}),
        "event_parent_group_id": xr.DataArray(np.array([group_ids_u32[0],group_ids_u32[0],group_ids_u32[1],group_ids_u32[2]],dtype=np.uint32).view(np.int32),dims=("event",),attrs={"_Unsigned":"true"}),
        "group_id": xr.DataArray(group_ids_u32.view(np.int32),dims=("group",),attrs={"_Unsigned":"true"}),
        "group_parent_flash_id": xr.DataArray(np.array([flash_ids_u32[0],flash_ids_u32[0],flash_ids_u32[1]],dtype=np.uint32).view(np.int32),dims=("group",),attrs={"_Unsigned":"true"}),
        "flash_id": xr.DataArray(flash_ids_u32.view(np.int32),dims=("flash",),attrs={"_Unsigned":"true"}),
        "flash_quality_flag": xr.DataArray(np.zeros(2,dtype=np.int8),dims=("flash",)),
        "group_quality_flag": xr.DataArray(np.zeros(3,dtype=np.int8),dims=("group",)),
    })
    lat, lon, flashes, good = map_events_to_flashes(dataset)
    assert good == 2
    assert np.allclose(lat, expected_lat, atol=scale/2)
    assert np.allclose(lon, expected_lon, atol=scale/2)

    # Sparse flash-extent and rolling-slot tests.
    cells = np.array([1, 1, 2, 1], dtype=np.int64)
    unique_flashes, local = np.unique(flashes, return_inverse=True)
    pairs = np.unique(cells * unique_flashes.size + local)
    fed_cells, fed_counts = np.unique(pairs // unique_flashes.size, return_counts=True)
    dense = np.zeros(10, dtype=np.uint32)
    add_sparse(dense, fed_cells, fed_counts.astype(np.uint32))
    assert dense[1] == 2 and dense[2] == 1
    end = parse_utc("2026-07-21T21:00:00Z")
    assert [len(window_slot_times(end, w)) for w in WINDOWS_MINUTES] == [1, 6, 12]
    assert floor_to_ten_minutes(parse_utc("2026-07-21T21:05:00Z")) == end

    # Controlled-mosaic ownership and strict no-fallback/no-sum behavior.
    owner, geometry = build_source_ownership(grid)
    seam = geometry["nominal_equal_angle_seam_longitude"]
    assert abs(seam - (-106.1)) < 0.01
    lon_grid, _ = grid.center_coordinates()
    assert np.all(owner[lon_grid < seam] == 18)
    assert np.all(owner[lon_grid > seam] == 19)
    simple_owner = np.array([[18, 18, 19, 19]], dtype=np.uint8)
    simple_g18 = np.array([[1, 0, 8, 9]], dtype=np.uint32)
    simple_g19 = np.array([[5, 6, 7, 0]], dtype=np.uint32)
    simple = build_controlled_mosaic(simple_g18, simple_g19, simple_owner)
    assert np.array_equal(simple, np.array([[1, 0, 7, 0]], dtype=np.uint32))
    print("Incremental GOES GLM controlled-mosaic self-test passed.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--analysis-time", default="", help="Optional shared UTC end time; blank selects newest synchronized radar-aligned data")
    parser.add_argument("--lookback-minutes", type=int, default=180)
    parser.add_argument("--minimum-completeness", type=float, default=0.80)
    parser.add_argument("--maximum-latency-minutes", type=int, default=45)
    parser.add_argument("--seam-band-degrees", type=float, default=DEFAULT_SEAM_BAND_DEGREES)
    parser.add_argument("--resolution-degrees", type=float, default=DEFAULT_RESOLUTION_DEGREES)
    parser.add_argument("--download-workers", type=int, default=10)
    parser.add_argument("--maximum-render-dimension", type=int, default=6000)
    parser.add_argument("--maximum-event-points", type=int, default=5000)
    parser.add_argument("--maximum-flash-centroids", type=int, default=3000)
    parser.add_argument("--cache-dir", default=".glm_mosaic_cache")
    parser.add_argument("--output-dir", default="glm_operational_staging")
    parser.add_argument("--publish-debug-layers", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--keep-downloads", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    return parser.parse_args()


def validate_args(args: argparse.Namespace) -> None:
    if not (0 < args.minimum_completeness <= 1):
        raise SystemExit("--minimum-completeness must be in (0, 1]")
    if args.lookback_minutes < 0 or args.maximum_latency_minutes < 0:
        raise SystemExit("lookback and maximum latency must be nonnegative")
    if args.resolution_degrees <= 0 or args.seam_band_degrees <= 0:
        raise SystemExit("resolution and seam band must be positive")
    # Reuse the existing cache/product functions without maintaining duplicate knobs.
    args.minimum_slot_completeness = args.minimum_completeness
    args.minimum_window_completeness = args.minimum_completeness


def main() -> int:
    args = parse_args()
    if args.self_test:
        self_test()
        return 0
    validate_args(args)

    output_dir = Path(args.output_dir).resolve()
    cache_root = Path(args.cache_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    cache_root.mkdir(parents=True, exist_ok=True)
    grid = GridSpec(resolution=args.resolution_degrees)
    print(f"GLM grid: {grid.height} rows × {grid.width} columns")
    print(f"Persistent sparse cache: {cache_root}")

    client = build_s3_client()
    target_end, target_keys = resolve_target_end_time(
        client, args.analysis_time, args.lookback_minutes, args.minimum_completeness,
    )
    if not args.analysis_time.strip():
        latency = (utc_now() - target_end).total_seconds() / 60.0
        if latency > args.maximum_latency_minutes:
            raise RuntimeError(
                f"Newest synchronized GLM data are {latency:.1f} minutes old, exceeding "
                f"the {args.maximum_latency_minutes}-minute operational limit"
            )

    required_times = window_slot_times(target_end, 60)
    temporary_root = Path(tempfile.mkdtemp(prefix="glm_mosaic_incremental_"))
    slots_built = 0
    slots_hit = 0
    try:
        for slot_end in required_times:
            if slot_exists(cache_root, "G19", slot_end) and slot_exists(cache_root, "G18", slot_end):
                slots_hit += 1
                print(f"Cache hit for synchronized slot {iso_z(slot_end)}")
                continue
            if slot_end == target_end:
                keys_by_satellite = target_keys
            else:
                start_time = slot_end - timedelta(minutes=SLOT_MINUTES)
                keys_by_satellite = {
                    satellite: list_window_keys(client, config["bucket"], start_time, slot_end)
                    for satellite, config in SATELLITES.items()
                }
            minimum_files = math.ceil(EXPECTED_FILES_PER_SLOT * args.minimum_completeness)
            if any(len(keys_by_satellite[s]) < minimum_files for s in SATELLITES):
                print(
                    f"WARNING: skipping incomplete backfill slot {iso_z(slot_end)}: "
                    + ", ".join(f"{s}={len(keys_by_satellite[s])}/{EXPECTED_FILES_PER_SLOT}" for s in SATELLITES),
                    file=sys.stderr,
                )
                continue
            build_slot_pair(client, slot_end, keys_by_satellite, cache_root, temporary_root, grid, args)
            slots_built += 1

        prune_cache(cache_root, CACHE_SLOT_COUNT)
        common_times = common_cached_slot_times(cache_root)
        if target_end not in common_times:
            raise RuntimeError("Newest synchronized GLM slot was not successfully cached")
        common_set = set(common_times)

        # First generate the six separate satellite reference products from cache.
        results: dict[tuple[str, int], ProductResult] = {}
        arrays: dict[tuple[str, int], np.ndarray] = {}
        ordered_results: list[ProductResult] = []
        for satellite in ("G19", "G18"):
            for window in WINDOWS_MINUTES:
                result, array = create_product(
                    satellite, window, target_end, common_set,
                    cache_root, output_dir, grid, args,
                )
                results[(satellite, window)] = result
                arrays[(satellite, window)] = array
                ordered_results.append(result)

        # Preserve the validated controlled-mosaic publication interface.
        owner, geometry = build_source_ownership(grid)
        ownership_metadata = create_source_ownership_products(
            owner, geometry, grid, output_dir, args,
        )
        mosaic_metadata: list[dict] = []
        mosaic_arrays: dict[int, np.ndarray] = {}
        for window in WINDOWS_MINUTES:
            metadata, mosaic = create_controlled_mosaic_product(
                window, target_end,
                arrays[("G18", window)], arrays[("G19", window)],
                results[("G18", window)], results[("G19", window)],
                owner, geometry, grid, output_dir, args,
            )
            mosaic_metadata.append(metadata)
            mosaic_arrays[window] = mosaic

        if np.any(mosaic_arrays[60] < mosaic_arrays[30]) or np.any(mosaic_arrays[30] < mosaic_arrays[5]):
            raise RuntimeError("Rolling mosaic monotonicity validation failed")

        # Artifact-only radar and raw-event diagnostics.
        debug_payloads = [
            build_debug_outputs(satellite, target_end, cache_root, output_dir, grid, args)
            for satellite in ("G19", "G18")
        ]
        generated_time = iso_z(utc_now())
        debug_html = output_dir / "glm_mosaic_incremental_debug.html"
        write_debug_html(debug_html, ordered_results, debug_payloads, generated_time, target_end)

        summary_path = output_dir / "glm_mosaic_summary.csv"
        with summary_path.open("w", newline="", encoding="utf-8") as handle:
            fieldnames = [
                "window_minutes", "window_start_utc", "window_end_utc", "maximum_value",
                "nonzero_grid_cells", "flash_cell_contributions",
                "g18_processed_files", "g18_expected_files", "g18_completeness_fraction",
                "g19_processed_files", "g19_expected_files", "g19_completeness_fraction",
                "g18_available_slots", "g19_available_slots",
            ]
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for metadata in mosaic_metadata:
                g18 = metadata["satellite_inputs"]["G18"]
                g19 = metadata["satellite_inputs"]["G19"]
                writer.writerow({
                    "window_minutes": metadata["window_minutes"],
                    "window_start_utc": metadata["window_start_utc"],
                    "window_end_utc": metadata["window_end_utc"],
                    "maximum_value": metadata["maximum_value"],
                    "nonzero_grid_cells": metadata["nonzero_grid_cells"],
                    "flash_cell_contributions": metadata["flash_cell_contributions"],
                    "g18_processed_files": g18["processed_files"],
                    "g18_expected_files": g18["expected_files"],
                    "g18_completeness_fraction": g18["completeness_fraction"],
                    "g19_processed_files": g19["processed_files"],
                    "g19_expected_files": g19["expected_files"],
                    "g19_completeness_fraction": g19["completeness_fraction"],
                    "g18_available_slots": g18["available_slots"],
                    "g19_available_slots": g19["available_slots"],
                })

        manifest_path = output_dir / "glm_mosaic_manifest.json"
        manifest = {
            "metadata_mode": "glm_dashboard_v1",
            "product": "Incremental operational GOES GLM controlled CONUS mosaic package",
            "window_end_utc": iso_z(target_end),
            "windows_minutes": list(WINDOWS_MINUTES),
            "mosaic_method": {
                "name": "exclusive lower-view-angle source ownership",
                "summation": False,
                "averaging": False,
                "blending": False,
                "secondary_source_gap_fill": False,
                "satellite_geometry": geometry,
            },
            "incremental_cache": {
                "slot_minutes": SLOT_MINUTES,
                "retained_synchronized_slots": [iso_z(value) for value in common_times],
                "retained_slot_count": len(common_times),
                "cache_hits_this_run": slots_hit,
                "new_slots_built_this_run": slots_built,
                "expected_lcfa_files_per_slot_per_satellite": EXPECTED_FILES_PER_SLOT,
                "cache_directory": str(cache_root),
            },
            "radar_coordination": {
                "wms_endpoint": "https://mesonet.agron.iastate.edu/cgi-bin/wms/nexrad/n0q-t.cgi",
                "wms_layer": "nexrad-n0q-wmst",
                "frame_interval_minutes": 10,
                "comparison_time_utc": iso_z(floor_to_ten_minutes(target_end)),
                "artifact_debug_html": debug_html.name,
            },
            "mosaic_products": mosaic_metadata,
            "satellite_reference_products": [asdict(result) for result in ordered_results],
            "source_ownership": ownership_metadata,
            "publish_debug_layers": args.publish_debug_layers,
            "artifact_only_diagnostics": [
                debug_html.name,
                "glm_g18_debug_event_density_5min.png",
                "glm_g18_debug_footprint_5min.png",
                "glm_g18_debug_event_sample_5min.geojson",
                "glm_g18_debug_flash_centroids_5min.geojson",
                "glm_g19_debug_event_density_5min.png",
                "glm_g19_debug_footprint_5min.png",
                "glm_g19_debug_event_sample_5min.geojson",
                "glm_g19_debug_flash_centroids_5min.geojson",
            ],
            "summary_csv": summary_path.name,
            "generated_time_utc": generated_time,
        }
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        print("\nIncremental operational GLM outputs:")
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
        else:
            shutil.rmtree(temporary_root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
