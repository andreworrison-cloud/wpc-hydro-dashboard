#!/usr/bin/env python3
"""Diagnostic GOES GLM 30- and 60-minute rolling flash-extent fields.

This script reads public NOAA GLM-L2-LCFA files from the GOES-19 and
GOES-18 AWS Open Data buckets. It processes each LCFA file once, derives
an LCFA-file flash extent density contribution, and accumulates those
contributions over synchronized rolling 30- and 60-minute windows.

GOES-19 and GOES-18 remain separate validation layers. The output is
artifact-only and does not modify a dashboard repository.
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
    "G19": {"bucket": "noaa-goes19", "label": "GOES-19 (East)"},
    "G18": {"bucket": "noaa-goes18", "label": "GOES-18 (West)"},
}

WEST = -130.0
EAST = -60.0
SOUTH = 20.0
NORTH = 55.0
DEFAULT_RESOLUTION_DEGREES = 0.02
ROLLING_WINDOWS_MINUTES = (30, 60)
MAX_WINDOW_MINUTES = max(ROLLING_WINDOWS_MINUTES)
CANDIDATE_STEP_MINUTES = 5
LCFA_FILES_PER_MINUTE = 3  # one file every 20 seconds

# Expanded diagnostic scale. The canned case will tell us whether the upper
# bins need further tuning before operational use.
ACCUM_BINS = [1, 2, 4, 8, 16, 32, 64, 128]
ACCUM_LABELS = ["1", "2–3", "4–7", "8–15", "16–31", "32–63", "64–127", "≥128"]
ACCUM_RGBA = [
    (0, 255, 255, 210),
    (0, 255, 0, 210),
    (255, 255, 0, 220),
    (255, 153, 0, 225),
    (255, 0, 0, 230),
    (255, 0, 255, 235),
    (199, 125, 255, 240),
    (255, 255, 255, 248),
]

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


@dataclass
class FileStats:
    file_name: str
    file_start_utc: str
    flashes_quality_controlled: int
    events_mapped_to_good_flashes: int
    events_in_domain: int
    flash_cell_contributions: int
    included_30min: bool
    included_60min: bool


@dataclass
class RollingResult:
    satellite: str
    satellite_label: str
    bucket: str
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
    maximum_accumulation: int
    native_geotiff: str
    leaflet_png: str
    metadata_json: str
    image_crs: str
    leaflet_bounds: list[list[float]]
    rendered_shape: list[int]


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
    count = 0
    for key in keys:
        key_time = key_start_time(key)
        if key_time is not None and start <= key_time < end:
            count += 1
    return count


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
            for window_minutes in ROLLING_WINDOWS_MINUTES:
                start = end - timedelta(minutes=window_minutes)
                listed = count_keys_in_window(keys, start, end)
                minimum = math.ceil(expected_files(window_minutes) * minimum_completeness)
                counts.append(f"{window_minutes}m={listed}/{expected_files(window_minutes)}")
                if listed < minimum:
                    complete = False
            detail_parts.append(f"{satellite} " + ", ".join(counts))

        attempts.append(f"end {iso_z(end)} ({'; '.join(detail_parts)})")
        if complete:
            print(f"Resolved common GLM rolling end time: {attempts[-1]}")
            return end, keys_by_satellite

        if requested_end.strip():
            break

    detail = "\n  ".join(attempts[:12])
    raise RuntimeError(
        "Could not find a common GOES-19/GOES-18 rolling window meeting "
        f"minimum completeness {minimum_completeness:.0%}.\n"
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


def write_native_geotiff(
    array: np.ndarray,
    grid: GridSpec,
    output_path: Path,
    window_minutes: int,
) -> None:
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
        destination.update_tags(
            product=f"LCFA-derived GLM rolling {window_minutes}-minute flash extent accumulation",
            units=f"flash extent contributions per grid cell per {window_minutes} minutes",
            zero_value="valid no-flash value",
        )


def render_web_mercator(
    array: np.ndarray,
    grid: GridSpec,
    output_path: Path,
    maximum_dimension: int,
) -> tuple[list[list[float]], list[int], dict[str, float]]:
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
    for index, lower in enumerate(ACCUM_BINS):
        upper = ACCUM_BINS[index + 1] if index + 1 < len(ACCUM_BINS) else None
        mask = destination >= lower
        if upper is not None:
            mask &= destination < upper
        rgba[mask] = ACCUM_RGBA[index]
    Image.fromarray(rgba, mode="RGBA").save(output_path, optimize=True)

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
    return leaflet_bounds, [dst_height, dst_width], transform_values


def nonzero_percentiles(array: np.ndarray) -> dict[str, float]:
    values = array[array > 0]
    if values.size == 0:
        return {name: 0.0 for name in ("p50", "p75", "p90", "p95", "p99", "p99_5", "p99_9")}
    requested = [50, 75, 90, 95, 99, 99.5, 99.9]
    computed = np.percentile(values.astype(np.float64), requested)
    names = ["p50", "p75", "p90", "p95", "p99", "p99_5", "p99_9"]
    return {name: float(value) for name, value in zip(names, computed)}


def bin_counts(array: np.ndarray) -> dict[str, int]:
    result: dict[str, int] = {}
    for index, lower in enumerate(ACCUM_BINS):
        upper = ACCUM_BINS[index + 1] if index + 1 < len(ACCUM_BINS) else None
        mask = array >= lower
        if upper is not None:
            mask &= array < upper
        result[ACCUM_LABELS[index]] = int(np.count_nonzero(mask))
    return result


def png_data_uri(path: Path) -> str:
    return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def html_escape_json(value) -> str:
    return json.dumps(value, separators=(",", ":"))


def write_interactive_html(
    output_path: Path,
    results: Sequence[RollingResult],
    generated_time: str,
) -> None:
    overlays = []
    for result in results:
        image_path = output_path.parent / result.leaflet_png
        overlays.append(
            {
                "name": (
                    f"{result.satellite_label} — "
                    f"{result.window_minutes}-min rolling accumulation"
                ),
                "dataUri": png_data_uri(image_path),
                "bounds": result.leaflet_bounds,
                "metadata": asdict(result),
            }
        )

    color_blocks = "".join(
        f'<span class="legend-bin" style="background:rgba({r},{g},{b},{a/255:.3f})">'
        f"{label}</span>"
        for label, (r, g, b, a) in zip(ACCUM_LABELS, ACCUM_RGBA)
    )

    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>GOES GLM 30/60-Minute Rolling Diagnostic</title>
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
  <style>
    html, body, #map {{ height: 100%; margin: 0; }}
    body {{ font-family: Arial, sans-serif; }}
    .panel {{ background: rgba(20,24,30,.94); color: white; padding: 10px 12px; border-radius: 6px; line-height: 1.35; max-width: 440px; box-shadow: 0 1px 8px rgba(0,0,0,.45); }}
    .panel h3 {{ margin: 0 0 6px; font-size: 15px; }}
    .panel small {{ color: #d5d9df; }}
    .legend-row {{ display: flex; border: 1px solid #333; margin-top: 6px; }}
    .legend-bin {{ flex: 1; color: #111; text-align: center; padding: 3px 4px; font-size: 10px; font-weight: 700; min-width: 38px; }}
    .metadata-table {{ width: 100%; border-collapse: collapse; margin-top: 6px; font-size: 11px; }}
    .metadata-table td {{ padding: 2px 4px; vertical-align: top; border-top: 1px solid rgba(255,255,255,.12); }}
    .metadata-table td:first-child {{ color: #a9c9ff; white-space: nowrap; }}
    .warning {{ color: #ffd166; font-weight: 700; margin-top: 5px; }}
  </style>
</head>
<body>
<div id="map"></div>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
const overlays = {html_escape_json(overlays)};
const map = L.map('map', {{ center: [38.5, -97.0], zoom: 4 }});
const dark = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{{z}}/{{y}}/{{x}}', {{ maxZoom: 16, attribution: 'Tiles © Esri' }}).addTo(map);
const darkLabels = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Reference/MapServer/tile/{{z}}/{{y}}/{{x}}', {{ maxZoom: 16 }}).addTo(map);
const osm = L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{ maxZoom: 19, attribution: '© OpenStreetMap contributors' }});
const topo = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{{z}}/{{y}}/{{x}}', {{ maxZoom: 19, attribution: 'Tiles © Esri' }});
const imagery = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{{z}}/{{y}}/{{x}}', {{ maxZoom: 19, attribution: 'Tiles © Esri' }});

const layerMap = {{}};
overlays.forEach((item, index) => {{
  const layer = L.imageOverlay(item.dataUri, item.bounds, {{ opacity: 0.88, interactive: false }});
  layerMap[item.name] = layer;
  if (index === 0) layer.addTo(map);
}});
L.control.layers(
  {{ 'Esri Dark Gray': dark, 'OpenStreetMap': osm, 'Esri Topographic': topo, 'Esri Imagery': imagery }},
  layerMap,
  {{ collapsed: false }}
).addTo(map);

map.on('baselayerchange', e => {{
  if (map.hasLayer(darkLabels)) map.removeLayer(darkLabels);
  if (e.name === 'Esri Dark Gray') darkLabels.addTo(map);
}});

fetch('https://raw.githubusercontent.com/PublicaMundi/MappingAPI/master/data/geojson/us-states.json')
  .then(r => r.json())
  .then(data => L.geoJSON(data, {{ style: {{ color: '#ffffff', weight: 1, fillOpacity: 0 }}, interactive: false }}).addTo(map))
  .catch(() => {{}});

const info = L.control({{ position: 'topright' }});
info.onAdd = () => {{
  const div = L.DomUtil.create('div', 'panel');
  const rows = overlays.map(item => {{
    const m = item.metadata;
    return `<tr><td>${{m.satellite}} ${{m.window_minutes}}m</td><td>${{m.window_start_utc}} – ${{m.window_end_utc}}<br>${{m.processed_files}}/${{m.expected_files}} files (${{(m.completeness_fraction*100).toFixed(0)}}%); max ${{m.maximum_accumulation}}</td></tr>`;
  }}).join('');
  div.innerHTML = `<h3>GOES GLM 30/60-Minute Rolling Diagnostic</h3>
    <small>LCFA-file flash extent contributions accumulated over synchronized rolling windows.</small>
    <table class="metadata-table">${{rows}}</table>
    <div class="warning">GOES-19 and GOES-18 remain separate. Do not add overlapping satellite layers together.</div>
    <small>Generated: {generated_time}</small>`;
  L.DomEvent.disableClickPropagation(div);
  return div;
}};
info.addTo(map);

const legend = L.control({{ position: 'bottomright' }});
legend.onAdd = () => {{
  const div = L.DomUtil.create('div', 'panel');
  div.innerHTML = `<strong>Accumulated flash extent contributions / 0.02° grid cell</strong><div class="legend-row">{color_blocks}</div>`;
  return div;
}};
legend.addTo(map);
</script>
</body>
</html>
"""
    output_path.write_text(html, encoding="utf-8")


