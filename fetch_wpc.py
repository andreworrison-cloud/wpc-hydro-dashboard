import geopandas as gpd
import pandas as pd
import requests
import zipfile
import io
import os
import re
import time
import tempfile
from datetime import datetime, timezone, timedelta

ERO_REST_URL = "https://mapservices.weather.noaa.gov/vector/rest/services/hazards/wpc_precip_hazards/MapServer/0/query"
MPD_FTP_URL = "https://ftp-wpc.ncep.noaa.gov/shapefiles/qpf/mpd/"
MPD_PRODUCT_URL = "https://www.wpc.ncep.noaa.gov/metwatch/metwatch_mpd_multi.php"
OUTPUT_FILENAME = "wpc_data.geojson"

NO_CACHE_HEADERS = {
    "Cache-Control": "no-cache, no-store, must-revalidate",
    "Pragma": "no-cache",
    "Expires": "0",
    "User-Agent": "WPC-Hydro-Dashboard-Bot/1.0"
}

MPD_RECENT_FILE_HOURS = 48
MAX_EXPIRATION_AHEAD_HOURS = 18
MAX_CANDIDATES = 30

def utc_now():
    return datetime.now(timezone.utc)

def extract_mpd_num(filename):
    match = re.search(r"MPD_(\d{3,4})_final", str(filename), re.IGNORECASE)
    if match: return int(match.group(1))
    match = re.search(r"\d{3,4}", str(filename))
    return int(match.group()) if match else None

def format_dt(dt):
    if dt is None or pd.isna(dt): return "Unknown"
    if isinstance(dt, pd.Timestamp): dt = dt.to_pydatetime()
    if dt.tzinfo is None: dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%HZ %b %d %Y")

def iso_dt(dt):
    if dt is None or pd.isna(dt): return ""
    if isinstance(dt, pd.Timestamp): dt = dt.to_pydatetime()
    if dt.tzinfo is None: dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def safe_to_wgs84(gdf):
    if gdf is None or gdf.empty: return gdf
    gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty].copy()
    if gdf.empty: return gdf
    if gdf.crs is None: gdf = gdf.set_crs("EPSG:4326", allow_override=True)
    else: gdf = gdf.to_crs("EPSG:4326")
    return gdf

def month_year_shift(year, month, shift):
    m = month + shift
    y = year
    while m < 1:
        m += 12
        y -= 1
    while m > 12:
        m -= 12
        y += 1
    return y, m

def resolve_ddhhmm(ddhhmm, reference_dt):
    if reference_dt is None: reference_dt = utc_now()
    if reference_dt.tzinfo is None: reference_dt = reference_dt.replace(tzinfo=timezone.utc)
    token = str(ddhhmm).strip()
    if not re.fullmatch(r"\d{6}", token): return None
    day, hour, minute = int(token[0:2]), int(token[2:4]), int(token[4:6])
    candidates = []
    for shift in [-1, 0, 1]:
        y, m = month_year_shift(reference_dt.year, reference_dt.month, shift)
        try: candidates.append(datetime(y, m, day, hour, minute, tzinfo=timezone.utc))
        except ValueError: continue
    if not candidates: return None
    return min(candidates, key=lambda d: abs((d - reference_dt).total_seconds()))

def parse_valid_range_text(text, reference_dt):
    if text is None: return None, None
    s = str(text)
    match = re.search(r"VALID\s+(\d{6})Z?\s*[-–]\s*(\d{6})Z?", s, re.IGNORECASE)
    if not match: match = re.search(r"(\d{6})Z?\s*[-–]\s*(\d{6})Z?", s, re.IGNORECASE)
    if not match: return None, None
    start = resolve_ddhhmm(match.group(1), reference_dt)
    end = resolve_ddhhmm(match.group(2), reference_dt)
    if start and end and end < start:
        while end < start: end += timedelta(days=1)
    return start, end

def fetch_valid_times_from_mpd_text(mpd_num, reference_dt):
    years_to_try = []
    if reference_dt: years_to_try.extend([reference_dt.year, reference_dt.year - 1, reference_dt.year + 1])
    else:
        now = utc_now()
        years_to_try.extend([now.year, now.year - 1])
    seen = set()
    for year in years_to_try:
        if year in seen: continue
        seen.add(year)
        try:
            resp = requests.get(MPD_PRODUCT_URL, params={"md": f"{mpd_num:04d}", "yr": str(year), "_": int(time.time())}, headers=NO_CACHE_HEADERS, timeout=20)
            if resp.status_code != 200: continue
            start, end = parse_valid_range_text(resp.text, reference_dt)
            if start and end: return start, end
        except: pass
    return None, None

