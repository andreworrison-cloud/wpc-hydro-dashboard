"""Smoothed cartographic isolines and conservative, automated pressure centers."""
from __future__ import annotations

import math

import contourpy
import numpy as np
from scipy.ndimage import (distance_transform_edt, gaussian_filter, label,
                           find_objects, map_coordinates, maximum_filter, minimum_filter)
from pyproj import Transformer

from surface_analysis import BOUNDS, PRODUCTS

SCHEMA = "surface-contours-v1"


def smooth_masked(values, sigma):
    """Normalize over valid neighbors and never fill an unsupported source cell."""
    a = np.asarray(values, dtype="float32")
    valid = np.isfinite(a)
    weight = gaussian_filter(valid.astype("float32"), sigma, mode="nearest")
    total = gaussian_filter(np.where(valid, a, 0), sigma, mode="nearest")
    return np.where(valid & (weight > .25), total / np.maximum(weight, 1e-8), np.nan).astype("float32")


def pressure_centers(smoothed, transform, crs, radius_m=300000, prominence_hpa=1):
    """Require a closed pressure anomaly on a complete 300-km ring.

    Excludes grid/missing-data edges and suppresses nearby duplicates. These are
    model-analysis extrema, not WPC's manually analyzed surface centers.
    """
    a = np.asarray(smoothed)
    valid = np.isfinite(a)
    spacing = min(abs(transform.a), abs(transform.e))
    radius = max(2, int(round(radius_m / spacing)))
    interior = distance_transform_edt(np.pad(valid, 1))[1:-1, 1:-1] > radius + 1
    candidates = []
    to_geo = Transformer.from_crs(crs, 4326, always_xy=True)
    angles = np.linspace(0, 2 * np.pi, 32, endpoint=False)
    for kind, sign, filt in (("H", 1, maximum_filter), ("L", -1, minimum_filter)):
        work = np.where(valid, a, -sign * np.inf)
        extrema = interior & (a == filt(work, size=2 * radius + 1, mode="constant", cval=-sign * np.inf))
        groups, count = label(extrema)
        for group_id, box in enumerate(find_objects(groups, max_label=count), 1):
            if box is None:
                continue
            rows, cols = np.nonzero(groups[box] == group_id)
            rows += box[0].start; cols += box[1].start
            near = np.argmin((rows - rows.mean()) ** 2 + (cols - cols.mean()) ** 2)
            row, col = int(rows[near]), int(cols[near])
            ring = map_coordinates(a, [row + radius_m / abs(transform.e) * np.sin(angles),
                                       col + radius_m / abs(transform.a) * np.cos(angles)], order=1, mode="constant", cval=np.nan)
            if not np.isfinite(ring).all():
                continue
            prominence = float(np.min(sign * (a[row, col] - ring)))
            if prominence < prominence_hpa:
                continue
            x=transform.c+transform.a*(col+.5)+transform.b*(row+.5)
            y=transform.f+transform.d*(col+.5)+transform.e*(row+.5)
            lon, lat = to_geo.transform(x, y)
            if not (BOUNDS[0][0] < lat < BOUNDS[1][0] and BOUNDS[0][1] < lon < BOUNDS[1][1]):
                continue
            candidates.append({"kind": kind, "value": round(float(a[row, col]), 1),
                               "prominence": round(prominence, 2), "x": x, "y": y,
                               "lon": lon, "lat": lat})
    chosen = []
    for p in sorted(candidates, key=lambda x: (-x["prominence"], x["kind"], x["lat"], x["lon"])):
        if any(p["kind"] == q["kind"] and math.hypot(p["x"] - q["x"], p["y"] - q["y"]) < 500000 for q in chosen):
            continue
        chosen.append(p)
        if len(chosen) >= 12:
            break
    return [{"type": "Feature", "properties": {"kind": "center", "symbol": p["kind"],
              "value": p["value"], "unit": "hPa", "prominence_hpa": p["prominence"]},
             "geometry": {"type": "Point", "coordinates": [round(p["lon"], 5), round(p["lat"], 5)]}}
            for p in chosen]


