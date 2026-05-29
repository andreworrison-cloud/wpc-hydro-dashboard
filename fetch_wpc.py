import geopandas as gpd
import pandas as pd
import requests
import zipfile
import io
import os
import re
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

# ERO points to the live NOAA Enterprise GIS database
ERO_REST_URL = "https://mapservices.weather.noaa.gov/vector/rest/services/hazards/wpc_precip_hazards/MapServer/0/query"
MPD_FTP_URL = "https://ftp-wpc.ncep.noaa.gov/shapefiles/qpf/mpd/"
OUTPUT_FILENAME = "wpc_data.geojson"

NO_CACHE_HEADERS = {
    "Cache-Control": "no-cache, no-store, must-revalidate",
    "Pragma": "no-cache",
    "Expires": "0",
    "User-Agent": "WPC-Hydro-Dashboard-Bot/1.0"
}

def fetch_and_process_ero():
    print("Fetching WPC Day 1 ERO from live NOAA REST API...")
    try:
        cache_bust_url = f"{ERO_REST_URL}?where=1=1&outFields=OUTLOOK&f=geojson&time_buster={int(time.time())}"
        response = requests.get(cache_bust_url, headers=NO_CACHE_HEADERS)
        response.raise_for_status()
        
        gdf = gpd.read_file(response.text, driver="GeoJSON")
        if gdf.empty or gdf.geometry.is_empty.all(): return None
            
        gdf = gdf[~gdf.geometry.is_empty]
        gdf["dataType"] = "ERO"
        
        outlook_col = next((col for col in gdf.columns if col.upper() == "OUTLOOK"), None)
        if outlook_col:
            gdf["OUTLOOK"] = gdf[outlook_col]
            columns_to_keep = ["dataType", "OUTLOOK", "geometry"]
        else:
            columns_to_keep = ["dataType", "geometry"]
            
        gdf = gdf[[col for col in columns_to_keep if col in gdf.columns]]
        return gdf
    except Exception as e:
        print(f"Failed to fetch ERO from REST API: {e}")
        return None

