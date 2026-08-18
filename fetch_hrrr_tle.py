#!/usr/bin/env python3
"""
HRRR-TLE Flash Flood Guidance — Experimental
Dashboard production backend derived from the frozen Version 3.3 algorithm.

Scientific contract:
- Six hourly time-lagged HRRR cycles.
- Common 12-hour valid interval.
- Newest member f01-f12, then f02-f13 ... oldest f06-f17.
- 40-km neighborhood.
- Latest available 1/3/6-h FFG aligned to the HRRR grid.
- Member frequency / consensus is NOT calibrated probability.
- Missing HRRR hours are never zero-filled.
- Existing published dashboard files are only replaced after a complete build.
"""

from __future__ import annotations

import argparse
import gc
import json
import math
import os
import shutil
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import matplotlib
matplotlib.use("Agg")

import cartopy.crs as ccrs
import matplotlib.pyplot as plt
import numpy as np
import requests
import scipy.ndimage as ndimage
import xarray as xr

from matplotlib.colors import BoundaryNorm, ListedColormap
from requests.adapters import HTTPAdapter
from scipy.ndimage import convolve, maximum_filter
from scipy.spatial import cKDTree
from urllib3.util.retry import Retry

UTC = timezone.utc

# ------------------------------ science ------------------------------
GRID_RES_KM = 3.0
NEIGHBORHOOD_KM = 40.0
TLE_MEMBER_COUNT = 6
TLE_COMMON_HOURS = 12
MIN_TLE_MEMBERS = 6  # dashboard package requires all six for a complete product
SINGLE_RUN_MAX_FXX = 18  # frozen notebook value retained for helper compatibility
DASHBOARD_HRRR_DIAGNOSTIC_HOURS = 12

QPF_1H_THRESHOLDS_IN = (1.0, 2.0, 3.0)
EVOLUTION_WINDOW_HOURS = 3
EVOLUTION_DISPLAY_MIN_MEMBERS = 2
PERSISTENCE_WINDOW_HOURS = 3
PERSISTENCE_REQUIRED_HOURS = 2
PERSISTENCE_HOURLY_THRESHOLDS_IN = (1.00,)
PERSISTENCE_3H_TOTAL_THRESHOLDS_IN = (2.00, 3.00)
RUN_CHANGE_GROUP_SIZE = 3
RUN_CHANGE_MIN_GROUP_MEMBERS = 2

# Dashboard overlay extent. Cartopy Mercator rendering plus these same
# geographic bounds gives Leaflet an EPSG:3857-compatible ImageOverlay.
MAP_EXTENT = (-125.0, -66.5, 23.0, 50.5)  # west, east, south, north
LEAFLET_BOUNDS = [[MAP_EXTENT[2], MAP_EXTENT[0]], [MAP_EXTENT[3], MAP_EXTENT[1]]]

CACHE_ROOT = Path(os.environ.get("HRRR_TLE_CACHE", ".cache/hrrr_tle"))
HRRR_CACHE = CACHE_ROOT / "hrrr"
FFG_CACHE = CACHE_ROOT / "ffg"

radius_pts = max(1, int(round(NEIGHBORHOOD_KM / GRID_RES_KM)))
yy, xx = np.ogrid[-radius_pts:radius_pts + 1, -radius_pts:radius_pts + 1]
CIRCULAR_FOOTPRINT = (xx**2 + yy**2) <= radius_pts**2

# ------------------------------ colors -------------------------------
# Preserve the V3.3 visual language.
RATIO_LEVELS = [0.75, 1.0, 1.25, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 20.0]
RATIO_COLORS = [
    "#ffff00", "#ffa500", "#ff0000", "#8b0000",
    "#ff00ff", "#800080", "#0000ff", "#00ffff", "#00ffff",
]
FREQ_COLORS_6 = ["#fff59d", "#ffcc80", "#ff8a65", "#ef5350", "#ab47bc", "#5e35b1"]
FREQ_COLORS_5 = ["#ffcc80", "#ff8a65", "#ef5350", "#ab47bc", "#5e35b1"]
FREQ_COLORS_3 = ["#ffcc80", "#ef5350", "#5e35b1"]
RUN_CHANGE_COLORS = ["#4575b4", "#7b3294", "#fdae61"]
COVERAGE_LEVELS = [1.0, 5.0, 10.0, 25.0, 50.0, 75.0, 100.01]
COVERAGE_COLORS = ["#e0f7fa", "#c8e6c9", "#fff59d", "#ffb74d", "#f44336", "#9c27b0"]

LAYER_FILES = {
    "hrrr_max_ratio": "hrrr_latest_12h_max_ffg_ratio.png",
    "hrrr_ffg_coverage": "hrrr_latest_12h_ffg_exceedance_coverage.png",
    "ffg_consensus": "hrrr_tle_ffg_consensus.png",
    "median_ratio": "hrrr_tle_median_neighborhood_ratio.png",
    "ffg_1h": "hrrr_tle_ffg_1h.png",
    "ffg_3h": "hrrr_tle_ffg_3h.png",
    "ffg_6h": "hrrr_tle_ffg_6h.png",
    "qpf1h_1in": "hrrr_tle_qpf1h_1in.png",
    "qpf1h_2in": "hrrr_tle_qpf1h_2in.png",
    "qpf1h_3in": "hrrr_tle_qpf1h_3in.png",
    "evolution_00_03": "hrrr_tle_evolution_00_03.png",
    "evolution_03_06": "hrrr_tle_evolution_03_06.png",
    "evolution_06_09": "hrrr_tle_evolution_06_09.png",
    "evolution_09_12": "hrrr_tle_evolution_09_12.png",
    "persistence_1in_2of3": "hrrr_tle_persistence_1in_2of3.png",
    "persistence_3h_2in": "hrrr_tle_persistence_3h_2in.png",
    "persistence_3h_3in": "hrrr_tle_persistence_3h_3in.png",
    "prior3": "hrrr_tle_prior3_consensus.png",
    "latest3": "hrrr_tle_latest3_consensus.png",
    "run_change": "hrrr_tle_run_change.png",
}

