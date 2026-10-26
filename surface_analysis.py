"""Display units, palettes and observed METAR values for the surface suite."""
from __future__ import annotations

import csv
import io
import math
from datetime import datetime, timezone

import numpy as np

REVISION = "rtma-surface-v4"
PRESSURE_REVISION = "hrrr-mslp-v2"
LEGACY_KEYS = ("temperature", "dewpoint", "wind_speed")
V2_KEYS = (*LEGACY_KEYS, "wind_direction", "wind_gust", "surface_pressure", "relative_humidity", "heat_index", "wind_chill")
BOUNDS = [[24.0, -125.0], [50.0, -66.0]]
ANALYSIS_WARN_MINUTES = 150
ANALYSIS_HIDE_MINUTES = 240
STATION_HIDE_MINUTES = 90
PRODUCTS = {
    "temperature": {
        "label": "2-m Temperature", "unit": "°F", "parameter": "TMP", "level": 2,
        "stops": [-40, -20, 0, 20, 32, 40, 50, 60, 70, 80, 90, 100, 110, 120],
        "colors": ["#6b1f91", "#843abf", "#2c40bd", "#0066e5", "#00b7f0", "#00c8b0", "#00a855", "#83c900", "#e7df00", "#ffb000", "#ff5b00", "#ee1515", "#c50070", "#7c009c"],
        "ticks": [-40, 0, 32, 60, 90, 120],
        "contour_interval": 10,
    },
    "dewpoint": {
        "label": "2-m Dewpoint", "unit": "°F", "parameter": "DPT", "level": 2,
        "stops": [-20, 0, 20, 30, 40, 50, 55, 60, 65, 70, 75, 80],
        "colors": ["#7a2c18", "#aa4a1c", "#cf7922", "#e9b13a", "#dad447", "#80c500", "#18b234", "#00a77f", "#009fc9", "#0069d9", "#3d36bb", "#9023b3"],
        "ticks": [-20, 0, 20, 40, 60, 80],
        "contour_interval": 10,
    },
    "wind_speed": {
        "label": "10-m Wind Speed", "unit": "kt", "parameter": "WIND", "level": 10,
        "stops": [0, 5, 10, 15, 20, 30, 40, 50, 60, 80],
        "colors": ["#0f2850", "#004fd1", "#00a6e8", "#00c4a1", "#55c928", "#e5dc00", "#ff9c00", "#f54015", "#cc157e", "#7413ae"],
        "ticks": [0, 10, 20, 40, 60, 80],
        "contour_interval": 10,
    },
}

PRODUCTS.update({
    "wind_gust": {
        "label": "10-m Wind Gust", "unit": "kt", "parameter": "GUST", "level": 10,
        "stops": [0,5,10,15,20,30,40,50,60,80],
        "colors": list(PRODUCTS["wind_speed"]["colors"]), "ticks": [0,10,20,40,60,80],
        "contour_interval": 10,
        "note": "RTMA wind-gust analysis at the displayed valid time; not an hourly maximum accumulation.",
    },
    "mslp": {
        "label": "Barometric Pressure (MSLP)", "unit": "hPa", "parameter": "MSLMA", "level": 0,
        "stops": [960,980,992,1000,1008,1012,1016,1020,1024,1028,1032,1040,1052,1060],
        "colors": ["#76148f","#4425ba","#144bdd","#007adb","#00afd3","#00c9b1","#35c45a","#a7d51b","#ffe000","#ffa000","#f45c13","#df2251","#ae218d","#641a93"],
        "ticks": [960,980,1000,1020,1040,1060],
        "contour_interval": 4, "smoothing_km": 18,
        "note": "Pressure reduced to mean sea level to compare the weather pattern across elevations. HRRR analysis uses MAPS sea-level reduction; station points show reported MSLP.",
    },
    "relative_humidity": {
        "label": "2-m Relative Humidity", "unit": "%", "derived_from": ["temperature","dewpoint"],
        "stops": [0,10,20,30,40,50,60,70,80,90,100],
        "colors": ["#aa3815","#cf5b10","#ec8b00","#f1be00","#d5db08","#80c61b","#12b34e","#00b293","#009cc8","#0067d9","#5130ba"],
        "ticks": [0,20,40,60,80,100],
        "contour_interval": 10,
        "method": "August-Roche-Magnus: 100*exp(17.625*Td/(243.04+Td)-17.625*T/(243.04+T)); T/Td in Celsius; RH relative to liquid water",
        "note": "Calculated from temperature and dewpoint; relative humidity with respect to liquid water, bounded to 0–100%.",
    },
    "heat_index": {
        "label": "Heat Index", "unit": "°F", "derived_from": ["temperature","relative_humidity"],
        "stops": [80,85,90,95,100,105,110,115,120,130,140],
        "colors": ["#ffe000","#ffc000","#ff9800","#ff6600","#f53313","#e31330","#cc075c","#ac0a8c","#8b0eaa","#650c91","#410766"],
        "ticks": [80,90,100,110,120,140],
        "contour_interval": 5,
        "method": "NWS/WPC Rothfusz regression with low/high humidity adjustments; displayed only when preliminary averaged Steadman HI >=80 F",
        "note": "Calculated for warm conditions passing the NWS preliminary 80°F heat-index screen. Other areas are transparent. Assumes shade/light wind.",
    },
    "wind_chill": {
        "label": "Wind Chill", "unit": "°F", "derived_from": ["temperature","wind_speed"],
        "stops": [-60,-40,-20,0,10,20,30,40,50],
        "colors": ["#7c0b98","#5a19bb","#243bdd","#006fe5","#009fdf","#00c3c6","#00bc86","#50c446","#bbd917"],
        "ticks": [-60,-40,-20,0,20,30,40,50],
        "contour_interval": 10,
        "method": "NWS: 35.74+0.6215*T-35.75*V^0.16+0.4275*T*V^0.16; T in F; V in mph; T<=50 F and V>3 mph",
        "note": "Calculated only at temperatures ≤50°F and sustained winds >3 mph. Other areas are transparent; gusts are not used.",
    },
})

