"""Experimental radar type classes. Hail is never a winter mix/ice flag.

MRMS PrecipFlag supplies precipitation support and a rain/snow fallback.
HRRR categorical surface fields supply winter phase information. Multiple
active phase families mean mix; sleet + freezing rain together still mean ice.
No temperatures, spatial smoothing, or invented transition bands are used.
"""
from __future__ import annotations

import numpy as np

REVISION = "mrms-hrrr-winter-v1"
UNKNOWN, RAIN, MIX, SNOW, ICE = range(5)
COLORS = {RAIN: "#2bc45b", MIX: "#bf65d9", SNOW: "#50b9f2", ICE: "#f14d87"}
LABELS = {RAIN: "Rain", MIX: "Mix", SNOW: "Snow", ICE: "Ice (sleet/freezing rain)"}
RAIN_FLAGS = (1, 6, 7, 10, 91, 96)


def classify(flag, rain=None, snow=None, pellets=None, freezing=None):
    """Return class IDs and model-support mask on the same grid.

    Unsupported MRMS flags, dry pixels and no-coverage stay unknown. Missing
    model values never become dry/rain. Values must be binary (0/1); they are
    categorical occurrence flags, not probabilities.
    """
    flag = np.asarray(flag)
    out = np.zeros(flag.shape, dtype=np.uint8)
    out[np.isin(flag, RAIN_FLAGS)] = RAIN
    out[flag == 3] = SNOW
    supported = np.zeros(flag.shape, dtype=bool)
    if all(a is not None for a in (rain, snow, pellets, freezing)):
        fields = [np.asarray(a) for a in (rain, snow, pellets, freezing)]
        if any(a.shape != flag.shape for a in fields):
            raise ValueError("Winter phase grids must align")
        valid = np.logical_and.reduce([np.isin(a, (0, 1)) for a in fields])
        r, s, p, f = [a == 1 for a in fields]
        ice = p | f
        count = r.astype(np.uint8) + s.astype(np.uint8) + ice.astype(np.uint8)
        supported = valid & (count > 0) & (out != UNKNOWN)
        out[supported & r] = RAIN
        out[supported & s] = SNOW
        out[supported & ice] = ICE
        out[supported & (count > 1)] = MIX
    return out, supported


def colorize(dbz, classes):
    """Hue encodes phase; brightness encodes echo strength, not snowfall rate."""
    # A small lookup table avoids multi-gigabyte RGB float intermediates at
    # native CONUS dimensions. Echo strength is shown in 5-dBZ display bins.
    palette = np.zeros((5,15,4),dtype=np.uint8)
    for code, color in COLORS.items():
        rgb = np.array([int(color[i:i+2], 16) for i in (1, 3, 5)])
        for i in range(15):
            palette[code,i,:3] = rgb*(0.55+0.45*min(i/9,1))
            palette[code,i,3] = 255
    bins = np.clip((np.where(np.isfinite(dbz),dbz,0)-5)//5,0,14).astype(np.uint8)
    rgba = palette[classes,bins]
    rgba[~np.isfinite(dbz) | (dbz<5)] = 0
    return rgba
