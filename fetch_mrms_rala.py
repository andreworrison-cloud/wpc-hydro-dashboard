#!/usr/bin/env python3
"""Build a dashboard-ready MRMS Reflectivity at Lowest Altitude (RALA) image.

Phase-1 backend proof of concept for the WPC Real-Time Hydrometeorological Dashboard.
No dashboard/app.js integration is performed here.

Official-source chain:
  1) NCEP MRMS operational HTTPS directory
  2) NOAA Open Data Dissemination (NODD) / AWS public MRMS bucket fallback

The script discovers the newest timestamped CONUS RALA file, enforces a freshness
limit, decodes the native GRIB2 field, reprojects it to Web Mercator, colorizes it
with a familiar radar reflectivity palette, and atomically publishes PNG + JSON
metadata/manifest.  If the source is stale or decoding/rendering fails, existing
outputs are left untouched.
"""

from __future__ import annotations

import argparse
import gzip
import json
import math
import os
import re
import shutil
import tempfile
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

import numpy as np
import requests
from PIL import Image
from pyproj import Transformer
from rasterio.crs import CRS
from rasterio.enums import Resampling
from rasterio.transform import from_bounds, from_origin
from rasterio.warp import reproject
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

UTC = timezone.utc
PRODUCT = "ReflectivityAtLowestAltitude"
REGION = "CONUS"
FIELD_HEIGHT_KM = 0.50
NCEP_DIR = "https://mrms.ncep.noaa.gov/2D/ReflectivityAtLowestAltitude/"
NODD_ROOT = "https://noaa-mrms-pds.s3.amazonaws.com"
NODD_PREFIX_ROOT = "CONUS/ReflectivityAtLowestAltitude_00.50"
FILENAME_RE = re.compile(
    r"MRMS_ReflectivityAtLowestAltitude_00\.50_(\d{8}-\d{6})\.grib2\.gz"
)
DEFAULT_FRESHNESS_MINUTES = 20.0
DEFAULT_OUTPUT_WIDTH = 6400
MIN_VISIBLE_DBZ = 5.0
MISSING_CUTOFF_DBZ = -90.0

# Familiar radar reflectivity display bins.  These are display colors only; the
# underlying MRMS dBZ field is not smoothed or altered before binning.
RADAR_COLOR_TABLE = [
    (5.0,  "#74c7ec"),
    (10.0, "#4aa8df"),
    (15.0, "#2e78bd"),
    (20.0, "#47c957"),
    (25.0, "#18ad45"),
    (30.0, "#05863b"),
    (35.0, "#fff12b"),
    (40.0, "#ffb52e"),
    (45.0, "#ff7518"),
    (50.0, "#f23b32"),
    (55.0, "#b81420"),
    (60.0, "#ff4fd8"),
    (65.0, "#b52bff"),
    (70.0, "#8055d6"),
    (75.0, "#ffffff"),
]


@dataclass(frozen=True)
class SourceCandidate:
    provider: str
    timestamp: datetime
    url: str
    key: str

    def iso(self) -> str:
        return self.timestamp.astimezone(UTC).isoformat().replace("+00:00", "Z")


def utc_now() -> datetime:
    return datetime.now(UTC)