def simplify(points, tolerance=1100):
    """Iterative Douglas-Peucker in display meters; preserve endpoints."""
    keep = np.zeros(len(points), dtype=bool); keep[[0, -1]] = True
    stack = [(0, len(points) - 1)]
    while stack:
        first, last = stack.pop()
        if last <= first + 1:
            continue
        delta = points[last] - points[first]
        length2 = np.dot(delta, delta)
        t = np.clip((points[first + 1:last] - points[first]) @ delta / max(length2, 1e-12), 0, 1)
        distance = np.linalg.norm(points[first + 1:last] - (points[first] + t[:, None] * delta), axis=1)
        far = int(np.argmax(distance)) + first + 1
        if distance[far - first - 1] > tolerance:
            keep[far] = True; stack.extend(((first, far), (far, last)))
    return points[keep]


def contour_collection(key, values, transform, valid_time, centers=()):
    """GeoJSON isolines; coordinate axes refer to sampled display pixel centers."""
    interval = PRODUCTS[key]["contour_interval"]
    stride = 4
    small = np.asarray(values)[::stride, ::stride]
    if key != "mslp":
        small = smooth_masked(small, 1.25)
    rows, cols = small.shape
    x = transform.c + (np.arange(cols) * stride + .5) * transform.a
    y = transform.f + (np.arange(rows) * stride + .5) * transform.e
    finite = small[np.isfinite(small)]
    features = []
    if finite.size:
        low, high = float(finite.min()), float(finite.max())
        levels = list(np.arange(math.floor(low / interval) * interval, high + interval, interval))
        if key == "temperature" and low < 32 < high:
            levels.append(32)
        generator = contourpy.contour_generator(x=x, y=y, z=np.ma.masked_invalid(small),
                      name="serial", line_type="Separate", corner_mask=False)
        to_geo = Transformer.from_crs(3857, 4326, always_xy=True)
        for value in sorted(set(v for v in levels if low < v < high)):
            for points in generator.lines(value):
                if len(points) < 3 or np.linalg.norm(np.diff(points, axis=0), axis=1).sum() < 30000:
                    continue
                points = simplify(points)
                lon, lat = to_geo.transform(points[:, 0], points[:, 1])
                features.append({"type": "Feature", "properties": {"kind": "contour", "value": float(value), "unit": PRODUCTS[key]["unit"]},
                                 "geometry": {"type": "LineString", "coordinates": np.round(np.column_stack((lon, lat)), 5).tolist()}})
    return {"type": "FeatureCollection", "schema": SCHEMA, "key": key, "valid_time": valid_time,
            "interval": interval, "pressure_smoothing_km": 18 if key == "mslp" else None,
            "features": features + list(centers)}


def validate_collection(data, key, valid_time):
    if data.get("type") != "FeatureCollection" or data.get("schema") != SCHEMA or data.get("key") != key or data.get("valid_time") != valid_time:
        raise ValueError("Contours do not match the analysis")
    features = data.get("features")
    if not isinstance(features, list) or len(features) > 10000 or data.get("interval") != PRODUCTS[key]["contour_interval"]:
        raise ValueError("Invalid contour features/interval")
    vertices = 0
    for f in features:
        p, g = f.get("properties", {}), f.get("geometry", {})
        if f.get("type") != "Feature" or not isinstance(p.get("value"), (int, float)) or not math.isfinite(p["value"]) or p.get("unit") != PRODUCTS[key]["unit"]:
            raise ValueError("Invalid contour value/unit")
        if p.get("kind") == "center":
            if key != "mslp" or p.get("symbol") not in ("H", "L") or g.get("type") != "Point":
                raise ValueError("Invalid pressure center")
            coordinates = [g.get("coordinates")]
        else:
            if p.get("kind") != "contour" or g.get("type") != "LineString" or len(g.get("coordinates", [])) < 2:
                raise ValueError("Invalid contour geometry")
            if abs(p["value"] / data["interval"] - round(p["value"] / data["interval"])) > 1e-6 and not (key == "temperature" and p["value"] == 32):
                raise ValueError("Contour value not on its interval")
            coordinates = g["coordinates"]
        vertices += len(coordinates)
        for c in coordinates:
            if not isinstance(c, list) or len(c) != 2 or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in c) or not (BOUNDS[0][1] <= c[0] <= BOUNDS[1][1] and BOUNDS[0][0] <= c[1] <= BOUNDS[1][0]):
                raise ValueError("Contour coordinate outside display bounds")
    if vertices > 250000:
        raise ValueError("Oversized contour geometry")
    return data