def fetch_and_process_mpds():
    print("Fetching active MPDs from WPC FTP...")
    try:
        # 1. Scrape the reliable KML directory to find exactly what numbers are active
        kml_url = f"https://www.wpc.ncep.noaa.gov/kml/mpd/?t={int(time.time())}"
        try:
            kml_resp = requests.get(kml_url, headers=NO_CACHE_HEADERS)
            active_kml_nums = re.findall(r'mpd(\d{3,4})\.kml', kml_resp.text, re.IGNORECASE)
            active_kml_nums = [int(n) for n in set(active_kml_nums)]
        except:
            active_kml_nums = []

        # 2. Get zip filenames from the FTP HTML directory (which might be cached)
        cache_bust_url = f"{MPD_FTP_URL}?t={int(time.time())}"
        response = requests.get(cache_bust_url, headers=NO_CACHE_HEADERS)
        
        raw_links = re.findall(r'href="([^"]*mpd[^"]*\.zip)"', response.text, re.IGNORECASE)
        if not raw_links: return None
            
        zip_files = [link.split('/')[-1] for link in raw_links]
        
        def extract_mpd_num(filename):
            match = re.search(r'\d{3,4}', filename)
            return int(match.group()) if match else 0
            
        zip_files = sorted(list(set(zip_files)), key=extract_mpd_num)
        
        # 3. KML SYNC: If the KML directory shows a new MPD that the FTP cache missed, add it!
        if zip_files and active_kml_nums:
            ftp_max_num = extract_mpd_num(zip_files[-1])
            kml_max_num = max(active_kml_nums)
            
            if kml_max_num > ftp_max_num:
                latest_format = zip_files[-1]
                match = re.search(r'\d{3,4}', latest_format)
                if match:
                    num_length = len(match.group())
                    for missing_num in range(ftp_max_num + 1, kml_max_num + 1):
                        if missing_num in active_kml_nums:
                            probe_filename = re.sub(r'\d{3,4}', str(missing_num).zfill(num_length), latest_format)
                            zip_files.append(probe_filename)
                            print(f"KML Sync: Bypassed FTP Cache to add missing MPD -> {probe_filename}")

        # 4. SAFE LOOK-AHEAD PROBE: Guess the next 2 numbers just in case everything is cached
        now = datetime.now(timezone.utc)
        
        if zip_files:
            max_num = extract_mpd_num(zip_files[-1])
            latest_format = zip_files[-1]
            match = re.search(r'\d{3,4}', latest_format)
            
            if match:
                num_length = len(match.group())
                for offset in range(1, 3):
                    probe_num = max_num + offset
                    probe_filename = re.sub(r'\d{3,4}', str(probe_num).zfill(num_length), latest_format)
                    probe_url = f"{MPD_FTP_URL}{probe_filename}?t={int(time.time())}"
                    
                    head_resp = requests.head(probe_url, headers=NO_CACHE_HEADERS)
                    if head_resp.status_code == 200:
                        last_mod = head_resp.headers.get("Last-Modified")
                        if last_mod:
                            file_time = parsedate_to_datetime(last_mod)
                            # CRITICAL: Only accept if the file was generated in the last 24 hours (prevents old files)
                            if (now - file_time).total_seconds() < 86400:
                                print(f"Proactive Cache Bypass: Found NEW active MPD -> {probe_filename}")
                                zip_files.append(probe_filename)
        
        zip_files = sorted(list(set(zip_files)), key=extract_mpd_num)
        recent_zips = zip_files[-15:]
        
        mpd_gdfs = []
        
        for zip_filename in recent_zips:
            zip_url = f"{MPD_FTP_URL}{zip_filename}"
            print(f"Checking MPD: {zip_filename}")
            
            z_resp = requests.get(zip_url, headers=NO_CACHE_HEADERS)
            if z_resp.status_code == 200:
                tmp_dir = f"/tmp/mpd_{zip_filename}"
                os.makedirs(tmp_dir, exist_ok=True)
                
                with zipfile.ZipFile(io.BytesIO(z_resp.content)) as z:
                    z.extractall(tmp_dir)
                    
                shp_files = [f for f in os.listdir(tmp_dir) if f.endswith(".shp")]
                if shp_files:
                    shp_path = os.path.join(tmp_dir, shp_files[0])
                    gdf = gpd.read_file(shp_path)
                    
                    # Safely map columns to uppercase to find expiration without ruining the original metadata for the frontend
                    col_map = {c.strip().upper(): c for c in gdf.columns}
                    expire_col = next((col_map[c] for c in ["EXPIRE", "EXPIRATION", "END_TIME"] if c in col_map), None)
                    
                    if expire_col:
                        def parse_wpc_time(t):
                            t_str = str(t).strip().split('.')[0]
                            try:
                                if len(t_str) == 10: return datetime.strptime(t_str, "%y%m%d%H%M").replace(tzinfo=timezone.utc)
                                if len(t_str) == 12: return datetime.strptime(t_str, "%Y%m%d%H%M").replace(tzinfo=timezone.utc)
                                parsed = pd.to_datetime(t_str)
                                return parsed.tz_localize('UTC') if parsed.tzinfo is None else parsed.tz_convert('UTC')
                            except: pass
                            return pd.NaT

                        gdf["expire_dt"] = gdf[expire_col].apply(parse_wpc_time)
                        # Keep polygon if it is mathematically active OR if time parsing fails (safe fallback to prevent false drops)
                        gdf = gdf[(gdf["expire_dt"] > now) | (gdf["expire_dt"].isna())]
                        
                        if gdf.empty:
                            print(f"  -> MPD {zip_filename} Expired. Dropping.")
                            continue
                            
                    print(f"  -> MPD {zip_filename} Active! Adding to dashboard.")
                    gdf = gdf.to_crs("EPSG:4326")
                    gdf["dataType"] = "MPD"
                    
                    gdf = gdf.drop(columns=["expire_dt"], errors="ignore")
                    mpd_gdfs.append(gdf)
                                
        if mpd_gdfs:
            return pd.concat(mpd_gdfs, ignore_index=True)
            
    except Exception as e:
        print(f"Failed to fetch MPDs: {e}")
        
    return None

def main():
    print("Starting WPC data processing...")
    final_gdfs = []
    
    ero_gdf = fetch_and_process_ero()
    if ero_gdf is not None and not ero_gdf.empty: final_gdfs.append(ero_gdf)
        
    mpd_gdf = fetch_and_process_mpds()
    if mpd_gdf is not None and not mpd_gdf.empty: final_gdfs.append(mpd_gdf)
        
    if final_gdfs:
        combined_gdf = pd.concat(final_gdfs, ignore_index=True)
        combined_gdf.to_file(OUTPUT_FILENAME, driver="GeoJSON")
        print(f"Successfully wrote {OUTPUT_FILENAME} with {len(combined_gdf)} features.")
    else:
        print("No valid data processed. GeoJSON not updated.")

if __name__ == "__main__":
    main()