def iso_z(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


def parse_timestamp(text: str) -> datetime | None:
    match = FILENAME_RE.search(text)
    if not match:
        return None
    return datetime.strptime(match.group(1), "%Y%m%d-%H%M%S").replace(tzinfo=UTC)


def make_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=4,
        connect=4,
        read=4,
        backoff_factor=1.0,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET", "HEAD"}),
        raise_on_status=False,
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.headers.update({
        "User-Agent": "WPC-Hydrometeorological-Dashboard-MRMS-RALA/1.0",
        "Accept": "*/*",
    })
    return session


def discover_ncep(session: requests.Session) -> list[SourceCandidate]:
    response = session.get(NCEP_DIR, timeout=(10, 30))
    response.raise_for_status()
    found: dict[str, SourceCandidate] = {}
    for filename in FILENAME_RE.findall(response.text):
        stamp = datetime.strptime(filename, "%Y%m%d-%H%M%S").replace(tzinfo=UTC)
        full_name = f"MRMS_{PRODUCT}_00.50_{filename}.grib2.gz"
        found[full_name] = SourceCandidate(
            provider="NCEP MRMS HTTPS",
            timestamp=stamp,
            url=NCEP_DIR + full_name,
            key=full_name,
        )
    return sorted(found.values(), key=lambda item: item.timestamp)


def _xml_text(element: ET.Element, suffix: str) -> str | None:
    for child in element.iter():
        if child.tag.endswith(suffix):
            return child.text
    return None


def discover_nodd(session: requests.Session, now: datetime) -> list[SourceCandidate]:
    candidates: dict[str, SourceCandidate] = {}
    # A 2-minute product yields < 1000 objects/day, so one list request per day is
    # enough. Search today and yesterday to be robust around 00 UTC.
    for day_offset in (0, 1):
        day = (now - timedelta(days=day_offset)).strftime("%Y%m%d")
        prefix = f"{NODD_PREFIX_ROOT}/{day}/"
        params = {"list-type": "2", "prefix": prefix, "max-keys": "1000"}
        response = session.get(NODD_ROOT + "/", params=params, timeout=(10, 40))
        response.raise_for_status()
        try:
            root = ET.fromstring(response.content)
        except ET.ParseError as exc:
            raise RuntimeError(f"Could not parse NOAA NODD S3 listing for {day}: {exc}") from exc
        for contents in root.iter():
            if not contents.tag.endswith("Contents"):
                continue
            key = _xml_text(contents, "Key")
            if not key:
                continue
            stamp = parse_timestamp(key)
            if stamp is None:
                continue
            candidates[key] = SourceCandidate(
                provider="NOAA NODD MRMS (AWS)",
                timestamp=stamp,
                url=f"{NODD_ROOT}/{key}",
                key=key,
            )
    return sorted(candidates.values(), key=lambda item: item.timestamp)


def choose_candidate(
    ncep: list[SourceCandidate],
    nodd: list[SourceCandidate],
    source_mode: str,
) -> SourceCandidate:
    pools: list[SourceCandidate]
    if source_mode == "ncep":
        pools = ncep
    elif source_mode == "nodd":
        pools = nodd
    else:
        pools = [*ncep, *nodd]
    if not pools:
        raise RuntimeError(f"No MRMS RALA source candidates discovered for mode={source_mode!r}.")
    return max(pools, key=lambda item: item.timestamp)


def download_file(session: requests.Session, candidate: SourceCandidate, destination: Path) -> int:
    with session.get(candidate.url, stream=True, timeout=(15, 90)) as response:
        response.raise_for_status()
        total = 0
        with destination.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if not chunk:
                    continue
                handle.write(chunk)
                total += len(chunk)
    if total < 10_000:
        raise RuntimeError(f"Downloaded RALA file is implausibly small: {total:,} bytes")
    with destination.open("rb") as handle:
        if handle.read(2) != b"\x1f\x8b":
            raise RuntimeError("Downloaded RALA file does not have a gzip header.")
    return total


def gunzip_file(source: Path, destination: Path) -> int:
    with gzip.open(source, "rb") as src, destination.open("wb") as dst:
        shutil.copyfileobj(src, dst, length=1024 * 1024)
    size = destination.stat().st_size
    if size < 100_000:
        raise RuntimeError(f"Decompressed RALA GRIB2 is implausibly small: {size:,} bytes")
    return size


def _codes_get_safe(eccodes, gid, key: str, default=None):
    try:
        return eccodes.codes_get(gid, key)
    except Exception:
        return default


def decode_grib(grib_path: Path) -> tuple[np.ndarray, object, dict]:
    try:
        import eccodes
    except ImportError as exc:
        raise RuntimeError(
            "The Python 'eccodes' package is required to decode MRMS GRIB2."
        ) from exc

    with grib_path.open("rb") as handle:
        gid = eccodes.codes_grib_new_from_file(handle)
        if gid is None:
            raise RuntimeError("No GRIB message was found in the RALA file.")
        try:
            nx = _codes_get_safe(eccodes, gid, "Nx") or _codes_get_safe(eccodes, gid, "Ni")
            ny = _codes_get_safe(eccodes, gid, "Ny") or _codes_get_safe(eccodes, gid, "Nj")
            nx, ny = int(nx), int(ny)
            raw = np.asarray(eccodes.codes_get_values(gid), dtype=np.float32)
            if raw.size != nx * ny:
                raise RuntimeError(
                    f"GRIB grid-size mismatch: Nx={nx}, Ny={ny}, values={raw.size:,}"
                )
            data = raw.reshape(ny, nx)

            lat1 = float(_codes_get_safe(eccodes, gid, "latitudeOfFirstGridPointInDegrees"))
            lat2 = float(_codes_get_safe(eccodes, gid, "latitudeOfLastGridPointInDegrees"))
            lon1 = float(_codes_get_safe(eccodes, gid, "longitudeOfFirstGridPointInDegrees"))
            lon2 = float(_codes_get_safe(eccodes, gid, "longitudeOfLastGridPointInDegrees"))
            lon1 = lon1 - 360.0 if lon1 > 180.0 else lon1
            lon2 = lon2 - 360.0 if lon2 > 180.0 else lon2

            dx = _codes_get_safe(eccodes, gid, "iDirectionIncrementInDegrees")
            dy = _codes_get_safe(eccodes, gid, "jDirectionIncrementInDegrees")
            dx = abs(float(dx)) if dx is not None else abs(lon2 - lon1) / max(nx - 1, 1)
            dy = abs(float(dy)) if dy is not None else abs(lat2 - lat1) / max(ny - 1, 1)

            i_negative = int(_codes_get_safe(eccodes, gid, "iScansNegatively", 0) or 0)
            j_positive = int(_codes_get_safe(eccodes, gid, "jScansPositively", 0) or 0)
            if i_negative:
                data = data[:, ::-1]
            if j_positive:
                data = data[::-1, :]

            west, east = min(lon1, lon2), max(lon1, lon2)
            south, north = min(lat1, lat2), max(lat1, lat2)
            transform = from_origin(west - dx / 2.0, north + dy / 2.0, dx, dy)

            data = np.where(data <= MISSING_CUTOFF_DBZ, np.nan, data).astype(np.float32)
            metadata = {
                "nx": nx,
                "ny": ny,
                "source_bounds_lonlat": [west, south, east, north],
                "grid_spacing_degrees": [dx, dy],
                "units": str(_codes_get_safe(eccodes, gid, "units", "dBZ")),
                "parameter_name": str(_codes_get_safe(eccodes, gid, "name", PRODUCT)),
                "discipline": _codes_get_safe(eccodes, gid, "discipline"),
                "parameter_category": _codes_get_safe(eccodes, gid, "parameterCategory"),
                "parameter_number": _codes_get_safe(eccodes, gid, "parameterNumber"),
                "min_dbz": float(np.nanmin(data)) if np.isfinite(data).any() else None,
                "max_dbz": float(np.nanmax(data)) if np.isfinite(data).any() else None,
            }
            return data, transform, metadata
        finally:
            eccodes.codes_release(gid)


def destination_grid(source_transform, source_shape: tuple[int, int], width: int):
    ny, nx = source_shape
    west = source_transform.c
    north = source_transform.f
    east = west + source_transform.a * nx
    south = north + source_transform.e * ny

    to_3857 = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)
    x0, y0 = to_3857.transform(west, south)
    x1, y1 = to_3857.transform(east, north)
    xmin, xmax = min(x0, x1), max(x0, x1)
    ymin, ymax = min(y0, y1), max(y0, y1)
    ratio = (ymax - ymin) / max(xmax - xmin, 1.0)
    height = max(1800, min(5000, int(round(width * ratio))))
    transform = from_bounds(xmin, ymin, xmax, ymax, width, height)
    return transform, width, height, (xmin, ymin, xmax, ymax)


