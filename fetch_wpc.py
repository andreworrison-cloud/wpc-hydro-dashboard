import geopandas as gpd
import pandas as pd
import requests
import zipfile
import io
import os
import time
from datetime import datetime, timezone, timedelta

# ERO points to the live NOAA Enterprise GIS database
ERO_REST_URL = "https://mapservices.weather.noaa.gov/vector/rest/services/hazards/wpc_precip_hazards/MapServer/0/query"
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
    print("Fetching active MPDs directly from Iowa Environmental Mesonet (IEM)...")
    try:
        now = datetime.now(timezone.utc)
        # Safely pull the last 24 hours of MPD issuances from IEM
        start = now - timedelta(hours=24)
        
        sts = start.strftime('%Y-%m-%dT%H:%M:%SZ')
        ets = now.strftime('%Y-%m-%dT%H:%M:%SZ')
        
        # Ask IEM's dynamic GIS generator for the MPD shapefiles
        iem_url = f"https://mesonet.agron.iastate.edu/cgi-bin/request/gis/wpc_mpd.py?sts={sts}&ets={ets}"
        print(f"Calling IEM API: {iem_url}")
        
        response = requests.get(iem_url, headers=NO_CACHE_HEADERS)
        response.raise_for_status()
        
        # If no MPDs were issued, IEM returns an HTML message instead of a zip file
        if 'application/zip' not in response.headers.get('content-type', ''):
            print("IEM API did not return a zip file. No MPDs currently active.")
            return None
            
        tmp_dir = "/tmp/iem_mpds"
        os.makedirs(tmp_dir, exist_ok=True)
        
        with zipfile.ZipFile(io.BytesIO(response.content)) as z:
            z.extractall(tmp_dir)
            
        shp_files = [f for f in os.listdir(tmp_dir) if f.endswith(".shp")]
        if not shp_files: return None
            
        shp_path = os.path.join(tmp_dir, shp_files[0])
        gdf = gpd.read_file(shp_path)
        
        if gdf.empty: return None
            
        gdf.columns = gdf.columns.str.upper()
        
        if "EXPIRE" in gdf.columns:
            # IEM parses times brilliantly into a standard format
            gdf["expire_dt"] = pd.to_datetime(gdf["EXPIRE"], errors="coerce", utc=True)
            
            # STRICT MATHEMATICAL FILTER: Only keep MPDs expiring in the future!
            gdf = gdf[gdf["expire_dt"] > now]
            
            if gdf.empty:
                print("All recent MPDs from IEM have expired. Dropping from dashboard.")
                return None
                
            print(f"Found {len(gdf)} ACTIVE MPD(s)! Formatting for dashboard.")
            gdf = gdf.to_crs("EPSG:4326")
            gdf["dataType"] = "MPD"
            
            # Format times back to the WPC string format (YYMMDDHHMM) that your app.js already expects
            def format_wpc_string(dt_val):
                if pd.isna(dt_val): return "Unknown"
                try:
                    dt = pd.to_datetime(dt_val)
                    return dt.strftime("%y%m%d%H%M")
                except:
                    return str(dt_val)
                    
            if "ISSUE" in gdf.columns:
                gdf["ISSUE"] = gdf["ISSUE"].apply(format_wpc_string)
            if "EXPIRE" in gdf.columns:
                gdf["EXPIRE"] = gdf["EXPIRE"].apply(format_wpc_string)
            
            # Strip the datetime object before converting to JSON to prevent crashes
            gdf = gdf.drop(columns=["expire_dt"], errors="ignore")
            return gdf
        else:
            print("Warning: EXPIRE column not found in IEM dataset.")
            return None
            
    except Exception as e:
        print(f"Failed to fetch MPDs from IEM: {e}")
        
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
