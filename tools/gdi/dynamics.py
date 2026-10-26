"""Companion diagnostics for GDI. This module never changes the GDI index.

Horizontal derivatives use earth-relative vectors and the spherical metric,
inverting the actual native latitude/longitude Jacobian. Below-ground winds
and moisture are excluded before filtering and before differentiation.
"""
import numpy as np
from scipy.ndimage import gaussian_filter

RECIPE = 'rap_gdi_dynamics_v1'
SIGMA_KM = 20.
RADIUS = 6371229.
MFC_LEVELS = (950, 900, 850, 700)
UPPER_LEVELS = (400, 300, 200)
LOWER_LEVELS = (1000, 950, 900, 850)


class Geometry:
    def __init__(self, longitude, latitude, radius=RADIUS):
        lo = np.unwrap(np.unwrap(np.deg2rad(longitude), axis=1), axis=0)
        self.phi = np.deg2rad(latitude)
        self.radius = float(radius)
        self.lo_j, self.lo_i = np.gradient(lo)
        self.la_j, self.la_i = np.gradient(self.phi)
        self.det = self.lo_i*self.la_j-self.lo_j*self.la_i
        if np.any(~np.isfinite(self.det)) or np.any(abs(self.det) < 1e-12):
            raise ValueError('Degenerate native coordinate Jacobian')

    def earth_wind(self, u, v, grid_relative, i_negative=False, j_positive=True):
        if not grid_relative:
            return np.asarray(u), np.asarray(v)
        # Positive grid axes can oppose the GRIB storage scan directions.
        ei, ni = np.cos(self.phi)*self.lo_i, self.la_i
        ej, nj = np.cos(self.phi)*self.lo_j, self.la_j
        li, lj = np.hypot(ei, ni), np.hypot(ej, nj)
        ei, ni = ei/li, ni/li
        ej, nj = ej/lj, nj/lj
        if np.max(abs(ei*ej+ni*nj)) > .003:
            raise ValueError('Non-orthogonal Lambert wind axes')
        si, sj = (-1 if i_negative else 1), (1 if j_positive else -1)
        return u*ei*si+v*ej*sj, u*ni*si+v*nj*sj

    def partials(self, field):
        fj, fi = np.gradient(field)
        return ((fi*self.la_j-fj*self.la_i)/self.det,
                (fj*self.lo_i-fi*self.lo_j)/self.det)

    def divergence(self, east, north):
        du_dlo, _ = self.partials(east)
        _, dv_dla = self.partials(north)
        return (du_dlo/np.cos(self.phi)+dv_dla-north*np.tan(self.phi))/self.radius


def filtered(field, sigma, support=.8):
    """Nominal physical-scale filter; never fill a missing/below-ground center."""
    good = np.isfinite(field)
    weight = gaussian_filter(good.astype(float), sigma, mode='constant', cval=0.)
    total = gaussian_filter(np.where(good, field, 0.), sigma, mode='constant', cval=0.)
    return np.where(good & (weight >= support), total/np.maximum(weight, 1e-12), np.nan)


def layer_mean(fields, levels, minimum_depth):
    """Trapezoidal pressure mean of complete adjacent, above-ground segments.

Never bridge a missing pressure level. Depth is retained for interpretation.
"""
    fields = np.asarray(fields)
    widths = np.diff(-np.asarray(levels, dtype=float)).reshape((-1,)+(1,)*(fields.ndim-1))
    valid = np.isfinite(fields[:-1]) & np.isfinite(fields[1:])
    depth = np.where(valid, widths, 0.).sum(axis=0)
    total = np.where(valid, (fields[:-1]+fields[1:])*.5*widths, 0.).sum(axis=0)
    return np.where(depth >= minimum_depth-1e-8, total/np.maximum(depth, 1.), np.nan), depth


def humidity_q(temperature, humidity, pressure, specific):
    if specific:
        return np.where((humidity >= 0)&(humidity < .1), humidity, np.nan)
    e = humidity/100*6.112*np.exp(17.67*(temperature-273.15)/(temperature-29.65))
    good = ((temperature > 150)&(temperature < 350)&(humidity >= 0)&(humidity <= 200)&(e < pressure))
    return np.where(good, .622*e/(pressure-.378*e), np.nan)


def calculate(fields, geometry, *, dx, dy, wind_flags, sigma_km=SIGMA_KM):
    sigma = (sigma_km*1000/dy, sigma_km*1000/dx)
    ps = fields['PRES', 'surface']/100.
    ps = np.where((ps > 500)&(ps < 1100), ps, np.nan)
    winds = {}
    for p in sorted(set(MFC_LEVELS+UPPER_LEVELS+LOWER_LEVELS), reverse=True):
        u, v = fields['UGRD', f'{p} mb'], fields['VGRD', f'{p} mb']
        good = (ps >= p)&np.isfinite(ps)&(abs(u) < 200)&(abs(v) < 200)
        winds[p] = geometry.earth_wind(np.where(good, u, np.nan), np.where(good, v, np.nan), **wind_flags)
    convergence = []
    for p in MFC_LEVELS:
        level = f'{p} mb'
        specific = ('SPFH', level) in fields
        q = humidity_q(fields['TMP', level], fields['SPFH' if specific else 'RH', level], p, specific)
        mixing_ratio = q/(1-q)
        u, v = winds[p]
        # Smooth the moisture flux, not q and wind independently.
        convergence.append(-geometry.divergence(filtered(mixing_ratio*u, sigma), filtered(mixing_ratio*v, sigma)))
    mfc, depth = layer_mean(convergence, MFC_LEVELS, 100.)
    upper_div = [geometry.divergence(filtered(winds[p][0], sigma), filtered(winds[p][1], sigma)) for p in UPPER_LEVELS]
    divergence, _ = layer_mean(upper_div, UPPER_LEVELS, 200.)
    rh = []
    for p in (400,300):
        level = f'{p} mb'
        if ('RH',level) in fields:
            value = fields['RH',level]
        else:
            q = humidity_q(fields['TMP',level],fields['SPFH',level],p,True)
            e = q*p/(.622+.378*q)
            t = fields['TMP',level]
            saturation = 6.112*np.exp(17.67*(t-273.15)/(t-29.65))
            value = 100*e/saturation
        rh.append(np.where((value >= 0)&(value <= 150)&(ps >= p),value,np.nan))
    upper_rh, _ = layer_mean(rh, (400, 300), 100.)
    pw = fields['PWAT', 'column']
    pw = np.where((pw >= 0)&(pw <= 200)&np.isfinite(ps), pw/25.4, np.nan)
    result = {'mfc':mfc*3.6e6, 'div':divergence*1e5,
              'rh':filtered(upper_rh, sigma), 'pw':filtered(pw, sigma), 'mfc_depth_hpa':depth}
    for prefix, levels, minimum in [('low', LOWER_LEVELS, 50.), ('upper', UPPER_LEVELS, 200.)]:
        for component in (0, 1):
            mean, _ = layer_mean([filtered(winds[p][component], sigma) for p in levels], levels, minimum)
            result[prefix+('_u' if component == 0 else '_v')] = mean*1.9438444924406048
    return result