MAKE_SMOOTHED_DISPLAY_FIELD = False
SMOOTH_SIGMA_GRIDPOINTS = 3.5

# ============================================================
# HTTP / TIME / GEOMETRY UTILITIES
# ============================================================

def build_http_session() -> requests.Session:
    retry = Retry(
        total=4,
        connect=4,
        read=4,
        status=4,
        backoff_factor=1.0,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(("GET", "HEAD")),
        raise_on_status=False,
    )
    session = requests.Session()
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.headers.update({"User-Agent": "WPC-HRRR-TLE-Dashboard/3.3"})
    return session


SESSION = build_http_session()


def utc_now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def hrrr_base_url(run_dt: datetime) -> str:
    return (
        "https://nomads.ncep.noaa.gov/pub/data/nccf/com/hrrr/prod/"
        f"hrrr.{run_dt:%Y%m%d}/conus"
    )


def hrrr_grib_url(run_dt: datetime, fxx: int) -> str:
    return f"{hrrr_base_url(run_dt)}/hrrr.t{run_dt:%H}z.wrfsfcf{fxx:02d}.grib2"


def apcp_1h_search_string(fxx: int) -> str:
    return f":APCP:surface:{fxx - 1}-{fxx} hour"


def find_latest_complete_hrrr(
    max_fxx: int = SINGLE_RUN_MAX_FXX,
    max_lookback_hours: int = 12,
) -> datetime:
    '''
    Find the newest HRRR cycle for which the requested hourly APCP
    record exists at max_fxx. This avoids using Herbie solely as an
    availability probe.
    '''
    now = utc_now_naive().replace(minute=0, second=0, microsecond=0)

    for offset in range(max_lookback_hours):
        run_dt = now - timedelta(hours=offset)
        idx_url = hrrr_grib_url(run_dt, max_fxx) + ".idx"
        try:
            r = SESSION.get(idx_url, timeout=15)
            wanted = apcp_1h_search_string(max_fxx)
            if r.status_code == 200 and wanted in r.text:
                print(f"✅ Latest complete HRRR cycle: {run_dt:%Y-%m-%d %HZ}")
                return run_dt
            print(f"ℹ️ {run_dt:%HZ} not complete through f{max_fxx:02d}")
        except requests.RequestException as exc:
            print(f"ℹ️ Could not check {run_dt:%HZ}: {exc}")

    raise RuntimeError(
        f"No HRRR cycle with hourly APCP through f{max_fxx:02d} "
        f"was found in the past {max_lookback_hours} hours."
    )


def latlon_to_unit_xyz(lat_deg: np.ndarray, lon_deg: np.ndarray) -> np.ndarray:
    '''
    Convert latitude/longitude to 3-D unit-sphere coordinates.
    This gives robust nearest-neighbor behavior across longitude wrapping.
    '''
    lat = np.deg2rad(np.asarray(lat_deg, dtype=float))
    lon = np.deg2rad(np.asarray(lon_deg, dtype=float))
    coslat = np.cos(lat)
    return np.column_stack(
        (
            (coslat * np.cos(lon)).ravel(),
            (coslat * np.sin(lon)).ravel(),
            np.sin(lat).ravel(),
        )
    )


def normalize_lons_for_plot(lons: np.ndarray) -> np.ndarray:
    return ((np.asarray(lons) + 180.0) % 360.0) - 180.0


def valid_window_label(start_dt: datetime, end_dt: datetime) -> str:
    if start_dt.date() == end_dt.date():
        return f"{start_dt:%Y-%m-%d %HZ}–{end_dt:%HZ}"
    return f"{start_dt:%Y-%m-%d %HZ}–{end_dt:%Y-%m-%d %HZ}"


# ============================================================
# HRRR HOURLY APCP RETRIEVAL
# ============================================================

def _extract_idx_byte_range(idx_text: str, search_str: str):
    lines = [ln for ln in idx_text.splitlines() if ln.strip()]

    for i, line in enumerate(lines):
        if search_str not in line:
            continue

        parts = line.split(":")
        if len(parts) < 2:
            continue

        start_byte = int(parts[1])
        end_byte = None

        if i + 1 < len(lines):
            next_parts = lines[i + 1].split(":")
            if len(next_parts) >= 2:
                end_byte = int(next_parts[1]) - 1

        return start_byte, end_byte

    return None, None


def download_nomads_subset(
    grib_url: str,
    search_str: str,
    local_file: Path,
) -> None:
    '''
    Download only the GRIB message matching search_str by using the
    NOMADS .idx byte offsets.
    '''
    local_file.parent.mkdir(parents=True, exist_ok=True)

    idx_resp = SESSION.get(grib_url + ".idx", timeout=20)
    if idx_resp.status_code != 200:
        raise RuntimeError(f"IDX HTTP {idx_resp.status_code}: {grib_url}.idx")

    start_byte, end_byte = _extract_idx_byte_range(idx_resp.text, search_str)
    if start_byte is None:
        raise RuntimeError(f"Could not locate '{search_str}' in {grib_url}.idx")

    range_value = (
        f"bytes={start_byte}-{end_byte}"
        if end_byte is not None
        else f"bytes={start_byte}-"
    )

    grib_resp = SESSION.get(
        grib_url,
        headers={"Range": range_value},
        timeout=45,
    )

    if grib_resp.status_code not in (200, 206):
        raise RuntimeError(f"GRIB HTTP {grib_resp.status_code}: {grib_url}")

    # A server that ignores Range can return the full GRIB with HTTP 200.
    # Accept 200 only when the returned byte count matches our expected
    # subset size (when an end byte is known).
    if grib_resp.status_code == 200 and end_byte is not None:
        expected = end_byte - start_byte + 1
        if len(grib_resp.content) != expected:
            raise RuntimeError(
                "NOMADS ignored the byte-range request and returned a "
                "different-sized object; refusing to cache an ambiguous file."
            )

    if len(grib_resp.content) < 100:
        raise RuntimeError(f"Downloaded subset is unexpectedly small: {grib_url}")

    tmp = local_file.with_suffix(local_file.suffix + ".part")
    tmp.write_bytes(grib_resp.content)
    tmp.replace(local_file)


