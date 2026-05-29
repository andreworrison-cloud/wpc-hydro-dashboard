import geopandas as gpd
import pandas as pd
import requests
import zipfile
import io
import os
import re
import time
from datetime import datetime, timezone

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
    print("Fetching WPC Day 1 ERO...")
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
        print(f"Failed to fetch ERO: {e}")
        return None

def fetch_and_process_mpds():
    print("Fetching active MPDs...")
    try:
        cache_bust_url = f"{MPD_FTP_URL}?t={int(time.time())}"
        response = requests.get(cache_bust_url, headers=NO_CACHE_HEADERS)
        
        raw_links = re.findall(r'href="([^"]*mpd[^"]*\.zip)"', response.text, re.IGNORECASE)
        if not raw_links: return None
            
        zip_files = [link.split('/')[-1] for link in raw_links]
        
        def extract_mpd_num(filename):
            match = re.search(r'\d{3,4}', filename)
            return int(match.group()) if match else 0
            
        # Limit to the most recent 15 files to prevent guessing dates on ancient archives
        zip_files = sorted(list(set(zip_files)), key=extract_mpd_num)
        recent_zips = zip_files[-15:]
        
        now = datetime.now(timezone.utc)
        mpd_gdfs = []
        
        for zip_filename in recent_zips:
            zip_url = f"{MPD_FTP_URL}{zip_filename}"
            print(f"\nChecking MPD: {zip_filename}")
            
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
                    
                    # Force columns to UPPERCASE to preserve original tags while making time searching easy
                    gdf.columns = gdf.columns.str.upper()
                    
                    # Extremely broad search for any expiration column
                    expire_col = None
                    for c in gdf.columns:
                        if "EXP" in c or "END" in c or "UNTIL" in c or "VALID_TO" in c:
                            expire_col = c
                            break
                            
                    if not expire_col:
                        print(f"  -> No expiration column found. Dropping.")
                        continue
                        
                    # Extremely robust time parser
                    def parse_wpc_time(t):
                        t_str = str(t).strip().split('.')[0]
                        digits = re.sub(r"\D", "", t_str)
                        try:
                            if len(digits) == 10: return datetime.strptime(digits, "%y%m%d%H%M").replace(tzinfo=timezone.utc)
                            if len(digits) == 12: return datetime.strptime(digits, "%Y%m%d%H%M").replace(tzinfo=timezone.utc)
                            if len(digits) == 14: return datetime.strptime(digits, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
                            parsed = pd.to_datetime(t_str, utc=True)
                            return parsed.to_pydatetime()
                        except: pass
                        return pd.NaT

                    gdf["expire_dt"] = gdf[expire_col].apply(parse_wpc_time)
                    
                    # STRICT MATHEMATICAL FILTER
                    active_gdf = gdf[gdf["expire_dt"] > now].copy()
                    
                    if active_gdf.empty:
                        print(f"  -> MPD Expired. Dropping.")
                        continue
                        
                    print(f"  -> MPD ACTIVE! Keeping for dashboard.")
                    active_gdf = active_gdf.to_crs("EPSG:4326")
                    active_gdf["dataType"] = "MPD"
                    
                    # Drop datetime objects before writing to GeoJSON
                    active_gdf = active_gdf.drop(columns=["expire_dt"], errors="ignore")
                    mpd_gdfs.append(active_gdf)
                                
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
        # Ensure dates are saved properly to prevent GeoJSON crash
        for col in combined_gdf.columns:
            if col != "geometry" and pd.api.types.is_datetime64_any_dtype(combined_gdf[col]):
                combined_gdf[col] = combined_gdf[col].astype(str)
                
        combined_gdf.to_file(OUTPUT_FILENAME, driver="GeoJSON")
        print(f"Successfully wrote {OUTPUT_FILENAME}")
    else:
        print("No valid data processed. GeoJSON not updated.")

if __name__ == "__main__":
    main()
