#!/usr/bin/env python3
"""Build the WPC Hydrometeorological Dashboard LightningCast CONUS product.

Retrieves authorized CIMSS/SSEC GOES-East and GOES-West CONUS LightningCast
placefile loops, selects the newest scan common to both feeds, applies exclusive
East/West source ownership, and renders a transparent Web-Mercator PNG plus
metadata and a compact manifest.

This backend intentionally does not modify the dashboard interface.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Sequence

from PIL import Image, ImageDraw

UTC = timezone.utc
DEFAULT_EAST_URL = "https://cimss.ssec.wisc.edu/severe_conv/NOAACIMSS_PLTG_GOES-East_CONUS_LOOP"
DEFAULT_WEST_URL = "https://cimss.ssec.wisc.edu/severe_conv/NOAACIMSS_PLTG_GOES-West_CONUS_LOOP"

THRESHOLDS = (10, 30, 50, 70, 90)
THRESHOLD_RGBA = {
    10: (80, 201, 134, 118),
    30: (255, 255, 81, 124),
    50: (255, 192, 108, 132),
    70: (255, 80, 80, 142),
    90: (255, 80, 255, 154),
}
THRESHOLD_RGB_SOURCE = {
    10: (80, 201, 134),
    30: (255, 255, 81),
    50: (255, 192, 108),
    70: (255, 80, 80),
    90: (255, 80, 255),
}

OWNERSHIP_SEAM_LON = -106.1
RENDER_WEST = -130.0
RENDER_EAST = -60.0
RENDER_SOUTH = 20.0
RENDER_NORTH = 55.0
DEFAULT_MAXIMUM_DIMENSION = 1800
USER_AGENT = "WPC-Hydrometeorological-Dashboard-LightningCast/1.0 (authorized CIMSS/SSEC data pull)"

TITLE_RE = re.compile(r"^Title:\s*(.+?)\s*$", re.IGNORECASE)
REFRESH_RE = re.compile(r"^Refresh:\s*(\d+)\s*$", re.IGNORECASE)
TIME_RANGE_RE = re.compile(
    r"^TimeRange:\s*(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)\s+"
    r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)\s*$",
    re.IGNORECASE,
)
COLOR_RE = re.compile(r"^Color:\s*(\d{1,3})\s+(\d{1,3})\s+(\d{1,3})\s*$", re.IGNORECASE)
LINE_HEADER_RE = re.compile(
    r'^Line:\s*[^\"]*\"GOES-(East|West)\s+CONUS\s+scan\s+time:\s*'
    r"(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2})Z"
    r"(?:\\n|\n).*?P\(LTG\)\s*>=\s*(\d{1,3})%\s+in\s+next\s+60\s+minutes",
    re.IGNORECASE,
)
COORD_RE = re.compile(
    r"^\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*,\s*"
    r"([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*$"
)


@dataclasses.dataclass
class Contour:
    satellite: str
    scan_time: datetime
    threshold: int
    color: tuple[int, int, int] | None
    points: list[tuple[float, float]]  # lon, lat

    @property
    def closed(self) -> bool:
        if len(self.points) < 3:
            return False
        lon0, lat0 = self.points[0]
        lon1, lat1 = self.points[-1]
        return math.hypot(lon1 - lon0, lat1 - lat0) <= 0.03


@dataclasses.dataclass
class ParsedPlacefile:
    expected_satellite: str
    title: str | None
    refresh_seconds: int | None
    time_ranges: list[tuple[datetime, datetime]]
    frame_times: set[datetime]
    contours_by_frame: dict[datetime, list[Contour]]
    threshold_colors: dict[int, set[tuple[int, int, int]]]
    invalid_coordinate_lines: int
    discarded_short_contours: int
    satellite_names_seen: set[str]
    warnings: list[str]


def utc_now() -> datetime:
    return datetime.now(tz=UTC)


def iso_z(value: datetime | None) -> str | None:
    return None if value is None else value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso_z(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


def parse_scan_time(date_text: str, minute_text: str) -> datetime:
    return datetime.strptime(f"{date_text} {minute_text}", "%Y-%m-%d %H:%M").replace(tzinfo=UTC)


def fetch_text(url: str, timeout_seconds: int, retries: int, maximum_bytes: int) -> tuple[str, dict[str, object]]:
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/plain,*/*;q=0.5",
                "Cache-Control": "no-cache",
            },
        )
        started = time.monotonic()
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                status = int(getattr(response, "status", response.getcode()))
                if status != 200:
                    raise RuntimeError(f"HTTP {status}")
                content_length = response.headers.get("Content-Length")
                if content_length and int(content_length) > maximum_bytes:
                    raise RuntimeError(f"Content-Length {content_length} exceeds maximum {maximum_bytes}")
                raw = response.read(maximum_bytes + 1)
                if len(raw) > maximum_bytes:
                    raise RuntimeError(f"response exceeded maximum {maximum_bytes} bytes")
                return raw.decode("utf-8", errors="replace"), {
                    "http_status": status,
                    "bytes_downloaded": len(raw),
                    "download_seconds": round(time.monotonic() - started, 3),
                    "download_attempt": attempt,
                    "last_modified": response.headers.get("Last-Modified"),
                    "etag": response.headers.get("ETag"),
                    "sha256": hashlib.sha256(raw).hexdigest(),
                }
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, RuntimeError) as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(min(2 ** (attempt - 1), 8))
    raise RuntimeError(f"failed to fetch {url} after {retries} attempts: {last_error}")


def parse_placefile(text: str, expected_satellite: str) -> ParsedPlacefile:
    title = None
    refresh_seconds = None
    time_ranges: list[tuple[datetime, datetime]] = []
    frame_times: set[datetime] = set()
    contours_by_frame: dict[datetime, list[Contour]] = defaultdict(list)
    threshold_colors: dict[int, set[tuple[int, int, int]]] = defaultdict(set)
    invalid_coordinate_lines = 0
    discarded_short_contours = 0
    satellite_names_seen: set[str] = set()
    warnings: list[str] = []
    current_color: tuple[int, int, int] | None = None
    current: Contour | None = None

    def finalize() -> None:
        nonlocal current, discarded_short_contours
        if current is None:
            return
        if len(current.points) >= 2:
            contours_by_frame[current.scan_time].append(current)
            frame_times.add(current.scan_time)
            if current.color is not None:
                threshold_colors[current.threshold].add(current.color)
        else:
            discarded_short_contours += 1
        current = None

    for raw_line in text.splitlines():
        line = raw_line.strip("\r")
        if title is None:
            match = TITLE_RE.match(line)
            if match:
                title = match.group(1).strip()
                continue
        match = REFRESH_RE.match(line)
        if match:
            refresh_seconds = int(match.group(1))
            continue
        match = TIME_RANGE_RE.match(line)
        if match:
            finalize()
            start = parse_iso_z(match.group(1))
            end = parse_iso_z(match.group(2))
            time_ranges.append((start, end))
            frame_times.add(start.replace(second=0, microsecond=0))
            continue
        match = COLOR_RE.match(line)
        if match:
            rgb = tuple(int(match.group(i)) for i in range(1, 4))
            current_color = rgb if all(0 <= v <= 255 for v in rgb) else None
            continue
        match = LINE_HEADER_RE.match(line)
        if match:
            finalize()
            satellite = match.group(1).title()
            satellite_names_seen.add(satellite)
            current = Contour(
                satellite=satellite,
                scan_time=parse_scan_time(match.group(2), match.group(3)),
                threshold=int(match.group(4)),
                color=current_color,
                points=[],
            )
            continue
        if line.strip().lower() == "end:":
            finalize()
            continue
        match = COORD_RE.match(line)
        if match and current is not None:
            lat = float(match.group(1))
            lon = float(match.group(2))
            if -90 <= lat <= 90 and -180 <= lon <= 180:
                current.points.append((lon, lat))
            else:
                invalid_coordinate_lines += 1
            continue
        if current is not None and line and not line.startswith(("Color:", "Line:", "TimeRange:")):
            invalid_coordinate_lines += 1

    finalize()
    if not text.strip():
        warnings.append("empty source document")
    if title is None:
        warnings.append("missing Title command")
    if not time_ranges:
        warnings.append("no TimeRange commands parsed")
    if satellite_names_seen and expected_satellite not in satellite_names_seen:
        warnings.append(f"expected GOES-{expected_satellite}, saw {sorted(satellite_names_seen)}")

    return ParsedPlacefile(
        expected_satellite=expected_satellite,
        title=title,
        refresh_seconds=refresh_seconds,
        time_ranges=time_ranges,
        frame_times=frame_times,
        contours_by_frame=dict(contours_by_frame),
        threshold_colors=dict(threshold_colors),
        invalid_coordinate_lines=invalid_coordinate_lines,
        discarded_short_contours=discarded_short_contours,
        satellite_names_seen=satellite_names_seen,
        warnings=warnings,
    )

def mercator_y(lat: float) -> float:
    lat = min(85.05112878, max(-85.05112878, lat))
    radians = math.radians(lat)
    return math.log(math.tan(math.pi / 4.0 + radians / 2.0))


def image_shape(max_dimension: int) -> tuple[int, int]:
    x_span = math.radians(RENDER_EAST - RENDER_WEST)
    y_span = mercator_y(RENDER_NORTH) - mercator_y(RENDER_SOUTH)
    aspect = x_span / y_span
    if aspect >= 1:
        width = max_dimension
        height = max(1, round(max_dimension / aspect))
    else:
        height = max_dimension
        width = max(1, round(max_dimension * aspect))
    return width, height


def project_to_pixel(lon: float, lat: float, width: int, height: int) -> tuple[float, float]:
    x = (lon - RENDER_WEST) / (RENDER_EAST - RENDER_WEST) * (width - 1)
    y_top = mercator_y(RENDER_NORTH)
    y_bottom = mercator_y(RENDER_SOUTH)
    y = (y_top - mercator_y(lat)) / (y_top - y_bottom) * (height - 1)
    return x, y


def clip_polygon_halfplane(
    points: list[tuple[float, float]], axis: str, limit: float, keep_greater: bool
) -> list[tuple[float, float]]:
    if not points:
        return []

    def value(point: tuple[float, float]) -> float:
        return point[0] if axis == "lon" else point[1]

    def inside(point: tuple[float, float]) -> bool:
        return value(point) >= limit if keep_greater else value(point) <= limit

    output: list[tuple[float, float]] = []
    previous = points[-1]
    previous_inside = inside(previous)
    for current in points:
        current_inside = inside(current)
        if current_inside != previous_inside:
            pv = value(previous)
            cv = value(current)
            fraction = 0.0 if cv == pv else (limit - pv) / (cv - pv)
            lon = previous[0] + fraction * (current[0] - previous[0])
            lat = previous[1] + fraction * (current[1] - previous[1])
            output.append((lon, lat))
        if current_inside:
            output.append(current)
        previous = current
        previous_inside = current_inside
    return output


def clip_polygon(points: list[tuple[float, float]], satellite: str) -> list[tuple[float, float]]:
    result = points[:]
    result = clip_polygon_halfplane(result, "lon", RENDER_WEST, True)
    result = clip_polygon_halfplane(result, "lon", RENDER_EAST, False)
    result = clip_polygon_halfplane(result, "lat", RENDER_SOUTH, True)
    result = clip_polygon_halfplane(result, "lat", RENDER_NORTH, False)
    if satellite == "West":
        result = clip_polygon_halfplane(result, "lon", OWNERSHIP_SEAM_LON, False)
    else:
        result = clip_polygon_halfplane(result, "lon", OWNERSHIP_SEAM_LON, True)
    return result


def clip_segment_to_rect(
    p0: tuple[float, float], p1: tuple[float, float], satellite: str
) -> tuple[tuple[float, float], tuple[float, float]] | None:
    if satellite == "West":
        xmin, xmax = RENDER_WEST, min(RENDER_EAST, OWNERSHIP_SEAM_LON)
    else:
        xmin, xmax = max(RENDER_WEST, OWNERSHIP_SEAM_LON), RENDER_EAST
    ymin, ymax = RENDER_SOUTH, RENDER_NORTH
    x0, y0 = p0
    x1, y1 = p1
    dx, dy = x1 - x0, y1 - y0
    p = (-dx, dx, -dy, dy)
    q = (x0 - xmin, xmax - x0, y0 - ymin, ymax - y0)
    u1, u2 = 0.0, 1.0
    for pi, qi in zip(p, q):
        if pi == 0:
            if qi < 0:
                return None
            continue
        t = qi / pi
        if pi < 0:
            u1 = max(u1, t)
        else:
            u2 = min(u2, t)
        if u1 > u2:
            return None
    return ((x0 + u1 * dx, y0 + u1 * dy), (x0 + u2 * dx, y0 + u2 * dy))


def render_product(
    frame_time: datetime,
    east: ParsedPlacefile,
    west: ParsedPlacefile,
    output_png: Path,
    maximum_dimension: int,
) -> dict[str, object]:
    width, height = image_shape(maximum_dimension)
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image, "RGBA")

    source_counts: dict[str, Counter] = {"East": Counter(), "West": Counter()}
    rendered_closed: Counter = Counter()
    rendered_open: Counter = Counter()
    source_color_mismatches: list[str] = []

    for threshold in THRESHOLDS:
        fill = THRESHOLD_RGBA[threshold]
        stroke = (*THRESHOLD_RGB_SOURCE[threshold], 238)
        for satellite, parsed in (("West", west), ("East", east)):
            contours = [c for c in parsed.contours_by_frame.get(frame_time, []) if c.threshold == threshold]
            source_counts[satellite][threshold] = len(contours)
            for contour in contours:
                if contour.color is not None and contour.color != THRESHOLD_RGB_SOURCE[threshold]:
                    source_color_mismatches.append(
                        f"GOES-{satellite} {threshold}% source RGB {contour.color} differs from expected {THRESHOLD_RGB_SOURCE[threshold]}"
                    )
                if contour.closed:
                    polygon = clip_polygon(contour.points, satellite)
                    if len(polygon) >= 3:
                        pixels = [project_to_pixel(lon, lat, width, height) for lon, lat in polygon]
                        draw.polygon(pixels, fill=fill, outline=stroke)
                        rendered_closed[threshold] += 1
                else:
                    any_segment = False
                    for a, b in zip(contour.points[:-1], contour.points[1:]):
                        clipped = clip_segment_to_rect(a, b, satellite)
                        if clipped is None:
                            continue
                        pixels = [
                            project_to_pixel(*clipped[0], width, height),
                            project_to_pixel(*clipped[1], width, height),
                        ]
                        draw.line(pixels, fill=stroke, width=2)
                        any_segment = True
                    if any_segment:
                        rendered_open[threshold] += 1

    image.save(output_png, format="PNG", optimize=True)
    visible = image.getchannel("A").getbbox() is not None
    return {
        "width": width,
        "height": height,
        "has_visible_pixels": visible,
        "source_contours_by_satellite_and_threshold": {
            satellite: {str(t): int(counter[t]) for t in THRESHOLDS}
            for satellite, counter in source_counts.items()
        },
        "rendered_closed_contours_by_threshold": {str(t): int(rendered_closed[t]) for t in THRESHOLDS},
        "rendered_open_contours_by_threshold": {str(t): int(rendered_open[t]) for t in THRESHOLDS},
        "source_color_mismatches": sorted(set(source_color_mismatches)),
    }


def latest_common_frame(east: ParsedPlacefile, west: ParsedPlacefile) -> datetime | None:
    common = east.frame_times & west.frame_times
    return max(common) if common else None


def source_summary(parsed: ParsedPlacefile, fetch_meta: dict[str, object], frame_time: datetime) -> dict[str, object]:
    contours = parsed.contours_by_frame.get(frame_time, [])
    counts = Counter(c.threshold for c in contours)
    return {
        "title": parsed.title,
        "refresh_seconds": parsed.refresh_seconds,
        "frame_count": len(parsed.frame_times),
        "selected_frame_contours": {str(t): int(counts[t]) for t in THRESHOLDS},
        "threshold_colors_observed": {
            str(t): [list(rgb) for rgb in sorted(parsed.threshold_colors.get(t, set()))]
            for t in THRESHOLDS
        },
        "invalid_coordinate_lines": parsed.invalid_coordinate_lines,
        "discarded_short_contours": parsed.discarded_short_contours,
        "warnings": parsed.warnings,
        "fetch": fetch_meta,
    }


def write_outputs(
    output_dir: Path,
    east_url: str,
    west_url: str,
    east: ParsedPlacefile,
    west: ParsedPlacefile,
    east_fetch: dict[str, object],
    west_fetch: dict[str, object],
    frame_time: datetime,
    fetched_at: datetime,
    maximum_dimension: int,
) -> None:
    png_name = "lightningcast_conus_probability_60min.png"
    metadata_name = "lightningcast_conus_probability_60min_metadata.json"
    manifest_name = "lightningcast_manifest.json"
    png_path = output_dir / png_name
    render = render_product(frame_time, east, west, png_path, maximum_dimension)

    age_minutes = round((fetched_at - frame_time).total_seconds() / 60.0, 2)
    metadata = {
        "metadata_mode": "lightningcast_dashboard_v1",
        "product_role": "probability_of_lightning_next_60_minutes",
        "display_label": "CIMSS/SSEC LightningCast — Probability of Lightning in Next 60 Minutes",
        "source_product": "LightningCast CONUS GRLevelX placefile loops",
        "source_attribution": "LightningCast data courtesy CIMSS/SSEC",
        "scan_time_utc": iso_z(frame_time),
        "forecast_window_start_utc": iso_z(frame_time),
        "forecast_window_end_utc": iso_z(frame_time + timedelta(minutes=60)),
        "fetched_at_utc": iso_z(fetched_at),
        "frame_age_minutes_at_fetch": age_minutes,
        "probability_thresholds_percent": list(THRESHOLDS),
        "standard_threshold_note": (
            "10%, 30%, 50%, 70%, and 90% are standard LightningCast probability categories; "
            "a frame may validly contain zero contours at any category."
        ),
        "source_urls": {"GOES-East": east_url, "GOES-West": west_url},
        "source_permission": (
            "CIMSS/SSEC permission obtained by the WPC dashboard project owner for direct server pulls "
            "and dashboard display."
        ),
        "satellite_ownership": {
            "method": "exclusive fixed longitude ownership",
            "seam_longitude": OWNERSHIP_SEAM_LON,
            "GOES-West": f"longitude < {OWNERSHIP_SEAM_LON}",
            "GOES-East": f"longitude >= {OWNERSHIP_SEAM_LON}",
            "summation": False,
            "averaging": False,
            "blending": False,
            "gap_fill": False,
            "note": "Dashboard-defined seam retained for consistency with the observed GLM controlled-mosaic suite.",
        },
        "rendering": {
            "image_crs": "EPSG:3857",
            "leaflet_bounds": [[RENDER_SOUTH, RENDER_WEST], [RENDER_NORTH, RENDER_EAST]],
            "rendered_shape": [render["height"], render["width"]],
            "threshold_labels": [f">= {t}%" for t in THRESHOLDS],
            "threshold_rgba": [list(THRESHOLD_RGBA[t]) for t in THRESHOLDS],
            "source_threshold_rgb": [list(THRESHOLD_RGB_SOURCE[t]) for t in THRESHOLDS],
            "closed_contours_filled": True,
            "open_contours_line_only": True,
            "resampling": "not applicable; vector contours rendered directly to Web Mercator",
        },
        "source_summary": {
            "GOES-East": source_summary(east, east_fetch, frame_time),
            "GOES-West": source_summary(west, west_fetch, frame_time),
        },
        "render_summary": render,
        "leaflet_png": png_name,
        "generated_time_utc": iso_z(utc_now()),
    }
    (output_dir / metadata_name).write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")

    manifest = {
        "manifest_mode": "lightningcast_dashboard_manifest_v1",
        "scan_time_utc": iso_z(frame_time),
        "forecast_window_end_utc": iso_z(frame_time + timedelta(minutes=60)),
        "probability_thresholds_percent": list(THRESHOLDS),
        "products": {
            "probability_next_60_minutes": {"png": png_name, "metadata_json": metadata_name}
        },
        "generated_time_utc": metadata["generated_time_utc"],
    }
    (output_dir / manifest_name).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

def run_self_test() -> None:
    east_sample = '''Title: NOAA LightningCast loop -- GOES-East CONUS sector
Refresh: 1
TimeRange: 2026-08-08T16:00:17Z 2026-08-08T16:05:17Z
Color: 080 201 134
Line: 2, 0, "GOES-East CONUS scan time: 2026-08-08 16:00Z\\nP(LTG) >= 10% in next 60 minutes at every encompassed location."
35.0, -105.0
36.0, -105.0
36.0, -103.0
35.0, -103.0
35.0, -105.0
End:
Color: 255 080 255
Line: 2, 0, "GOES-East CONUS scan time: 2026-08-08 16:00Z\\nP(LTG) >= 90% in next 60 minutes at every encompassed location."
35.2, -104.8
35.8, -104.8
35.8, -104.0
35.2, -104.0
35.2, -104.8
End:
'''
    west_sample = '''Title: NOAA LightningCast loop -- GOES-West CONUS sector
Refresh: 1
TimeRange: 2026-08-08T16:00:17Z 2026-08-08T16:05:17Z
Color: 255 255 081
Line: 2, 0, "GOES-West CONUS scan time: 2026-08-08 16:00Z\\nP(LTG) >= 30% in next 60 minutes at every encompassed location."
34.0, -112.0
35.0, -112.0
35.0, -108.0
34.0, -108.0
34.0, -112.0
End:
'''
    east = parse_placefile(east_sample, "East")
    west = parse_placefile(west_sample, "West")
    frame = latest_common_frame(east, west)
    assert iso_z(frame) == "2026-08-08T16:00:00Z"
    assert len(east.contours_by_frame[frame]) == 2
    assert any(c.threshold == 90 for c in east.contours_by_frame[frame])
    assert len(west.contours_by_frame[frame]) == 1

    import tempfile
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "test.png"
        summary = render_product(frame, east, west, path, 600)
        assert path.exists() and path.stat().st_size > 100
        assert summary["has_visible_pixels"] is True
        with Image.open(path) as image:
            assert image.mode == "RGBA"
            assert image.getchannel("A").getbbox() is not None
    print("LightningCast production parser/rendering self-test passed.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--east-url", default=os.environ.get("LIGHTNINGCAST_EAST_URL", DEFAULT_EAST_URL))
    parser.add_argument("--west-url", default=os.environ.get("LIGHTNINGCAST_WEST_URL", DEFAULT_WEST_URL))
    parser.add_argument("--output-dir", default="lightningcast_output")
    parser.add_argument("--timeout-seconds", type=int, default=60)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--maximum-bytes", type=int, default=80_000_000)
    parser.add_argument("--maximum-age-minutes", type=float, default=20.0)
    parser.add_argument("--maximum-render-dimension", type=int, default=DEFAULT_MAXIMUM_DIMENSION)
    parser.add_argument("--self-test", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.self_test:
        run_self_test()
        return 0

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    fetched_at = utc_now()

    try:
        east_text, east_fetch = fetch_text(args.east_url, args.timeout_seconds, args.retries, args.maximum_bytes)
        west_text, west_fetch = fetch_text(args.west_url, args.timeout_seconds, args.retries, args.maximum_bytes)
        east = parse_placefile(east_text, "East")
        west = parse_placefile(west_text, "West")
        frame_time = latest_common_frame(east, west)
        if frame_time is None:
            raise RuntimeError("no scan time common to both GOES-East and GOES-West LightningCast loops")
        age_minutes = (fetched_at - frame_time).total_seconds() / 60.0
        if age_minutes < -5:
            raise RuntimeError(f"selected common frame is {-age_minutes:.1f} minutes in the future")
        if age_minutes > args.maximum_age_minutes:
            raise RuntimeError(
                f"selected common frame is {age_minutes:.1f} minutes old; maximum is {args.maximum_age_minutes:.1f} minutes"
            )
        if east.invalid_coordinate_lines or west.invalid_coordinate_lines:
            raise RuntimeError(
                f"invalid coordinate lines parsed: East={east.invalid_coordinate_lines}, West={west.invalid_coordinate_lines}"
            )
        write_outputs(
            output_dir,
            args.east_url,
            args.west_url,
            east,
            west,
            east_fetch,
            west_fetch,
            frame_time,
            fetched_at,
            args.maximum_render_dimension,
        )
        print(f"LightningCast product built for {iso_z(frame_time)}")
        print(f"Output: {output_dir / 'lightningcast_conus_probability_60min.png'}")
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
