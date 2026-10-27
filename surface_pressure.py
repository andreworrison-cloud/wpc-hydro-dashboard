"""Conservative observation increments on an hourly HRRR MSLP background.

This is a dashboard objective analysis, not an operational data-assimilation
product. Only reported sea-level pressure is used; altimeter settings are not
interchangeable with MSLP. All distances below are in the native HRRR projection.
"""
import numpy as np
from scipy.ndimage import map_coordinates
from scipy.spatial import cKDTree
from pyproj import Transformer

from surface_analysis import parse_time


def blend_pressure(background, transform, crs, points, cycle, now):
    a = np.asarray(background, dtype='float32')
    to_xy = Transformer.from_crs(4326, crs, always_xy=True)
    stations = []
    seen = set()
    for p in sorted(points, key=lambda p: p.get('time', ''), reverse=True):
        try:
            value = float(p['mslp'])
            time = parse_time(p['time'])
            offset = abs((time-cycle).total_seconds())/60
            age = (now-time).total_seconds()/60
            if p['id'] in seen or not np.isfinite(value) or not 850 <= value <= 1100 or not 0 <= age <= 90 or offset > 60:
                continue
            seen.add(p['id'])
            x, y = to_xy.transform(p['lon'], p['lat'])
            col, row = ~transform * (x, y)
            bg = float(map_coordinates(a, [[row-.5], [col-.5]], order=1, mode='constant', cval=np.nan)[0])
            if not np.isfinite(bg) or abs(value-bg) > 12:
                continue
            stations.append((x, y, value-bg, np.exp(-.5*(offset/30)**2), p['id'], p['time']))
        except (KeyError, TypeError, ValueError):
            continue
    # Reject isolated innovations inconsistent with at least three neighbors.
    if stations:
        xy = np.array([s[:2] for s in stations])
        neighbors = cKDTree(xy).query_ball_point(xy, 150000)
        keep = []
        for i, s in enumerate(stations):
            other = [stations[j][2] for j in neighbors[i] if j != i]
            if len(other) < 3 or abs(s[2]-np.median(other)) <= 4:
                keep.append(s)
        stations = keep
    numerator = np.zeros_like(a)
    weight = np.zeros_like(a)
    if stations:
        xy = np.array([s[:2] for s in stations])
        # Thin influence statistically, so a dense airport cluster is not
        # mistaken for many independent observations of the same air mass.
        density = cKDTree(xy).query_ball_point(xy, 50000, return_length=True)
        dx, dy = abs(transform.a), abs(transform.e)
        radius, sigma = 240000, 80000
        for s, count in zip(stations, density):
            x, y, increment, temporal, _, _ = s
            col, row = ~transform * (x, y)
            r0, r1 = max(0, int(row-radius/dy)), min(a.shape[0], int(row+radius/dy)+1)
            c0, c1 = max(0, int(col-radius/dx)), min(a.shape[1], int(col+radius/dx)+1)
            xx = transform.c+(np.arange(c0, c1)+.5)*transform.a
            yy = transform.f+(np.arange(r0, r1)+.5)*transform.e
            d2 = (xx[None, :]-x)**2+(yy[:, None]-y)**2
            # Subtract the cutoff value for a continuous zero at 240 km.
            w = np.maximum(0, np.exp(-d2/(2*sigma*sigma))-np.exp(-4.5))*temporal/count
            numerator[r0:r1, c0:c1] += w*increment
            weight[r0:r1, c0:c1] += w
    correction = np.clip(numerator/(weight+.5), -6, 6)
    result = a+correction
    diagnostics = {'method': 'HRRR + METAR objective analysis',
                   'accepted_stations': len(stations), 'sigma_km': 80,
                   'radius_km': 240, 'time_window_minutes': 60,
                   'max_correction_hpa': round(float(np.max(np.abs(correction))), 3),
                   'mode': 'observation-adjusted' if stations else 'HRRR background only',
                   'stations': [{'id': s[4], 'time': s[5]} for s in stations]}
    return result, diagnostics
