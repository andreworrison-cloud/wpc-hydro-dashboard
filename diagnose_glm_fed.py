#!/usr/bin/env python3
"""Diagnostic GOES GLM five-minute flash extent density generator.

This script reads public NOAA GLM-L2-LCFA files from the GOES-19 and
GOES-18 AWS Open Data buckets. It derives a regular-grid flash extent
density field by counting each quality-controlled flash once in every
grid cell containing at least one constituent GLM event.

The output is intended for scientific/visual validation before any
operational dashboard integration. It does not modify a repository.
"""

from __future__ import annotations

import argparse
import base64
import csv
import json
import math
import os
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
    },
    "G18": {
        "bucket": "noaa-goes18",
        "label": "GOES-18 (West)",
    },
}

# Diagnostic CONUS domain. This intentionally matches the broad dashboard view.
WEST = -130.0
EAST = -60.0
SOUTH = 20.0
NORTH = 55.0
DEFAULT_RESOLUTION_DEGREES = 0.02
WINDOW_MINUTES = 5
EXPECTED_FILES_PER_WINDOW = 15  # one LCFA file every 20 seconds

# Lower bounds and colors for 5-minute LCFA-derived FED.
FED_BINS = [1, 2, 4, 8, 16, 32, 64]
FED_LABELS = ["1", "2–3", "4–7", "8–15", "16–31", "32–63", "≥64"]
FED_RGBA = [
    (0, 255, 255, 210),   # cyan
    (0, 255, 0, 210),     # green
    (255, 255, 0, 220),   # yellow
    (255, 153, 0, 225),   # orange
    (255, 0, 0, 230),     # red
    (255, 0, 255, 235),   # magenta
    (255, 255, 255, 245), # white
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
        return from_origin(
            self.west,
            self.north,
            self.resolution,
            self.resolution,
        )


@dataclass
class FileStats:
    file_name: str
    flashes_quality_controlled: int
    events_mapped_to_good_flashes: int
    events_in_domain: int
    flash_cell_contributions: int


@dataclass
class SatelliteResult:
    satellite: str
    satellite_label: str
    bucket: str
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
    maximum_fed: int
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


def floor_to_window(value: datetime, minutes: int = WINDOW_MINUTES) -> datetime:
    value = value.astimezone(UTC).replace(second=0, microsecond=0)
    return value.replace(minute=(value.minute // minutes) * minutes)


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
        minute=0,
        second=0,
        microsecond=0,
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


def resolve_common_window(
    client,
    requested_end: str,
    lookback_minutes: int,
    minimum_completeness: float,
) -> tuple[datetime, datetime, dict[str, list[str]]]:
    minimum_files = math.ceil(EXPECTED_FILES_PER_WINDOW * minimum_completeness)
    if requested_end.strip():
        end = floor_to_window(parse_utc(requested_end))
        candidates = [end]
    else:
        newest = floor_to_window(utc_now())
        candidates = [
            newest - timedelta(minutes=offset)
            for offset in range(0, lookback_minutes + 1, WINDOW_MINUTES)
        ]

    attempts: list[str] = []
    for end in candidates:
        start = end - timedelta(minutes=WINDOW_MINUTES)
        keys_by_satellite: dict[str, list[str]] = {}
        complete = True
        parts: list[str] = []
        for satellite, config in SATELLITES.items():
            keys = list_window_keys(client, config["bucket"], start, end)
            keys_by_satellite[satellite] = keys
            parts.append(f"{satellite}={len(keys)}")
            if len(keys) < minimum_files:
                complete = False
        attempts.append(f"{iso_z(start)}–{iso_z(end)} ({', '.join(parts)})")
        if complete:
            print(f"Resolved common GLM window: {attempts[-1]}")
            return start, end, keys_by_satellite

        if requested_end.strip():
            break

    detail = "\n  ".join(attempts[:12])
    raise RuntimeError(
        "Could not find a common GOES-19/GOES-18 five-minute window "
        f"meeting minimum completeness {minimum_completeness:.0%}.\n"
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
    completed.sort()
    return completed


def values(dataset: xr.Dataset, name: str, required: bool = True) -> np.ndarray | None:
    if name not in dataset.variables:
        if required:
            raise KeyError(f"Required LCFA variable missing: {name}")
        return None
    return np.asarray(dataset[name].values)


def _unsigned_requested(variable: xr.DataArray) -> bool:
    return str(variable.attrs.get("_Unsigned", "false")).strip().lower() == "true"


def _reinterpret_unsigned(raw: np.ndarray, variable: xr.DataArray) -> np.ndarray:
    """Honor the GOES-R NetCDF _Unsigned convention without changing bytes."""
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
        candidates = np.asarray(variable.attrs[key]).reshape(-1)
        for candidate in candidates:
            try:
                mask |= raw == candidate
            except (TypeError, ValueError):
                pass
    return mask


def science_values(dataset: xr.Dataset, name: str) -> np.ndarray:
    """Decode a packed GOES-R science variable into physical units.

    GOES-R LCFA event latitude and longitude are packed integers. NOAA
    specifies that _Unsigned must be applied before scale_factor/add_offset.
    The dataset is opened with mask_and_scale=False so identifiers remain
    exact; this helper performs the required decoding only for science fields.
    """
    if name not in dataset.variables:
        raise KeyError(f"Required LCFA variable missing: {name}")
    variable = dataset[name]
    raw = np.asarray(variable.values)
    missing = _missing_mask(raw, variable)
    unpacked = _reinterpret_unsigned(raw, variable).astype(np.float64, copy=False)
    scale = float(np.asarray(variable.attrs.get("scale_factor", 1.0)).reshape(-1)[0])
    offset = float(np.asarray(variable.attrs.get("add_offset", 0.0)).reshape(-1)[0])
    decoded = unpacked * scale + offset
    decoded = np.asarray(decoded, dtype=np.float64)
    decoded[missing] = np.nan
    return decoded


def identifier_values(dataset: xr.Dataset, name: str) -> np.ndarray:
    """Read an identifier exactly while honoring the GOES-R _Unsigned flag."""
    if name not in dataset.variables:
        raise KeyError(f"Required LCFA variable missing: {name}")
    variable = dataset[name]
    raw = np.asarray(variable.values)
    unpacked = _reinterpret_unsigned(raw, variable)
    return unpacked.astype(np.int64, copy=False)


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

    # Keep only good groups whose parent flash also passed quality control.
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


def accumulate_file_fed(path: Path, grid: GridSpec) -> tuple[np.ndarray, FileStats]:
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
        return counts, FileStats(path.name, good_flash_count, mapped_event_count, 0, 0)

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

    return counts, FileStats(
        file_name=path.name,
        flashes_quality_controlled=good_flash_count,
        events_mapped_to_good_flashes=mapped_event_count,
        events_in_domain=int(event_lat.size),
        flash_cell_contributions=int(unique_pairs.size),
    )


def write_native_geotiff(array: np.ndarray, grid: GridSpec, output_path: Path) -> None:
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
            product="LCFA-derived GLM five-minute flash extent density",
            units="flashes per grid cell per five minutes",
            zero_value="valid no-flash value",
        )


def render_web_mercator(
    array: np.ndarray,
    grid: GridSpec,
    output_path: Path,
    maximum_dimension: int,
) -> tuple[list[list[float]], list[int], dict[str, float]]:
    src_transform = grid.transform
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
        src_transform=src_transform,
        src_crs="EPSG:4326",
        dst_transform=dst_transform,
        dst_crs="EPSG:3857",
        resampling=Resampling.nearest,
    )

    rgba = np.zeros((dst_height, dst_width, 4), dtype=np.uint8)
    for index, lower in enumerate(FED_BINS):
        upper = FED_BINS[index + 1] if index + 1 < len(FED_BINS) else None
        mask = destination >= lower
        if upper is not None:
            mask &= destination < upper
        rgba[mask] = FED_RGBA[index]
    Image.fromarray(rgba, mode="RGBA").save(output_path, optimize=True)

    mercator_bounds = array_bounds(dst_height, dst_width, dst_transform)
    lonlat_bounds = transform_bounds(
        "EPSG:3857",
        "EPSG:4326",
        *mercator_bounds,
        densify_pts=21,
    )
    west, south, east, north = lonlat_bounds
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


def png_data_uri(path: Path) -> str:
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def html_escape_json(value) -> str:
    return json.dumps(value, separators=(",", ":"))


def write_interactive_html(
    output_path: Path,
    results: Sequence[SatelliteResult],
    generated_time: str,
) -> None:
    overlays = []
    for result in results:
        image_path = output_path.parent / result.leaflet_png
        overlays.append(
            {
                "name": f"{result.satellite_label} — 5-min FED",
                "dataUri": png_data_uri(image_path),
                "bounds": result.leaflet_bounds,
                "metadata": asdict(result),
            }
        )

    color_blocks = "".join(
        f'<span class="legend-bin" style="background:rgba({r},{g},{b},{a/255:.3f})">'
        f"{label}</span>"
        for label, (r, g, b, a) in zip(FED_LABELS, FED_RGBA)
    )

    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>GOES GLM 5-Minute FED Diagnostic</title>
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
  <style>
    html, body, #map {{ height: 100%; margin: 0; }}
    body {{ font-family: Arial, sans-serif; }}
    .panel {{ background: rgba(20, 24, 30, 0.94); color: white; padding: 10px 12px; border-radius: 6px; line-height: 1.35; max-width: 390px; box-shadow: 0 1px 8px rgba(0,0,0,.45); }}
    .panel h3 {{ margin: 0 0 6px; font-size: 15px; }}
    .panel small {{ color: #d5d9df; }}
    .legend-row {{ display: flex; border: 1px solid #333; margin-top: 6px; }}
    .legend-bin {{ flex: 1; color: #111; text-align: center; padding: 3px 4px; font-size: 11px; font-weight: 700; min-width: 34px; }}
    .metadata-table {{ width: 100%; border-collapse: collapse; margin-top: 6px; font-size: 11px; }}
    .metadata-table td {{ padding: 2px 4px; vertical-align: top; border-top: 1px solid rgba(255,255,255,.12); }}
    .metadata-table td:first-child {{ color: #a9c9ff; white-space: nowrap; }}
    .warning {{ color: #ffd166; font-weight: 700; }}
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
    return `<tr><td>${{m.satellite}}</td><td>${{m.window_start_utc}} – ${{m.window_end_utc}}<br>${{m.processed_files}}/${{m.expected_files}} files (${{(m.completeness_fraction*100).toFixed(0)}}%); max ${{m.maximum_fed}}</td></tr>`;
  }}).join('');
  div.innerHTML = `<h3>GOES GLM 5-Minute FED Diagnostic</h3>
    <small>LCFA-derived flash extent density. Each quality-controlled flash is counted once in every grid cell containing one or more of its constituent events.</small>
    <table class="metadata-table">${{rows}}</table>
    <div class="warning">East and West are separate validation layers; do not add them together in the overlap region.</div>
    <small>Generated: {generated_time}</small>`;
  L.DomEvent.disableClickPropagation(div);
  return div;
}};
info.addTo(map);

const legend = L.control({{ position: 'bottomright' }});
legend.onAdd = () => {{
  const div = L.DomUtil.create('div', 'panel');
  div.innerHTML = `<strong>Flashes per 0.02° grid cell / 5 min</strong><div class="legend-row">{color_blocks}</div>`;
  return div;
}};
legend.addTo(map);
</script>
</body>
</html>
"""
    output_path.write_text(html, encoding="utf-8")


def process_satellite(
    client,
    satellite: str,
    keys: Sequence[str],
    window_start: datetime,
    window_end: datetime,
    output_dir: Path,
    working_dir: Path,
    grid: GridSpec,
    workers: int,
    maximum_render_dimension: int,
) -> SatelliteResult:
    config = SATELLITES[satellite]
    satellite_dir = working_dir / satellite.lower()
    downloaded = download_keys(client, config["bucket"], keys, satellite_dir, workers)
    if not downloaded:
        raise RuntimeError(f"No {satellite} LCFA files downloaded")

    aggregate = np.zeros((grid.height, grid.width), dtype=np.uint32)
    file_stats: list[FileStats] = []
    for index, path in enumerate(downloaded, start=1):
        print(f"[{satellite}] Processing {index}/{len(downloaded)}: {path.name}")
        try:
            contribution, stats = accumulate_file_fed(path, grid)
        except Exception as error:
            print(f"WARNING: [{satellite}] skipping unreadable file {path.name}: {error}", file=sys.stderr)
            continue
        aggregate += contribution
        file_stats.append(stats)

    if not file_stats:
        raise RuntimeError(f"No usable {satellite} LCFA files were processed")

    stem = f"glm_{satellite.lower()}_fed_5min"
    geotiff_path = output_dir / f"{stem}.tif"
    png_path = output_dir / f"{stem}.png"
    metadata_path = output_dir / f"{stem}_metadata.json"
    per_file_csv = output_dir / f"{stem}_files.csv"

    write_native_geotiff(aggregate, grid, geotiff_path)
    leaflet_bounds, rendered_shape, rendered_transform = render_web_mercator(
        aggregate,
        grid,
        png_path,
        maximum_render_dimension,
    )

    processed_files = len(file_stats)
    result = SatelliteResult(
        satellite=satellite,
        satellite_label=config["label"],
        bucket=config["bucket"],
        window_start_utc=iso_z(window_start),
        window_end_utc=iso_z(window_end),
        expected_files=EXPECTED_FILES_PER_WINDOW,
        listed_files=len(keys),
        processed_files=processed_files,
        completeness_fraction=processed_files / EXPECTED_FILES_PER_WINDOW,
        quality_controlled_flash_records=sum(s.flashes_quality_controlled for s in file_stats),
        events_mapped_to_good_flashes=sum(s.events_mapped_to_good_flashes for s in file_stats),
        events_in_domain=sum(s.events_in_domain for s in file_stats),
        flash_cell_contributions=sum(s.flash_cell_contributions for s in file_stats),
        nonzero_grid_cells=int(np.count_nonzero(aggregate)),
        maximum_fed=int(aggregate.max(initial=0)),
        native_geotiff=geotiff_path.name,
        leaflet_png=png_path.name,
        metadata_json=metadata_path.name,
        image_crs="EPSG:3857",
        leaflet_bounds=leaflet_bounds,
        rendered_shape=rendered_shape,
    )

    metadata = {
        **asdict(result),
        "product": "Diagnostic LCFA-derived GLM five-minute flash extent density",
        "source_product": PRODUCT_PREFIX,
        "methodology": (
            "Quality-controlled flashes are mapped through group and event parent-child "
            "identifiers. A flash contributes one count to each regular 0.02-degree grid "
            "cell containing at least one constituent GLM event."
        ),
        "quality_control": (
            "flash_quality_flag == 0 and group_quality_flag == 0 when those variables "
            "are present; packed event coordinates are decoded by honoring _Unsigned "
            "before scale_factor and add_offset"
        ),
        "important_note": (
            "This is a diagnostic LCFA-derived field, not the official NOAA gridded FED product. "
            "GOES-19 and GOES-18 overlap detections are not deduplicated."
        ),
        "units": "flashes per grid cell per five minutes",
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
            "bins": FED_BINS,
            "labels": FED_LABELS,
            "rgba": FED_RGBA,
        },
        "generated_time_utc": iso_z(utc_now()),
    }
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    with per_file_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(asdict(file_stats[0]).keys()))
        writer.writeheader()
        for stats in file_stats:
            writer.writerow(asdict(stats))

    return result


def write_summary_csv(output_path: Path, results: Sequence[SatelliteResult]) -> None:
    rows = [asdict(result) for result in results]
    fieldnames = list(rows[0].keys())
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def self_test() -> None:
    grid = GridSpec(west=-100.0, east=-99.0, south=30.0, north=31.0, resolution=0.1)

    # Emulate the GOES-R packed-coordinate convention, including signed storage
    # whose bytes must first be reinterpreted as unsigned before scaling.
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
                np.array([group_ids_u32[0], group_ids_u32[0], group_ids_u32[1], group_ids_u32[2]], dtype=np.uint32).view(np.int32),
                dims=("event",),
                attrs={"_Unsigned": "true"},
            ),
            "group_id": xr.DataArray(
                group_ids_u32.view(np.int32),
                dims=("group",),
                attrs={"_Unsigned": "true"},
            ),
            "group_parent_flash_id": xr.DataArray(
                np.array([flash_ids_u32[0], flash_ids_u32[0], flash_ids_u32[1]], dtype=np.uint32).view(np.int32),
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

    # Synthetic extent logic: the first flash has repeated events in one cell and
    # one event in another cell. It must count once in each cell. The second flash
    # shares the first cell.
    columns = np.floor((event_lon - grid.west) / grid.resolution).astype(np.int64)
    rows = np.floor((grid.north - event_lat) / grid.resolution).astype(np.int64)
    cells = rows * grid.width + columns
    unique_flashes, local = np.unique(event_flash, return_inverse=True)
    combined = cells * unique_flashes.size + local
    pairs = np.unique(combined)
    unique_cells = pairs // unique_flashes.size
    counts = np.bincount(unique_cells, minlength=grid.height * grid.width)
    field = counts.reshape(grid.height, grid.width)

    first_cell = int(cells[0])
    second_cell = int(cells[2])
    assert field.flat[first_cell] == 2, field
    assert field.flat[second_cell] == 1, field
    assert int(field.sum()) == 3, field

    parsed = parse_goes_timestamp("20262151600000")
    assert parsed.year == 2026 and parsed.timetuple().tm_yday == 215
    assert parsed.hour == 16 and parsed.minute == 0

    print("GLM FED packed-coordinate and extent self-test passed.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--analysis-time",
        default="",
        help=(
            "UTC five-minute window ending time, e.g. 2026-08-03T16:00:00Z. "
            "Blank selects the newest common GOES-19/GOES-18 window."
        ),
    )
    parser.add_argument("--lookback-minutes", type=int, default=180)
    parser.add_argument("--minimum-completeness", type=float, default=0.80)
    parser.add_argument("--resolution-degrees", type=float, default=DEFAULT_RESOLUTION_DEGREES)
    parser.add_argument("--download-workers", type=int, default=8)
    parser.add_argument("--maximum-render-dimension", type=int, default=6000)
    parser.add_argument("--output-dir", default="glm_fed_diagnostic_output")
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
    window_start, window_end, keys_by_satellite = resolve_common_window(
        client,
        args.analysis_time,
        args.lookback_minutes,
        args.minimum_completeness,
    )

    temporary_root = Path(tempfile.mkdtemp(prefix="glm_fed_"))
    try:
        results: list[SatelliteResult] = []
        for satellite in ("G19", "G18"):
            result = process_satellite(
                client=client,
                satellite=satellite,
                keys=keys_by_satellite[satellite],
                window_start=window_start,
                window_end=window_end,
                output_dir=output_dir,
                working_dir=temporary_root,
                grid=grid,
                workers=args.download_workers,
                maximum_render_dimension=args.maximum_render_dimension,
            )
            results.append(result)

        generated_time = iso_z(utc_now())
        summary_path = output_dir / "glm_fed_5min_summary.csv"
        html_path = output_dir / "glm_fed_5min_diagnostic.html"
        write_summary_csv(summary_path, results)
        write_interactive_html(html_path, results, generated_time)

        manifest = {
            "product": "GOES GLM five-minute FED diagnostic package",
            "window_start_utc": iso_z(window_start),
            "window_end_utc": iso_z(window_end),
            "satellites": [asdict(result) for result in results],
            "interactive_html": html_path.name,
            "summary_csv": summary_path.name,
            "generated_time_utc": generated_time,
        }
        (output_dir / "glm_fed_5min_manifest.json").write_text(
            json.dumps(manifest, indent=2),
            encoding="utf-8",
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
