import os, requests, concurrent.futures, warnings, gc, json
from datetime import datetime, timezone, timedelta
from pathlib import Path
import xarray as xr
import numpy as np
from scipy.interpolate import griddata
from scipy.spatial import cKDTree
import matplotlib.pyplot as plt
from matplotlib import ticker

warnings.filterwarnings('ignore')

class EROCamEngine:
    def __init__(self, output_dir="grib_cache_ero"):
        self.grib_dir = Path(output_dir)
        self.grib_dir.mkdir(exist_ok=True, parents=True)
        self.headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        self.idx_cache = {}
        self.refs_cycle_source = None

        self.qpf_thresh_in = [0.5, 1, 2, 3]
        self.qpf_thresh_mm = [12.7, 25.4, 50.8, 76.2]
        self.ffg_durations = [1, 3, 6]


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

    def _probe_idx(self, source, grib_url, timeout=8):
        """Probe the .idx endpoint with GET (not HEAD) and print the HTTP result."""
        idx_url = grib_url + ".idx"
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
            print(f"IDX probe [{r.status_code}] {source}: {idx_url}")
            return r.status_code in (200, 206)
        except requests.RequestException as e:
            print(f"IDX probe [ERROR] {source}: {idx_url} ({type(e).__name__})")
            return False



    def _probe_grib(self, source, grib_url, timeout=10):
        """Probe only the first byte of a GRIB2 object."""
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
            print(f"GRIB probe [{r.status_code}] {source}: {grib_url}")
            return r.status_code in (200, 206)
        except requests.RequestException as e:
            print(f"GRIB probe [ERROR] {source}: {grib_url} ({type(e).__name__})")
            return False

    def _refs_candidates(self, d_str, cycle, product, fxx):
        return self._refs_product_urls(d_str, cycle, product, fxx)

    def _get_fxx_range_for_ero(self, cycle):
        """Matches the user's logic to perfectly bound the 12Z-12Z ERO period."""
        if cycle == 12: return range(1, 25)
        elif cycle == 18: return range(1, 19)
        elif cycle == 0: return range(12, 37)
        elif cycle == 6: return range(6, 31)
        return None


    def _get_latest_cycle(self, model):
        now = datetime.now(timezone.utc)
        curr_cycle = now.replace(
            hour=(now.hour // 6) * 6, minute=0, second=0, microsecond=0
        )

        for i in range(8):
            dt = curr_cycle - timedelta(hours=6 * i)
            cycle = dt.hour
            d_str = dt.strftime("%Y%m%d")

            fxx_range = self._get_fxx_range_for_ero(cycle)
            if not fxx_range:
                continue
            max_fxx = max(fxx_range)

            if model == "HREF":
                prob_url = (
                    f"https://nomads.ncep.noaa.gov/pub/data/nccf/com/href/prod/"
                    f"href.{d_str}/ensprod/"
                    f"href.t{cycle:02d}z.conus.prob.f{max_fxx:02d}.grib2"
                )
                if self._probe_idx("HREF-NOMADS", prob_url):
                    print(
                        f"HREF ERO candidate accepted: {d_str} {cycle:02d}Z "
                        f"(PROB f{max_fxx:02d})"
                    )
                    return d_str, cycle, fxx_range, dt
            else:
                for source, prob_url in self._refs_candidates(
                    d_str, cycle, "prob", max_fxx
                ):
                    if self._probe_grib(source, prob_url):
                        self.refs_cycle_source = source
                        print(
                            f"REFS ERO candidate accepted: {d_str} {cycle:02d}Z "
                            f"via {source} (direct PROB GRIB f{max_fxx:02d})"
                        )
                        return d_str, cycle, fxx_range, dt

        print(f"ERROR: No usable {model} ERO cycle found in the last 48 hours.")
        return None, None, None, None

    def _get_idx(self, url):
        if url not in self.idx_cache:
            try:
                r = requests.get(url, headers=self.headers, timeout=10, allow_redirects=True)
                if r.status_code in (200, 206):
                    self.idx_cache[url] = r.text
                else:
                    print(f"IDX fetch [{r.status_code}]: {url}")
                    self.idx_cache[url] = ""
            except requests.RequestException as e:
                print(f"IDX fetch [ERROR]: {url} ({type(e).__name__})")
                self.idx_cache[url] = ""
        return self.idx_cache[url]

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
        if out_file.exists(): return True

        # HREF passes one URL pair. REFS passes ordered URL lists:
        # AWS first, then NOMADS parallel, then NOMADS production.
        urls = list(url) if isinstance(url, (list, tuple)) else [url]
        idx_urls = list(idx_url) if isinstance(idx_url, (list, tuple)) else [idx_url]

        for source_url, source_idx_url in zip(urls, idx_urls):
            start_b, end_b = self._parse_idx(self._get_idx(source_idx_url), p_type, val, fxx)
            if start_b is None:
                continue

            rng = f"bytes={start_b}-{end_b}" if end_b else f"bytes={start_b}-"
            try:
                r = requests.get(
                    source_url,
                    headers={"Range": rng, "User-Agent": self.headers["User-Agent"]},
                    timeout=30
                )
                if r.status_code in (200, 206):
                    with open(out_file, 'wb') as f:
                        f.write(r.content)
                    return True
            except requests.RequestException:
                continue

        return False



    def _download_refs_full(self, d_str, cycle, product, fxx):
        """
        Download one complete REFS GRIB2 product, trying the current parallel
        feed first. Returns (path, source) or (None, None).

        The file is streamed to disk so it is never held in memory as one large
        bytes object. Callers delete it immediately after local ecCodes scanning.
        """
        for source, url in self._refs_candidates(d_str, cycle, product, fxx):
            try:
                r = requests.get(
                    url,
                    headers={"User-Agent": self.headers["User-Agent"]},
                    timeout=(10, 180),
                    allow_redirects=True,
                    stream=True,
                )
                if r.status_code not in (200, 206):
                    # 404 is expected for forecast hours/products not published.
                    continue

                suffix = f"{d_str}_{cycle:02d}_{product}_f{fxx:02d}.grib2"
                out_file = self.grib_dir / f"REFS_FULL_{suffix}"
                total = r.headers.get("Content-Length", "?")
                print(
                    f"REFS full-GRIB download: {d_str} {cycle:02d}Z "
                    f"{product.upper()} f{fxx:02d} via {source} "
                    f"(Content-Length={total})"
                )

                with open(out_file, "wb") as f:
                    for chunk in r.iter_content(chunk_size=1024 * 1024):
                        if chunk:
                            f.write(chunk)

                if out_file.exists() and out_file.stat().st_size > 16:
                    return out_file, source

                try:
                    out_file.unlink()
                except FileNotFoundError:
                    pass
            except requests.RequestException as e:
                print(
                    f"REFS download error {source} {product} f{fxx:02d}: "
                    f"{type(e).__name__}"
                )

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


    def generate_ero_data(self):
        print("Starting ERO Super-Ensemble Data Generation...")

        h_date, h_cyc, h_fxx_range, h_dt = self._get_latest_cycle("HREF")
        r_date, r_cyc, r_fxx_range, r_dt = self._get_latest_cycle("REFS")

        if not h_date or not r_date:
            print(
                f"ERO cycle discovery summary -> HREF: {h_date or 'MISSING'} | "
                f"REFS: {r_date or 'MISSING'}"
            )
            return {"error": "Missing Core Ensemble Runs for ERO Window."}

        print(
            f"Locked Models for ERO -> HREF: {h_cyc:02d}Z | "
            f"REFS: {r_cyc:02d}Z"
        )
        print(
            f"REFS direct-GRIB cycle source: "
            f"{self.refs_cycle_source or 'unknown'}"
        )

        base_12z = h_dt.replace(hour=12, minute=0, second=0, microsecond=0)
        start_ero = base_12z
        end_ero = start_ero + timedelta(hours=24)
        ero_valid_str = (
            f"12Z {start_ero.strftime('%b %d')} &mdash; "
            f"12Z {end_ero.strftime('%b %d')}"
        )

        data_store = {
            "QPF": {
                t: {"HREF": None, "REFS": None}
                for t in self.qpf_thresh_in
            },
            "FFG_MAX": {"HREF": None, "REFS": None},
        }
        coords = {"HREF": [None, None], "REFS": [None, None]}

        shared_fxx_range = sorted(list(set(h_fxx_range) & set(r_fxx_range)))
        window_start = shared_fxx_range[0] - 1

        # ---------------- HREF ----------------
        h_base = (
            f"https://nomads.ncep.noaa.gov/pub/data/nccf/com/href/prod/"
            f"href.{h_date}/ensprod"
        )
        href_tasks = []

        for fxx in shared_fxx_range:
            for t_in, t_mm in zip(self.qpf_thresh_in, self.qpf_thresh_mm):
                href_tasks.append(
                    (
                        f"{h_base}/href.t{h_cyc:02d}z.conus.prob.f{fxx:02d}.grib2",
                        f"{h_base}/href.t{h_cyc:02d}z.conus.prob.f{fxx:02d}.grib2.idx",
                        "QPF",
                        t_mm,
                        fxx,
                        self.grib_dir / f"H_Q_{t_in}_{fxx}.grib2",
                    )
                )

            for d in self.ffg_durations:
                if fxx - d >= window_start:
                    href_tasks.append(
                        (
                            f"{h_base}/href.t{h_cyc:02d}z.conus.ffri.f{fxx:02d}.grib2",
                            f"{h_base}/href.t{h_cyc:02d}z.conus.ffri.f{fxx:02d}.grib2.idx",
                            "FFG",
                            d,
                            fxx,
                            self.grib_dir / f"H_F_{d}_{fxx}.grib2",
                        )
                    )

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            list(executor.map(self._fetch_grib, href_tasks))

        for fxx in shared_fxx_range:
            for t_in in self.qpf_thresh_in:
                file = self.grib_dir / f"H_Q_{t_in}_{fxx}.grib2"
                if file.exists():
                    (
                        data_store["QPF"][t_in]["HREF"],
                        coords["HREF"][0],
                        coords["HREF"][1],
                        _,
                    ) = self._extract_max(
                        file,
                        data_store["QPF"][t_in]["HREF"],
                        coords["HREF"][0],
                        coords["HREF"][1],
                    )
                    try:
                        file.unlink()
                    except Exception:
                        pass

            for d in self.ffg_durations:
                if fxx - d >= window_start:
                    file = self.grib_dir / f"H_F_{d}_{fxx}.grib2"
                    if file.exists():
                        (
                            data_store["FFG_MAX"]["HREF"],
                            coords["HREF"][0],
                            coords["HREF"][1],
                            _,
                        ) = self._extract_max(
                            file,
                            data_store["FFG_MAX"]["HREF"],
                            coords["HREF"][0],
                            coords["HREF"][1],
                        )
                        try:
                            file.unlink()
                        except Exception:
                            pass

        # ---------------- REFS ----------------
        refs_hours_used = []
        refs_ffri_hours_used = []

        for fxx in shared_fxx_range:
            full_prob, source = self._download_refs_full(
                r_date, r_cyc, "prob", fxx
            )
            if full_prob is not None:
                try:
                    qpf_fields, rlats, rlons = self._scan_refs_prob_file(
                        full_prob, fxx
                    )
                    found_any = False
                    for t_in, t_mm in zip(
                        self.qpf_thresh_in, self.qpf_thresh_mm
                    ):
                        arr = qpf_fields.get(float(t_mm))
                        if arr is not None:
                            data_store["QPF"][t_in]["REFS"] = self._merge_max(
                                data_store["QPF"][t_in]["REFS"], arr
                            )
                            found_any = True
                    if found_any:
                        refs_hours_used.append(fxx)
                        if coords["REFS"][0] is None:
                            coords["REFS"] = [rlats, rlons]
                finally:
                    try:
                        full_prob.unlink()
                    except Exception:
                        pass

            if any(fxx - d >= window_start for d in self.ffg_durations):
                full_ffri, _ = self._download_refs_full(
                    r_date, r_cyc, "ffri", fxx
                )
                if full_ffri is not None:
                    try:
                        ffg_fields, rlats, rlons = self._scan_refs_ffri_file(
                            full_ffri, fxx
                        )
                        found_ffg = False
                        for d in self.ffg_durations:
                            if fxx - d >= window_start:
                                arr = ffg_fields.get(d)
                                if arr is not None:
                                    data_store["FFG_MAX"]["REFS"] = self._merge_max(
                                        data_store["FFG_MAX"]["REFS"], arr
                                    )
                                    found_ffg = True
                        if found_ffg:
                            refs_ffri_hours_used.append(fxx)
                            if coords["REFS"][0] is None:
                                coords["REFS"] = [rlats, rlons]
                    finally:
                        try:
                            full_ffri.unlink()
                        except Exception:
                            pass

        print(
            "REFS ERO QPF forecast hours used: "
            + (
                ", ".join(f"f{h:02d}" for h in sorted(set(refs_hours_used)))
                if refs_hours_used
                else "NONE"
            )
        )
        if refs_ffri_hours_used:
            print(
                "REFS ERO FFRI forecast hours used: "
                + ", ".join(
                    f"f{h:02d}" for h in sorted(set(refs_ffri_hours_used))
                )
            )
        else:
            print(
                "REFS FFRI unavailable/no usable fields; "
                "ERO FFG guidance will use HREF-only for this run."
            )

        dashboard_payload = {
            "metadata": {
                "href_cycle": h_cyc,
                "refs_cycle": r_cyc,
                "lats": coords["HREF"][0],
                "lons": coords["HREF"][1],
                "ero_valid_str": ero_valid_str,
            },
            "QPF": {},
            "FFG_MAX": {},
        }

        for t_in in self.qpf_thresh_in:
            href_data = data_store["QPF"][t_in]["HREF"]
            refs_data = data_store["QPF"][t_in]["REFS"]
            refs_interp, super_ens = self._create_super_ensemble(
                href_data,
                coords["HREF"][0],
                coords["HREF"][1],
                refs_data,
                coords["REFS"][0],
                coords["REFS"][1],
            )

            dashboard_payload["QPF"][f"{t_in}_inch"] = {
                "HREF": href_data,
                "REFS": refs_interp,
                "SUPER": super_ens,
            }

        href_ffg = data_store["FFG_MAX"]["HREF"]
        refs_ffg = data_store["FFG_MAX"]["REFS"]
        refs_ffg_interp, super_ens_ffg = self._create_super_ensemble(
            href_ffg,
            coords["HREF"][0],
            coords["HREF"][1],
            refs_ffg,
            coords["REFS"][0],
            coords["REFS"][1],
        )

        dashboard_payload["FFG_MAX"] = {
            "HREF": href_ffg,
            "REFS": refs_ffg_interp,
            "SUPER": super_ens_ffg,
        }

        return dashboard_payload

    def export_dashboard_layers(self, payload):
        if "error" in payload:
            raise RuntimeError(payload["error"])

        print("Exporting Geo-Registered PNGs and Metadata...")
        os.makedirs("static", exist_ok=True)
        
        lats = payload["metadata"]["lats"]
        lons = payload["metadata"]["lons"]
        
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
            data = np.where(data < levels[0], np.nan, data)
            fig = plt.figure(figsize=(10, 6), dpi=300, frameon=False)
            ax = plt.Axes(fig, [0., 0., 1., 1.])
            ax.set_axis_off()
            fig.add_axes(ax)
            ax.contourf(x_wm, y_wm, data, levels=levels, cmap=cmap, extend='max', alpha=0.65)
            ax.set_xlim(min_x, max_x)
            ax.set_ylim(min_y, max_y)
            plt.savefig(f'static/{filename}', format='png', transparent=True)
            plt.close()

        prob_levels = [10, 30, 50, 70, 90, 100]
        
        for t_in, models in payload["QPF"].items():
            save_png(models["HREF"], f'ero_qpf_{t_in}_href.png', 'YlGnBu', prob_levels)
            save_png(models["REFS"], f'ero_qpf_{t_in}_refs.png', 'YlGnBu', prob_levels)
            save_png(models["SUPER"], f'ero_qpf_{t_in}_super.png', 'YlGnBu', prob_levels)
            
        for model_name, model_data in payload["FFG_MAX"].items():
            save_png(model_data, f'ero_ffg_{model_name.lower()}.png', 'YlOrRd', prob_levels)

        bounds = [
            [float(np.nanmin(lats)), float(np.nanmin(lons))],
            [float(np.nanmax(lats)), float(np.nanmax(lons))]
        ]
        
        valid_time_str = f"Day 1 ERO Window (HREF {payload['metadata']['href_cycle']:02d}Z | REFS {payload['metadata']['refs_cycle']:02d}Z)"
        
        with open("static/ero_cam_metadata.json", "w") as f:
            json.dump({
                "valid_time": valid_time_str,
                "ero_window_str": payload['metadata']['ero_valid_str'],
                "bounds": bounds
            }, f)
        
        print("PNG mapping complete!")

if __name__ == "__main__":
    engine = EROCamEngine()
    result = engine.generate_ero_data()
    engine.export_dashboard_layers(result)