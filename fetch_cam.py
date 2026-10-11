import os, requests, concurrent.futures, warnings, gc, json, time
from datetime import datetime, timezone, timedelta
from pathlib import Path
import xarray as xr
import numpy as np
from scipy.interpolate import griddata
from scipy.spatial import cKDTree
import matplotlib.pyplot as plt
from matplotlib import ticker

warnings.filterwarnings('ignore')

# Dashboard rendering profile. This increases PNG pixel density only; the HREF,
# REFS, probability thresholds, existing REFS-to-HREF interpolation, and
# super-ensemble calculations are intentionally unchanged.
MAP_RENDER_DPI = 600       # 10 x 6 inches -> 6000 x 3600 px
RENDER_REVISION = "cam-operational-integrity-v1c"

class EnsembleNowcastEngine:
    def __init__(self, output_dir="grib_cache"):
        self.grib_dir = Path(output_dir)
        self.grib_dir.mkdir(exist_ok=True, parents=True)
        self.headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        self.idx_cache = {}
        self.refs_cycle_source = None

        # Dashboard Configurations
        self.windows = [(4, 9), (10, 15)] # +3h to +9h, and +9h to +15h
        self.qpf_thresh_in = [0.5, 1, 2, 3]
        self.qpf_thresh_mm = [12.7, 25.4, 50.8, 76.2]
        self.ffg_durations = [1, 3, 6]


    @staticmethod
    def _ffg_duration_expected(fxx, duration, window_start):
        """
        Return whether an FFG-exceedance duration is expected at this forecast
        hour and is fully contained inside the selected nowcast window.

        The 1-hour FFG perspective is hourly. The 3-hour and 6-hour
        perspectives are carried on the 3-hour forecast cadence.
        """
        if fxx - duration < window_start:
            return False
        if duration == 1:
            return True
        if duration in (3, 6):
            return fxx % 3 == 0
        return True


    def _refs_product_urls(self, d_str, cycle, product, fxx):
        """
        Candidate full-GRIB REFS URLs.

        Current pre-implementation data are proven available on NOMADS-PARA
        without companion .idx files. Keep AWS-V1 and future NOMADS-PROD as
        secondary candidates so the same code can survive later dataflow changes.
        """
        filename = f"refs.t{cycle:02d}z.{product}.f{fxx:02d}.conus.grib2"
        rel = f"refs.{d_str}/{cycle:02d}/ensprod/{filename}"
        return [
            ("NOMADS-PARA", f"https://nomads.ncep.noaa.gov/pub/data/nccf/com/refs/para/{rel}"),
            ("AWS-V1",      f"https://noaa-rrfs-pds.s3.amazonaws.com/refs/v1.0/{rel}"),
            ("NOMADS-PROD", f"https://nomads.ncep.noaa.gov/pub/data/nccf/com/refs/prod/{rel}"),
        ]

    def _probe_idx(self, source, grib_url, timeout=8, attempts=3):
        """Probe the HREF .idx endpoint with bounded retry."""
        idx_url = grib_url + ".idx"
        for attempt in range(1, attempts + 1):
            try:
                r = requests.get(
                    idx_url,
                    headers={
                        "Range": "bytes=0-1023",
                        "User-Agent": self.headers["User-Agent"],
                    },
                    timeout=timeout,
                    allow_redirects=True,
                )
                status = r.status_code
                ok = status in (200, 206) and bool(r.text.strip())
                r.close()
                if ok:
                    print(f"IDX probe [{status}] {source}: {idx_url}")
                    return True
                print(
                    f"IDX probe [{status}] {source} attempt "
                    f"{attempt}/{attempts}: {idx_url}"
                )
                if status == 404:
                    return False
            except requests.RequestException as e:
                print(
                    f"IDX probe [ERROR] {source} attempt "
                    f"{attempt}/{attempts}: {idx_url} ({type(e).__name__})"
                )
            if attempt < attempts:
                time.sleep(min(attempt, 2))
        return False

    def _probe_grib(
        self, source, grib_url, timeout=10, verbose=True, attempts=3
    ):
        """Probe a REFS GRIB object with bounded retry."""
        for attempt in range(1, attempts + 1):
            try:
                r = requests.get(
                    grib_url,
                    headers={
                        "Range": "bytes=0-0",
                        "User-Agent": self.headers["User-Agent"],
                    },
                    timeout=timeout,
                    allow_redirects=True,
                    stream=True,
                )
                status = r.status_code
                r.close()
                if status in (200, 206):
                    if verbose:
                        print(f"GRIB probe [{status}] {source}: {grib_url}")
                    return True
                if verbose or attempt == attempts:
                    print(
                        f"GRIB probe [{status}] {source} attempt "
                        f"{attempt}/{attempts}: {grib_url}"
                    )
                if status == 404:
                    return False
            except requests.RequestException as e:
                if verbose or attempt == attempts:
                    print(
                        f"GRIB probe [ERROR] {source} attempt "
                        f"{attempt}/{attempts}: {grib_url} "
                        f"({type(e).__name__})"
                    )
            if attempt < attempts:
                time.sleep(min(attempt, 2))
        return False

    def _refs_candidates(self, d_str, cycle, product, fxx):
        return self._refs_product_urls(d_str, cycle, product, fxx)


    def _get_latest_cycle(self, model, max_fxx, target_init=None):
        """
        Find the newest usable cycle. When target_init is supplied, require the
        other ensemble to use that exact initialization so the relative
        +3-to-+9 and +9-to-+15 windows represent the same absolute times.
        """
        now = datetime.now(timezone.utc)
        curr_cycle = now.replace(
            hour=(now.hour // 6) * 6, minute=0, second=0, microsecond=0
        )

        for i in range(8):
            dt = curr_cycle - timedelta(hours=6 * i)
            if target_init is not None and dt != target_init:
                continue

            cycle = dt.hour
            d_str = dt.strftime("%Y%m%d")

            if model == "HREF":
                prob_url = (
                    f"https://nomads.ncep.noaa.gov/pub/data/nccf/com/href/prod/"
                    f"href.{d_str}/ensprod/"
                    f"href.t{cycle:02d}z.conus.prob.f{max_fxx:02d}.grib2"
                )
                if self._probe_idx("HREF-NOMADS", prob_url):
                    print(
                        f"HREF candidate accepted: {d_str} {cycle:02d}Z "
                        f"(PROB f{max_fxx:02d})"
                    )
                    return d_str, cycle, dt
            else:
                for source, prob_url in self._refs_candidates(
                    d_str, cycle, "prob", max_fxx
                ):
                    if self._probe_grib(source, prob_url):
                        self.refs_cycle_source = source
                        print(
                            f"REFS candidate accepted: {d_str} {cycle:02d}Z "
                            f"via {source} (direct PROB GRIB f{max_fxx:02d})"
                        )
                        return d_str, cycle, dt

        if target_init is not None:
            print(
                f"ERROR: No usable {model} cycle matching "
                f"{target_init:%Y%m%d %H}Z."
            )
        else:
            print(f"ERROR: No usable {model} cycle found in the last 48 hours.")
        return None, None, None

    def _get_idx(self, url, attempts=4):
        """
        Fetch one HREF index with bounded retry/backoff. Cache only successful
        responses so a transient NOMADS failure cannot poison the entire run.
        """
        cached = self.idx_cache.get(url)
        if cached:
            return cached

        for attempt in range(1, attempts + 1):
            try:
                r = requests.get(
                    url,
                    headers={
                        "Range": "bytes=0-2097151",
                        "User-Agent": self.headers["User-Agent"],
                    },
                    timeout=(8, 20),
                    allow_redirects=True,
                )
                if r.status_code in (200, 206) and r.text.strip():
                    self.idx_cache[url] = r.text
                    return r.text
                print(
                    f"IDX fetch [{r.status_code}] attempt "
                    f"{attempt}/{attempts}: {url}"
                )
            except requests.RequestException as e:
                print(
                    f"IDX fetch [ERROR] attempt {attempt}/{attempts}: "
                    f"{url} ({type(e).__name__})"
                )
            if attempt < attempts:
                time.sleep(min(2 * attempt, 6))
        return ""

    def _parse_idx(self, idx_text, param_type, val, fxx):
        lines = idx_text.strip().split('\n')
        duration = 1 if param_type == "QPF" else val
        start_h = fxx - duration
        if start_h < 0: return None, None
        
        v_starts = [f"{start_h}-{fxx} hour", f"{start_h}-{fxx} hr", f"{start_h:02d}-{fxx:02d} hour", f"{duration} hour", f"{duration} hr"]
        if start_h == 0: v_starts.extend([f"0-{fxx} hour", f"0-{fxx} hr", f"0-{duration} hour"])
            
        for i, line in enumerate(lines):
            line_low = line.lower()
            if param_type == "QPF":
                if "apcp" not in line_low or "<" in line_low: continue
                if f"prob>{val}" not in line_low.replace(" ", "") and f"prob>={val}" not in line_low.replace(" ", ""): continue
            elif param_type == "FFG":
                if "ffg" not in line_low: continue
                
            parts = [p.strip() for p in line_low.split(":")]
            time_match = False
            for p in parts:
                for vs in v_starts:
                    if p.startswith(vs) and (len(p) == len(vs) or p[len(vs)] == ' '): time_match = True; break
                if time_match: break
                
            if time_match:
                start_byte = int(parts[1])
                end_byte = None
                for j in range(i+1, len(lines)):
                    if len(lines[j].split(":")) > 1 and lines[j].split(":")[1].isdigit():
                        end_byte = int(lines[j].split(":")[1]) - 1; break
                return start_byte, end_byte
        return None, None

    def _fetch_grib(self, args):
        url, idx_url, p_type, val, fxx, out_file = args
        if out_file.exists() and out_file.stat().st_size > 16:
            return True

        urls = list(url) if isinstance(url, (list, tuple)) else [url]
        idx_urls = list(idx_url) if isinstance(idx_url, (list, tuple)) else [idx_url]

        for source_url, source_idx_url in zip(urls, idx_urls):
            idx_text = self._get_idx(source_idx_url)
            start_b, end_b = self._parse_idx(idx_text, p_type, val, fxx)
            if start_b is None:
                print(
                    f"HREF index match missing: {p_type} value={val} "
                    f"f{fxx:02d} from {source_idx_url}"
                )
                continue

            rng = f"bytes={start_b}-{end_b}" if end_b else f"bytes={start_b}-"
            for attempt in range(1, 4):
                try:
                    r = requests.get(
                        source_url,
                        headers={
                            "Range": rng,
                            "User-Agent": self.headers["User-Agent"],
                        },
                        timeout=(10, 60),
                        allow_redirects=True,
                    )
                    if (
                        r.status_code in (200, 206)
                        and len(r.content) > 16
                        and r.content[:4] == b"GRIB"
                    ):
                        tmp = out_file.with_suffix(out_file.suffix + ".part")
                        tmp.write_bytes(r.content)
                        tmp.replace(out_file)
                        return True
                    print(
                        f"HREF range fetch [{r.status_code}] attempt "
                        f"{attempt}/3: {p_type} value={val} f{fxx:02d}"
                    )
                except requests.RequestException as e:
                    print(
                        f"HREF range fetch [ERROR] attempt {attempt}/3: "
                        f"{p_type} value={val} f{fxx:02d} "
                        f"({type(e).__name__})"
                    )
                if attempt < 3:
                    time.sleep(min(2 * attempt, 5))
        return False

    def _download_refs_full(self, d_str, cycle, product, fxx):
        """Download and validate one complete REFS GRIB2 product."""
        suffix = f"{d_str}_{cycle:02d}_{product}_f{fxx:02d}.grib2"
        out_file = self.grib_dir / f"REFS_FULL_{suffix}"

        for source, url in self._refs_candidates(d_str, cycle, product, fxx):
            for attempt in range(1, 4):
                out_file.unlink(missing_ok=True)
                try:
                    r = requests.get(
                        url,
                        headers={"User-Agent": self.headers["User-Agent"]},
                        timeout=(10, 180),
                        allow_redirects=True,
                        stream=True,
                    )
                    if r.status_code not in (200, 206):
                        print(
                            f"REFS full-GRIB HTTP {r.status_code} "
                            f"{source} {product} f{fxx:02d} "
                            f"attempt {attempt}/3"
                        )
                        r.close()
                        if r.status_code == 404:
                            break
                        if attempt < 3:
                            time.sleep(min(2 * attempt, 6))
                        continue

                    total = r.headers.get("Content-Length", "?")
                    print(
                        f"REFS full-GRIB download: {d_str} {cycle:02d}Z "
                        f"{product.upper()} f{fxx:02d} via {source} "
                        f"(attempt {attempt}/3, Content-Length={total})"
                    )
                    with open(out_file, "wb") as fh:
                        for chunk in r.iter_content(chunk_size=1024 * 1024):
                            if chunk:
                                fh.write(chunk)
                    r.close()

                    if out_file.exists() and out_file.stat().st_size > 16:
                        with open(out_file, "rb") as fh:
                            if fh.read(4) == b"GRIB":
                                return out_file, source

                    print(
                        f"REFS full-GRIB validation failed {source} "
                        f"{product} f{fxx:02d} attempt {attempt}/3"
                    )
                    out_file.unlink(missing_ok=True)
                except requests.RequestException as e:
                    out_file.unlink(missing_ok=True)
                    print(
                        f"REFS download error {source} {product} f{fxx:02d} "
                        f"attempt {attempt}/3: {type(e).__name__}"
                    )
                if attempt < 3:
                    time.sleep(min(2 * attempt, 6))

        out_file.unlink(missing_ok=True)
        return None, None

    @staticmethod
    def _codes_get_safe(eccodes, gid, key, default=None):
        try:
            return eccodes.codes_get(gid, key)
        except Exception:
            return default

    def _grib_step_bounds(self, eccodes, gid):
        """Return (start_hour, end_hour) using ecCodes step metadata."""
        start = self._codes_get_safe(eccodes, gid, "startStep")
        end = self._codes_get_safe(eccodes, gid, "endStep")

        try:
            if start is not None and end is not None:
                return float(start), float(end)
        except Exception:
            pass

        step_range = self._codes_get_safe(eccodes, gid, "stepRange")
        if step_range is not None:
            s = str(step_range).strip()
            try:
                if "-" in s:
                    a, b = s.split("-", 1)
                    return float(a), float(b)
                v = float(s)
                length = self._codes_get_safe(eccodes, gid, "lengthOfTimeRange")
                if length is not None:
                    try:
                        return v - float(length), v
                    except Exception:
                        pass
                return v, v
            except Exception:
                pass

        return None, None

    def _probability_limits(self, eccodes, gid):
        """
        Collect decoded probability threshold limits.

        ecCodes/WMO template naming has evolved, so support both older
        lower/upper-limit names and newer first/second-limit names.
        """
        values = []

        for key in ("lowerLimit", "upperLimit", "firstLimit", "secondLimit"):
            v = self._codes_get_safe(eccodes, gid, key)
            try:
                fv = float(v)
                if np.isfinite(fv) and abs(fv) < 1.0e8:
                    values.append(fv)
            except Exception:
                pass

        scaled_pairs = [
            ("scaleFactorOfLowerLimit", "scaledValueOfLowerLimit"),
            ("scaleFactorOfUpperLimit", "scaledValueOfUpperLimit"),
            ("scaleFactorOfFirstLimit", "scaledValueOfFirstLimit"),
            ("scaleFactorOfSecondLimit", "scaledValueOfSecondLimit"),
        ]
        for sf_key, sv_key in scaled_pairs:
            sf = self._codes_get_safe(eccodes, gid, sf_key)
            sv = self._codes_get_safe(eccodes, gid, sv_key)
            try:
                sfv = float(sf)
                svv = float(sv)
                if (
                    np.isfinite(sfv)
                    and np.isfinite(svv)
                    and abs(sfv) < 100
                    and abs(svv) < 1.0e12
                ):
                    values.append(svv * (10.0 ** (-sfv)))
            except Exception:
                pass

        # Preserve order while de-duplicating near-identical encodings.
        unique = []
        for v in values:
            if not any(abs(v - u) < 1.0e-6 for u in unique):
                unique.append(v)
        return unique


    def _decode_refs_grid(self, eccodes, gid, include_coords=True):
        """Decode one matching REFS GRIB message."""
        try:
            values = np.asarray(
                eccodes.codes_get_array(gid, "values"), dtype=np.float32
            )
        except Exception as e:
            print(f"REFS ecCodes value decode failed: {type(e).__name__}: {e}")
            return None, None, None

        nx = self._codes_get_safe(eccodes, gid, "Nx")
        ny = self._codes_get_safe(eccodes, gid, "Ny")
        if nx is None:
            nx = self._codes_get_safe(eccodes, gid, "Ni")
        if ny is None:
            ny = self._codes_get_safe(eccodes, gid, "Nj")

        try:
            nx, ny = int(nx), int(ny)
        except Exception:
            print("REFS ecCodes could not determine Nx/Ny for a matching message.")
            return None, None, None

        if nx * ny != values.size:
            print(
                f"REFS grid-size mismatch: Nx={nx} Ny={ny} "
                f"points={values.size}"
            )
            return None, None, None

        values = values.reshape(ny, nx)
        values = np.clip(np.nan_to_num(values, nan=0.0), 0.0, 100.0)

        if not include_coords:
            return values, None, None

        try:
            lats = np.asarray(
                eccodes.codes_get_array(gid, "latitudes"), dtype=np.float32
            ).reshape(ny, nx)
            lons = np.asarray(
                eccodes.codes_get_array(gid, "longitudes"), dtype=np.float32
            ).reshape(ny, nx)
        except Exception as e:
            print(f"REFS ecCodes coordinate decode failed: {type(e).__name__}: {e}")
            return None, None, None

        lons = np.where(lons > 180.0, lons - 360.0, lons)
        return values, lats, lons

    def _scan_refs_prob_file(self, file_path, fxx):
        """
        Scan a full REFS 'prob' GRIB locally and extract the 1-hour APCP
        exceedance probabilities used by the dashboard.
        """
        try:
            import eccodes
        except ImportError as e:
            raise RuntimeError(
                "The eccodes Python package is required for direct REFS GRIB decoding."
            ) from e

        targets = {float(mm): None for mm in self.qpf_thresh_mm}
        coords = [None, None]
        candidate_debug = []

        with open(file_path, "rb") as f:
            while True:
                gid = eccodes.codes_grib_new_from_file(f)
                if gid is None:
                    break
                try:
                    discipline = self._codes_get_safe(eccodes, gid, "discipline")
                    category = self._codes_get_safe(eccodes, gid, "parameterCategory")
                    number = self._codes_get_safe(eccodes, gid, "parameterNumber")
                    short_name = str(
                        self._codes_get_safe(eccodes, gid, "shortName", "")
                    ).upper()

                    is_apcp = (
                        discipline == 0 and category == 1 and number == 8
                    ) or short_name in ("APCP", "TP")

                    if not is_apcp:
                        continue

                    probability_type = self._codes_get_safe(
                        eccodes, gid, "probabilityType"
                    )
                    try:
                        probability_type = int(probability_type)
                    except Exception:
                        probability_type = None

                    # Original index matching used "prob > threshold".
                    if probability_type not in (1, 3):
                        continue

                    start_h, end_h = self._grib_step_bounds(eccodes, gid)
                    if start_h is None or end_h is None:
                        continue

                    # Preserve the original 1-hour APCP selection.
                    if abs(end_h - float(fxx)) > 0.01 or abs((end_h - start_h) - 1.0) > 0.01:
                        continue

                    limits = self._probability_limits(eccodes, gid)
                    if len(candidate_debug) < 12:
                        candidate_debug.append(
                            (start_h, end_h, probability_type, limits, short_name)
                        )

                    matched_mm = None
                    for target_mm in targets:
                        if targets[target_mm] is not None:
                            continue
                        if any(abs(limit - target_mm) <= 0.06 for limit in limits):
                            matched_mm = target_mm
                            break

                    if matched_mm is None:
                        continue

                    data, lats, lons = self._decode_refs_grid(
                        eccodes, gid, include_coords=(coords[0] is None)
                    )
                    if data is None:
                        continue

                    targets[matched_mm] = data
                    if coords[0] is None:
                        coords = [lats, lons]

                    print(
                        f"REFS local match: f{fxx:02d} 1-h APCP "
                        f"probability > {matched_mm:g} mm"
                    )

                    if all(v is not None for v in targets.values()):
                        break
                finally:
                    eccodes.codes_release(gid)

        missing = [mm for mm, arr in targets.items() if arr is None]
        if missing:
            print(
                f"WARNING: REFS f{fxx:02d} missing local QPF thresholds: "
                + ", ".join(f"{m:g} mm" for m in missing)
            )
            if candidate_debug:
                print(
                    "REFS APCP candidate metadata sample: "
                    + "; ".join(
                        f"step={a:g}-{b:g},ptype={p},limits={lims}"
                        for a, b, p, lims, _ in candidate_debug[:6]
                    )
                )

        return targets, coords[0], coords[1]

    def _scan_refs_ffri_file(self, file_path, fxx):
        """
        Scan a full REFS FFRI GRIB locally for 1/3/6-hour probabilities of
        precipitation exceeding Flash Flood Guidance.

        FFRI is still allowed to be absent in the pre-implementation feed.
        """
        try:
            import eccodes
        except ImportError as e:
            raise RuntimeError(
                "The eccodes Python package is required for direct REFS GRIB decoding."
            ) from e

        targets = {int(d): None for d in self.ffg_durations}
        coords = [None, None]

        with open(file_path, "rb") as f:
            while True:
                gid = eccodes.codes_grib_new_from_file(f)
                if gid is None:
                    break
                try:
                    discipline = self._codes_get_safe(eccodes, gid, "discipline")
                    category = self._codes_get_safe(eccodes, gid, "parameterCategory")
                    number = self._codes_get_safe(eccodes, gid, "parameterNumber")
                    short_name = str(
                        self._codes_get_safe(eccodes, gid, "shortName", "")
                    ).upper()
                    name = str(self._codes_get_safe(eccodes, gid, "name", "")).upper()
                    units = str(self._codes_get_safe(eccodes, gid, "units", ""))

                    # NCEP GRIB2 discipline 1/category 1/parameter 194 = PPFFG.
                    is_ppffg = (
                        discipline == 1 and category == 1 and number == 194
                    ) or (
                        ("FFG" in short_name or "FLASH FLOOD GUIDANCE" in name)
                        and "%" in units
                    )
                    if not is_ppffg:
                        continue

                    start_h, end_h = self._grib_step_bounds(eccodes, gid)
                    if start_h is None or end_h is None:
                        continue
                    if abs(end_h - float(fxx)) > 0.01:
                        continue

                    duration = int(round(end_h - start_h))
                    if duration not in targets or targets[duration] is not None:
                        continue

                    data, lats, lons = self._decode_refs_grid(
                        eccodes, gid, include_coords=(coords[0] is None)
                    )
                    if data is None:
                        continue

                    targets[duration] = data
                    if coords[0] is None:
                        coords = [lats, lons]
                    print(
                        f"REFS local FFG match: f{fxx:02d} "
                        f"{duration}-h FFG exceedance probability"
                    )

                    if all(v is not None for v in targets.values()):
                        break
                finally:
                    eccodes.codes_release(gid)

        return targets, coords[0], coords[1]

    @staticmethod
    def _merge_max(current, new):
        if new is None:
            return current
        if current is None:
            return new
        return np.fmax(current, new)

    def _extract_max(self, file_path, current_max, lats, lons):
        xr.backends.file_manager.FILE_CACHE.clear()
        try:
            with xr.open_dataset(file_path, engine="cfgrib", backend_kwargs={'indexpath': ''}) as ds:
                da = list(ds.data_vars.values())[0]
                temp_data = np.clip(np.nan_to_num(da.values, nan=0.0), 0, 100)
                current_max = temp_data if current_max is None else np.fmax(current_max, temp_data)
                if lats is None:
                    lats = da['latitude' if 'latitude' in da.coords else 'lat'].values
                    lons = np.where(da['longitude' if 'longitude' in da.coords else 'lon'].values > 180, da['longitude' if 'longitude' in da.coords else 'lon'].values - 360, da['longitude' if 'longitude' in da.coords else 'lon'].values)
            gc.collect()
            return current_max, lats, lons, True
        except: return current_max, lats, lons, False

    def _create_super_ensemble(self, h_data, h_lats, h_lons, r_data, r_lats, r_lons):
        if h_data is None: return None, None
        if r_data is None: return None, h_data 
        
        mask = ~np.isnan(r_data.ravel())
        pts = np.column_stack((r_lons.ravel()[mask], r_lats.ravel()[mask]))
        if len(pts) > 0: 
            refs_interp = griddata(pts, r_data.ravel()[mask], (h_lons, h_lats), method='linear', fill_value=0.0)
            dists, _ = cKDTree(pts).query(np.column_stack((h_lons.ravel(), h_lats.ravel())))
            refs_interp_flat = refs_interp.ravel()
            refs_interp_flat[dists > 0.1] = np.nan
            refs_interp = refs_interp_flat.reshape(h_lats.shape)
            refs_interp[np.isnan(h_data)] = np.nan
            return refs_interp, (h_data + refs_interp) / 2.0
        return None, h_data


    def generate_dashboard_data(self):
        print("Starting Super-Ensemble Data Generation...")
        max_req_fxx = max(w[1] for w in self.windows)

        h_date, h_cyc, h_dt = self._get_latest_cycle("HREF", max_req_fxx)
        if not h_date:
            return {
                "no_update": True,
                "reason": "No complete HREF nowcast cycle is currently available."
            }

        # Relative nowcast windows must share the same absolute initialization.
        # Do not blend HREF +3/+9 guidance with REFS +3/+9 guidance from a
        # different cycle.
        r_date, r_cyc, r_dt = self._get_latest_cycle(
            "REFS", max_req_fxx, target_init=h_dt
        )
        if not r_date:
            return {
                "no_update": True,
                "reason": (
                    f"REFS {h_date} {h_cyc:02d}Z has not completed through "
                    f"f{max_req_fxx:02d}; retaining the last aligned CAM package."
                ),
            }

        print(f"Locked Models -> HREF: {h_date} {h_cyc:02d}Z | REFS: {r_date} {r_cyc:02d}Z")
        print(
            f"REFS direct-GRIB cycle source: "
            f"{self.refs_cycle_source or 'unknown'}"
        )

        data_store = {
            w: {
                "QPF": {
                    t: {"HREF": None, "REFS": None}
                    for t in self.qpf_thresh_in
                },
                "FFG_MAX": {"HREF": None, "REFS": None},
            }
            for w in self.windows
        }
        coords = {"HREF": [None, None], "REFS": [None, None]}

        # ---------------- HREF ----------------
        h_base = (
            f"https://nomads.ncep.noaa.gov/pub/data/nccf/com/href/prod/"
            f"href.{h_date}/ensprod"
        )
        href_tasks = []
        href_labels = []

        for w in self.windows:
            window_start = w[0] - 1
            for fxx in range(w[0], w[1] + 1):
                prob_url = (
                    f"{h_base}/href.t{h_cyc:02d}z.conus.prob."
                    f"f{fxx:02d}.grib2"
                )
                prob_idx = prob_url + ".idx"
                for t_in, t_mm in zip(self.qpf_thresh_in, self.qpf_thresh_mm):
                    out_file = self.grib_dir / (
                        f"H_{h_date}_{h_cyc:02d}_Q_{t_in}_{fxx:02d}.grib2"
                    )
                    href_tasks.append(
                        (prob_url, prob_idx, "QPF", t_mm, fxx, out_file)
                    )
                    href_labels.append(
                        f"{w[0]-1}-{w[1]}h QPF {t_in}-inch f{fxx:02d}"
                    )

                ffri_url = (
                    f"{h_base}/href.t{h_cyc:02d}z.conus.ffri."
                    f"f{fxx:02d}.grib2"
                )
                ffri_idx = ffri_url + ".idx"
                for d in self.ffg_durations:
                    if self._ffg_duration_expected(fxx, d, window_start):
                        out_file = self.grib_dir / (
                            f"H_{h_date}_{h_cyc:02d}_F_{d}_{fxx:02d}.grib2"
                        )
                        href_tasks.append(
                            (ffri_url, ffri_idx, "FFG", d, fxx, out_file)
                        )
                        href_labels.append(
                            f"{w[0]-1}-{w[1]}h {d}-h FFG f{fxx:02d}"
                        )

        # Fetch each HREF index once before launching byte-range workers.
        href_idx_urls = list(dict.fromkeys(task[1] for task in href_tasks))
        missing_href_idx = []
        for idx_url in href_idx_urls:
            if not self._get_idx(idx_url):
                missing_href_idx.append(idx_url)
            time.sleep(0.05)

        if missing_href_idx:
            reason = (
                "HREF index acquisition is incomplete; retaining the last "
                "complete nowcast package."
            )
            print(reason)
            for url in missing_href_idx:
                print(f"  Missing HREF index: {url}")
            return {"no_update": True, "reason": reason}

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            href_fetch_ok = list(executor.map(self._fetch_grib, href_tasks))

        failed_href_fetches = [
            label
            for label, ok in zip(href_labels, href_fetch_ok)
            if not ok
        ]
        if failed_href_fetches:
            reason = (
                "HREF byte-range acquisition is incomplete; retaining the "
                "last complete nowcast package."
            )
            print(reason)
            print("  Failed HREF fields: " + ", ".join(failed_href_fetches[:60]))
            return {"no_update": True, "reason": reason}

        href_qpf_hours = {
            w: {t: set() for t in self.qpf_thresh_in}
            for w in self.windows
        }
        href_ffg_slots = {w: set() for w in self.windows}
        href_decode_failures = []

        for w in self.windows:
            window_start = w[0] - 1
            for fxx in range(w[0], w[1] + 1):
                for t_in in self.qpf_thresh_in:
                    file = self.grib_dir / (
                        f"H_{h_date}_{h_cyc:02d}_Q_{t_in}_{fxx:02d}.grib2"
                    )
                    new_max, new_lats, new_lons, decoded = self._extract_max(
                        file,
                        data_store[w]["QPF"][t_in]["HREF"],
                        coords["HREF"][0],
                        coords["HREF"][1],
                    )
                    if decoded:
                        data_store[w]["QPF"][t_in]["HREF"] = new_max
                        coords["HREF"] = [new_lats, new_lons]
                        href_qpf_hours[w][t_in].add(fxx)
                    else:
                        href_decode_failures.append(
                            f"{w[0]-1}-{w[1]}h QPF {t_in}-inch f{fxx:02d}"
                        )
                    file.unlink(missing_ok=True)

                for d in self.ffg_durations:
                    if self._ffg_duration_expected(fxx, d, window_start):
                        file = self.grib_dir / (
                            f"H_{h_date}_{h_cyc:02d}_F_{d}_{fxx:02d}.grib2"
                        )
                        new_max, new_lats, new_lons, decoded = self._extract_max(
                            file,
                            data_store[w]["FFG_MAX"]["HREF"],
                            coords["HREF"][0],
                            coords["HREF"][1],
                        )
                        if decoded:
                            data_store[w]["FFG_MAX"]["HREF"] = new_max
                            coords["HREF"] = [new_lats, new_lons]
                            href_ffg_slots[w].add((fxx, d))
                        else:
                            href_decode_failures.append(
                                f"{w[0]-1}-{w[1]}h {d}-h FFG f{fxx:02d}"
                            )
                        file.unlink(missing_ok=True)

        if href_decode_failures:
            reason = (
                "HREF GRIB decoding is incomplete; retaining the last complete "
                "nowcast package."
            )
            print(reason)
            print("  Failed HREF decodes: " + ", ".join(href_decode_failures[:60]))
            return {"no_update": True, "reason": reason}

        # ---------------- REFS ----------------
        refs_qpf_hours = {w: set() for w in self.windows}
        refs_ffri_hours = {w: set() for w in self.windows}
        refs_ffg_slots = {w: set() for w in self.windows}

        for w in self.windows:
            window_start = w[0] - 1
            for fxx in range(w[0], w[1] + 1):
                full_prob, source = self._download_refs_full(
                    r_date, r_cyc, "prob", fxx
                )
                if full_prob is not None:
                    try:
                        qpf_fields, rlats, rlons = self._scan_refs_prob_file(
                            full_prob, fxx
                        )
                        missing_thresholds = [
                            t_in
                            for t_in, t_mm in zip(
                                self.qpf_thresh_in, self.qpf_thresh_mm
                            )
                            if qpf_fields.get(float(t_mm)) is None
                        ]
                        if not missing_thresholds:
                            for t_in, t_mm in zip(
                                self.qpf_thresh_in, self.qpf_thresh_mm
                            ):
                                arr = qpf_fields[float(t_mm)]
                                data_store[w]["QPF"][t_in]["REFS"] = self._merge_max(
                                    data_store[w]["QPF"][t_in]["REFS"], arr
                                )
                            refs_qpf_hours[w].add(fxx)
                            if coords["REFS"][0] is None:
                                coords["REFS"] = [rlats, rlons]
                        else:
                            print(
                                f"REFS QPF f{fxx:02d} missing threshold fields: "
                                + ", ".join(
                                    f"{t:g}in" for t in missing_thresholds
                                )
                            )
                    finally:
                        full_prob.unlink(missing_ok=True)

                if any(
                    self._ffg_duration_expected(fxx, d, window_start)
                    for d in self.ffg_durations
                ):
                    full_ffri, _ = self._download_refs_full(
                        r_date, r_cyc, "ffri", fxx
                    )
                    if full_ffri is not None:
                        try:
                            ffg_fields, rlats, rlons = self._scan_refs_ffri_file(
                                full_ffri, fxx
                            )
                            found_any = False
                            for d in self.ffg_durations:
                                if self._ffg_duration_expected(
                                    fxx, d, window_start
                                ):
                                    arr = ffg_fields.get(d)
                                    if arr is not None:
                                        data_store[w]["FFG_MAX"]["REFS"] = self._merge_max(
                                            data_store[w]["FFG_MAX"]["REFS"], arr
                                        )
                                        refs_ffg_slots[w].add((fxx, d))
                                        found_any = True
                            if found_any:
                                refs_ffri_hours[w].add(fxx)
                                if coords["REFS"][0] is None:
                                    coords["REFS"] = [rlats, rlons]
                        finally:
                            full_ffri.unlink(missing_ok=True)

        # Validate the exact scientific contract for both windows. A temporal
        # maximum built from only part of a window must never be published as
        # if it represented the full MetWatch nowcast period.
        completeness_errors = []
        window_contract = {}

        for w in self.windows:
            window_start = w[0] - 1
            expected_hours = set(range(w[0], w[1] + 1))
            expected_ffg_slots = {
                (fxx, d)
                for fxx in expected_hours
                for d in self.ffg_durations
                if self._ffg_duration_expected(fxx, d, window_start)
            }

            for t_in in self.qpf_thresh_in:
                missing = sorted(expected_hours - href_qpf_hours[w][t_in])
                if missing:
                    completeness_errors.append(
                        f"HREF {window_start}-{w[1]}h QPF {t_in}in missing "
                        + ",".join(f"f{h:02d}" for h in missing)
                    )

            missing_href_ffg = sorted(expected_ffg_slots - href_ffg_slots[w])
            if missing_href_ffg:
                completeness_errors.append(
                    f"HREF {window_start}-{w[1]}h FFG missing "
                    + ",".join(
                        f"f{fxx:02d}/{d}h"
                        for fxx, d in missing_href_ffg
                    )
                )

            missing_refs_qpf = sorted(expected_hours - refs_qpf_hours[w])
            if missing_refs_qpf:
                completeness_errors.append(
                    f"REFS {window_start}-{w[1]}h QPF missing "
                    + ",".join(f"f{h:02d}" for h in missing_refs_qpf)
                )

            missing_refs_ffg = sorted(expected_ffg_slots - refs_ffg_slots[w])
            if missing_refs_ffg:
                completeness_errors.append(
                    f"REFS {window_start}-{w[1]}h FFG missing "
                    + ",".join(
                        f"f{fxx:02d}/{d}h"
                        for fxx, d in missing_refs_ffg
                    )
                )

            w_label = f"{window_start}h_to_{w[1]}h"
            window_contract[w_label] = {
                "forecast_hours": list(range(w[0], w[1] + 1)),
                "hourly_qpf_periods": [
                    f"{fxx-1}-{fxx}h"
                    for fxx in range(w[0], w[1] + 1)
                ],
                "ffg_slots": [
                    {"forecast_hour": fxx, "duration_hours": d}
                    for fxx, d in sorted(expected_ffg_slots)
                ],
            }

        if completeness_errors:
            reason = (
                "CAM nowcast processing is incomplete; retaining the last "
                "verified complete HREF/REFS package."
            )
            print(reason)
            for error in completeness_errors:
                print("  " + error)
            return {"no_update": True, "reason": reason}

        print(
            "CAM completeness check passed for both +3-to-+9 and +9-to-+15 "
            "windows."
        )

        dashboard_payload = {
            "metadata": {
                "href_cycle": h_cyc,
                "refs_cycle": r_cyc,
                "href_init_utc": h_dt.isoformat().replace("+00:00", "Z"),
                "refs_init_utc": r_dt.isoformat().replace("+00:00", "Z"),
                "lats": coords["HREF"][0],
                "lons": coords["HREF"][1],
                "window_contract": window_contract,
            },
            "windows": {},
        }

        for w in self.windows:
            w_label = f"{w[0]-1}h_to_{w[1]}h"
            dashboard_payload["windows"][w_label] = {"QPF": {}, "FFG_MAX": {}}

            for t_in in self.qpf_thresh_in:
                href_data = data_store[w]["QPF"][t_in]["HREF"]
                refs_data = data_store[w]["QPF"][t_in]["REFS"]
                refs_interp, super_ens = self._create_super_ensemble(
                    href_data,
                    coords["HREF"][0],
                    coords["HREF"][1],
                    refs_data,
                    coords["REFS"][0],
                    coords["REFS"][1],
                )
                dashboard_payload["windows"][w_label]["QPF"][f"{t_in}_inch"] = {
                    "HREF": href_data,
                    "REFS": refs_interp,
                    "SUPER": super_ens,
                }

            href_ffg = data_store[w]["FFG_MAX"]["HREF"]
            refs_ffg = data_store[w]["FFG_MAX"]["REFS"]
            refs_ffg_interp, super_ens_ffg = self._create_super_ensemble(
                href_ffg,
                coords["HREF"][0],
                coords["HREF"][1],
                refs_ffg,
                coords["REFS"][0],
                coords["REFS"][1],
            )
            dashboard_payload["windows"][w_label]["FFG_MAX"] = {
                "HREF": href_ffg,
                "REFS": refs_ffg_interp,
                "SUPER": super_ens_ffg,
            }

        return dashboard_payload

    def export_dashboard_layers(self, payload):
        if payload.get("no_update"):
            print(
                "No CAM nowcast files changed: "
                + str(payload.get("reason") or "upstream guidance is incomplete")
            )
            return
        if "error" in payload:
            raise RuntimeError(payload["error"])

        print(f"Exporting Geo-Registered PNGs at 6000x3600 px (DPI={MAP_RENDER_DPI}) and Metadata...")
        os.makedirs("static", exist_ok=True)
        
        lats = payload["metadata"]["lats"]
        lons = payload["metadata"]["lons"]
        
        # Web Mercator Projection for Leaflet Alignment
        R_earth = 6378137.0
        x_wm = R_earth * np.radians(lons)
        y_wm = R_earth * np.log(np.tan(np.pi/4 + np.radians(lats)/2))
        min_x, max_x = np.nanmin(x_wm), np.nanmax(x_wm)
        min_y, max_y = np.nanmin(y_wm), np.nanmax(y_wm)

        def save_png(data, filename, cmap, levels):
            if data is None:
                stale = Path("static") / filename
                if stale.exists():
                    stale.unlink()
                    print(f"Removed stale unavailable layer: {stale}")
                return
            
            # Mask out probabilities less than 10% for a clean transparent background
            data = np.where(data < levels[0], np.nan, data)
            
            fig = plt.figure(figsize=(10, 6), dpi=MAP_RENDER_DPI, frameon=False)
            ax = plt.Axes(fig, [0., 0., 1., 1.])
            ax.set_axis_off()
            fig.add_axes(ax)
            
            ax.contourf(
                x_wm, y_wm, data, levels=levels, cmap=cmap, extend='max',
                alpha=0.65, antialiased=True
            )
            
            ax.set_xlim(min_x, max_x)
            ax.set_ylim(min_y, max_y)
            plt.savefig(f'static/{filename}', format='png', transparent=True, dpi=MAP_RENDER_DPI)
            plt.close()

        # NWS Probability Contour Thresholds (10%, 30%, 50%, 70%, 90%)
        prob_levels = [10, 30, 50, 70, 90, 100]
        
        for w_label, w_data in payload["windows"].items():
            for t_in, models in w_data["QPF"].items():
                save_png(models["HREF"], f'cam_qpf_{w_label}_{t_in}_href.png', 'YlGnBu', prob_levels)
                save_png(models["REFS"], f'cam_qpf_{w_label}_{t_in}_refs.png', 'YlGnBu', prob_levels)
                save_png(models["SUPER"], f'cam_qpf_{w_label}_{t_in}_super.png', 'YlGnBu', prob_levels)
                
            for model_name, model_data in w_data["FFG_MAX"].items():
                save_png(model_data, f'cam_ffg_{w_label}_{model_name.lower()}.png', 'YlOrRd', prob_levels)

        # Save metadata and bounding box for Leaflet
        bounds = [
            [float(np.nanmin(lats)), float(np.nanmin(lons))],
            [float(np.nanmax(lats)), float(np.nanmax(lons))]
        ]
        
        valid_time_str = f"Ensemble Nowcast (HREF {payload['metadata']['href_cycle']:02d}Z | REFS {payload['metadata']['refs_cycle']:02d}Z)"
        
        with open("static/cam_metadata.json", "w") as f:
            json.dump({
                "valid_time": valid_time_str,
                "href_init_utc": payload['metadata']['href_init_utc'],
                "refs_init_utc": payload['metadata']['refs_init_utc'],
                "window_contract": payload['metadata']['window_contract'],
                "hourly_qpf_thresholds_in": self.qpf_thresh_in,
                "ffg_durations_hours": self.ffg_durations,
                "source_completeness_contract": "aligned HREF/REFS cycles and complete selected fields required before publication",
                "bounds": bounds,
                "rendering": {
                    "revision": RENDER_REVISION,
                    "map_pixel_dimensions": [6000, 3600],
                    "map_dpi": MAP_RENDER_DPI,
                    "probability_thresholds_unchanged": True,
                    "contour_antialiasing_display_only": True,
                    "refs_to_href_interpolation_unchanged": True
                }
            }, f)
        
        print("PNG mapping complete!")

if __name__ == "__main__":
    engine = EnsembleNowcastEngine()
    result = engine.generate_dashboard_data()
    engine.export_dashboard_layers(result)