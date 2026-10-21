#!/usr/bin/env python3
"""Test-only LightningCast source diagnostic.

This utility downloads GOES-East and GOES-West LightningCast CONUS placefile
loops, parses only enough geometry to validate the feed, and writes compact
JSON/Markdown summaries. It intentionally does not save or republish contour
coordinates.

The default URLs are the public NOAA/CIMSS test feeds. They are suitable for a
nonpublishing source diagnostic only. Production dashboard use should be moved
to an authorized NOAA operational distribution endpoint when that endpoint is
available to the project.
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
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence

UTC = timezone.utc
DEFAULT_EAST_URL = (
    "https://cimss.ssec.wisc.edu/severe_conv/"
    "NOAACIMSS_PLTG_GOES-East_CONUS_LOOP"
)
DEFAULT_WEST_URL = (
    "https://cimss.ssec.wisc.edu/severe_conv/"
    "NOAACIMSS_PLTG_GOES-West_CONUS_LOOP"
)
EXPECTED_THRESHOLDS = (10, 30, 50, 70)
USER_AGENT = (
    "WPC-Hydrometeorological-Dashboard-LightningCast-Diagnostic/1.0 "
    "(test-only; no contour redistribution)"
)

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
class ContourAccumulator:
    satellite: str
    scan_time: datetime
    threshold: int
    color: tuple[int, int, int] | None
    point_count: int = 0
    min_lat: float = math.inf
    max_lat: float = -math.inf
    min_lon: float = math.inf
    max_lon: float = -math.inf

    def add(self, lat: float, lon: float) -> None:
        self.point_count += 1
        self.min_lat = min(self.min_lat, lat)
        self.max_lat = max(self.max_lat, lat)
        self.min_lon = min(self.min_lon, lon)
        self.max_lon = max(self.max_lon, lon)


@dataclasses.dataclass
class ParsedPlacefile:
    expected_satellite: str
    title: str | None
    refresh_seconds: int | None
    time_ranges: list[tuple[datetime, datetime]]
    frame_counts: dict[datetime, Counter]
    frame_point_counts: dict[datetime, Counter]
    frame_bounds: dict[datetime, list[float]]
    threshold_colors: dict[int, set[tuple[int, int, int]]]
    parsed_contours: int
    discarded_contours: int
    invalid_coordinate_lines: int
    satellite_names_seen: set[str]
    warnings: list[str]


def utc_now() -> datetime:
    return datetime.now(tz=UTC)


def iso_z(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso_z(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


def parse_scan_time(date_text: str, minute_text: str) -> datetime:
    return datetime.strptime(
        f"{date_text} {minute_text}", "%Y-%m-%d %H:%M"
    ).replace(tzinfo=UTC)


def parse_thresholds(value: str) -> tuple[int, ...]:
    thresholds = tuple(sorted({int(item.strip()) for item in value.split(",") if item.strip()}))
    if not thresholds or any(item < 0 or item > 100 for item in thresholds):
        raise argparse.ArgumentTypeError("thresholds must be comma-separated integers from 0 to 100")
    return thresholds


def safe_age_minutes(scan_time: datetime | None, reference: datetime) -> float | None:
    if scan_time is None:
        return None
    return round((reference - scan_time).total_seconds() / 60.0, 2)


def fetch_text(
    url: str,
    timeout_seconds: int,
    retries: int,
    maximum_bytes: int,
) -> tuple[str, dict[str, object]]:
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
                    raise RuntimeError(
                        f"Content-Length {content_length} exceeds maximum {maximum_bytes} bytes"
                    )
                raw = response.read(maximum_bytes + 1)
                if len(raw) > maximum_bytes:
                    raise RuntimeError(f"response exceeded maximum {maximum_bytes} bytes")
                elapsed = round(time.monotonic() - started, 3)
                return raw.decode("utf-8", errors="replace"), {
                    "http_status": status,
                    "content_type": response.headers.get("Content-Type"),
                    "content_length_header": content_length,
                    "last_modified": response.headers.get("Last-Modified"),
                    "etag": response.headers.get("ETag"),
                    "download_seconds": elapsed,
                    "download_attempt": attempt,
                    "bytes_downloaded": len(raw),
                    "sha256": hashlib.sha256(raw).hexdigest(),
                }
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, RuntimeError) as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(min(2 ** (attempt - 1), 8))
    raise RuntimeError(f"failed after {retries} attempts: {last_error}")


def update_bounds(target: list[float] | None, contour: ContourAccumulator) -> list[float]:
    if target is None:
        return [contour.min_lat, contour.max_lat, contour.min_lon, contour.max_lon]
    target[0] = min(target[0], contour.min_lat)
    target[1] = max(target[1], contour.max_lat)
    target[2] = min(target[2], contour.min_lon)
    target[3] = max(target[3], contour.max_lon)
    return target


def parse_placefile(text: str, expected_satellite: str) -> ParsedPlacefile:
    title: str | None = None
    refresh_seconds: int | None = None
    time_ranges: list[tuple[datetime, datetime]] = []
    frame_counts: dict[datetime, Counter] = defaultdict(Counter)
    frame_point_counts: dict[datetime, Counter] = defaultdict(Counter)
    frame_bounds: dict[datetime, list[float]] = {}
    threshold_colors: dict[int, set[tuple[int, int, int]]] = defaultdict(set)
    current_color: tuple[int, int, int] | None = None
    current: ContourAccumulator | None = None
    parsed_contours = 0
    discarded_contours = 0
    invalid_coordinate_lines = 0
    satellite_names_seen: set[str] = set()
    warnings: list[str] = []

    def finalize_current() -> None:
        nonlocal current, parsed_contours, discarded_contours
        if current is None:
            return
        if current.point_count >= 2:
            frame_counts[current.scan_time][current.threshold] += 1
            frame_point_counts[current.scan_time][current.threshold] += current.point_count
            frame_bounds[current.scan_time] = update_bounds(
                frame_bounds.get(current.scan_time), current
            )
            if current.color is not None:
                threshold_colors[current.threshold].add(current.color)
            parsed_contours += 1
        else:
            discarded_contours += 1
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
            finalize_current()
            time_ranges.append((parse_iso_z(match.group(1)), parse_iso_z(match.group(2))))
            continue
        match = COLOR_RE.match(line)
        if match:
            values = tuple(int(match.group(index)) for index in range(1, 4))
            if any(value < 0 or value > 255 for value in values):
                warnings.append(f"invalid RGB value ignored: {values}")
                current_color = None
            else:
                current_color = values
            continue
        match = LINE_HEADER_RE.match(line)
        if match:
            finalize_current()
            satellite = match.group(1).title()
            satellite_names_seen.add(satellite)
            current = ContourAccumulator(
                satellite=satellite,
                scan_time=parse_scan_time(match.group(2), match.group(3)),
                threshold=int(match.group(4)),
                color=current_color,
            )
            continue
        if line.strip().lower() == "end:":
            finalize_current()
            continue
        match = COORD_RE.match(line)
        if match and current is not None:
            lat = float(match.group(1))
            lon = float(match.group(2))
            if -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0:
                current.add(lat, lon)
            else:
                invalid_coordinate_lines += 1
            continue
        if current is not None and line and not line.startswith(("Color:", "Line:", "TimeRange:")):
            invalid_coordinate_lines += 1

    finalize_current()

    if not text.strip():
        warnings.append("empty source document")
    if title is None:
        warnings.append("missing Title command")
    if not time_ranges:
        warnings.append("no TimeRange commands parsed")
    if not frame_counts:
        warnings.append("no contour geometry parsed")
    if satellite_names_seen and expected_satellite not in satellite_names_seen:
        warnings.append(
            f"expected GOES-{expected_satellite}, saw {sorted(satellite_names_seen)}"
        )

    return ParsedPlacefile(
        expected_satellite=expected_satellite,
        title=title,
        refresh_seconds=refresh_seconds,
        time_ranges=time_ranges,
        frame_counts=dict(frame_counts),
        frame_point_counts=dict(frame_point_counts),
        frame_bounds=frame_bounds,
        threshold_colors=dict(threshold_colors),
        parsed_contours=parsed_contours,
        discarded_contours=discarded_contours,
        invalid_coordinate_lines=invalid_coordinate_lines,
        satellite_names_seen=satellite_names_seen,
        warnings=warnings,
    )


def latest_frame_time(parsed: ParsedPlacefile) -> datetime | None:
    if parsed.frame_counts:
        return max(parsed.frame_counts)
    candidates = [start.replace(second=0, microsecond=0) for start, _ in parsed.time_ranges]
    return max(candidates) if candidates else None


def summarize_source(
    satellite: str,
    url: str,
    parsed: ParsedPlacefile,
    fetch_metadata: dict[str, object],
    fetched_at: datetime,
    expected_thresholds: Sequence[int],
    maximum_age_minutes: float,
) -> dict[str, object]:
    latest = latest_frame_time(parsed)
    counts = parsed.frame_counts.get(latest, Counter()) if latest else Counter()
    point_counts = parsed.frame_point_counts.get(latest, Counter()) if latest else Counter()
    bounds = parsed.frame_bounds.get(latest) if latest else None
    observed_thresholds = sorted(parsed.threshold_colors)
    age = safe_age_minutes(latest, fetched_at)
    warnings = list(parsed.warnings)

    if latest is None:
        warnings.append("latest frame time unavailable")
    elif age is not None and age > maximum_age_minutes:
        warnings.append(
            f"latest frame is {age:.1f} minutes old; threshold is {maximum_age_minutes:.1f}"
        )
    elif age is not None and age < -5:
        warnings.append(f"latest frame is {-age:.1f} minutes in the future")

    missing_loop_thresholds = sorted(set(expected_thresholds) - set(observed_thresholds))
    if missing_loop_thresholds:
        warnings.append(
            "expected threshold(s) not observed anywhere in loop: "
            + ", ".join(str(item) for item in missing_loop_thresholds)
        )

    latest_counts = {str(value): int(counts.get(value, 0)) for value in expected_thresholds}
    latest_points = {str(value): int(point_counts.get(value, 0)) for value in expected_thresholds}
    color_summary = {
        str(threshold): [list(color) for color in sorted(colors)]
        for threshold, colors in sorted(parsed.threshold_colors.items())
    }

    return {
        "satellite": f"GOES-{satellite}",
        "sector": "CONUS",
        "source_url": url,
        "source_format": "GRLevelX placefile loop",
        "source_use": "test-only diagnostic; contour coordinates are not retained",
        "fetched_at_utc": iso_z(fetched_at),
        "fetch": fetch_metadata,
        "title": parsed.title,
        "refresh_seconds": parsed.refresh_seconds,
        "satellite_names_seen": sorted(parsed.satellite_names_seen),
        "time_range_count": len(parsed.time_ranges),
        "first_time_range_start_utc": iso_z(min((item[0] for item in parsed.time_ranges), default=None)),
        "latest_time_range_start_utc": iso_z(max((item[0] for item in parsed.time_ranges), default=None)),
        "parsed_frame_count": len(parsed.frame_counts),
        "latest_frame_time_utc": iso_z(latest),
        "latest_frame_age_minutes": age,
        "maximum_age_minutes": maximum_age_minutes,
        "latest_contour_count_total": int(sum(counts.values())),
        "latest_coordinate_count_total": int(sum(point_counts.values())),
        "latest_contours_by_threshold": latest_counts,
        "latest_coordinates_by_threshold": latest_points,
        "latest_bounds": (
            {
                "south": round(bounds[0], 4),
                "north": round(bounds[1], 4),
                "west": round(bounds[2], 4),
                "east": round(bounds[3], 4),
            }
            if bounds
            else None
        ),
        "thresholds_observed_in_loop": observed_thresholds,
        "threshold_colors_observed": color_summary,
        "parsed_contours_across_loop": parsed.parsed_contours,
        "discarded_short_contours": parsed.discarded_contours,
        "invalid_coordinate_lines": parsed.invalid_coordinate_lines,
        "warnings": warnings,
        "usable": latest is not None and parsed.parsed_contours > 0,
        "fresh": age is not None and -5 <= age <= maximum_age_minutes,
    }


def failed_source_summary(
    satellite: str,
    url: str,
    fetched_at: datetime,
    error: Exception,
    maximum_age_minutes: float,
) -> dict[str, object]:
    return {
        "satellite": f"GOES-{satellite}",
        "sector": "CONUS",
        "source_url": url,
        "source_format": "unknown; fetch failed",
        "source_use": "test-only diagnostic",
        "fetched_at_utc": iso_z(fetched_at),
        "maximum_age_minutes": maximum_age_minutes,
        "warnings": [str(error)],
        "usable": False,
        "fresh": False,
    }


def source_status(source: dict[str, object]) -> str:
    if not source.get("usable"):
        return "FAIL"
    if source.get("warnings"):
        return "WARN"
    return "PASS"


def build_cross_source_summary(
    east: dict[str, object],
    west: dict[str, object],
    sync_tolerance_minutes: float,
) -> dict[str, object]:
    east_time_text = east.get("latest_frame_time_utc")
    west_time_text = west.get("latest_frame_time_utc")
    if not isinstance(east_time_text, str) or not isinstance(west_time_text, str):
        return {
            "synchronization_difference_minutes": None,
            "synchronization_tolerance_minutes": sync_tolerance_minutes,
            "within_tolerance": False,
            "effective_latest_time_utc": None,
            "warnings": ["cannot compare source times because one or both are unavailable"],
        }
    east_time = parse_iso_z(east_time_text)
    west_time = parse_iso_z(west_time_text)
    difference = abs((east_time - west_time).total_seconds()) / 60.0
    within = difference <= sync_tolerance_minutes
    warnings = [] if within else [
        f"East/West latest-frame difference is {difference:.1f} minutes; "
        f"tolerance is {sync_tolerance_minutes:.1f}"
    ]
    return {
        "synchronization_difference_minutes": round(difference, 2),
        "synchronization_tolerance_minutes": sync_tolerance_minutes,
        "within_tolerance": within,
        "effective_latest_time_utc": iso_z(min(east_time, west_time)),
        "warnings": warnings,
    }


def render_markdown(report: dict[str, object]) -> str:
    sources = report["sources"]
    cross = report["cross_source"]
    lines = [
        "# LightningCast source diagnostic",
        "",
        f"**Overall status:** {report['status']}",
        "",
        "> Test-only source inspection. No LightningCast contour coordinates were saved, uploaded, or published.",
        "",
        "| Source | Status | Latest frame | Age | Contours 10/30/50/70 | Bounds |",
        "|---|---:|---|---:|---:|---|",
    ]
    for key in ("east", "west"):
        source = sources[key]
        counts = source.get("latest_contours_by_threshold") or {}
        contour_text = "/".join(str(counts.get(str(value), 0)) for value in EXPECTED_THRESHOLDS)
        bounds = source.get("latest_bounds")
        if isinstance(bounds, dict):
            bounds_text = (
                f"{bounds['south']:.2f}–{bounds['north']:.2f}°N, "
                f"{abs(bounds['east']):.2f}–{abs(bounds['west']):.2f}°W"
            )
        else:
            bounds_text = "Unavailable"
        age = source.get("latest_frame_age_minutes")
        age_text = f"{float(age):.1f} min" if isinstance(age, (int, float)) else "Unavailable"
        lines.append(
            f"| {source.get('satellite', key)} | {source_status(source)} | "
            f"{source.get('latest_frame_time_utc') or 'Unavailable'} | {age_text} | "
            f"{contour_text} | {bounds_text} |"
        )

    lines.extend(
        [
            "",
            "## East/West synchronization",
            "",
            f"- Difference: **{cross.get('synchronization_difference_minutes')} minutes**",
            f"- Tolerance: **{cross.get('synchronization_tolerance_minutes')} minutes**",
            f"- Within tolerance: **{cross.get('within_tolerance')}**",
            f"- Effective latest time: **{cross.get('effective_latest_time_utc') or 'Unavailable'}**",
            "",
            "## Warnings",
            "",
        ]
    )
    warnings: list[str] = []
    for key in ("east", "west"):
        for warning in sources[key].get("warnings") or []:
            warnings.append(f"{sources[key].get('satellite', key)}: {warning}")
    for warning in cross.get("warnings") or []:
        warnings.append(f"Cross-source: {warning}")
    if warnings:
        lines.extend(f"- {warning}" for warning in warnings)
    else:
        lines.append("- None")

    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "- A zero count at a probability threshold can be meteorologically valid for the latest frame.",
            "- The diagnostic checks source access, placefile structure, frame timing, contour counts, bounds, and East/West synchronization.",
            "- It does not create a dashboard layer and does not authorize redistribution of the source feed.",
            "",
        ]
    )
    return "\n".join(lines)


def run_self_test() -> None:
    sample = """Title: NOAA LightningCast loop -- GOES-East CONUS sector