def reproject_dbz(data: np.ndarray, src_transform, output_width: int):
    dst_transform, width, height, bounds_3857 = destination_grid(
        src_transform, data.shape, output_width
    )
    dst = np.full((height, width), np.nan, dtype=np.float32)
    reproject(
        source=data,
        destination=dst,
        src_transform=src_transform,
        src_crs=CRS.from_epsg(4326),
        src_nodata=np.nan,
        dst_transform=dst_transform,
        dst_crs=CRS.from_epsg(3857),
        dst_nodata=np.nan,
        resampling=Resampling.nearest,
        num_threads=2,
        init_dest_nodata=True,
    )
    return dst, dst_transform, bounds_3857


def hex_rgba(value: str) -> tuple[int, int, int, int]:
    value = value.lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16), 255


def colorize(dbz: np.ndarray) -> np.ndarray:
    rgba = np.zeros((*dbz.shape, 4), dtype=np.uint8)
    finite = np.isfinite(dbz)
    for threshold, color in RADAR_COLOR_TABLE:
        mask = finite & (dbz >= threshold)
        rgba[mask] = hex_rgba(color)
    rgba[~finite | (dbz < MIN_VISIBLE_DBZ), 3] = 0
    return rgba


def leaflet_bounds_from_mercator(bounds_3857: tuple[float, float, float, float]):
    xmin, ymin, xmax, ymax = bounds_3857
    to_ll = Transformer.from_crs("EPSG:3857", "EPSG:4326", always_xy=True)
    west, south = to_ll.transform(xmin, ymin)
    east, north = to_ll.transform(xmax, ymax)
    return [[south, west], [north, east]]


