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
MPD_ACTIVE_URL = "https://www.wpc.ncep.noaa.gov/metwatch/metwatch_mpd.php"
MPD_TEXT_URL = "https://www.wpc.ncep.noaa.gov/metwatch/metwatch_mpd_multi.php"
OUTPUT_FILENAME = "wpc_data.geojson"

NO_CACHE_HEADERS = {
    "Cache-Control": "no-cache, no-store, must-revalidate",
    "Pragma": "no-cache",
    "Expires": "0",
    "User-Agent": "WPC-Hydro-Dashboard-Bot/3.0"
}

def utc_now():
    return datetime.now(timezone.utc)

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

def resolve_ddhhmm(ddhhmm, reference_dt=None):
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

def fetch_active_mpd_numbers():
    print(f"Scraping exact active MPDs directly from WPC webpage ({MPD_ACTIVE_URL})...")
    try:
        r = requests.get(f"{MPD_ACTIVE_URL}?t={int(time.time())}", headers=NO_CACHE_HEADERS, timeout=15)
        r.raise_for_status()
        
        matches = re.findall(r'md=(\d{3,4})', r.text)
        active_nums = set(int(m) for m in matches)
        
        print(f" -> Found active MPD numbers candidate list: {list(active_nums)}")
        return list(active_nums)
    except Exception as e:
        print(f"Failed to scrape active MPD numbers: {e}")
        return []

def fetch_mpd_times_from_text(mpd_num):
    print(f" -> Scraping official text bulletin for MPD {mpd_num:04d} exact valid times...")
    now = utc_now()
    
    for yr in [now.year, now.year - 1]:
        try:
            r = requests.get(f"{MPD_TEXT_URL}?md={mpd_num:04d}&yr={yr}", headers=NO_CACHE_HEADERS, timeout=15)
            if r.status_code != 200: continue
            
            match = re.search(r'VALID\s+(\d{6})Z?\s*[-–]\s*(\d{6})Z?', r.text, re.IGNORECASE)
            if match:
                start_dt = resolve_ddhhmm(match.group(1), now)
                end_dt = resolve_ddhhmm(match.group(2), now)
                return start_dt, end_dt
        except: pass
    return None, None

def fetch_and_process_mpds():
    active_nums = fetch_active_mpd_numbers()
    if not active_nums:
        print("No active MPDs found on WPC webpage. Map will be cleared of MPDs.")
        return None

    mpd_gdfs = []
    
    for mpd_num in active_nums:
        print(f"\nProcessing MPD {mpd_num:04d}...")
        
        issue_dt, expire_dt = fetch_mpd_times_from_text(mpd_num)
        
        if not issue_dt or not expire_dt:
            print(f" -> Could not parse official times for {mpd_num:04d} from text. Skipping.")
            continue
            
        # --- THE TIME-GATE FIX ---
        # If the current time has passed the expiration time, skip it entirely!
        if utc_now() > expire_dt:
            print(f" -> MPD {mpd_num:04d} has expired (Expired at {expire_dt.strftime('%H%MZ %b %d %Y')}). Purging from data feed.")
            continue
            
        zip_filename = f"MPD_{mpd_num:04d}_final.zip"
        zip_url = f"{MPD_FTP_URL}{zip_filename}"
            
        z_resp = requests.get(zip_url, headers=NO_CACHE_HEADERS, timeout=30)
        if z_resp.status_code != 200:
            print(f" -> Shapefile {zip_filename} not found on FTP. Skipping.")
            continue
            
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
                
                col_map = {c.strip().upper(): c for c in gdf.columns}
                tag_col = next((col_map[c] for c in ["TAG", "SUBJECT", "PROB"] if c in col_map), None)
                
                extracted_tag = ""
                if tag_col and not pd.isna(gdf[tag_col].iloc[0]):
                    raw_tag = str(gdf[tag_col].iloc[0])
                    parts = raw_tag.split("...")
                    formatted_parts = [p.strip().capitalize() for p in parts]
                    extracted_tag = "...".join(formatted_parts)
                else:
                    row_str = str(gdf.iloc[0].to_dict()).upper()
                    if "FLASH FLOODING LIKELY" in row_str: extracted_tag = "Flash flooding likely"
                    elif "FLASH FLOODING POSSIBLE" in row_str: extracted_tag = "Flash flooding possible"
                    else: extracted_tag = "See WPC for details"
                
                mpd_display_title = f"MPD {mpd_num:04d}"
                        
                issue_str = issue_dt.strftime("%H%MZ %b %d %Y")
                expire_str = expire_dt.strftime("%H%MZ %b %d %Y")
                valid_str = f"{issue_str} - {expire_str}"

                print(f" -> Successfully mapped! {mpd_display_title} Valid: {valid_str}")

                active_gdf = gdf.copy()
                active_gdf["dataType"] = "MPD"
                active_gdf["mpd_number"] = f"{mpd_num:04d}"
                active_gdf["mpd_tag"] = extracted_tag
                active_gdf["valid_start_utc"] = issue_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
                active_gdf["valid_end_utc"] = expire_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
                active_gdf["valid_time"] = valid_str
                active_gdf["hoverText"] = f"{mpd_display_title}<br>{extracted_tag}<br>Valid: {valid_str}"
                
                mpd_gdfs.append(active_gdf)

            except Exception as e:
                print(f" -> Error processing shapefile geometry: {e}")
                
    if mpd_gdfs:
        return gpd.GeoDataFrame(pd.concat(mpd_gdfs, ignore_index=True), geometry="geometry", crs="EPSG:4326")
    return None

def main():
    final_gdfs = []
    
    ero_gdf = fetch_and_process_ero()
    if ero_gdf is not None and not ero_gdf.empty: final_gdfs.append(ero_gdf)
        
    mpd_gdf = fetch_and_process_mpds()
    if mpd_gdf is not None and not mpd_gdf.empty: final_gdfs.append(mpd_gdf)
    
    if not final_gdfs:
        print("No valid data processed. GeoJSON not updated.")
        return
        
    combined_gdf = gpd.GeoDataFrame(pd.concat(final_gdfs, ignore_index=True), geometry="geometry", crs="EPSG:4326")
    combined_gdf = combined_gdf[combined_gdf.geometry.notna() & ~combined_gdf.geometry.is_empty].copy()
    
    for col in combined_gdf.columns:
        if col == "geometry": continue
        if pd.api.types.is_datetime64_any_dtype(combined_gdf[col]): combined_gdf[col] = combined_gdf[col].astype(str)
        if combined_gdf[col].dtype == "object": combined_gdf[col] = combined_gdf[col].where(combined_gdf[col].notna(), "").astype(str)
            
    combined_gdf.to_file(OUTPUT_FILENAME, driver="GeoJSON")
    print(f"Successfully wrote clean data to {OUTPUT_FILENAME}")

if __name__ == "__main__":
    main()