def _read_apcp_subset(local_file: Path):
    ds = xr.open_dataset(
        local_file,
        engine="cfgrib",
        backend_kwargs={"indexpath": ""},
    )
    try:
        if not ds.data_vars:
            raise RuntimeError(f"No data variables found in {local_file}")

        # Prefer a variable whose GRIB metadata indicates total precipitation.
        candidates = []
        for name, da in ds.data_vars.items():
            short_name = str(da.attrs.get("GRIB_shortName", "")).lower()
            if name.lower() in {"tp", "apcp"} or short_name in {"tp", "apcp"}:
                candidates.append(name)

        vname = candidates[0] if candidates else list(ds.data_vars)[0]
        da = ds[vname]

        if da.ndim != 2:
            raise RuntimeError(
                f"Expected 2-D hourly APCP, got {da.ndim}-D variable '{vname}'"
            )

        if "latitude" not in ds or "longitude" not in ds:
            raise RuntimeError("Latitude/longitude coordinates are missing")

        qpf_in = np.asarray(da.values, dtype=float) / 25.4
        lats = np.asarray(ds.latitude.values, dtype=float)
        lons = np.asarray(ds.longitude.values, dtype=float)
        return qpf_in, lats, lons
    finally:
        ds.close()


def get_hrrr_hourly_qpf(
    run_dt: datetime,
    fxx_list,
):
    '''
    Retrieve a complete list of incremental 1-hour APCP fields.
    Missing/corrupt hours cause this member to fail; they are never
    silently replaced with zero precipitation.
    '''
    fxx_list = [int(x) for x in fxx_list]
    if not fxx_list or min(fxx_list) < 1:
        raise ValueError("fxx_list must contain forecast hours >= 1")

    fields = []
    lats = lons = None

    cycle_dir = HRRR_CACHE / f"{run_dt:%Y%m%d}" / f"{run_dt:%H}"
    cycle_dir.mkdir(parents=True, exist_ok=True)

    for fxx in fxx_list:
        grib_url = hrrr_grib_url(run_dt, fxx)
        local_file = cycle_dir / (
            f"hrrr.{run_dt:%Y%m%d}.t{run_dt:%H}z."
            f"wrfsfcf{fxx:02d}.apcp_1h.grib2"
        )
        search_str = apcp_1h_search_string(fxx)

        last_error = None
        for attempt in (1, 2):
            try:
                if not local_file.exists() or local_file.stat().st_size < 100:
                    download_nomads_subset(grib_url, search_str, local_file)

                qpf_in, lat_i, lon_i = _read_apcp_subset(local_file)

                if lats is None:
                    lats, lons = lat_i, lon_i
                else:
                    if lat_i.shape != lats.shape or lon_i.shape != lons.shape:
                        raise RuntimeError("HRRR grid geometry changed within member")

                fields.append(qpf_in)
                last_error = None
                break

            except Exception as exc:
                last_error = exc
                if local_file.exists():
                    local_file.unlink(missing_ok=True)

        if last_error is not None:
            raise RuntimeError(
                f"Failed HRRR {run_dt:%Y-%m-%d %HZ} f{fxx:02d}: {last_error}"
            )

    return np.stack(fields, axis=0), lats, lons


# ============================================================
# FFG RETRIEVAL AND ALIGNMENT
# ============================================================

def _select_ffg_variable(ds: xr.Dataset) -> str:
    if not ds.data_vars:
        raise RuntimeError("FFG dataset contains no data variables")

    # FFG archives are compact; retain a conservative fallback but validate
    # the resulting field later.
    return list(ds.data_vars)[0]


def _open_ffg_duration(local_path: Path, step_range: str):
    ds = xr.open_dataset(
        local_path,
        engine="cfgrib",
        backend_kwargs={
            "filter_by_keys": {"stepRange": step_range},
            "indexpath": "",
        },
    )
    try:
        vname = _select_ffg_variable(ds)
        da = ds[vname]

        if da.ndim != 2:
            raise RuntimeError(
                f"Expected 2-D FFG field for stepRange={step_range}; got {da.ndim}-D"
            )

        vals_in = np.asarray(da.values, dtype=float) / 25.4
        lats = np.asarray(da.latitude.values, dtype=float)
        lons = np.asarray(da.longitude.values, dtype=float)
        return vals_in, lats, lons
    finally:
        ds.close()


