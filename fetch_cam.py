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

    def _refs_product_urls(self, d_str, cycle, filename):
        """Return REFS URLs in preferred order: AWS, NOMADS parallel, NOMADS production."""
        rel = f"refs.{d_str}/{cycle:02d}/ensprod/{filename}"
        return [
            ("AWS", f"https://noaa-rrfs-pds.s3.amazonaws.com/refs/v1.0/{rel}"),
            ("NOMADS-PARA", f"https://nomads.ncep.noaa.gov/pub/data/nccf/com/refs/para/{rel}"),
            ("NOMADS-PROD", f"https://nomads.ncep.noaa.gov/pub/data/nccf/com/refs/prod/{rel}"),
        ]
        

    def _get_latest_cycle(self, model, max_fxx):
        now = datetime.now(timezone.utc)
        curr_cycle = now.replace(hour=(now.hour // 6) * 6, minute=0, second=0, microsecond=0)
        for i in range(8):
            dt = curr_cycle - timedelta(hours=6 * i)
            cycle = dt.hour
            d_str = dt.strftime("%Y%m%d")
            
            if model == "HREF":
                idx_prob = f"https://nomads.ncep.noaa.gov/pub/data/nccf/com/href/prod/href.{d_str}/ensprod/href.t{cycle:02d}z.conus.prob.f{max_fxx:02d}.grib2.idx"
                idx_ffri = f"https://nomads.ncep.noaa.gov/pub/data/nccf/com/href/prod/href.{d_str}/ensprod/href.t{cycle:02d}z.conus.ffri.f{max_fxx:02d}.grib2.idx"
                try:
                    if requests.head(idx_prob, headers=self.headers, timeout=5).status_code == 200 and requests.head(idx_ffri, headers=self.headers, timeout=5).status_code == 200:
                        return d_str, cycle
                except: pass
            else:
                prob_name = f"refs.t{cycle:02d}z.prob.f{max_fxx:02d}.conus.grib2"
                ffri_name = f"refs.t{cycle:02d}z.ffri.f{max_fxx:02d}.conus.grib2"
                prob_sources = self._refs_product_urls(d_str, cycle, prob_name)
                ffri_sources = self._refs_product_urls(d_str, cycle, ffri_name)

                for (source, prob_url), (_, ffri_url) in zip(prob_sources, ffri_sources):
                    try:
                        if (requests.head(prob_url + ".idx", headers=self.headers, timeout=5, allow_redirects=True).status_code == 200 and
                            requests.head(ffri_url + ".idx", headers=self.headers, timeout=5, allow_redirects=True).status_code == 200):
                            self.refs_cycle_source = source
                            return d_str, cycle
                    except requests.RequestException:
                        pass
        return None, None

    def _get_idx(self, url):
        if url not in self.idx_cache:
            try:
                r = requests.get(url, headers=self.headers, timeout=10)
                self.idx_cache[url] = r.text if r.status_code == 200 else ""
            except: self.idx_cache[url] = ""
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
        max_req_fxx = max([w[1] for w in self.windows])
        
        h_date, h_cyc = self._get_latest_cycle("HREF", max_req_fxx)
        r_date, r_cyc = self._get_latest_cycle("REFS", max_req_fxx)
        
        if not h_date or not r_date:
            return {"error": f"Missing Core Ensemble Runs out to f{max_req_fxx}."}
            
        print(f"Locked Models -> HREF: {h_cyc:02d}Z | REFS: {r_cyc:02d}Z")
        
        data_store = {w: {"QPF": {t: {"HREF": None, "REFS": None} for t in self.qpf_thresh_in}, 
                          "FFG_MAX": {"HREF": None, "REFS": None}} for w in self.windows}
        coords = {"HREF": [None, None], "REFS": [None, None]}
        
        tasks = []
        
        h_base = f"https://nomads.ncep.noaa.gov/pub/data/nccf/com/href/prod/href.{h_date}/ensprod"
        print(f"REFS cycle discovery source: {self.refs_cycle_source or 'unknown'}")
        
        for w in self.windows:
            window_start = w[0] - 1  # e.g., for w=(4,9), start is 3.
            for fxx in range(w[0], w[1] + 1):
                # 1. Queue QPF (1-hour durations strictly inside the window)
                for t_in, t_mm in zip(self.qpf_thresh_in, self.qpf_thresh_mm):
                    tasks.append((f"{h_base}/href.t{h_cyc:02d}z.conus.prob.f{fxx:02d}.grib2", f"{h_base}/href.t{h_cyc:02d}z.conus.prob.f{fxx:02d}.grib2.idx", "QPF", t_mm, fxx, self.grib_dir/f"H_Q_{t_in}_{fxx}.grib2"))
                    r_name = f"refs.t{r_cyc:02d}z.prob.f{fxx:02d}.conus.grib2"
                    r_sources = self._refs_product_urls(r_date, r_cyc, r_name)
                    r_urls = [u for _, u in r_sources]
                    tasks.append((r_urls, [u + ".idx" for u in r_urls], "QPF", t_mm, fxx, self.grib_dir/f"R_Q_{t_in}_{fxx}.grib2"))
                
                # 2. Queue FFG (STRICTLY CONFINED TO WINDOW)
                for d in self.ffg_durations:
                    if fxx - d >= window_start:
                        tasks.append((f"{h_base}/href.t{h_cyc:02d}z.conus.ffri.f{fxx:02d}.grib2", f"{h_base}/href.t{h_cyc:02d}z.conus.ffri.f{fxx:02d}.grib2.idx", "FFG", d, fxx, self.grib_dir/f"H_F_{d}_{fxx}.grib2"))
                        r_name = f"refs.t{r_cyc:02d}z.ffri.f{fxx:02d}.conus.grib2"
                        r_sources = self._refs_product_urls(r_date, r_cyc, r_name)
                        r_urls = [u for _, u in r_sources]
                        tasks.append((r_urls, [u + ".idx" for u in r_urls], "FFG", d, fxx, self.grib_dir/f"R_F_{d}_{fxx}.grib2"))

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            list(executor.map(self._fetch_grib, tasks))

        for w in self.windows:
            window_start = w[0] - 1
            for fxx in range(w[0], w[1] + 1):
                for t_in in self.qpf_thresh_in:
                    for model, prefix in [("HREF", "H"), ("REFS", "R")]:
                        file = self.grib_dir/f"{prefix}_Q_{t_in}_{fxx}.grib2"
                        if file.exists():
                            data_store[w]["QPF"][t_in][model], coords[model][0], coords[model][1], _ = self._extract_max(file, data_store[w]["QPF"][t_in][model], coords[model][0], coords[model][1])
                            try: file.unlink()
                            except: pass
                
                for d in self.ffg_durations:
                    if fxx - d >= window_start: # STRICT BOUNDARY CHECK
                        for model, prefix in [("HREF", "H"), ("REFS", "R")]:
                            file = self.grib_dir/f"{prefix}_F_{d}_{fxx}.grib2"
                            if file.exists():
                                data_store[w]["FFG_MAX"][model], coords[model][0], coords[model][1], _ = self._extract_max(file, data_store[w]["FFG_MAX"][model], coords[model][0], coords[model][1])
                                try: file.unlink()
                                except: pass

        dashboard_payload = {
            "metadata": {
                "href_cycle": h_cyc, "refs_cycle": r_cyc,
                "lats": coords["HREF"][0], "lons": coords["HREF"][1]
            },
            "windows": {}
        }

        for w in self.windows:
            w_label = f"{w[0]-1}h_to_{w[1]}h"
            dashboard_payload["windows"][w_label] = {"QPF": {}, "FFG_MAX": {}}
            
            for t_in in self.qpf_thresh_in:
                href_data = data_store[w]["QPF"][t_in]["HREF"]
                refs_data = data_store[w]["QPF"][t_in]["REFS"]
                refs_interp, super_ens = self._create_super_ensemble(href_data, coords["HREF"][0], coords["HREF"][1], refs_data, coords["REFS"][0], coords["REFS"][1])
                
                dashboard_payload["windows"][w_label]["QPF"][f"{t_in}_inch"] = {
                    "HREF": href_data, "REFS": refs_interp, "SUPER": super_ens
                }

            href_ffg = data_store[w]["FFG_MAX"]["HREF"]
            refs_ffg = data_store[w]["FFG_MAX"]["REFS"]
            refs_ffg_interp, super_ens_ffg = self._create_super_ensemble(href_ffg, coords["HREF"][0], coords["HREF"][1], refs_ffg, coords["REFS"][0], coords["REFS"][1])
            
            dashboard_payload["windows"][w_label]["FFG_MAX"] = {
                "HREF": href_ffg, "REFS": refs_ffg_interp, "SUPER": super_ens_ffg
            }

        return dashboard_payload

    def export_dashboard_layers(self, payload):
        if "error" in payload:
            print("Error in payload. Cannot export maps.")
            return

        print("Exporting Geo-Registered PNGs and Metadata...")
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
            if data is None: return
            
            # Mask out probabilities less than 10% for a clean transparent background
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
                "bounds": bounds
            }, f)
        
        print("PNG mapping complete!")

if __name__ == "__main__":
    engine = EnsembleNowcastEngine()
    result = engine.generate_dashboard_data()
    engine.export_dashboard_layers(result)
