"""Experimental radar type classes. Hail is never a winter mix/ice flag.

MRMS PrecipFlag supplies precipitation support and a rain/snow fallback.
HRRR categorical surface fields supply winter phase information. Multiple
active phase families mean mix; sleet + freezing rain together still mean ice.
No temperatures, spatial smoothing, or invented transition bands are used.
"""
from __future__ import annotations

import numpy as np

REVISION = "mrms-hrrr-winter-v2"
FRAMES_DIR = "winter_frames_v2"
UNKNOWN, RAIN, MIX, SNOW, ICE = range(5)
COLORS = {RAIN: "#2bc45b", MIX: "#bf65d9", SNOW: "#50b9f2", ICE: "#f14d87"}
LABELS = {RAIN: "Rain", MIX: "Mix", SNOW: "Snow", ICE: "Ice (sleet/freezing rain)"}
RAIN_FLAGS = (1, 6, 7, 10, 91, 96)
THRESHOLDS_DBZ = list(range(5, 80, 5))
INTENSITY_COLORS = {
    RAIN: ['#8ce6b6','#49d17c','#23bc48','#139a32','#08732b','#b0ce22','#fff02b','#ffbc29','#ff8623','#f34b25','#db2027','#b80e24','#940b21','#72091c','#500615'],
    MIX: ['#f0e4fa','#e3cef4','#d5b3ec','#c795e4','#b77adb','#a763d0','#974dc3','#853bb4','#742da2','#63218e','#531879','#451163','#380c50','#2b083e','#20052e'],
    SNOW: ['#d0f7fa','#a7eef5','#7ce2f1','#50d1ed','#2ab9e5','#169cdb','#1b7bcf','#265cc2','#3845b1','#49349d','#542589','#531a74','#49125f','#3b0c4d','#2c073b'],
    ICE: ['#ffe3ef','#ffd0e5','#ffb8d8','#ff9dca','#ff80b9','#fa61a6','#f34392','#e72d7e','#d81e6d','#c4155f','#ad0e52','#940a47','#7c073c','#660531','#500426'],
}


def intensity_metadata():
    return {'units':'dBZ', 'thresholds_dbz':THRESHOLDS_DBZ,
            'colors':{str(c):colors for c,colors in INTENSITY_COLORS.items()},
            'bin_rule':'lower inclusive; 75+ uses final color; below 5 transparent'}


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
    for code, colors in INTENSITY_COLORS.items():
        for i,color in enumerate(colors):
            palette[code,i,:3] = [int(color[j:j+2],16) for j in (1,3,5)]
            palette[code,i,3] = 255
    bins = np.clip((np.where(np.isfinite(dbz),dbz,0)-5)//5,0,14).astype(np.uint8)
    rgba = palette[classes,bins]
    rgba[~np.isfinite(dbz) | (dbz<5)] = 0
    return rgba