def parse_time_value(value):
    if value is None or pd.isna(value): return pd.NaT
    if isinstance(value, pd.Timestamp):
        if pd.isna(value): return pd.NaT
        if value.tzinfo is None: return value.to_pydatetime().replace(tzinfo=timezone.utc)
        return value.to_pydatetime().astimezone(timezone.utc)
    if isinstance(value, datetime):
        if value.tzinfo is None: return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    raw = str(value).strip()
    if raw.lower() in ["", "nan", "nat", "none", "null"]: return pd.NaT
    raw = raw.split(".")[0]
    digits = re.sub(r"\D", "", raw)
    
    for fmt, nchar in [("%y%m%d%H%M", 10), ("%Y%m%d%H%M", 12), ("%Y%m%d%H%M%S", 14)]:
        if len(digits) == nchar:
            try: return datetime.strptime(digits, fmt).replace(tzinfo=timezone.utc)
            except: pass

    # THE EPOCH FALLBACK WAS REMOVED HERE TO KILL THE 2055 TIME TRAVEL BUG

    try:
        parsed = pd.to_datetime(raw, utc=True, errors="coerce")
        if pd.notna(parsed): return parsed.to_pydatetime().astimezone(timezone.utc)
    except: pass
    return pd.NaT

def find_column(gdf, exact_names=None, contains=None):
    exact_names = exact_names or []
    contains = contains or []
    col_map = {c.strip().upper(): c for c in gdf.columns}
    for name in exact_names:
        if name.upper() in col_map: return col_map[name.upper()]
    for upper_col, original_col in col_map.items():
        for piece in contains:
            if piece.upper() in upper_col: return original_col
    return None

def parse_mpd_directory_entries():
    response = requests.get(f"{MPD_FTP_URL}?t={int(time.time())}", headers=NO_CACHE_HEADERS, timeout=30)
    response.raise_for_status()
    entries = []
    for line in response.text.splitlines():
        href_match = re.search(r'href="(?P<filename>MPD_(?P<num>\d{3,4})_final\.zip)"', line, re.IGNORECASE)
        if not href_match: continue
        filename = href_match.group("filename")
        mpd_num = int(href_match.group("num"))
        modified_dt = None
        mod_match = re.search(r"</a>\s*(?P<date>\d{2}-[A-Za-z]{3}-\d{4})\s+(?P<time>\d{2}:\d{2})", line)
        if mod_match:
            try: modified_dt = datetime.strptime(f"{mod_match.group('date')} {mod_match.group('time')}", "%d-%b-%Y %H:%M").replace(tzinfo=timezone.utc)
            except: modified_dt = None
        entries.append({"filename": filename, "url": f"{MPD_FTP_URL}{filename}", "mpd_num": mpd_num, "modified_dt": modified_dt})
    return entries

def select_recent_mpd_candidates(entries, now):
    entries_with_time = [e for e in entries if e["modified_dt"] is not None]
    if entries_with_time:
        recent = [e for e in entries_with_time if e["modified_dt"] >= now - timedelta(hours=MPD_RECENT_FILE_HOURS)]
        recent = sorted(recent, key=lambda e: e["modified_dt"], reverse=True)
        return recent[:MAX_CANDIDATES]
    return sorted(entries, key=lambda e: e["mpd_num"] if e["mpd_num"] is not None else -1, reverse=True)[:MAX_CANDIDATES]

def read_mpd_zip(entry):
    z_resp = requests.get(entry["url"], headers=NO_CACHE_HEADERS, timeout=30)
    if z_resp.status_code != 200: return None
    with tempfile.TemporaryDirectory() as tmp_dir:
        try:
            with zipfile.ZipFile(io.BytesIO(z_resp.content)) as z: z.extractall(tmp_dir)
            shp_files = [os.path.join(tmp_dir, f) for f in os.listdir(tmp_dir) if f.lower().endswith(".shp")]
            if not shp_files: return None
            gdf = gpd.read_file(shp_files[0])
            return safe_to_wgs84(gdf)
        except: return None

def infer_valid_times_from_shapefile(gdf, reference_dt):
    for col in gdf.columns:
        if col == "geometry": continue
        for value in gdf[col].dropna().astype(str).head(10):
            start, end = parse_valid_range_text(value, reference_dt)
            if start and end: return start, end

    start_col = find_column(gdf, exact_names=["VALID", "VALIDTIME", "VALID_TIME", "VALID_FROM", "START", "START_TIME", "BEGIN", "BEGIN_TIME", "ISSUE", "ISSUED", "ISSUE_TIME", "INIT", "INIT_TIME"], contains=["VALID_FROM", "START", "BEGIN", "ISSUE", "INIT"])
    end_col = find_column(gdf, exact_names=["EXPIRE", "EXPIRATION", "EXPIR", "EXP_TIME", "END", "END_TIME", "VALID_TO", "VALIDEND", "VALID_UNTIL", "UNTIL"], contains=["EXP", "END", "VALID_TO", "UNTIL"])
    
    start_dt, end_dt = None, None
    if start_col:
        for value in gdf[start_col].dropna().head(10):
            start_dt = parse_time_value(value)
            if start_dt: break
    if end_col:
        for value in gdf[end_col].dropna().head(10):
            end_dt = parse_time_value(value)
            if end_dt: break
    return start_dt, end_dt

