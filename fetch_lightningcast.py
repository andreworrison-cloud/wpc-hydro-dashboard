#!/usr/bin/env python3
"""Build the WPC Hydrometeorological Dashboard LightningCast CONUS product.

Retrieves authorized CIMSS/SSEC GOES-East and GOES-West CONUS LightningCast
placefile loops, selects the newest clean scan common to both feeds within the freshness window, groups nested LightningCast contours into coherent storm objects, applies the established v1E East/West ownership logic, and renders the native LightningCast probability contours to a transparent Web-Mercator PNG plus metadata and a compact manifest.

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

OWNERSHIP_LONGITUDE = -106.1
OBJECT_LINK_PADDING_DEGREES = 0.18
OBJECT_SWAP_PADDING_DEGREES = 0.25
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
        return contour_is_closed(self.points)

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        lons = [point[0] for point in self.points]
        lats = [point[1] for point in self.points]
        return min(lons), min(lats), max(lons), max(lats)

    @property
    def representative_lon(self) -> float:
        if not self.points:
            return 0.0
        return sum(point[0] for point in self.points) / len(self.points)


@dataclasses.dataclass
class StormObject:
    satellite: str
    contours: list[Contour]

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        boxes = [contour.bbox for contour in self.contours]
        return (
            min(box[0] for box in boxes),
            min(box[1] for box in boxes),
            max(box[2] for box in boxes),
            max(box[3] for box in boxes),
        )

    @property
    def representative_lon(self) -> float:
        # Give the outer 10% contour family the strongest geographic weight when present.
        anchors = [contour for contour in self.contours if contour.threshold == min(c.threshold for c in self.contours)]
        points = [point for contour in anchors for point in contour.points]
        if not points:
            points = [point for contour in self.contours for point in contour.points]
        return sum(point[0] for point in points) / len(points) if points else 0.0

    @property
    def thresholds(self) -> tuple[int, ...]:
        return tuple(sorted({contour.threshold for contour in self.contours}))

    @property
    def contour_count(self) -> int:
        return len(self.contours)

    @property
    def closed_count(self) -> int:
        return sum(1 for contour in self.contours if contour.closed)

    @property
    def threshold_count(self) -> int:
        return len(self.thresholds)

    @property
    def completeness_score(self) -> tuple[int, int, int, float]:
        return (
            self.closed_count,
            self.threshold_count,
            self.contour_count,
            -abs(self.representative_lon - OWNERSHIP_LONGITUDE),
        )


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
    invalid_lines_by_frame: dict[datetime, int]
    invalid_line_examples_by_frame: dict[datetime, list[str]]
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
    invalid_lines_by_frame: dict[datetime, int] = defaultdict(int)
    invalid_line_examples_by_frame: dict[datetime, list[str]] = defaultdict(list)
    discarded_short_contours = 0
    satellite_names_seen: set[str] = set()
    warnings: list[str] = []
    current_color: tuple[int, int, int] | None = None
    current: Contour | None = None

    def record_invalid(frame_time: datetime | None, raw_value: str) -> None:
        nonlocal invalid_coordinate_lines
        invalid_coordinate_lines += 1
        if frame_time is None:
            return
        invalid_lines_by_frame[frame_time] += 1
        examples = invalid_line_examples_by_frame[frame_time]
        if len(examples) < 5:
            examples.append(raw_value[:240])

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
                record_invalid(current.scan_time, line)
            continue
        if current is not None and line and not line.startswith(("Color:", "Line:", "TimeRange:")):
            record_invalid(current.scan_time, line)

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
        invalid_lines_by_frame=dict(invalid_lines_by_frame),
        invalid_line_examples_by_frame=dict(invalid_line_examples_by_frame),
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


def contour_is_closed(points: Sequence[tuple[float, float]], tolerance_degrees: float = 0.20) -> bool:
    if len(points) < 3:
        return False
    lon0, lat0 = points[0]
    lon1, lat1 = points[-1]
    return math.hypot(lon1 - lon0, lat1 - lat0) <= tolerance_degrees


def contour_longitude_extent(contours: Sequence[Contour]) -> tuple[float, float] | None:
    lons: list[float] = []
    for contour in contours:
        lons.extend(point[0] for point in contour.points)
    if not lons:
        return None
    return min(lons), max(lons)


def clip_polygon_to_render_bounds(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    result = points[:]
    result = clip_polygon_halfplane(result, "lon", RENDER_WEST, True)
    result = clip_polygon_halfplane(result, "lon", RENDER_EAST, False)
    result = clip_polygon_halfplane(result, "lat", RENDER_SOUTH, True)
    result = clip_polygon_halfplane(result, "lat", RENDER_NORTH, False)
    return result


def close_contour_if_nearly_closed(points: list[tuple[float, float]], tolerance_degrees: float = 0.20) -> list[tuple[float, float]]:
    if contour_is_closed(points, tolerance_degrees):
        if points[0] != points[-1]:
            return points + [points[0]]
    return points


def bbox_intersects_or_near(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
    padding: float = OBJECT_LINK_PADDING_DEGREES,
) -> bool:
    return not (
        a[2] + padding < b[0]
        or b[2] + padding < a[0]
        or a[3] + padding < b[1]
        or b[3] + padding < a[1]
    )


def group_contours_into_objects(contours: Sequence[Contour], satellite: str) -> list[StormObject]:
    """Group nested/adjacent probability contours into same-satellite storm objects.

    Connectivity uses bounding-box overlap with a small tolerance so the 10/30/50/70/90
    family for a convective feature is handled as one ownership unit. The source contour
    coordinates themselves are never changed by this grouping.
    """
    candidates = [contour for contour in contours if contour.threshold in THRESHOLDS and contour.points]
    if not candidates:
        return []

    parents = list(range(len(candidates)))

    def find(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parents[rb] = ra

    for i, left in enumerate(candidates):
        for j in range(i + 1, len(candidates)):
            right = candidates[j]
            # Different thresholds are the most important links; same-threshold links are
            # allowed only when their boxes actually overlap, which avoids joining distinct
            # nearby storms merely because the tolerance boxes touch.
            padding = OBJECT_LINK_PADDING_DEGREES if left.threshold != right.threshold else 0.0
            if bbox_intersects_or_near(left.bbox, right.bbox, padding):
                union(i, j)

    grouped: dict[int, list[Contour]] = defaultdict(list)
    for index, contour in enumerate(candidates):
        grouped[find(index)].append(contour)

    return [StormObject(satellite=satellite, contours=value) for value in grouped.values()]


def storm_object_owner(storm: StormObject) -> str:
    """Assign an intact nested probability family to one satellite.

    The fixed longitude is an ownership discriminator only. No source contour is clipped,
    split, closed, or reshaped at this longitude.
    """
    return "West" if storm.representative_lon < OWNERSHIP_LONGITUDE else "East"


def should_swap_to_alternate(primary: StormObject, alternate: StormObject) -> bool:
    """Use an overlapping opposite-satellite family only when it is materially more complete."""
    if alternate.completeness_score <= primary.completeness_score:
        return False
    if alternate.closed_count > primary.closed_count:
        return True
    if alternate.threshold_count > primary.threshold_count:
        return True
    if alternate.contour_count >= primary.contour_count + 2:
        return True
    return False


def select_contours_for_render(
    frame_time: datetime, east: ParsedPlacefile, west: ParsedPlacefile
) -> tuple[dict[int, list[Contour]], dict[str, Counter], dict[str, object]]:
    selected: dict[int, list[Contour]] = {threshold: [] for threshold in THRESHOLDS}
    ownership_counts: dict[str, Counter] = {"East": Counter(), "West": Counter()}

    west_objects = group_contours_into_objects(west.contours_by_frame.get(frame_time, []), "West")
    east_objects = group_contours_into_objects(east.contours_by_frame.get(frame_time, []), "East")

    west_selected = {index for index, storm in enumerate(west_objects) if storm_object_owner(storm) == "West"}
    east_selected = {index for index, storm in enumerate(east_objects) if storm_object_owner(storm) == "East"}

    swaps: list[dict[str, object]] = []
    used_west: set[int] = set()
    used_east: set[int] = set()

    for sat_name, selected_ids, objects, other_name, other_objects, other_selected in (
        ("West", west_selected, west_objects, "East", east_objects, east_selected),
        ("East", east_selected, east_objects, "West", west_objects, west_selected),
    ):
        for idx in list(selected_ids):
            if sat_name == "West" and idx in used_west:
                continue
            if sat_name == "East" and idx in used_east:
                continue
            primary = objects[idx]
            overlapping = []
            for j, candidate in enumerate(other_objects):
                if j in other_selected:
                    continue
                if (other_name == "West" and j in used_west) or (other_name == "East" and j in used_east):
                    continue
                if bbox_intersects_or_near(primary.bbox, candidate.bbox, OBJECT_SWAP_PADDING_DEGREES):
                    overlapping.append((j, candidate))
            if not overlapping:
                continue
            best_j, best_candidate = max(overlapping, key=lambda item: item[1].completeness_score)
            if should_swap_to_alternate(primary, best_candidate):
                selected_ids.discard(idx)
                other_selected.add(best_j)
                if sat_name == "West":
                    used_east.add(best_j)
                else:
                    used_west.add(best_j)
                swaps.append({
                    "replaced_satellite": sat_name,
                    "replaced_thresholds": list(primary.thresholds),
                    "replacement_satellite": other_name,
                    "replacement_thresholds": list(best_candidate.thresholds),
                    "primary_score": list(primary.completeness_score[:3]),
                    "alternate_score": list(best_candidate.completeness_score[:3]),
                    "primary_bbox": [round(v, 3) for v in primary.bbox],
                    "alternate_bbox": [round(v, 3) for v in best_candidate.bbox],
                })

    object_summary: dict[str, object] = {}
    for satellite, objects, selected_ids in (("West", west_objects, west_selected), ("East", east_objects, east_selected)):
        retained = [storm for i, storm in enumerate(objects) if i in selected_ids]
        rejected = [storm for i, storm in enumerate(objects) if i not in selected_ids]
        for storm in retained:
            for contour in storm.contours:
                selected[contour.threshold].append(contour)
                ownership_counts[satellite][contour.threshold] += 1
        object_summary[satellite] = {
            "source_object_count": len(objects),
            "retained_object_count": len(retained),
            "rejected_object_count": len(rejected),
            "retained_threshold_families": {
                ",".join(str(value) for value in storm.thresholds): sum(
                    1 for candidate in retained if candidate.thresholds == storm.thresholds
                )
                for storm in retained
            },
            "retained_closed_contours": sum(storm.closed_count for storm in retained),
            "retained_total_contours": sum(storm.contour_count for storm in retained),
        }
    object_summary["cross_satellite_family_swaps"] = swaps
    object_summary["cross_satellite_family_splitting"] = False
    object_summary["swap_padding_degrees"] = OBJECT_SWAP_PADDING_DEGREES

    return selected, ownership_counts, object_summary


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


def clip_segment_to_rect(
    p0: tuple[float, float], p1: tuple[float, float]
) -> tuple[tuple[float, float], tuple[float, float]] | None:
    xmin, xmax = RENDER_WEST, RENDER_EAST
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
    selected_counts: dict[str, Counter] = {"East": Counter(), "West": Counter()}
    rendered_lines: Counter = Counter()
    source_color_mismatches: list[str] = []

    selected_contours, ownership_counts, object_summary = select_contours_for_render(frame_time, east, west)

    for threshold in THRESHOLDS:
        stroke = (*THRESHOLD_RGB_SOURCE[threshold], 242)
        for satellite, parsed in (("West", west), ("East", east)):
            contours = [c for c in parsed.contours_by_frame.get(frame_time, []) if c.threshold == threshold]
            source_counts[satellite][threshold] = len(contours)
            selected_counts[satellite][threshold] = ownership_counts[satellite][threshold]

        for contour in selected_contours[threshold]:
            if contour.color is not None and contour.color != THRESHOLD_RGB_SOURCE[threshold]:
                source_color_mismatches.append(
                    f"GOES-{contour.satellite} {threshold}% source RGB {contour.color} differs from expected {THRESHOLD_RGB_SOURCE[threshold]}"
                )
            any_segment = False
            for a, b in zip(contour.points[:-1], contour.points[1:]):
                clipped = clip_segment_to_rect(a, b)
                if clipped is None:
                    continue
                pixels = [
                    project_to_pixel(*clipped[0], width, height),
                    project_to_pixel(*clipped[1], width, height),
                ]
                draw.line(pixels, fill=stroke, width=2)
                any_segment = True
            if any_segment:
                rendered_lines[threshold] += 1

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
        "selected_contours_by_satellite_and_threshold": {
            satellite: {str(t): int(counter[t]) for t in THRESHOLDS}
            for satellite, counter in selected_counts.items()
        },
        "rendered_contour_lines_by_threshold": {str(t): int(rendered_lines[t]) for t in THRESHOLDS},
        "source_color_mismatches": sorted(set(source_color_mismatches)),
        "ownership_longitude": OWNERSHIP_LONGITUDE,
        "storm_object_summary": object_summary,
    }


def common_frames_newest_first(east: ParsedPlacefile, west: ParsedPlacefile) -> list[datetime]:
    return sorted(east.frame_times & west.frame_times, reverse=True)


def frame_invalid_count(parsed: ParsedPlacefile, frame_time: datetime) -> int:
    return int(parsed.invalid_lines_by_frame.get(frame_time, 0))


def select_clean_common_frame(
    east: ParsedPlacefile,
    west: ParsedPlacefile,
    fetched_at: datetime,
    maximum_age_minutes: float,
) -> tuple[datetime, dict[str, object]]:
    common = common_frames_newest_first(east, west)
    if not common:
        raise RuntimeError("no scan time common to both GOES-East and GOES-West LightningCast loops")

    skipped_dirty: list[dict[str, object]] = []
    skipped_future: list[str] = []
    stale_newest: datetime | None = None

    for frame_time in common:
        age_minutes = (fetched_at - frame_time).total_seconds() / 60.0
        if age_minutes < -5:
            skipped_future.append(iso_z(frame_time) or "unknown")
            continue
        if age_minutes > maximum_age_minutes:
            if stale_newest is None:
                stale_newest = frame_time
            break

        east_bad = frame_invalid_count(east, frame_time)
        west_bad = frame_invalid_count(west, frame_time)
        if east_bad or west_bad:
            skipped_dirty.append({
                "scan_time_utc": iso_z(frame_time),
                "age_minutes": round(age_minutes, 2),
                "GOES-East_invalid_lines": east_bad,
                "GOES-West_invalid_lines": west_bad,
            })
            continue

        return frame_time, {
            "policy": "newest clean exact-common frame within freshness window",
            "selected_frame_clean": True,
            "selected_frame_age_minutes": round(age_minutes, 2),
            "skipped_dirty_common_frames": skipped_dirty,
            "skipped_future_common_frames": skipped_future,
            "newest_common_frame_utc": iso_z(common[0]),
            "newest_east_frame_utc": iso_z(max(east.frame_times)) if east.frame_times else None,
            "newest_west_frame_utc": iso_z(max(west.frame_times)) if west.frame_times else None,
        }

    if skipped_dirty:
        details = "; ".join(
            f"{item['scan_time_utc']} East={item['GOES-East_invalid_lines']} West={item['GOES-West_invalid_lines']}"
            for item in skipped_dirty[:5]
        )
        raise RuntimeError(
            f"no clean common LightningCast frame within {maximum_age_minutes:.1f} minutes; dirty recent frames: {details}"
        )

    reference = stale_newest or common[0]
    age_minutes = (fetched_at - reference).total_seconds() / 60.0
    raise RuntimeError(
        f"selected common frame is {age_minutes:.1f} minutes old; maximum is {maximum_age_minutes:.1f} minutes"
    )


def latest_common_frame(east: ParsedPlacefile, west: ParsedPlacefile) -> datetime | None:
    common = common_frames_newest_first(east, west)
    return common[0] if common else None


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
        "invalid_lines_by_frame": {
            iso_z(frame): int(count) for frame, count in sorted(parsed.invalid_lines_by_frame.items())
        },
        "invalid_line_examples_by_frame": {
            iso_z(frame): examples for frame, examples in sorted(parsed.invalid_line_examples_by_frame.items())
        },
        "selected_frame_invalid_lines": frame_invalid_count(parsed, frame_time),
        "discarded_short_contours": parsed.discarded_short_contours,
        "warnings": parsed.warnings,
        "fetch": fetch_meta,
    }


def write_source_diagnostics(
    output_dir: Path,
    east: ParsedPlacefile,
    west: ParsedPlacefile,
    east_fetch: dict[str, object],
    west_fetch: dict[str, object],
    fetched_at: datetime,
) -> None:
    def one(parsed: ParsedPlacefile, fetch_meta: dict[str, object]) -> dict[str, object]:
        return {
            "newest_frame_utc": iso_z(max(parsed.frame_times)) if parsed.frame_times else None,
            "frame_count": len(parsed.frame_times),
            "invalid_coordinate_lines_total": parsed.invalid_coordinate_lines,
            "invalid_lines_by_frame": {
                iso_z(frame): int(count) for frame, count in sorted(parsed.invalid_lines_by_frame.items())
            },
            "invalid_line_examples_by_frame": {
                iso_z(frame): examples for frame, examples in sorted(parsed.invalid_line_examples_by_frame.items())
            },
            "warnings": parsed.warnings,
            "fetch": fetch_meta,
        }

    common = common_frames_newest_first(east, west)
    payload = {
        "diagnostic_mode": "lightningcast_source_integrity_v1",
        "fetched_at_utc": iso_z(fetched_at),
        "newest_common_frames_utc": [iso_z(frame) for frame in common[:12]],
        "GOES-East": one(east, east_fetch),
        "GOES-West": one(west, west_fetch),
    }
    (output_dir / "lightningcast_source_diagnostics.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )


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
    frame_selection: dict[str, object],
) -> None:
    png_name = "lightningcast_conus_probability_60min.png"
    metadata_name = "lightningcast_conus_probability_60min_metadata.json"
    manifest_name = "lightningcast_manifest.json"
    png_path = output_dir / png_name
    render = render_product(frame_time, east, west, png_path, maximum_dimension)

    age_minutes = round((fetched_at - frame_time).total_seconds() / 60.0, 2)
    metadata = {
        "metadata_mode": "lightningcast_dashboard_v1e",
        "generator_revision": "v1f_frame_scoped_integrity",
        "product_role": "probability_of_lightning_next_60_minutes",
        "display_label": "CIMSS/SSEC LightningCast — Probability of Lightning in Next 60 Minutes",
        "source_product": "LightningCast CONUS GRLevelX probability contour placefile loops",
        "source_attribution": "LightningCast data courtesy CIMSS/SSEC",
        "scan_time_utc": iso_z(frame_time),
        "forecast_window_start_utc": iso_z(frame_time),
        "forecast_window_end_utc": iso_z(frame_time + timedelta(minutes=60)),
        "fetched_at_utc": iso_z(fetched_at),
        "frame_age_minutes_at_fetch": age_minutes,
        "frame_selection": frame_selection,
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
            "method": "fixed whole-storm-object representative-longitude ownership with completeness-based overlap swaps",
            "ownership_longitude": OWNERSHIP_LONGITUDE,
            "GOES-West": f"whole same-satellite contour families with representative longitude < {OWNERSHIP_LONGITUDE}",
            "GOES-East": f"whole same-satellite contour families with representative longitude >= {OWNERSHIP_LONGITUDE}",
            "summation": False,
            "averaging": False,
            "blending": False,
            "gap_fill": False,
            "cross_boundary_geometry_clipping": False,
            "cross_threshold_family_splitting": False,
            "cross_satellite_family_splitting": False,
            "swap_padding_degrees": OBJECT_SWAP_PADDING_DEGREES,
            "object_link_padding_degrees": OBJECT_LINK_PADDING_DEGREES,
            "representative_longitude_field": "mean longitude of the object's outermost available probability contour(s)",
            "note": (
                "Nested/adjacent probability contours from one satellite are grouped into a storm object and retained or rejected together. "
                "In the overlap region, a more complete opposite-satellite family may replace a truncated family, but no family is split across satellites. "
                "Source contour geometry is never cut or altered at the ownership longitude."
            ),
        },
        "rendering": {
            "image_crs": "EPSG:3857",
            "leaflet_bounds": [[RENDER_SOUTH, RENDER_WEST], [RENDER_NORTH, RENDER_EAST]],
            "rendered_shape": [render["height"], render["width"]],
            "threshold_labels": [f">= {t}%" for t in THRESHOLDS],
            "threshold_rgba": [list(THRESHOLD_RGBA[t]) for t in THRESHOLDS],
            "source_threshold_rgb": [list(THRESHOLD_RGB_SOURCE[t]) for t in THRESHOLDS],
            "contour_lines_only": True,
            "polygon_fill_inference": False,
            "line_width_pixels": 2,
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
        assert summary["ownership_longitude"] == OWNERSHIP_LONGITUDE
        assert "storm_object_summary" in summary
        assert summary["storm_object_summary"]["cross_satellite_family_splitting"] is False
        assert sum(summary["rendered_contour_lines_by_threshold"].values()) >= 1
        with Image.open(path) as image:
            assert image.mode == "RGBA"
            assert image.getchannel("A").getbbox() is not None

    # Frame-scoped integrity test: newest West frame is malformed, previous common frame is clean.
    east_integrity = '''Title: NOAA LightningCast loop -- GOES-East CONUS sector
Refresh: 1
TimeRange: 2026-08-08T16:05:17Z 2026-08-08T16:10:17Z
Color: 080 201 134
Line: 2, 0, "GOES-East CONUS scan time: 2026-08-08 16:05Z\\nP(LTG) >= 10% in next 60 minutes at every encompassed location."
35.0, -105.0
36.0, -105.0
End:
TimeRange: 2026-08-08T16:00:17Z 2026-08-08T16:05:17Z
Color: 080 201 134
Line: 2, 0, "GOES-East CONUS scan time: 2026-08-08 16:00Z\\nP(LTG) >= 10% in next 60 minutes at every encompassed location."
35.0, -105.0
36.0, -105.0
End:
'''
    west_integrity = '''Title: NOAA LightningCast loop -- GOES-West CONUS sector
Refresh: 1
TimeRange: 2026-08-08T16:05:17Z 2026-08-08T16:10:17Z
Color: 080 201 134
Line: 2, 0, "GOES-West CONUS scan time: 2026-08-08 16:05Z\\nP(LTG) >= 10% in next 60 minutes at every encompassed location."
35.0, -112.0
nan, -111.0
36.0, -112.0
End:
TimeRange: 2026-08-08T16:00:17Z 2026-08-08T16:05:17Z
Color: 080 201 134
Line: 2, 0, "GOES-West CONUS scan time: 2026-08-08 16:00Z\\nP(LTG) >= 10% in next 60 minutes at every encompassed location."
35.0, -112.0
36.0, -112.0
End:
'''
    ei = parse_placefile(east_integrity, "East")
    wi = parse_placefile(west_integrity, "West")
    now = datetime(2026, 8, 8, 16, 10, tzinfo=UTC)
    chosen, selection = select_clean_common_frame(ei, wi, now, 20.0)
    assert iso_z(chosen) == "2026-08-08T16:00:00Z"
    assert frame_invalid_count(wi, datetime(2026, 8, 8, 16, 5, tzinfo=UTC)) == 1
    assert selection["selected_frame_clean"] is True
    assert len(selection["skipped_dirty_common_frames"]) == 1

    print("LightningCast production parser/rendering/frame-integrity self-test passed.")

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
        write_source_diagnostics(output_dir, east, west, east_fetch, west_fetch, fetched_at)

        if east.invalid_coordinate_lines or west.invalid_coordinate_lines:
            print(
                f"Source loop integrity notice: invalid lines across full loops East={east.invalid_coordinate_lines}, West={west.invalid_coordinate_lines}",
                file=sys.stderr,
            )
            for label, parsed in (("East", east), ("West", west)):
                for dirty_frame, count in sorted(parsed.invalid_lines_by_frame.items(), reverse=True)[:5]:
                    examples = parsed.invalid_line_examples_by_frame.get(dirty_frame, [])
                    sample = f"; example={examples[0]!r}" if examples else ""
                    print(f"  GOES-{label} dirty frame {iso_z(dirty_frame)}: {count} invalid line(s){sample}", file=sys.stderr)

        frame_time, frame_selection = select_clean_common_frame(
            east, west, fetched_at, args.maximum_age_minutes
        )
        skipped = frame_selection.get("skipped_dirty_common_frames") or []
        if skipped:
            print(
                f"Selected clean fallback common frame {iso_z(frame_time)} after skipping {len(skipped)} dirty newer common frame(s).",
                file=sys.stderr,
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
            frame_selection,
        )
        print(f"LightningCast product built for {iso_z(frame_time)}")
        print(f"Output: {output_dir / 'lightningcast_conus_probability_60min.png'}")
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
