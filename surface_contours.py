"""Smoothed cartographic isolines and conservative, automated pressure centers."""
from __future__ import annotations

import math

import contourpy
import numpy as np
from scipy.ndimage import gaussian_filter
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


def closed_centers(loops, values, x, y, crs):
    """One center for each innermost closed 4-hPa circulation.

    Derive symbols from the same unsimplified contour paths as the map. Nested
    isobars share a center; distinct adjacent circulations are never suppressed
    by a fixed distance. Open contours and contours surrounding missing data
    cannot certify a center.
    """
    from rasterio.features import geometry_mask
    from rasterio.transform import Affine
    from scipy.ndimage import binary_erosion
    to_geo = Transformer.from_crs(crs, 4326, always_xy=True)
    dx, dy = x[1]-x[0], y[1]-y[0]
    candidates = []
    for loop_id, (level, path) in enumerate(loops):
        if len(path) < 4 or not np.allclose(path[0], path[-1], atol=.01, rtol=0):
            continue
        area = abs(np.sum(path[:-1, 0]*path[1:, 1]-path[1:, 0]*path[:-1, 1]))/2
        candidates.append((area, level, path, loop_id))
    chosen = []
    for _, level, path, loop_id in sorted(candidates, key=lambda c: c[0]):
        cols = (path[:, 0]-x[0])/dx; rows = (path[:, 1]-y[0])/dy
        c0, c1 = max(0, int(np.floor(cols.min()))), min(len(x), int(np.ceil(cols.max()))+1)
        r0, r1 = max(0, int(np.floor(rows.min()))), min(len(y), int(np.ceil(rows.max()))+1)
        if c1 <= c0 or r1 <= r0:
            continue
        t = Affine(dx, 0, x[c0]-dx/2, 0, dy, y[r0]-dy/2)
        inside = geometry_mask([{'type':'Polygon', 'coordinates':[path.tolist()]}],
                              (r1-r0, c1-c0), t, invert=True)
        sub = values[r0:r1, c0:c1]
        if not inside.any() or not np.isfinite(sub[inside]).all():
            continue
        rim = inside & ~binary_erosion(inside)
        sign = 1 if np.median(sub[rim]-level) > 0 else -1
        kind = 'H' if sign == 1 else 'L'
        nested = [p for p in chosen if p['symbol'] == kind and r0 <= p['row'] < r1
                  and c0 <= p['col'] < c1 and inside[p['row']-r0, p['col']-c0]]
        if nested:
            for p in nested:
                p['contour_ids'].append(loop_id)
            continue
        extreme = np.max(sign*sub[inside])
        rr, cc = np.nonzero(inside & (sign*sub == extreme))
        near = np.argmin((rr-rr.mean())**2+(cc-cc.mean())**2)
        row, col = int(rr[near]+r0), int(cc[near]+c0)
        value = float(values[row, col])
        if sign*(value-level) < .05:
            continue
        lon, lat = to_geo.transform(x[col], y[row])
        if not (BOUNDS[0][0] < lat < BOUNDS[1][0] and BOUNDS[0][1] < lon < BOUNDS[1][1]):
            continue
        chosen.append({'symbol':kind, 'row':row, 'col':col, 'value':value,
                       'lon':lon, 'lat':lat, 'prominence':sign*(value-level), 'level':float(level), 'contour_ids':[loop_id]})
    return [{'type':'Feature', 'properties':{'kind':'center', 'symbol':p['symbol'],
             'value':round(p['value'], 4), 'unit':'hPa', 'prominence_hpa':round(float(p['prominence']), 4),
             'enclosing_isobar_hpa':p['level'], 'contour_ids':p['contour_ids']},
             'geometry':{'type':'Point', 'coordinates':[round(p['lon'], 5), round(p['lat'], 5)]}}
            for p in chosen]


def pressure_centers(smoothed, transform, crs):
    """Standalone native-grid equivalent, used for analytic verification."""
    a = np.asarray(smoothed)
    finite = a[np.isfinite(a)]
    if not finite.size:
        return []
    x = transform.c+(np.arange(a.shape[1])+.5)*transform.a
    y = transform.f+(np.arange(a.shape[0])+.5)*transform.e
    generator = contourpy.contour_generator(x=x, y=y, z=np.ma.masked_invalid(a),
                    name='serial', line_type='Separate', corner_mask=False)
    loops = [(v, path) for v in np.arange(math.floor(finite.min()/4)*4, finite.max(), 4)
             for path in generator.lines(v)]
    return closed_centers(loops, a, x, y, crs)


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
    loops = []
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
                if key == "mslp":
                    loops.append((value, points.copy()))
                points = simplify(points)
                lon, lat = to_geo.transform(points[:, 0], points[:, 1])
                features.append({"type": "Feature", "properties": {"kind": "contour", "value": float(value), "unit": PRODUCTS[key]["unit"], **({"contour_id":len(loops)-1} if key=="mslp" else {})},
                                 "geometry": {"type": "LineString", "coordinates": np.round(np.column_stack((lon, lat)), 5).tolist()}})
    if key == "mslp" and rows > 1 and cols > 1:
        full = np.asarray(values)
        full_x = transform.c+(np.arange(full.shape[1])+.5)*transform.a
        full_y = transform.f+(np.arange(full.shape[0])+.5)*transform.e
        regional = list(centers)
        centers = closed_centers(loops, full, full_x, full_y, 3857)
        represented = {i for center in centers for i in center['properties']['contour_ids']}
        # Discard degenerate/unsupported closed paths, never leave an orphan
        # closed isobar. Open paths remain valid without an in-domain center.
        features = [f for f in features if f['properties']['contour_id'] in represented
                    or not np.allclose(loops[f['properties']['contour_id']][1][0],
                                       loops[f['properties']['contour_id']][1][-1], atol=.01, rtol=0)]
        # Native-grid regional candidates supplement (never replace) centers
        # tied to displayed closed contours. Use geodesic duplicate distances.
        from pyproj import Geod
        geod = Geod(ellps='WGS84')
        to_display = Transformer.from_crs(4326,3857,always_xy=True)
        for candidate in regional:
            lon,lat = candidate['geometry']['coordinates']
            if any(c['properties']['symbol']==candidate['properties']['symbol'] and
                   geod.inv(lon,lat,*c['geometry']['coordinates'])[2]<75000 for c in centers):
                continue
            # Read the same displayed scalar field used by color and sampling.
            from scipy.ndimage import map_coordinates
            px,py = to_display.transform(lon,lat)
            col,row = ~transform*(px,py)
            value = float(map_coordinates(full,[[row-.5],[col-.5]],order=1,
                                          mode='constant',cval=np.nan)[0])
            if np.isfinite(value):
                candidate = {**candidate,'properties':{**candidate['properties'],'value':round(value,4)}}
                centers.append(candidate)
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
            level=p.get("enclosing_isobar_hpa")
            if level is not None and ((p["symbol"]=="L" and p["value"]>=level) or (p["symbol"]=="H" and p["value"]<=level)):
                raise ValueError("Pressure center contradicts enclosing isobar")
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
