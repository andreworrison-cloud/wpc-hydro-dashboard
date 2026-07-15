import os
import json
import requests
import xarray as xr
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap, BoundaryNorm
import cartopy.crs as ccrs
from datetime import datetime, timedelta

# --- 1. CONFIGURATION ---
NWM_FILE = "nwm_temp.nc"
OUTPUT_PNG = "static/nwm_soil_saturation.png"
OUTPUT_JSON = "static/nwm_metadata.json"
# Exact Leaflet Bounds
BOUNDS = [[21.0, -130.0], [55.0, -65.0]] 

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) WPC-Hydro-Dashboard'
}

# --- 2. BULLETPROOF DOWNLOAD LOOP ---
found_data = False
target_time = None

for hour_lag in range(1, 7):
    target_time = datetime.utcnow() - timedelta(hours=hour_lag)
    date_str = target_time.strftime('%Y%m%d')
    hour_str = target_time.strftime('%H')
    
    url = f"https://nomads.ncep.noaa.gov/pub/data/nccf/com/nwm/prod/nwm.{date_str}/analysis_assim/nwm.t{hour_str}z.analysis_assim.land.tm00.conus.nc"
    print(f"Checking NOAA NWM for: {date_str} {hour_str}Z...")
    
    try:
        response = requests.get(url, headers=HEADERS, timeout=20)
        if response.status_code == 200:
            print("Success! Live NWM data found. Downloading...")
            with open(NWM_FILE, 'wb') as f:
                f.write(response.content)
            found_data = True
            break
        else:
            print(f" -> Not yet available (HTTP {response.status_code}).")
    except requests.RequestException as e:
        print(f" -> Connection error: {e}")

if not found_data:
    print("CRITICAL: Could not find any recent NWM data.")
    exit(1)

# --- 3. PROCESS NETCDF WITH XARRAY ---
try:
    print("Processing NWM NetCDF file...")
    ds = xr.open_dataset(NWM_FILE, engine='h5netcdf')
    
    soil_sat = ds['SOILSAT_TOP'].values[0, :, :] * 100.0
    x = ds.x.values
    y = ds.y.values
        
except Exception as e:
    print(f"Failed to process NWM file: {e}")
    if os.path.exists(NWM_FILE):
        os.remove(NWM_FILE)
    exit(1)

# --- 4. RENDER TO TRANSPARENT PNG WITH CARTOPY ---
print("Reprojecting and Rendering NWM Soil Saturation PNG...")

# Define the native NWM Lambert Conformal projection
nwm_crs = ccrs.LambertConformal(
    central_longitude=-97.0, 
    central_latitude=40.0, 
    standard_parallels=(30.0, 60.0), 
    globe=ccrs.Globe(semimajor_axis=6370000, semiminor_axis=6370000)
)

fig = plt.figure(figsize=(16, 10), dpi=150)
# Create a flat Plate Carrée axes so Leaflet can overlay it properly
ax = plt.axes(projection=ccrs.PlateCarree())
ax.set_axis_off()

colors = ["#d2b48c", "#e0eee0", "#90ee90", "#3cb371", "#00ced1", "#1e90ff", "#00008b"]
bounds = [0, 40, 60, 70, 80, 90, 95, 100]
cmap = ListedColormap(colors)
norm = BoundaryNorm(bounds, cmap.N)

masked_data = np.ma.masked_where((soil_sat < 0) | np.isnan(soil_sat), soil_sat)

# Map the data using Cartopy to physically un-warp the projection
c = ax.pcolormesh(x, y, masked_data, transform=nwm_crs, cmap=cmap, norm=norm, shading='auto')

# Force the final image edges to lock EXACTLY to our Leaflet bounds
ax.set_extent([-130.0, -65.0, 21.0, 55.0], crs=ccrs.PlateCarree())

# Remove all whitespace so the image dimensions match the coordinate box
fig.subplots_adjust(left=0, right=1, bottom=0, top=1)

os.makedirs('static', exist_ok=True)
plt.savefig(OUTPUT_PNG, transparent=True, format='png', pad_inches=0)
plt.close(fig)

# --- 5. EXPORT METADATA ---
metadata = {
    "valid_time": f"NWM Saturation: {target_time.strftime('%b %d, %Y %H')}Z",
    "bounds": BOUNDS
}

with open(OUTPUT_JSON, 'w') as f:
    json.dump(metadata, f)

if os.path.exists(NWM_FILE):
    os.remove(NWM_FILE)

print("NWM Real-Time data successfully reprojected and exported!")