def fetch_and_align_ffg(
    reference_dt: datetime,
    target_lats: np.ndarray,
    target_lons: np.ndarray,
    max_lookback_hours: int = 48,
):
    '''
    Find the newest available IEM FFG grid at or before reference_dt,
    then map 1-, 3-, and 6-hour FFG to the HRRR grid.
    '''
    local_ffg_path = None
    ffg_dt = None

    for offset in range(max_lookback_hours):
        dt = reference_dt - timedelta(hours=offset)
        date_path = dt.strftime("%Y/%m/%d")
        file_time = dt.strftime("%Y%m%d%H")
        url = (
            "https://mesonet.agron.iastate.edu/archive/data/"
            f"{date_path}/model/ffg/5kmffg_{file_time}.grib2"
        )
        local = FFG_CACHE / f"{dt:%Y%m%d}" / f"5kmffg_{file_time}.grib2"
        local.parent.mkdir(parents=True, exist_ok=True)

        if local.exists() and local.stat().st_size > 1000:
            local_ffg_path = local
            ffg_dt = dt
            break

        try:
            r = SESSION.get(url, timeout=30)
            if r.status_code == 200 and len(r.content) > 1000:
                tmp = local.with_suffix(local.suffix + ".part")
                tmp.write_bytes(r.content)
                tmp.replace(local)
                local_ffg_path = local
                ffg_dt = dt
                break
        except requests.RequestException:
            pass

    if local_ffg_path is None or ffg_dt is None:
        raise RuntimeError(
            f"No IEM FFG grid found in the {max_lookback_hours} h "
            f"ending at {reference_dt:%Y-%m-%d %HZ}"
        )

    ffg1_src, src_lat1, src_lon1 = _open_ffg_duration(local_ffg_path, "0-1")
    ffg3_src, src_lat3, src_lon3 = _open_ffg_duration(local_ffg_path, "0-3")
    ffg6_src, src_lat6, src_lon6 = _open_ffg_duration(local_ffg_path, "0-6")

    if not (
        src_lat1.shape == src_lat3.shape == src_lat6.shape
        and src_lon1.shape == src_lon3.shape == src_lon6.shape
    ):
        raise RuntimeError("1/3/6-h FFG grids do not share the same geometry")

    src_xyz = latlon_to_unit_xyz(src_lat1, src_lon1)
    target_xyz = latlon_to_unit_xyz(target_lats, target_lons)

    tree = cKDTree(src_xyz)
    _, idxs = tree.query(target_xyz, k=1)

    shape = target_lats.shape
    ffg_1h = ffg1_src.ravel()[idxs].reshape(shape)
    ffg_3h = ffg3_src.ravel()[idxs].reshape(shape)
    ffg_6h = ffg6_src.ravel()[idxs].reshape(shape)

    # Only positive finite guidance values are usable in ratios.
    for arr in (ffg_1h, ffg_3h, ffg_6h):
        arr[~np.isfinite(arr) | (arr <= 0)] = np.nan

    age_h = (reference_dt - ffg_dt).total_seconds() / 3600.0
    print(f"✅ FFG analysis: {ffg_dt:%Y-%m-%d %HZ} (age {age_h:.1f} h)")

    return ffg_1h, ffg_3h, ffg_6h, ffg_dt


# ============================================================
# HYDROMETEOROLOGICAL METRICS
# ============================================================

def rolling_accumulations(qpf_stack: np.ndarray, hours: int) -> np.ndarray:
    '''
    Rolling accumulation ending at each eligible forecast hour.
    A duration is only evaluated when its full accumulation window lies
    inside the supplied common valid-time interval.
    '''
    if hours < 1:
        raise ValueError("hours must be >= 1")
    if qpf_stack.shape[0] < hours:
        raise ValueError(
            f"Need at least {hours} hourly fields; got {qpf_stack.shape[0]}"
        )

    return np.stack(
        [
            np.sum(qpf_stack[t - hours + 1:t + 1], axis=0)
            for t in range(hours - 1, qpf_stack.shape[0])
        ],
        axis=0,
    )


def max_ratio_for_duration(
    qpf_stack: np.ndarray,
    ffg: np.ndarray,
    hours: int,
) -> np.ndarray:
    qpf_accum = rolling_accumulations(qpf_stack, hours)
    safe_ffg = np.where(np.isfinite(ffg) & (ffg > 0), ffg, np.nan)

    with np.errstate(invalid="ignore", divide="ignore"):
        ratio_stack = qpf_accum / safe_ffg[None, ...]

    return np.nanmax(ratio_stack, axis=0)


def compute_run_ratio_fields(
    qpf_stack: np.ndarray,
    ffg_1h: np.ndarray,
    ffg_3h: np.ndarray,
    ffg_6h: np.ndarray,
):
    ratio_1h = max_ratio_for_duration(qpf_stack, ffg_1h, 1)
    ratio_3h = max_ratio_for_duration(qpf_stack, ffg_3h, 3)
    ratio_6h = max_ratio_for_duration(qpf_stack, ffg_6h, 6)

    combined = np.nanmax(
        np.stack((ratio_1h, ratio_3h, ratio_6h), axis=0),
        axis=0,
    )

    return {
        "1h": ratio_1h,
        "3h": ratio_3h,
        "6h": ratio_6h,
        "combined": combined,
    }


def neighborhood_max(field: np.ndarray) -> np.ndarray:
    work = np.where(np.isfinite(field), field, -np.inf)
    out = maximum_filter(
        work,
        footprint=CIRCULAR_FOOTPRINT,
        mode="constant",
        cval=-np.inf,
    )
    out[~np.isfinite(out)] = np.nan
    return out


def neighborhood_event(binary_event: np.ndarray) -> np.ndarray:
    '''
    1 where the event occurs anywhere inside the neighborhood, else 0.
    '''
    return maximum_filter(
        np.asarray(binary_event, dtype=float),
        footprint=CIRCULAR_FOOTPRINT,
        mode="constant",
        cval=0.0,
    )


def neighborhood_coverage_fraction(binary_event: np.ndarray) -> np.ndarray:
    count = convolve(
        np.asarray(binary_event, dtype=float),
        CIRCULAR_FOOTPRINT.astype(float),
        mode="constant",
        cval=0.0,
    )
    return 100.0 * count / float(CIRCULAR_FOOTPRINT.sum())


def member_frequency(member_binary_fields) -> np.ndarray:
    '''
    Percentage of available members containing the event.
    This is member frequency / consensus, NOT calibrated probability.
    '''
    stack = np.stack(member_binary_fields, axis=0).astype(float)
    return 100.0 * np.mean(stack, axis=0)


def optional_smoothed_display(raw_frequency: np.ndarray):
    if not MAKE_SMOOTHED_DISPLAY_FIELD:
        return None
    return ndimage.gaussian_filter(
        raw_frequency,
        sigma=SMOOTH_SIGMA_GRIDPOINTS,
    )


# ====================================================================
# DASHBOARD-SPECIFIC AVAILABILITY / TIMING
# ====================================================================

def _idx_contains_apcp(run_dt: datetime, fxx: int) -> bool:
    try:
        r = SESSION.get(hrrr_grib_url(run_dt, fxx) + ".idx", timeout=18)
        return r.status_code == 200 and apcp_1h_search_string(fxx) in r.text
    except requests.RequestException:
        return False