Refresh: 1
TimeRange: 2026-08-05T16:00:17Z 2026-08-05T16:05:17Z
Color: 080 201 134
Line: 2, 0, \"GOES-East CONUS scan time: 2026-08-05 16:00Z\\nP(LTG) >= 10% in next 60 minutes at every encompassed location.\"
35.0, -100.0
35.5, -100.5
35.0, -100.0
End:
Color: 255 255 081
Line: 2, 0, \"GOES-East CONUS scan time: 2026-08-05 16:00Z\\nP(LTG) >= 30% in next 60 minutes at every encompassed location.\"
35.1, -100.1
35.2, -100.2
End:
TimeRange: 2026-08-05T16:05:17Z 2026-08-05T16:10:17Z
Color: 080 201 134
Line: 2, 0, \"GOES-East CONUS scan time: 2026-08-05 16:05Z\\nP(LTG) >= 10% in next 60 minutes at every encompassed location.\"
36.0, -101.0
36.5, -101.5
End:
Color: 255 080 080
Line: 2, 0, \"GOES-East CONUS scan time: 2026-08-05 16:05Z\\nP(LTG) >= 70% in next 60 minutes at every encompassed location.\"
36.1, -101.1
36.2, -101.2
End:
"""
    parsed = parse_placefile(sample, "East")
    latest = latest_frame_time(parsed)
    assert iso_z(latest) == "2026-08-05T16:05:00Z"
    assert parsed.frame_counts[latest][10] == 1
    assert parsed.frame_counts[latest][70] == 1
    assert parsed.frame_counts[latest][30] == 0
    assert parsed.threshold_colors[10] == {(80, 201, 134)}
    assert parsed.frame_bounds[latest] == [36.0, 36.5, -101.5, -101.0]
    assert parsed.parsed_contours == 4
    assert parsed.invalid_coordinate_lines == 0
    print("LightningCast placefile diagnostic self-test passed.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--east-url",
        default=os.environ.get("LIGHTNINGCAST_EAST_URL", DEFAULT_EAST_URL),
        help="GOES-East CONUS placefile URL",
    )
    parser.add_argument(
        "--west-url",
        default=os.environ.get("LIGHTNINGCAST_WEST_URL", DEFAULT_WEST_URL),
        help="GOES-West CONUS placefile URL",
    )
    parser.add_argument("--output-dir", default="lightningcast_diagnostic")
    parser.add_argument("--timeout-seconds", type=int, default=60)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--maximum-bytes", type=int, default=80_000_000)
    parser.add_argument("--maximum-age-minutes", type=float, default=45.0)
    parser.add_argument("--sync-tolerance-minutes", type=float, default=15.0)
    parser.add_argument(
        "--expected-thresholds",
        type=parse_thresholds,
        default=EXPECTED_THRESHOLDS,
    )
    parser.add_argument(
        "--enforce-realtime",
        action="store_true",
        help="exit nonzero when a usable source is stale or East/West times exceed tolerance",
    )
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
    source_results: dict[str, dict[str, object]] = {}

    for key, satellite, url in (
        ("east", "East", args.east_url),
        ("west", "West", args.west_url),
    ):
        print(f"Fetching GOES-{satellite} LightningCast diagnostic source...")
        try:
            text, fetch_metadata = fetch_text(
                url=url,
                timeout_seconds=args.timeout_seconds,
                retries=args.retries,
                maximum_bytes=args.maximum_bytes,
            )
            parsed = parse_placefile(text, satellite)
            source_results[key] = summarize_source(
                satellite=satellite,
                url=url,
                parsed=parsed,
                fetch_metadata=fetch_metadata,
                fetched_at=fetched_at,
                expected_thresholds=args.expected_thresholds,
                maximum_age_minutes=args.maximum_age_minutes,
            )
        except Exception as exc:  # keep a report even when one source fails
            source_results[key] = failed_source_summary(
                satellite=satellite,
                url=url,
                fetched_at=fetched_at,
                error=exc,
                maximum_age_minutes=args.maximum_age_minutes,
            )

    cross = build_cross_source_summary(
        source_results["east"],
        source_results["west"],
        args.sync_tolerance_minutes,
    )
    hard_failure = any(not source_results[key].get("usable") for key in ("east", "west"))
    realtime_failure = args.enforce_realtime and (
        any(not source_results[key].get("fresh") for key in ("east", "west"))
        or not cross.get("within_tolerance")
    )
    has_warnings = any(source_results[key].get("warnings") for key in ("east", "west")) or bool(
        cross.get("warnings")
    )
    status = "FAIL" if hard_failure or realtime_failure else ("WARN" if has_warnings else "PASS")

    report: dict[str, object] = {
        "diagnostic_mode": "lightningcast_source_diagnostic_v1",
        "generated_at_utc": iso_z(utc_now()),
        "status": status,
        "publication": {
            "dashboard_files_created": False,
            "contour_coordinates_retained": False,
            "contour_payload_uploaded": False,
            "note": (
                "Default public CIMSS placefiles are inspected only for source diagnostics. "
                "Production publication requires an authorized NOAA operational source."
            ),
        },
        "configuration": {
            "expected_thresholds_percent": list(args.expected_thresholds),
            "maximum_age_minutes": args.maximum_age_minutes,
            "sync_tolerance_minutes": args.sync_tolerance_minutes,
            "enforce_realtime": args.enforce_realtime,
            "timeout_seconds": args.timeout_seconds,
            "retries": args.retries,
            "maximum_bytes": args.maximum_bytes,
        },
        "sources": source_results,
        "cross_source": cross,
    }

    json_path = output_dir / "lightningcast_source_diagnostic.json"
    markdown_path = output_dir / "lightningcast_source_diagnostic.md"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(report), encoding="utf-8")

    print(render_markdown(report))
    print(f"Wrote {json_path}")
    print(f"Wrote {markdown_path}")
    return 1 if hard_failure or realtime_failure else 0


if __name__ == "__main__":
    raise SystemExit(main())
