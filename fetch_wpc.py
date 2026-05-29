import geopandas as gpd
import pandas as pd
import requests
import zipfile
import io
import os
import re
import time
from datetime import datetime, timezone

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
        # 1. Scrape the KML directory to find exactly what numbers WPC considers active
        kml_url = f"https://www.wpc.ncep.noaa.gov/kml/mpd/?t={int(time.time())}"
        active_kml_nums = []
        try:
            kml_resp = requests.get(kml_url, headers=NO_CACHE_HEADERS)
            # Find any number associated with an MPD kml file
            for match in re.finditer(r'mpd.*?(\d{3,4}).*?\.kml', kml_resp.text, re.IGNORECASE):
                active_kml_nums.append(int(match.group(1)))
            active_kml_nums = list(set(active_kml_nums))
            print(f"Active MPDs according to WPC KML Directory: {active_kml_nums}")
        except:
            print("Warning: Could not fetch KML directory for sync.")

        # 2. Get zip filenames from the FTP HTML directory
        cache_bust_url = f"{MPD_FTP_URL}?t={int(time.time())}"
        response = requests.get(cache_bust_url, headers=NO_CACHE_HEADERS)
        
        raw_links = re.findall(r'href="([^"]*mpd[^"]*\.zip)"', response.text, re.IGNORECASE)
        if not raw_links: return None
            
        zip_files = [link.split('/')[-1] for link in raw_links]
        
        def extract_mpd_num(filename):
            match = re.search(r'\d{3,4}', filename)
            return int(match.group()) if match else 0
            
        zip_files = sorted(list(set(zip_files)), key=extract_mpd_num)
        recent_zips = zip_files[-15:]
        
        now = datetime.now(timezone.utc)
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
                    
                    # PRINT THE COLUMNS TO THE LOG SO WE CAN SEE WPC's EXACT NAMING SCHEMA
                    print(f"  -> Shapefile Columns found: {list(gdf.columns)}")
                    
                    col_map = {c.strip().upper(): c for c in gdf.columns}
                    
                    # Broadened search for the expiration column
                    expire_col = next((col_map[c] for c in ["EXPIRE", "EXPIRATION", "END_TIME", "END", "EXP", "VALID_TO"] if c in col_map), None)
                    if not expire_col:
                        for c in col_map:
                            if "EXP" in c or "END" in c:
                                expire_col = col_map[c]
                                break
                    
                    mpd_num = extract_mpd_num(zip_filename)
                    
                    if expire_col:
                        def parse_wpc_time(t):
                            t_str = str(t).strip().split('.')[0]
                            try:
                                if len(t_str) == 10: return datetime.strptime(t_str, "%y%m%d%H%M").replace(tzinfo=timezone.utc)
                                if len(t_str) == 12: return datetime.strptime(t_str, "%Y%m%d%H%M").replace(tzinfo=timezone.utc)
                            except: pass
                            return pd.NaT

                        gdf["expire_dt"] = gdf[expire_col].apply(parse_wpc_time)
                        gdf = gdf[gdf["expire_dt"] > now]
                        
                        if gdf.empty:
                            print(f"  -> MPD {zip_filename} mathematically expired. Dropping.")
                            continue
                    else:
                        # KML TRUST FALLBACK: If we can't find the column, check the active KML list!
                        if mpd_num not in active_kml_nums:
                            print(f"  -> No expiration column found AND not on active KML list. Dropping.")
                            continue
                        else:
                            print(f"  -> No expiration column found, BUT it is on the active KML list! Trusting WPC and keeping.")
                        
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
