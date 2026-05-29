import geopandas as gpd
import pandas as pd
import requests
import zipfile
import io
import os
import re
import time
from datetime import datetime, timezone

ERO_DAY1_ZIP_URL = "https://www.wpc.ncep.noaa.gov/qpf/ero_day1.zip"
MPD_FTP_URL = "https://ftp-wpc.ncep.noaa.gov/shapefiles/qpf/mpd/"
OUTPUT_FILENAME = "wpc_data.geojson"

# Aggressive headers to force NOAA's Akamai CDN to bypass cache
NO_CACHE_HEADERS = {
    "Cache-Control": "no-cache, no-store, must-revalidate",
    "Pragma": "no-cache",
    "Expires": "0",
    "User-Agent": "WPC-Hydro-Dashboard-Bot/1.0"
}

def fetch_and_process_ero():
    print("Fetching absolute latest WPC Day 1 ERO directly from WPC ZIP...")
    try:
        cache_bust_url = f"{ERO_DAY1_ZIP_URL}?t={int(time.time())}"
        response = requests.get(cache_bust_url, headers=NO_CACHE_HEADERS)
        response.raise_for_status()
        
        tmp_dir = "/tmp/ero_shapefile"
        os.makedirs(tmp_dir, exist_ok=True)
        
        with zipfile.ZipFile(io.BytesIO(response.content)) as z:
            z.extractall(tmp_dir)
            
        shp_files = [f for f in os.listdir(tmp_dir) if f.endswith(".shp")]
        if not shp_files:
            return None
            
        shp_path = os.path.join(tmp_dir, shp_files[0])
        gdf = gpd.read_file(shp_path)
        
        if gdf.empty or gdf.geometry.is_empty.all():
            return None
            
        gdf = gdf.to_crs("EPSG:4326")
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
        print(f"Failed to fetch ERO from ZIP: {e}")
        return None

def fetch_and_process_mpds():
    print("Fetching active MPDs from WPC FTP...")
    try:
        response = requests.get(MPD_FTP_URL, headers=NO_CACHE_HEADERS)
        response.raise_for_status()
        
        zip_files = re.findall(r'href="([^"]+\.zip)"', response.text)
        if not zip_files: return None
            
        zip_files = sorted(list(set(zip_files)))
        recent_zips = zip_files[-10:]
        
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
                    
                    gdf.columns = gdf.columns.str.upper()
                    expire_col = next((col for col in ["EXPIRE", "EXPIRATION", "END_TIME"] if col in gdf.columns), None)
                    
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
                            print("  -> MPD Expired. Dropping from dashboard.")
                            continue
                            
                    print("  -> MPD Active! Adding to dashboard.")
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