def write_summary_csv(output_path: Path, results: Sequence[RollingResult]) -> None:
    rows = [asdict(result) for result in results]
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def process_satellite(
    client,
    satellite: str,
    keys: Sequence[str],
    end_time: datetime,
    output_dir: Path,
    working_dir: Path,
    grid: GridSpec,
    workers: int,
    maximum_render_dimension: int,
    minimum_completeness: float,
) -> list[RollingResult]:
    config = SATELLITES[satellite]
    satellite_dir = working_dir / satellite.lower()
    downloaded = download_keys(client, config["bucket"], keys, satellite_dir, workers)
    if not downloaded:
        raise RuntimeError(f"No {satellite} LCFA files downloaded")

    aggregates = {
        window: np.zeros((grid.height, grid.width), dtype=np.uint32)
        for window in ROLLING_WINDOWS_MINUTES
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
            for window in ROLLING_WINDOWS_MINUTES
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
                included_30min=included[30],
                included_60min=included[60],
            )
        )

    if not file_stats:
        raise RuntimeError(f"No usable {satellite} LCFA files were processed")

    per_file_csv = output_dir / f"glm_{satellite.lower()}_fed_rolling_files.csv"
    with per_file_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(asdict(file_stats[0]).keys()))
        writer.writeheader()
        for stats in file_stats:
            writer.writerow(asdict(stats))

    results: list[RollingResult] = []
    for window in ROLLING_WINDOWS_MINUTES:
        start_time = end_time - timedelta(minutes=window)
        listed_files = count_keys_in_window(keys, start_time, end_time)
        included_stats = [
            stats
            for stats in file_stats
            if (stats.included_30min if window == 30 else stats.included_60min)
        ]
        processed_files = len(included_stats)
        expected = expected_files(window)
        completeness = processed_files / expected
        if completeness < minimum_completeness:
            raise RuntimeError(
                f"{satellite} {window}-minute processed completeness "
                f"{processed_files}/{expected} ({completeness:.1%}) is below "
                f"the required {minimum_completeness:.1%}."
            )

        aggregate = aggregates[window]
        stem = f"glm_{satellite.lower()}_fed_{window}min"
        geotiff_path = output_dir / f"{stem}.tif"
        png_path = output_dir / f"{stem}.png"
        metadata_path = output_dir / f"{stem}_metadata.json"

        write_native_geotiff(aggregate, grid, geotiff_path, window)
        leaflet_bounds, rendered_shape, rendered_transform = render_web_mercator(
            aggregate, grid, png_path, maximum_render_dimension
        )

        result = RollingResult(
            satellite=satellite,
            satellite_label=config["label"],
            bucket=config["bucket"],
            window_minutes=window,
            window_start_utc=iso_z(start_time),
            window_end_utc=iso_z(end_time),
            expected_files=expected,
            listed_files=listed_files,
            processed_files=processed_files,
            completeness_fraction=completeness,
            quality_controlled_flash_records=sum(
                stats.flashes_quality_controlled for stats in included_stats
            ),
            events_mapped_to_good_flashes=sum(
                stats.events_mapped_to_good_flashes for stats in included_stats
            ),
            events_in_domain=sum(stats.events_in_domain for stats in included_stats),
            flash_cell_contributions=sum(
                stats.flash_cell_contributions for stats in included_stats
            ),
            nonzero_grid_cells=int(np.count_nonzero(aggregate)),
            maximum_accumulation=int(aggregate.max(initial=0)),
            native_geotiff=geotiff_path.name,
            leaflet_png=png_path.name,
            metadata_json=metadata_path.name,
            image_crs="EPSG:3857",
            leaflet_bounds=leaflet_bounds,
            rendered_shape=rendered_shape,
        )

        metadata = {
            **asdict(result),
            "product": (
                f"Diagnostic LCFA-derived GLM rolling {window}-minute "
                "flash extent accumulation"
            ),
            "source_product": PRODUCT_PREFIX,
            "methodology": (
                "Each LCFA file is processed independently. Within a file, each "
                "quality-controlled flash contributes one count to every 0.02-degree "
                "grid cell containing at least one constituent event. File-level "
                "contributions are then summed over the rolling window."
            ),
            "quality_control": (
                "flash_quality_flag == 0 and group_quality_flag == 0 when present; "
                "packed event coordinates honor _Unsigned before scale_factor and "
                "add_offset"
            ),
            "important_note": (
                "This is an LCFA-derived diagnostic accumulation, not the official NOAA "
                "gridded FED product. GOES-19 and GOES-18 overlap detections are not "
                "deduplicated and must not be added together."
            ),
            "units": (
                f"flash extent contributions per 0.02-degree grid cell per {window} minutes"
            ),
            "nonzero_percentiles": nonzero_percentiles(aggregate),
            "render_bin_counts": bin_counts(aggregate),
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
                "bins": ACCUM_BINS,
                "labels": ACCUM_LABELS,
                "rgba": ACCUM_RGBA,
            },
            "generated_time_utc": iso_z(utc_now()),
        }
        metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        results.append(result)

    return results