def publish_outputs(
    output_dir: Path,
    rgba: np.ndarray,
    candidate: SourceCandidate,
    discovered: dict,
    decode_meta: dict,
    bounds_3857: tuple[float, float, float, float],
    source_age_minutes: float,
    freshness_minutes: float,
    allow_stale: bool,
    download_size: int,
    grib_size: int,
):
    output_dir.mkdir(parents=True, exist_ok=True)
    parent = output_dir.parent
    staging = Path(tempfile.mkdtemp(prefix="mrms_rala_stage_", dir=parent))
    try:
        png_name = "mrms_rala_conus_latest.png"
        metadata_name = "mrms_rala_metadata.json"
        manifest_name = "mrms_rala_manifest.json"
        diagnostics_name = "mrms_rala_source_diagnostics.json"

        image = Image.fromarray(rgba, mode="RGBA")
        image.save(staging / png_name, format="PNG", compress_level=6)
        if (staging / png_name).stat().st_size < 20_000:
            raise RuntimeError("Rendered RALA PNG is implausibly small.")

        generated = utc_now()
        leaflet_bounds = leaflet_bounds_from_mercator(bounds_3857)
        fresh = source_age_minutes <= freshness_minutes
        color_table = [
            {"threshold_dbz": threshold, "color": color}
            for threshold, color in RADAR_COLOR_TABLE
        ]
        metadata = {
            "metadata_mode": "mrms_rala_dashboard_v1",
            "generator_revision": "v1_backend_poc",
            "product": PRODUCT,
            "region": REGION,
            "field_height_km": FIELD_HEIGHT_KM,
            "units": "dBZ",
            "source_provider": candidate.provider,
            "source_url": candidate.url,
            "source_key": candidate.key,
            "source_valid_time_utc": candidate.iso(),
            "generated_utc": iso_z(generated),
            "source_age_minutes": round(source_age_minutes, 2),
            "freshness_limit_minutes": freshness_minutes,
            "fresh": fresh,
            "diagnostic_allow_stale": bool(allow_stale),
            "native_resolution_description": "MRMS 1-km RALA grid (operational product)",
            "source_grid": decode_meta,
            "display": {
                "projection": "EPSG:3857",
                "image_width_px": int(rgba.shape[1]),
                "image_height_px": int(rgba.shape[0]),
                "leaflet_bounds": leaflet_bounds,
                "visible_minimum_dbz": MIN_VISIBLE_DBZ,
                "resampling": "nearest-neighbor",
                "smoothing": False,
                "color_table": color_table,
            },
            "download_bytes_gzip": download_size,
            "download_bytes_grib2": grib_size,
            "source_policy": (
                "Official NCEP MRMS HTTPS and NOAA NODD/AWS only; no IEM dependency. "
                "Newest discovered official timestamp wins in auto mode."
            ),
            "quality_control": {
                "missing_values_masked_at_or_below_dbz": MISSING_CUTOFF_DBZ,
                "transactional_publish": True,
                "stale_source_not_published_unless_diagnostic_override": True,
            },
        }
        manifest = {
            "metadata_mode": "mrms_rala_dashboard_manifest_v1",
            "latest_valid_time_utc": candidate.iso(),
            "generated_utc": iso_z(generated),
            "fresh": fresh,
            "source_age_minutes": round(source_age_minutes, 2),
            "png": png_name,
            "metadata": metadata_name,
            "bounds": leaflet_bounds,
        }
        (staging / metadata_name).write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
        (staging / manifest_name).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        (staging / diagnostics_name).write_text(json.dumps(discovered, indent=2) + "\n", encoding="utf-8")

        for name in (png_name, metadata_name, manifest_name, diagnostics_name):
            os.replace(staging / name, output_dir / name)
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def candidate_dict(item: SourceCandidate) -> dict:
    return {
        "provider": item.provider,
        "timestamp_utc": item.iso(),
        "url": item.url,
        "key": item.key,
    }


