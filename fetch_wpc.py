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
            
    try:
        val = float(raw)
        if val > 1e12: return datetime.fromtimestamp(val / 1000.0, tz=timezone.utc)
        if val > 1e9: return datetime.fromtimestamp(val, tz=timezone.utc)
    except: pass
    
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

def fetch_and_process_ero():
    print("Fetching WPC Day 1 ERO...")
    try:
        response = requests.get(f"{ERO_REST_URL}?where=1=1&outFields=OUTLOOK&f=geojson&time_buster={int(time.time())}", headers=NO_CACHE_HEADERS, timeout=30)
        response.raise_for_status()
        gdf = gpd.read_file(response.text, driver="GeoJSON")
        if gdf.empty or gdf.geometry.is_empty.all(): return None
        gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty].copy()
        gdf["dataType"] = "ERO"
        outlook_col = next((col for col in gdf.columns if col.upper() == "OUTLOOK"), None)
        if outlook_col: gdf["OUTLOOK"] = gdf[outlook_col]
        return gdf[[c for c in ["dataType", "OUTLOOK", "geometry"] if c in gdf.columns]].copy()
    except Exception as e:
        print(f"ERO failed: {e}")
        return None

def fetch_and_process_mpds():
    print("Fetching active MPDs...")
    now = utc_now()
    mpd_gdfs = []
    try:
        response = requests.get(f"{MPD_FTP_URL}?t={int(time.time())}", headers=NO_CACHE_HEADERS, timeout=30)
        response.raise_for_status()
        entries = []
        for line in response.text.splitlines():
            href_match = re.search(r'href="(?P<filename>MPD_(?P<num>\d{3,4})_final\.zip)"', line, re.IGNORECASE)
            if not href_match: continue
            
            filename = href_match.group("filename")
            mpd_num = int(href_match.group("num"))
            mod_match = re.search(r"</a>\s*(?P<date>\d{2}-[A-Za-z]{3}-\d{4})\s+(?P<time>\d{2}:\d{2})", line)
            
            modified_dt = None
            if mod_match:
                try: modified_dt = datetime.strptime(f"{mod_match.group('date')} {mod_match.group('time')}", "%d-%b-%Y %H:%M").replace(tzinfo=timezone.utc)
                except: pass
                
            entries.append({"filename": filename, "url": f"{MPD_FTP_URL}{filename}", "mpd_num": mpd_num, "modified_dt": modified_dt})

        if not entries: return None
        
        entries_with_time = [e for e in entries if e["modified_dt"] is not None]
        if entries_with_time:
            recent = [e for e in entries_with_time if e["modified_dt"] >= now - timedelta(hours=MPD_RECENT_FILE_HOURS)]
            candidates = sorted(recent, key=lambda e: e["modified_dt"], reverse=True)[:MAX_CANDIDATES]
        else:
            candidates = sorted(entries, key=lambda e: e["mpd_num"] if e["mpd_num"] is not None else -1, reverse=True)[:MAX_CANDIDATES]

        for entry in candidates:
            print(f"\nChecking: {entry['filename']}")
            z_resp = requests.get(entry["url"], headers=NO_CACHE_HEADERS, timeout=30)
            if z_resp.status_code != 200: continue
            
            with tempfile.TemporaryDirectory() as tmp_dir:
                try:
                    with zipfile.ZipFile(io.BytesIO(z_resp.content)) as z: z.extractall(tmp_dir)
                    shp_files = [os.path.join(tmp_dir, f) for f in os.listdir(tmp_dir) if f.lower().endswith(".shp")]
                    if not shp_files: continue
                    
                    gdf = gpd.read_file(shp_files[0])
                    gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty].copy()
                    if gdf.empty: continue
                    if gdf.crs is None: gdf = gdf.set_crs("EPSG:4326", allow_override=True)
                    else: gdf = gdf.to_crs("EPSG:4326")
                    
                    expire_col = find_column(gdf, exact_names=["EXPIRE", "EXPIRATION", "EXPIR", "EXP_TIME", "END", "END_TIME", "VALID_TO", "VALIDEND", "VALID_END", "VALID_UNTIL"], contains=["EXP", "END", "VALID_TO", "VALIDEND", "UNTIL"])
                    issue_col = find_column(gdf, exact_names=["ISSUE", "ISSUED", "ISSUE_TIME", "ISSUED_TIME", "START", "START_TIME", "VALID_FROM", "VALID_START", "BEGIN", "BEGIN_TIME"], contains=["ISSUE", "START", "BEGIN", "VALID_FROM", "VALID_START"])
                    
                    if not expire_col:
                        print("  -> No expiration column. Dropping.")
                        continue
                        
                    gdf["expire_dt_calc"] = gdf[expire_col].apply(parse_time_value)
                    gdf["issue_dt_calc"] = gdf[issue_col].apply(parse_time_value) if issue_col else pd.NaT
                    
                    expire_dt = gdf["expire_dt_calc"].dropna().iloc[0] if gdf["expire_dt_calc"].notna().any() else pd.NaT
                    issue_dt = gdf["issue_dt_calc"].dropna().iloc[0] if gdf["issue_dt_calc"].notna().any() else pd.NaT
                    
                    if pd.isna(expire_dt): continue
                    if expire_dt > now + timedelta(hours=MAX_EXPIRATION_AHEAD_HOURS): continue
                    
                    if pd.notna(issue_dt):
                        is_active = issue_dt <= now <= expire_dt
                    else:
                        recently_modified = (entry["modified_dt"] is not None and entry["modified_dt"] >= now - timedelta(hours=MPD_RECENT_FILE_HOURS))
                        is_active = now <= expire_dt and recently_modified
                        
                    if not is_active: continue
                    
                    print(f"  -> ACTIVE!")
                    active_gdf = gdf.copy()
                    active_gdf["dataType"] = "MPD"
                    active_gdf["mpd_number"] = f"{entry['mpd_num']:04d}" if entry['mpd_num'] is not None else ""
                    
                    tag_col = find_column(gdf, exact_names=["TAG", "SUBJECT", "PROB"], contains=["TAG", "SUBJ"])
                    if tag_col and not pd.isna(active_gdf[tag_col].iloc[0]):
                        shapefile_tag = str(active_gdf[tag_col].iloc[0])
                        if "..." in shapefile_tag:
                            isolated = shapefile_tag.split("...")[-1].strip()
                            active_gdf["mpd_tag"] = isolated.capitalize()
                        else:
                            active_gdf["mpd_tag"] = shapefile_tag.title()
                    else:
                        active_gdf["mpd_tag"] = f"MPD {entry['mpd_num']:04d}" if entry['mpd_num'] is not None else "MPD"
                        
                    active_gdf["valid_start_utc"] = iso_dt(issue_dt)
                    active_gdf["valid_end_utc"] = iso_dt(expire_dt)
                    active_gdf["valid_time"] = f"{format_dt(issue_dt)} - {format_dt(expire_dt)}"
                    active_gdf["hoverText"] = f"{active_gdf['mpd_tag'].iloc[0]}\nValid: {active_gdf['valid_time'].iloc[0]}"
                    
                    # NOTE: We are NOT dropping columns. Preserving them ensures JavaScript colors work!
                    active_gdf = active_gdf.drop(columns=["expire_dt_calc", "issue_dt_calc"], errors="ignore")
                    mpd_gdfs.append(active_gdf)
                except Exception as e:
                    print(f"  -> Error: {e}")
                    
        if mpd_gdfs: return gpd.GeoDataFrame(pd.concat(mpd_gdfs, ignore_index=True), geometry="geometry", crs="EPSG:4326")
        return None
    except Exception as e:
        print(f"Failed: {e}")
        return None

def main():
    final_gdfs = []
    ero_gdf = fetch_and_process_ero()
    if ero_gdf is not None: final_gdfs.append(ero_gdf)
    mpd_gdf = fetch_and_process_mpds()
    if mpd_gdf is not None: final_gdfs.append(mpd_gdf)
    
    if final_gdfs:
        combined_gdf = gpd.GeoDataFrame(pd.concat(final_gdfs, ignore_index=True), geometry="geometry", crs="EPSG:4326")
        for col in combined_gdf.columns:
            if col == "geometry": continue
            if pd.api.types.is_datetime64_any_dtype(combined_gdf[col]): combined_gdf[col] = combined_gdf[col].astype(str)
            if combined_gdf[col].dtype == "object": combined_gdf[col] = combined_gdf[col].where(combined_gdf[col].notna(), "").astype(str)
        combined_gdf.to_file(OUTPUT_FILENAME, driver="GeoJSON")
        print("Success")
    else: print("No data")

if __name__ == "__main__": main()