def self_test() -> None:
    grid = GridSpec(west=-100.0, east=-99.0, south=30.0, north=31.0, resolution=0.1)

    expected_lon = np.array([-99.95, -99.94, -99.85, -99.96], dtype=np.float64)
    expected_lat = np.array([30.95, 30.94, 30.95, 30.96], dtype=np.float64)
    scale = 0.002
    packed_lon_u16 = np.rint((expected_lon + 180.0) / scale).astype(np.uint16)
    packed_lat_u16 = np.rint((expected_lat + 90.0) / scale).astype(np.uint16)

    group_ids_u32 = np.array([0xF0000001, 0xF0000002, 0xF0000003], dtype=np.uint32)
    flash_ids_u32 = np.array([0xE0000001, 0xE0000002], dtype=np.uint32)

    dataset = xr.Dataset(
        data_vars={
            "event_lat": xr.DataArray(
                packed_lat_u16.view(np.int16),
                dims=("event",),
                attrs={"_Unsigned": "true", "scale_factor": scale, "add_offset": -90.0},
            ),
            "event_lon": xr.DataArray(
                packed_lon_u16.view(np.int16),
                dims=("event",),
                attrs={"_Unsigned": "true", "scale_factor": scale, "add_offset": -180.0},
            ),
            "event_parent_group_id": xr.DataArray(
                np.array(
                    [group_ids_u32[0], group_ids_u32[0], group_ids_u32[1], group_ids_u32[2]],
                    dtype=np.uint32,
                ).view(np.int32),
                dims=("event",),
                attrs={"_Unsigned": "true"},
            ),
            "group_id": xr.DataArray(
                group_ids_u32.view(np.int32),
                dims=("group",),
                attrs={"_Unsigned": "true"},
            ),
            "group_parent_flash_id": xr.DataArray(
                np.array(
                    [flash_ids_u32[0], flash_ids_u32[0], flash_ids_u32[1]],
                    dtype=np.uint32,
                ).view(np.int32),
                dims=("group",),
                attrs={"_Unsigned": "true"},
            ),
            "flash_id": xr.DataArray(
                flash_ids_u32.view(np.int32),
                dims=("flash",),
                attrs={"_Unsigned": "true"},
            ),
            "flash_quality_flag": xr.DataArray(np.zeros(2, dtype=np.int8), dims=("flash",)),
            "group_quality_flag": xr.DataArray(np.zeros(3, dtype=np.int8), dims=("group",)),
        }
    )

    event_lat, event_lon, event_flash, good_flash_count = map_events_to_flashes(dataset)
    assert good_flash_count == 2
    assert np.allclose(event_lat, expected_lat, atol=scale / 2)
    assert np.allclose(event_lon, expected_lon, atol=scale / 2)

    columns = np.floor((event_lon - grid.west) / grid.resolution).astype(np.int64)
    rows = np.floor((grid.north - event_lat) / grid.resolution).astype(np.int64)
    cells = rows * grid.width + columns
    unique_flashes, local = np.unique(event_flash, return_inverse=True)
    combined = cells * unique_flashes.size + local
    unique_cells = np.unique(combined) // unique_flashes.size
    field = np.bincount(unique_cells, minlength=grid.height * grid.width).reshape(
        grid.height, grid.width
    )
    assert field.flat[int(cells[0])] == 2
    assert field.flat[int(cells[2])] == 1
    assert int(field.sum()) == 3

    end = parse_utc("2026-07-21T21:00:00Z")
    starts = [
        end - timedelta(minutes=59, seconds=40),
        end - timedelta(minutes=29, seconds=40),
        end - timedelta(seconds=20),
    ]
    assert sum(end - timedelta(minutes=30) <= value < end for value in starts) == 2
    assert sum(end - timedelta(minutes=60) <= value < end for value in starts) == 3
    assert expected_files(30) == 90
    assert expected_files(60) == 180

    synthetic = np.array([[0, 1, 2, 4, 8, 16, 32, 64, 128]], dtype=np.uint16)
    counts = bin_counts(synthetic)
    assert counts["1"] == 1 and counts["≥128"] == 1

    print("GLM 30/60-minute rolling packed-coordinate and accumulation self-test passed.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--analysis-time",
        default="",
        help=(
            "UTC rolling-window ending time, e.g. 2026-07-21T21:00:00Z. "
            "Blank selects the newest common GOES-19/GOES-18 end time."
        ),
    )
    parser.add_argument("--lookback-minutes", type=int, default=180)
    parser.add_argument("--minimum-completeness", type=float, default=0.80)
    parser.add_argument("--resolution-degrees", type=float, default=DEFAULT_RESOLUTION_DEGREES)
    parser.add_argument("--download-workers", type=int, default=10)
    parser.add_argument("--maximum-render-dimension", type=int, default=6000)
    parser.add_argument("--output-dir", default="glm_rolling_diagnostic_output")
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

    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    grid = GridSpec(resolution=args.resolution_degrees)
    print(f"Diagnostic grid: {grid.height} rows × {grid.width} columns")

    client = build_s3_client()
    end_time, keys_by_satellite = resolve_common_end_time(
        client,
        args.analysis_time,
        args.lookback_minutes,
        args.minimum_completeness,
    )

    temporary_root = Path(tempfile.mkdtemp(prefix="glm_rolling_"))
    try:
        results: list[RollingResult] = []
        for satellite in ("G19", "G18"):
            results.extend(
                process_satellite(
                    client=client,
                    satellite=satellite,
                    keys=keys_by_satellite[satellite],
                    end_time=end_time,
                    output_dir=output_dir,
                    working_dir=temporary_root,
                    grid=grid,
                    workers=args.download_workers,
                    maximum_render_dimension=args.maximum_render_dimension,
                    minimum_completeness=args.minimum_completeness,
                )
            )

        results.sort(key=lambda item: (item.satellite, item.window_minutes), reverse=False)
        # Keep the preferred display order: GOES-19 30/60, then GOES-18 30/60.
        results.sort(key=lambda item: ((0 if item.satellite == "G19" else 1), item.window_minutes))

        generated_time = iso_z(utc_now())
        summary_path = output_dir / "glm_fed_rolling_30_60min_summary.csv"
        html_path = output_dir / "glm_fed_rolling_30_60min_diagnostic.html"
        write_summary_csv(summary_path, results)
        write_interactive_html(html_path, results, generated_time)

        manifest = {
            "product": "GOES GLM rolling 30- and 60-minute diagnostic package",
            "window_end_utc": iso_z(end_time),
            "windows_minutes": list(ROLLING_WINDOWS_MINUTES),
            "satellites": [asdict(result) for result in results],
            "interactive_html": html_path.name,
            "summary_csv": summary_path.name,
            "generated_time_utc": generated_time,
        }
        (output_dir / "glm_fed_rolling_30_60min_manifest.json").write_text(
            json.dumps(manifest, indent=2), encoding="utf-8"
        )

        print("\nDiagnostic outputs:")
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
