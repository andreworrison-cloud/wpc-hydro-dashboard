"""Display units, palettes and observed METAR values for the surface suite."""
from __future__ import annotations

import csv
import io
import math
from datetime import datetime, timezone

import numpy as np

REVISION = "rtma-surface-v1"
BOUNDS = [[24.0, -125.0], [50.0, -66.0]]
ANALYSIS_WARN_MINUTES = 150
ANALYSIS_HIDE_MINUTES = 240
STATION_HIDE_MINUTES = 90
PRODUCTS = {
    "temperature": {
        "label": "2-m Temperature", "unit": "°F", "parameter": "TMP", "level": 2,
        "stops": [-40, -20, 0, 20, 32, 40, 50, 60, 70, 80, 90, 100, 110, 120],
        "colors": ["#e1d9ff", "#9d67c9", "#5444aa", "#2865b0", "#36b7dc", "#69cdb7", "#66bd63", "#b8cf55", "#f3dc54", "#f6a342", "#ed6639", "#ca3038", "#9e1855", "#691256"],
        "ticks": [-40, 0, 32, 60, 90, 120],
    },
    "dewpoint": {
        "label": "2-m Dewpoint", "unit": "°F", "parameter": "DPT", "level": 2,
        "stops": [-20, 0, 20, 30, 40, 50, 55, 60, 65, 70, 75, 80],
        "colors": ["#70523c", "#a17b50", "#c0a57a", "#d8cfac", "#c9d8b6", "#9acb85", "#66ba70", "#329e83", "#208eab", "#3067b3", "#6651a8", "#963ba0"],
        "ticks": [-20, 0, 20, 40, 60, 80],
    },
    "wind_speed": {
        "label": "10-m Wind Speed", "unit": "kt", "parameter": "WIND", "level": 10,
        "stops": [0, 5, 10, 15, 20, 30, 40, 50, 60, 80],
        "colors": ["#d9e2e7", "#a1d7df", "#58bfc4", "#48ab84", "#90bd60", "#e6d554", "#f3a444", "#e46b40", "#bd3e66", "#783d9d"],
        "ticks": [0, 10, 20, 40, 60, 80],
    },
}


def iso(value):
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_time(value):
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("Time must include timezone")
    return result.astimezone(timezone.utc)


def display_values(key, values):
    a = np.asarray(values, dtype="float32")
    if key in ("temperature", "dewpoint"):
        low = 173.15 if key == "dewpoint" else 183.15
        a = np.where((a >= low) & (a <= 333.15), a, np.nan)
        return (a - 273.15) * (9 / 5) + 32
    if key == "wind_speed":
        return np.where((a >= 0) & (a <= 130), a * 1.9438444924406, np.nan)
    raise ValueError("Unknown surface product")


def colorize(key, values):
    p = PRODUCTS[key]
    rgb = np.array([[int(c[i:i+2], 16) for i in (1, 3, 5)] for c in p["colors"]])
    a = np.asarray(values)
    finite = np.isfinite(a)
    safe = np.where(finite, a, p["stops"][0])
    result = np.zeros(a.shape + (4,), dtype="uint8")
    for channel in range(3):
        result[..., channel] = np.rint(np.interp(safe, p["stops"], rgb[:, channel])).astype("uint8")
    result[..., 3] = np.where(finite, 255, 0)
    return result


def number(value, low, high):
    try:
        n = float(value)
        return n if math.isfinite(n) and low <= n <= high else None
    except (TypeError, ValueError):
        return None


def parse_metars(text, now):
    """Latest real report per station; field QC is independent, no interpolation."""
    lines = text.splitlines()
    start = next((i for i, line in enumerate(lines) if line.startswith("raw_text,station_id,")), None)
    if start is None:
        raise ValueError("METAR CSV header missing")
    latest = {}
    for row in csv.DictReader(io.StringIO("\n".join(lines[start:]))):
        station = row.get("station_id", "")
        if not station.isalnum() or not 3 <= len(station) <= 5 or row.get("metar_type") not in ("METAR", "SPECI"):
            continue
        try:
            time = parse_time(row["observation_time"])
        except (KeyError, TypeError, ValueError):
            continue
        if not 0 <= (now - time).total_seconds() <= STATION_HIDE_MINUTES * 60:
            continue
        lat = number(row.get("latitude"), BOUNDS[0][0], BOUNDS[1][0])
        lon = number(row.get("longitude"), BOUNDS[0][1], BOUNDS[1][1])
        if lat is None or lon is None:
            continue
        if station not in latest or time > latest[station][0]:
            latest[station] = time, row, lat, lon
    points = []
    for station, (time, row, lat, lon) in sorted(latest.items()):
        temp = number(row.get("temp_c"), -90, 60)
        dew = number(row.get("dewpoint_c"), -100, 60)
        if temp is not None and dew is not None and dew > temp + .5:
            dew = None
        speed = number(row.get("wind_speed_kt"), 0, 250)
        if temp is None and dew is None and speed is None:
            continue
        points.append({"id": station, "lat": lat, "lon": lon, "time": iso(time),
                       "temperature": None if temp is None else round(temp * 1.8 + 32, 1),
                       "dewpoint": None if dew is None else round(dew * 1.8 + 32, 1),
                       "wind_speed": speed, "wind_gust": number(row.get("wind_gust_kt"), 0, 300),
                       "wind_direction": number(row.get("wind_dir_degrees"), 0, 360),
                       "raw": row.get("raw_text", "")[:500]})
    return points