RTMA_KEYS = tuple(key for key in PRODUCTS if key != "mslp")
SOURCE_FIELDS = {
    key: {**PRODUCTS[key], "type": "heightAboveGround",
          "grib": grib, "source_units": units}
    for key, grib, units in (
        ("temperature", (0,0,0), "K"), ("dewpoint", (0,0,6), "K"),
        ("wind_speed", (0,2,1), "m s**-1"), ("wind_gust", (0,2,22), "m s**-1"),
    )
}


def relative_humidity(temperature_f, dewpoint_f):
    t, d = np.broadcast_arrays(np.asarray(temperature_f,dtype="float64"), np.asarray(dewpoint_f,dtype="float64"))
    t, d = (t-32)/1.8, (d-32)/1.8
    valid = np.isfinite(t) & np.isfinite(d) & (t>=-90) & (t<=60) & (d>=-100) & (d<=t+.5)
    with np.errstate(invalid="ignore", over="ignore"):
        rh = 100*np.exp(17.625*d/(243.04+d)-17.625*t/(243.04+t))
    return np.where(valid,np.clip(rh,0,100),np.nan)


def heat_index(temperature_f, rh):
    """WPC screening and adjusted Rothfusz; cooler conditions remain missing."""
    t, r = np.broadcast_arrays(np.asarray(temperature_f,dtype="float64"),np.asarray(rh,dtype="float64"))
    preliminary = (.5*(t+61+1.2*(t-68)+.094*r)+t)/2
    valid = np.isfinite(t)&np.isfinite(r)&(r>=0)&(r<=100)&(t<=140)&(preliminary>=80)
    with np.errstate(invalid="ignore", over="ignore"):
        hi = (-42.379+2.04901523*t+10.14333127*r-.22475541*t*r-.00683783*t*t
              -.05481717*r*r+.00122874*t*t*r+.00085282*t*r*r-.00000199*t*t*r*r)
        dry = ((13-r)/4)*np.sqrt(np.maximum(0,(17-np.abs(t-95))/17))
        wet = ((r-85)/10)*((87-t)/5)
        hi = hi-np.where((r<13)&(t>=80)&(t<=112),dry,0)+np.where((r>85)&(t>=80)&(t<=87),wet,0)
    return np.where(valid,hi,np.nan)


def wind_chill(temperature_f, wind_kt):
    t, k = np.broadcast_arrays(np.asarray(temperature_f,dtype="float64"),np.asarray(wind_kt,dtype="float64"))
    mph = k*1.1507794480235
    valid = np.isfinite(t)&np.isfinite(k)&(t>=-130)&(t<=50)&(mph>3)&(k<=250)
    v = np.maximum(mph,0)**.16
    return np.where(valid,35.74+.6215*t-35.75*v+.4275*t*v,np.nan)


def derive_products(fields):
    rh=relative_humidity(fields["temperature"],fields["dewpoint"])
    return {**fields,"relative_humidity":rh.astype("float32"),
            "heat_index":heat_index(fields["temperature"],rh).astype("float32"),
            "wind_chill":wind_chill(fields["temperature"],fields["wind_speed"]).astype("float32")}


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
    if key in ("wind_speed", "wind_gust"):
        return np.where((a >= 0) & (a <= 130), a * 1.9438444924406, np.nan)
    if key == "mslp":
        return np.where((a>=85000)&(a<=110000),a/100,np.nan)
    raise ValueError("Unknown surface product")


def colorize(key, values):
    p = PRODUCTS[key]
    rgb = np.array([[int(c[i:i+2], 16) for i in (1, 3, 5)] for c in p["colors"]])
    a = np.asarray(values)
    finite = np.isfinite(a)
    safe = np.where(finite, np.mod(a,360) if p.get("cyclic") else a, p["stops"][0])
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
        gust = number(row.get("wind_gust_kt"), 0, 300)
        mslp = number(row.get("sea_level_pressure_mb"), 850, 1100)
        direction = number(row.get("wind_dir_degrees"),0,360)
        if speed is None or speed<1:
            direction=None
        elif direction is not None:
            direction=direction%360
        if temp is None and dew is None and speed is None and gust is None and mslp is None:
            continue
        tf = None if temp is None else temp*1.8+32
        df = None if dew is None else dew*1.8+32
        rh = float(relative_humidity(np.nan if tf is None else tf,np.nan if df is None else df))
        hi = float(heat_index(np.nan if tf is None else tf,rh))
        wc = float(wind_chill(np.nan if tf is None else tf,np.nan if speed is None else speed))
        optional = lambda n: round(n,1) if math.isfinite(n) else None
        points.append({"id": station, "lat": lat, "lon": lon, "time": iso(time),
                       "temperature": None if tf is None else round(tf,1), "dewpoint": None if df is None else round(df,1),
                       "wind_speed": speed, "wind_gust": gust, "wind_direction": direction,
                       "mslp": mslp, "relative_humidity":optional(rh), "heat_index":optional(hi), "wind_chill":optional(wc),
                       "raw": row.get("raw_text", "")[:500]})
    return points