def run_build(args) -> int:
    session = make_session()
    now = utc_now()
    discovery_errors = []
    ncep: list[SourceCandidate] = []
    nodd: list[SourceCandidate] = []

    if args.source_mode in ("auto", "ncep"):
        try:
            ncep = discover_ncep(session)
        except Exception as exc:
            discovery_errors.append(f"NCEP discovery failed: {type(exc).__name__}: {exc}")
            if args.source_mode == "ncep":
                raise
    if args.source_mode in ("auto", "nodd"):
        try:
            nodd = discover_nodd(session, now)
        except Exception as exc:
            discovery_errors.append(f"NODD discovery failed: {type(exc).__name__}: {exc}")
            if args.source_mode == "nodd":
                raise

    candidate = choose_candidate(ncep, nodd, args.source_mode)
    age_minutes = (now - candidate.timestamp).total_seconds() / 60.0
    diagnostics = {
        "checked_utc": iso_z(now),
        "source_mode": args.source_mode,
        "selected": candidate_dict(candidate),
        "selected_age_minutes": round(age_minutes, 2),
        "freshness_limit_minutes": args.freshness_minutes,
        "discovery_errors": discovery_errors,
        "ncep_latest": candidate_dict(ncep[-1]) if ncep else None,
        "nodd_latest": candidate_dict(nodd[-1]) if nodd else None,
        "ncep_candidate_count": len(ncep),
        "nodd_candidate_count": len(nodd),
    }

    print(json.dumps(diagnostics, indent=2))
    if age_minutes > args.freshness_minutes and not args.allow_stale:
        raise RuntimeError(
            f"Newest official MRMS RALA frame is {age_minutes:.1f} minutes old; "
            f"maximum allowed is {args.freshness_minutes:.1f} minutes. "
            "Existing outputs were not changed."
        )

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="mrms_rala_download_") as tmp:
        tmpdir = Path(tmp)
        gz_path = tmpdir / "rala.grib2.gz"
        grib_path = tmpdir / "rala.grib2"
        download_size = download_file(session, candidate, gz_path)
        grib_size = gunzip_file(gz_path, grib_path)
        print(f"Downloaded {download_size:,} gzip bytes; decompressed {grib_size:,} GRIB2 bytes.")

        data, src_transform, decode_meta = decode_grib(grib_path)
        print(
            f"Decoded RALA grid {decode_meta['nx']}x{decode_meta['ny']} "
            f"range={decode_meta['min_dbz']}..{decode_meta['max_dbz']} dBZ"
        )
        projected, _dst_transform, bounds_3857 = reproject_dbz(
            data, src_transform, args.output_width
        )
        rgba = colorize(projected)
        nontransparent = int(np.count_nonzero(rgba[..., 3]))
        if nontransparent < 100:
            raise RuntimeError(
                f"Rendered RALA image has too few visible radar pixels ({nontransparent})."
            )
        print(
            f"Rendered Web-Mercator RGBA {rgba.shape[1]}x{rgba.shape[0]} "
            f"with {nontransparent:,} visible pixels."
        )
        publish_outputs(
            output_dir=output_dir,
            rgba=rgba,
            candidate=candidate,
            discovered=diagnostics,
            decode_meta=decode_meta,
            bounds_3857=bounds_3857,
            source_age_minutes=age_minutes,
            freshness_minutes=args.freshness_minutes,
            allow_stale=args.allow_stale,
            download_size=download_size,
            grib_size=grib_size,
        )
    print(f"MRMS RALA backend package published to {output_dir}")
    return 0