def fetch_and_process_ero():
    print("Fetching WPC Day 1 ERO...")
    params = {"where": "1=1", "outFields": "OUTLOOK", "returnGeometry": "true", "f": "geojson", "outSR": "4326", "time_buster": int(time.time())}
    try:
        response = requests.get(ERO_REST_URL, params=params, headers=NO_CACHE_HEADERS, timeout=30)
        response.raise_for_status()
        geojson = response.json()
        features = geojson.get("features", [])
        if not features: return None
        gdf = gpd.GeoDataFrame.from_features(features, crs="EPSG:4326")
        gdf = safe_to_wgs84(gdf)
        if gdf is None or gdf.empty: return None
        outlook_col = next((col for col in gdf.columns if col.upper() == "OUTLOOK"), None)
        gdf["dataType"] = "ERO"
        if outlook_col:
            gdf["OUTLOOK"] = gdf[outlook_col]
            keep = ["dataType", "OUTLOOK", "geometry"]
        else: keep = ["dataType", "geometry"]
        return gdf[[col for col in keep if col in gdf.columns]].copy()
    except: return None

def fetch_and_process_mpds():
    print("Fetching active MPDs...")
    now = utc_now()
    mpd_gdfs = []
    try:
        entries = parse_mpd_directory_entries()
        if not entries: return None
        candidates = select_recent_mpd_candidates(entries, now)
        
        for entry in candidates:
            zip_filename = entry["filename"]
            mpd_num = entry["mpd_num"]
            gdf = read_mpd_zip(entry)
            if gdf is None or gdf.empty: continue
            
            reference_dt = entry["modified_dt"] or now
            valid_start, valid_end = infer_valid_times_from_shapefile(gdf, reference_dt)
            
            # THE MAGIC WEB SCRAPER FALLBACK THAT SAVES BROKEN WPC SHAPEFILES
            if valid_end is None:
                fallback_start, fallback_end = fetch_valid_times_from_mpd_text(mpd_num, reference_dt)
                if fallback_start: valid_start = fallback_start
                if fallback_end: valid_end = fallback_end
                
            if valid_end is None: continue
            
            if valid_start is not None: is_active = valid_start <= now <= valid_end
            else: is_active = now <= valid_end
            
            if not is_active: continue
            
            mpd_tag = f"MPD {mpd_num:04d}"
            valid_time = f"{format_dt(valid_start)} - {format_dt(valid_end)}"
            
            active_gdf = gdf.copy()
            active_gdf["dataType"] = "MPD"
            active_gdf["mpd_number"] = f"{mpd_num:04d}"
            active_gdf["mpd_tag"] = mpd_tag
            active_gdf["valid_start_utc"] = iso_dt(valid_start)
            active_gdf["valid_end_utc"] = iso_dt(valid_end)
            active_gdf["valid_time"] = valid_time
            active_gdf["hoverText"] = f"{mpd_tag}\nValid: {valid_time}"

            # COLUMN DELETION REMOVED TO PRESERVE JAVASCRIPT COLOR FORMATTING
            mpd_gdfs.append(active_gdf)

        if mpd_gdfs:
            return gpd.GeoDataFrame(pd.concat(mpd_gdfs, ignore_index=True), geometry="geometry", crs="EPSG:4326")
        return None
    except Exception as e:
        print(f"Failed to fetch MPDs: {e}")
        return None

def main():
    final_gdfs = []
    ero_gdf = fetch_and_process_ero()
    if ero_gdf is not None and not ero_gdf.empty: final_gdfs.append(ero_gdf)
    mpd_gdf = fetch_and_process_mpds()
    if mpd_gdf is not None and not mpd_gdf.empty: final_gdfs.append(mpd_gdf)
    
    if not final_gdfs: return
    combined_gdf = gpd.GeoDataFrame(pd.concat(final_gdfs, ignore_index=True), geometry="geometry", crs="EPSG:4326")
    combined_gdf = combined_gdf[combined_gdf.geometry.notna() & ~combined_gdf.geometry.is_empty].copy()
    
    for col in combined_gdf.columns:
        if col == "geometry": continue
        if pd.api.types.is_datetime64_any_dtype(combined_gdf[col]): combined_gdf[col] = combined_gdf[col].astype(str)
        if combined_gdf[col].dtype == "object": combined_gdf[col] = combined_gdf[col].where(combined_gdf[col].notna(), "").astype(str)
            
    combined_gdf.to_file(OUTPUT_FILENAME, driver="GeoJSON")

if __name__ == "__main__": main()
