import geopandas as gpd
import pandas as pd
import requests
import zipfile
import io
import os
import re
from datetime import datetime, timezone

ERO_DAY1_URL = "https://mapservices.weather.noaa.gov/vector/rest/services/hazards/wpc_precip_hazards/MapServer/0/query?where=1=1&outFields=OUTLOOK&f=geojson"
MPD_FTP_URL = "https://ftp-wpc.ncep.noaa.gov/shapefiles/qpf/mpd/"
OUTPUT_FILENAME = "wpc_data.geojson"

def fetch_and_process_ero():
    print("Fetching WPC Day 1 ERO...")
    try:
        response = requests.get(ERO_DAY1_URL)
        response.raise_for_status()
        gdf = gpd.read_file(response.text, driver="GeoJSON")
        
        if gdf.empty or gdf.geometry.is_empty.all():
            return None
            
        gdf = gdf[~gdf.geometry.is_empty]
        gdf["dataType"] = "ERO"
        return gdf
    except Exception as e:
        print(f"Failed to fetch ERO: {e}")
        return None

def fetch_and_process_mpds():
    print("Fetching active MPDs from WPC FTP...")
    try:
        response = requests.get(MPD_FTP_URL)
        response.raise_for_status()
        
        zip_files = re.findall(r'href="([^"]+\.zip)"', response.text)
        if not zip_files: return None
            
        zip_files = sorted(list(set(zip_files)))
        recent_zips = zip_files[-10:] # Only check the 10 most recent to save bandwidth
        
        now = datetime.now(timezone.utc)
        mpd_gdfs = []
        
        for zip_filename in recent_zips:
            zip_url = f"{MPD_FTP_URL}{zip_filename}"
            print(f"Checking MPD: {zip_filename}")
            
            z_resp = requests.get(zip_url)
            if z_resp.status_code == 200:
                tmp_dir = f"/tmp/mpd_{zip_filename}"
                with zipfile.ZipFile(io.BytesIO(z_resp.content)) as z:
                    z.extractall(tmp_dir)
                    
                shp_files = [f for f in os.listdir(tmp_dir) if f.endswith(".shp")]
                if shp_files:
                    shp_path = os.path.join(tmp_dir, shp_files[0])
                    gdf = gpd.read_file(shp_path)
                    
                    # Capitalize columns to easily find EXPIRE
                    gdf.columns = gdf.columns.str.upper()
                    
                    # Dynamically find the expiration column
                    expire_col = next((col for col in ["EXPIRE", "EXPIRATION", "END_TIME"] if col in gdf.columns), None)
                    
                    if expire_col:
                        # WPC time parser for YYMMDDHHMM or YYYYMMDDHHMM formats
                        def parse_wpc_time(t):
                            t_str = str(t).strip().split('.')[0]
                            try:
                                if len(t_str) == 10: return datetime.strptime(t_str, "%y%m%d%H%M").replace(tzinfo=timezone.utc)
                                if len(t_str) == 12: return datetime.strptime(t_str, "%Y%m%d%H%M").replace(tzinfo=timezone.utc)
                            except: pass
                            return pd.NaT

                        gdf["expire_dt"] = gdf[expire_col].apply(parse_wpc_time)
                        
                        # Filter out polygons mathematically
                        gdf = gdf[gdf["expire_dt"] > now]
                        
                        if gdf.empty:
                            print("  -> MPD Expired. Dropping from dashboard.")
                            continue
                            
                    print("  -> MPD Active! Adding to dashboard.")
                    gdf = gdf.to_crs("EPSG:4326")
                    gdf["dataType"] = "MPD"
                    
                    # We keep all metadata columns for the frontend popup, but drop the datetime object to avoid JSON crashes
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