def self_test(output_dir: Path) -> int:
    output_dir.mkdir(parents=True, exist_ok=True)
    # Synthetic reflectivity bands exercise reprojection/colorization without
    # requiring network access or ecCodes.
    ny, nx = 400, 700
    y, x = np.mgrid[0:ny, 0:nx]
    field = np.full((ny, nx), np.nan, dtype=np.float32)
    for cx, cy, peak, radius in ((180, 200, 65, 85), (460, 150, 50, 70), (560, 290, 40, 55)):
        r = np.hypot(x - cx, y - cy)
        values = peak - 0.65 * r
        mask = r <= radius
        field[mask] = np.maximum(np.nan_to_num(field[mask], nan=-999), values[mask])
    src_transform = from_origin(-130.005, 55.005, 0.1, 0.0875)
    projected, _transform, _bounds = reproject_dbz(field, src_transform, 1600)
    rgba = colorize(projected)
    Image.fromarray(rgba, mode="RGBA").save(output_dir / "mrms_rala_self_test.png")
    if np.count_nonzero(rgba[..., 3]) < 1000:
        raise RuntimeError("Self-test generated too few visible pixels.")
    print("MRMS RALA self-test PASS")
    return 0


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default="diagnostics/mrms_rala")
    parser.add_argument(
        "--source-mode", choices=("auto", "ncep", "nodd"), default="auto",
        help="auto chooses the newest timestamp from official NCEP and NOAA NODD sources",
    )
    parser.add_argument("--freshness-minutes", type=float, default=DEFAULT_FRESHNESS_MINUTES)
    parser.add_argument("--output-width", type=int, default=DEFAULT_OUTPUT_WIDTH)
    parser.add_argument(
        "--allow-stale", action="store_true",
        help="diagnostic override only; metadata remains explicitly marked stale",
    )
    parser.add_argument("--self-test", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.output_width < 1200 or args.output_width > 9000:
        raise SystemExit("--output-width must be between 1200 and 9000 pixels")
    if args.freshness_minutes <= 0:
        raise SystemExit("--freshness-minutes must be positive")
    if args.self_test:
        return self_test(Path(args.output_dir))
    try:
        return run_build(args)
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
