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


def filter_small_pressure_features(values, transform, crs, points, accepted_ids,
                                   max_diameter_km=120):
    """Remove small closed components unless observations support the closure.

    The test is on native-grid area (equivalent-circle diameter), not display
    pixels. A retained small system needs an interior report on its side of the
    isobar and two exterior reports on the other side within 150 km. Larger
    systems retain HRRR support even where reports are sparse.
    """
    from scipy.ndimage import label, find_objects, binary_dilation
    from surface_contours import smooth_masked
    a = np.array(values, dtype='float32', copy=True)
    valid = np.isfinite(a)
    if not valid.any():
        return a, {'removed_features': 0, 'supported_features': 0, 'max_diameter_km': max_diameter_km}
    to_xy = Transformer.from_crs(4326, crs, always_xy=True)
    obs = []
    for p in points:
        if p.get('id') not in accepted_ids or p.get('mslp') is None:
            continue
        x, y = to_xy.transform(p['lon'], p['lat'])
        c, r = ~transform * (x, y)
        r, c = int(np.floor(r)), int(np.floor(c))
        if 0 <= r < a.shape[0] and 0 <= c < a.shape[1]:
            obs.append((r, c, float(p['mslp']), x, y))
    cell_area = abs(transform.a*transform.e)
    max_area = np.pi*(max_diameter_km*1000/2)**2
    unsafe = binary_dilation(~valid)
    unsafe[[0,-1],:] = True; unsafe[:,[0,-1]] = True
    removed = supported = 0
    levels = np.arange(np.floor(np.nanmin(a)/4)*4, np.nanmax(a)+4, 4)
    # Remove deepest small nested components first, then their enclosing rings.
    for sign in (-1, 1):
        for level in (levels if sign < 0 else levels[::-1]):
            groups, count = label(valid & (sign*(a-level) > 0))
            sizes = np.bincount(groups.ravel())
            for gid, box in enumerate(find_objects(groups, max_label=count), 1):
                if box is None or sizes[gid]*cell_area > max_area:
                    continue
                component = groups[box] == gid
                if np.any(unsafe[box] & component):
                    continue
                interior = [o for o in obs if groups[o[0],o[1]] == gid and sign*(o[2]-level) >= .2]
                confirmed = False
                for o in interior:
                    exterior = [q for q in obs if groups[q[0],q[1]] != gid
                                and sign*(q[2]-level) <= -.2
                                and (q[3]-o[3])**2+(q[4]-o[4])**2 <= 150000**2]
                    if len(exterior) >= 2:
                        confirmed = True; break
                if confirmed:
                    supported += 1
                else:
                    # Flatten only the unsupported anomaly to its enclosing
                    # isobar. Apply a light final smooth to avoid a hard edge.
                    a[box][component] = level
                    removed += 1
    if removed:
        a = smooth_masked(a, 6000/abs(transform.a))
    return a, {'removed_features':removed, 'supported_features':supported,
               'max_diameter_km':max_diameter_km, 'support_rule':'one interior + two exterior METAR reports; 0.2 hPa contrast; 150 km'}