def aligned_member_fxx(member_index: int) -> list[int]:
    return list(range(1 + member_index, 1 + member_index + TLE_COMMON_HOURS))


def candidate_is_complete(latest_dt: datetime) -> bool:
    """
    Fast production readiness test:
    verify the maximum required incremental APCP message for each of the six
    aligned HRRR members (f12 through f17). The actual download stage still
    validates every required hour and refuses zero-fill.
    """
    for member_index in range(TLE_MEMBER_COUNT):
        run_dt = latest_dt - timedelta(hours=member_index)
        max_fxx = TLE_COMMON_HOURS + member_index
        if not _idx_contains_apcp(run_dt, max_fxx):
            return False
    return True


def find_latest_tle_cycle(max_lookback_hours: int = 14) -> datetime:
    now = datetime.now(UTC).replace(tzinfo=None, minute=0, second=0, microsecond=0)
    for offset in range(max_lookback_hours + 1):
        candidate = now - timedelta(hours=offset)
        print(f"Checking HRRR-TLE readiness for {candidate:%Y-%m-%d %HZ} ...")
        if candidate_is_complete(candidate):
            print(f"✅ Newest complete HRRR-TLE anchor cycle: {candidate:%Y-%m-%d %HZ}")
            return candidate
    raise RuntimeError("No complete six-cycle HRRR-TLE package found in lookback window.")


# ====================================================================
# V3.3 TIMING / PERSISTENCE FUNCTIONS
# ====================================================================

def hourly_combined_ratio_stack(qpf_stack, ffg_1h, ffg_3h, ffg_6h):
    safe_1h = np.where(np.isfinite(ffg_1h) & (ffg_1h > 0), ffg_1h, np.nan)
    safe_3h = np.where(np.isfinite(ffg_3h) & (ffg_3h > 0), ffg_3h, np.nan)
    safe_6h = np.where(np.isfinite(ffg_6h) & (ffg_6h > 0), ffg_6h, np.nan)
    hourly_ratios = []
    for t in range(qpf_stack.shape[0]):
        components = []
        with np.errstate(invalid="ignore", divide="ignore"):
            components.append(qpf_stack[t] / safe_1h)
            if t >= 2:
                components.append(np.sum(qpf_stack[t - 2:t + 1], axis=0) / safe_3h)
            if t >= 5:
                components.append(np.sum(qpf_stack[t - 5:t + 1], axis=0) / safe_6h)
        hourly_ratios.append(np.nanmax(np.stack(components, axis=0), axis=0))
    return np.stack(hourly_ratios, axis=0)


def hourly_neighborhood_exceedance_stack(hourly_ratio_stack):
    fields = []
    for ratio in hourly_ratio_stack:
        raw = (np.isfinite(ratio) & (ratio >= 1.0)).astype(np.float32)
        fields.append(neighborhood_event(raw))
    return np.stack(fields, axis=0).astype(np.uint8)


def any_event_in_hour_slice(hourly_event_stack, start_idx, end_idx):
    return np.max(hourly_event_stack[start_idx:end_idx], axis=0)


def repeated_hourly_qpf_event(qpf_stack, threshold_in,
                              required_hours=PERSISTENCE_REQUIRED_HOURS,
                              window_hours=PERSISTENCE_WINDOW_HOURS):
    event = np.zeros(qpf_stack.shape[1:], dtype=bool)
    for start in range(0, qpf_stack.shape[0] - window_hours + 1):
        hit_count = np.sum(qpf_stack[start:start + window_hours] >= threshold_in, axis=0)
        event |= hit_count >= required_hours
    return event.astype(np.float32)


def max_rolling_qpf_event(qpf_stack, hours, threshold_in):
    accum = rolling_accumulations(qpf_stack, hours)
    max_accum = np.nanmax(accum, axis=0)
    return (np.isfinite(max_accum) & (max_accum >= threshold_in)).astype(np.float32)


# ====================================================================
# RENDERING
# ====================================================================

def _mercator_figsize():
    west, east, south, north = MAP_EXTENT
    def my(lat):
        lat = np.deg2rad(lat)
        return np.log(np.tan(np.pi / 4.0 + lat / 2.0))
    width = np.deg2rad(east - west)
    height = my(north) - my(south)
    ratio = width / height
    return (16.0, 16.0 / ratio)


def render_overlay(data, out_path: Path, levels, colors, mask_below=None):
    arr = np.asarray(data, dtype=np.float32)
    if mask_below is not None:
        arr = np.where(arr >= mask_below, arr, np.nan)
    arr = np.ma.masked_invalid(arr)

    cmap = ListedColormap(colors)
    cmap.set_bad((0, 0, 0, 0))
    cmap.set_under((0, 0, 0, 0))
    norm = BoundaryNorm(levels, cmap.N, clip=False)

    fig = plt.figure(figsize=_mercator_figsize(), dpi=100)
    fig.patch.set_alpha(0.0)
    ax = fig.add_axes([0, 0, 1, 1], projection=ccrs.Mercator())
    ax.set_extent(MAP_EXTENT, crs=ccrs.PlateCarree())
    ax.set_axis_off()
    ax.patch.set_alpha(0.0)

    ax.pcolormesh(
        normalize_lons_for_plot(lons),
        lats,
        arr,
        cmap=cmap,
        norm=norm,
        transform=ccrs.PlateCarree(),
        shading="auto",
        rasterized=True,
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, transparent=True, facecolor="none", edgecolor="none", pad_inches=0)
    plt.close(fig)


def frequency_levels(member_count: int, minimum_count: int = 1):
    step = 100.0 / member_count
    counts = list(range(minimum_count, member_count + 1))
    centers = [step * c for c in counts]
    low = centers[0] - step / 2.0
    edges = [low] + [c + step / 2.0 for c in centers]
    edges[-1] = 100.01
    return edges


def write_json(path: Path, payload: dict):
    path.write_text(json.dumps(payload, indent=2, sort_keys=False), encoding="utf-8")


# ====================================================================
# MAIN SCIENCE + PACKAGE BUILD
# ====================================================================

def build(output_dir: Path, force: bool = False) -> int:
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "hrrr_tle_manifest.json"

    latest_dt = find_latest_tle_cycle()
    latest_hrrr_dt = find_latest_complete_hrrr(
        max_fxx=DASHBOARD_HRRR_DIAGNOSTIC_HOURS,
        max_lookback_hours=14,
    )

    if manifest_path.exists() and not force:
        try:
            old = json.loads(manifest_path.read_text(encoding="utf-8"))
            same_tle = old.get("latest_cycle_utc") == latest_dt.strftime("%Y-%m-%dT%H:00:00Z")
            same_hrrr = old.get("latest_hrrr_diagnostic_cycle_utc") == latest_hrrr_dt.strftime("%Y-%m-%dT%H:00:00Z")
            if same_tle and same_hrrr:
                print("ℹ️ Newest HRRR diagnostics and HRRR-TLE package are already published; exiting without churn.")
                return 0
        except Exception:
            pass

    common_valid_times = [latest_dt + timedelta(hours=h) for h in range(1, TLE_COMMON_HOURS + 1)]
    common_start = latest_dt
    common_end = common_valid_times[-1]
    tle_run_dts = [latest_dt - timedelta(hours=i) for i in range(TLE_MEMBER_COUNT)]

    # Download newest aligned member first to establish HRRR grid.
    print(f"\n--- Member 0: {latest_dt:%Y-%m-%d %HZ} f01-f12 ---")
    qpf0, lats0, lons0 = get_hrrr_hourly_qpf(latest_dt, aligned_member_fxx(0))
    global lats, lons
    lats = lats0
    lons = lons0

    ffg_1h, ffg_3h, ffg_6h, ffg_dt = fetch_and_align_ffg(latest_dt, lats, lons)
    ffg_age_h = (latest_dt - ffg_dt).total_seconds() / 3600.0

    # ------------------------------------------------------------
    # Latest deterministic HRRR diagnostics — independent of TLE.
    # Use the newest HRRR cycle complete through f12, even when that
    # cycle is newer than the six-cycle TLE anchor.
    # ------------------------------------------------------------
    diagnostic_fxx = list(range(1, DASHBOARD_HRRR_DIAGNOSTIC_HOURS + 1))
    print(
        f"\n--- Latest HRRR diagnostics: {latest_hrrr_dt:%Y-%m-%d %HZ} "
        f"f01-f{DASHBOARD_HRRR_DIAGNOSTIC_HOURS:02d} ---"
    )

    if latest_hrrr_dt == latest_dt:
        qpf_hrrr = qpf0.astype(np.float32, copy=False)
        diag_lats, diag_lons = lats, lons
        diag_ffg_1h, diag_ffg_3h, diag_ffg_6h, diag_ffg_dt = (
            ffg_1h, ffg_3h, ffg_6h, ffg_dt
        )
    else:
        qpf_hrrr, diag_lats, diag_lons = get_hrrr_hourly_qpf(
            latest_hrrr_dt,
            diagnostic_fxx,
        )
        qpf_hrrr = qpf_hrrr.astype(np.float32, copy=False)
        if diag_lats.shape != lats.shape or diag_lons.shape != lons.shape:
            raise RuntimeError("Latest-HRRR diagnostic grid geometry mismatch")
        diag_ffg_1h, diag_ffg_3h, diag_ffg_6h, diag_ffg_dt = fetch_and_align_ffg(
            latest_hrrr_dt,
            lats,
            lons,
        )

    diagnostic_ffg_age_h = (
        latest_hrrr_dt - diag_ffg_dt
    ).total_seconds() / 3600.0

    diagnostic_ratios = compute_run_ratio_fields(
        qpf_hrrr,
        diag_ffg_1h,
        diag_ffg_3h,
        diag_ffg_6h,
    )
    diagnostic_max_ratio = neighborhood_max(
        diagnostic_ratios["combined"]
    ).astype(np.float32)

    diagnostic_exceed_raw = (
        np.isfinite(diagnostic_ratios["combined"])
        & (diagnostic_ratios["combined"] >= 1.0)
    ).astype(np.float32)
    diagnostic_ffg_coverage = neighborhood_coverage_fraction(
        diagnostic_exceed_raw
    ).astype(np.float32)

    diagnostic_valid_start = latest_hrrr_dt
    diagnostic_valid_end = latest_hrrr_dt + timedelta(
        hours=DASHBOARD_HRRR_DIAGNOSTIC_HOURS
    )

    member_records = []
    for member_index, run_dt in enumerate(tle_run_dts):
        fxx = aligned_member_fxx(member_index)
        try:
            if member_index == 0:
                qpf = qpf0.astype(np.float32, copy=False)
                lat_m, lon_m = lats, lons
            else:
                print(f"\n--- Member {member_index}: {run_dt:%Y-%m-%d %HZ} "
                      f"f{fxx[0]:02d}-f{fxx[-1]:02d} ---")
                qpf, lat_m, lon_m = get_hrrr_hourly_qpf(run_dt, fxx)
                qpf = qpf.astype(np.float32, copy=False)

            if lat_m.shape != lats.shape or lon_m.shape != lons.shape:
                raise RuntimeError("HRRR member grid geometry mismatch")

            ratios = compute_run_ratio_fields(qpf, ffg_1h, ffg_3h, ffg_6h)
            ratios = {k: np.asarray(v, dtype=np.float32) for k, v in ratios.items()}
            member_records.append({"run_dt": run_dt, "fxx": fxx, "qpf": qpf, "ratios": ratios})
        except Exception as exc:
            raise RuntimeError(f"Required member {run_dt:%Y-%m-%d %HZ} failed: {exc}") from exc

    n_members = len(member_records)
    if n_members != TLE_MEMBER_COUNT:
        raise RuntimeError(f"Dashboard publication requires 6/6 members; got {n_members}/6.")

    # Core magnitude and consensus.
    tle_member_neighborhood_ratio = np.stack(
        [neighborhood_max(rec["ratios"]["combined"]).astype(np.float32) for rec in member_records],
        axis=0,
    )
    tle_median_neighborhood_ratio = np.nanmedian(tle_member_neighborhood_ratio, axis=0).astype(np.float32)
    del tle_member_neighborhood_ratio

    tle_combined_events = []
    for rec in member_records:
        event = (np.isfinite(rec["ratios"]["combined"]) & (rec["ratios"]["combined"] >= 1.0)).astype(np.float32)
        tle_combined_events.append(neighborhood_event(event).astype(np.uint8))
    tle_frequency_raw = member_frequency(tle_combined_events).astype(np.float32)

    tle_duration_frequency = {}
    for duration in ("1h", "3h", "6h"):
        events = []
        for rec in member_records:
            ratio = rec["ratios"][duration]
            event = (np.isfinite(ratio) & (ratio >= 1.0)).astype(np.float32)
            events.append(neighborhood_event(event).astype(np.uint8))
        tle_duration_frequency[duration] = member_frequency(events).astype(np.float32)

    tle_qpf1h_frequency = {}
    for threshold in QPF_1H_THRESHOLDS_IN:
        events = []
        for rec in member_records:
            max_qpf1h = np.nanmax(rec["qpf"], axis=0)
            event = (np.isfinite(max_qpf1h) & (max_qpf1h >= threshold)).astype(np.float32)
            events.append(neighborhood_event(event).astype(np.uint8))
        tle_qpf1h_frequency[threshold] = member_frequency(events).astype(np.float32)

    # Hourly / evolution / persistence.
    for rec in member_records:
        hourly_ratio = hourly_combined_ratio_stack(rec["qpf"], ffg_1h, ffg_3h, ffg_6h)
        rec["hourly_neigh_ffg_event"] = hourly_neighborhood_exceedance_stack(hourly_ratio)
        del hourly_ratio
        gc.collect()

    evolution = {}
    for start in range(0, TLE_COMMON_HOURS, EVOLUTION_WINDOW_HOURS):
        end = start + EVOLUTION_WINDOW_HOURS
        events = [any_event_in_hour_slice(rec["hourly_neigh_ffg_event"], start, end)
                  for rec in member_records]
        evolution[(start, end)] = member_frequency(events).astype(np.float32)

    persistence = {}
    for threshold in PERSISTENCE_HOURLY_THRESHOLDS_IN:
        events = [
            neighborhood_event(repeated_hourly_qpf_event(rec["qpf"], threshold)).astype(np.uint8)
            for rec in member_records
        ]
        persistence[f"2of3_ge_{threshold:.2f}in"] = member_frequency(events).astype(np.float32)

    for threshold in PERSISTENCE_3H_TOTAL_THRESHOLDS_IN:
        events = [
            neighborhood_event(max_rolling_qpf_event(rec["qpf"], 3, threshold)).astype(np.uint8)
            for rec in member_records
        ]
        persistence[f"3h_ge_{threshold:.2f}in"] = member_frequency(events).astype(np.float32)

    latest_group_count = np.sum(np.stack(tle_combined_events[:3], axis=0), axis=0)
    prior_group_count = np.sum(np.stack(tle_combined_events[3:6], axis=0), axis=0)
    latest_group_frequency = (100.0 * latest_group_count / 3.0).astype(np.float32)
    prior_group_frequency = (100.0 * prior_group_count / 3.0).astype(np.float32)

    latest_signal = latest_group_count >= RUN_CHANGE_MIN_GROUP_MEMBERS
    prior_signal = prior_group_count >= RUN_CHANGE_MIN_GROUP_MEMBERS
    run_change = np.zeros(lats.shape, dtype=np.uint8)
    run_change[prior_signal & ~latest_signal] = 1
    run_change[prior_signal & latest_signal] = 2
    run_change[~prior_signal & latest_signal] = 3

    # Build into a staging directory; publish only after every PNG + metadata succeeds.
    staging = Path(tempfile.mkdtemp(prefix="hrrr_tle_stage_", dir=str(output_dir.parent)))
    try:
        freq6_levels = frequency_levels(6, 1)
        freq5_levels = frequency_levels(6, 2)
        freq3_levels = frequency_levels(3, 1)

        # Latest deterministic HRRR diagnostics (standalone, not TLE).
        render_overlay(
            diagnostic_max_ratio,
            staging / LAYER_FILES["hrrr_max_ratio"],
            RATIO_LEVELS,
            RATIO_COLORS,
            mask_below=0.75,
        )
        render_overlay(
            diagnostic_ffg_coverage,
            staging / LAYER_FILES["hrrr_ffg_coverage"],
            COVERAGE_LEVELS,
            COVERAGE_COLORS,
            mask_below=1.0,
        )

        render_overlay(tle_frequency_raw, staging / LAYER_FILES["ffg_consensus"],
                       freq6_levels, FREQ_COLORS_6, mask_below=100/6 - 0.1)
        render_overlay(tle_median_neighborhood_ratio, staging / LAYER_FILES["median_ratio"],
                       RATIO_LEVELS, RATIO_COLORS, mask_below=0.75)

        for dur, key in [("1h", "ffg_1h"), ("3h", "ffg_3h"), ("6h", "ffg_6h")]:
            render_overlay(tle_duration_frequency[dur], staging / LAYER_FILES[key],
                           freq6_levels, FREQ_COLORS_6, mask_below=100/6 - 0.1)

        for threshold, key in [(1.0, "qpf1h_1in"), (2.0, "qpf1h_2in"), (3.0, "qpf1h_3in")]:
            render_overlay(tle_qpf1h_frequency[threshold], staging / LAYER_FILES[key],
                           freq6_levels, FREQ_COLORS_6, mask_below=100/6 - 0.1)

        for (start, end), key in [
            ((0,3), "evolution_00_03"),
            ((3,6), "evolution_03_06"),
            ((6,9), "evolution_06_09"),
            ((9,12), "evolution_09_12"),
        ]:
            render_overlay(evolution[(start, end)], staging / LAYER_FILES[key],
                           freq5_levels, FREQ_COLORS_5, mask_below=200/6 - 0.1)

        render_overlay(persistence["2of3_ge_1.00in"], staging / LAYER_FILES["persistence_1in_2of3"],
                       freq6_levels, FREQ_COLORS_6, mask_below=100/6 - 0.1)
        render_overlay(persistence["3h_ge_2.00in"], staging / LAYER_FILES["persistence_3h_2in"],
                       freq6_levels, FREQ_COLORS_6, mask_below=100/6 - 0.1)
        render_overlay(persistence["3h_ge_3.00in"], staging / LAYER_FILES["persistence_3h_3in"],
                       freq6_levels, FREQ_COLORS_6, mask_below=100/6 - 0.1)

        render_overlay(prior_group_frequency, staging / LAYER_FILES["prior3"],
                       freq3_levels, FREQ_COLORS_3, mask_below=100/3 - 0.1)
        render_overlay(latest_group_frequency, staging / LAYER_FILES["latest3"],
                       freq3_levels, FREQ_COLORS_3, mask_below=100/3 - 0.1)
        render_overlay(run_change, staging / LAYER_FILES["run_change"],
                       [0.5, 1.5, 2.5, 3.5], RUN_CHANGE_COLORS, mask_below=0.5)

        latest_cycles = [rec["run_dt"].strftime("%HZ") for rec in member_records[:3]]
        prior_cycles = [rec["run_dt"].strftime("%HZ") for rec in member_records[3:6]]

        metadata = {
            "metadata_mode": "hrrr_tle_dashboard_v3_3",
            "algorithm_version": "3.3",
            "experimental": True,
            "latest_hrrr_diagnostic_cycle_utc": latest_hrrr_dt.strftime("%Y-%m-%dT%H:00:00Z"),
            "hrrr_diagnostic_valid_start_utc": diagnostic_valid_start.strftime("%Y-%m-%dT%H:00:00Z"),
            "hrrr_diagnostic_valid_end_utc": diagnostic_valid_end.strftime("%Y-%m-%dT%H:00:00Z"),
            "hrrr_diagnostic_fxx_start": 1,
            "hrrr_diagnostic_fxx_end": DASHBOARD_HRRR_DIAGNOSTIC_HOURS,
            "hrrr_diagnostic_ffg_analysis_utc": diag_ffg_dt.strftime("%Y-%m-%dT%H:00:00Z"),
            "hrrr_diagnostic_ffg_age_hours": round(diagnostic_ffg_age_h, 1),
            "latest_cycle_utc": latest_dt.strftime("%Y-%m-%dT%H:00:00Z"),
            "common_valid_start_utc": common_start.strftime("%Y-%m-%dT%H:00:00Z"),
            "common_valid_end_utc": common_end.strftime("%Y-%m-%dT%H:00:00Z"),
            "members_available": n_members,
            "member_cycles_utc": [d.strftime("%Y-%m-%dT%H:00:00Z") for d in tle_run_dts],
            "member_lead_ranges": [
                {"cycle_utc": d.strftime("%Y-%m-%dT%H:00:00Z"),
                 "fxx_start": aligned_member_fxx(i)[0],
                 "fxx_end": aligned_member_fxx(i)[-1]}
                for i, d in enumerate(tle_run_dts)
            ],
            "ffg_analysis_utc": ffg_dt.strftime("%Y-%m-%dT%H:00:00Z"),
            "ffg_age_hours": round(ffg_age_h, 1),
            "neighborhood_km": NEIGHBORHOOD_KM,
            "image_crs": "EPSG:3857",
            "bounds": LEAFLET_BOUNDS,
            "generated_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "latest_three_cycles": latest_cycles,
            "prior_three_cycles": prior_cycles,
            "run_change_signal_threshold": "2/3 members",
            "member_frequency_note": "Member frequency / consensus; NOT calibrated probability.",
            "evolution_display_note": "Evolution overlays suppress 1/6 support; underlying science threshold is unchanged.",
            "layers": {
                key: {"file": filename} for key, filename in LAYER_FILES.items()
            },
        }

        write_json(staging / "hrrr_tle_metadata.json", metadata)
        write_json(staging / "hrrr_tle_manifest.json", {
            "metadata_mode": "hrrr_tle_dashboard_manifest_v1",
            "algorithm_version": "3.3",
            "latest_hrrr_diagnostic_cycle_utc": metadata["latest_hrrr_diagnostic_cycle_utc"],
            "hrrr_diagnostic_valid_end_utc": metadata["hrrr_diagnostic_valid_end_utc"],
            "latest_cycle_utc": metadata["latest_cycle_utc"],
            "common_valid_start_utc": metadata["common_valid_start_utc"],
            "common_valid_end_utc": metadata["common_valid_end_utc"],
            "generated_utc": metadata["generated_utc"],
            "metadata_file": "hrrr_tle_metadata.json",
            "layers": metadata["layers"],
        })

        # Sanity-check all expected files before publication.
        expected = list(LAYER_FILES.values()) + ["hrrr_tle_metadata.json", "hrrr_tle_manifest.json"]
        for name in expected:
            p = staging / name
            if not p.exists() or p.stat().st_size < (200 if p.suffix == ".png" else 50):
                raise RuntimeError(f"Staging validation failed for {name}")

        for name in expected:
            shutil.copy2(staging / name, output_dir / name)

        print(f"✅ Published HRRR diagnostics {latest_hrrr_dt:%Y-%m-%d %HZ} + HRRR-TLE V3.3 {latest_dt:%Y-%m-%d %HZ}")
        return 0
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="static", help="Dashboard static output directory")
    parser.add_argument("--force", action="store_true", help="Rebuild even if the anchor cycle is unchanged")
    args = parser.parse_args()
    raise SystemExit(build(Path(args.output_dir), force=args.force))


if __name__ == "__main__":
    main()
