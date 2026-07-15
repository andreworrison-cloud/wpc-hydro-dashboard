import os
import json
import requests
import xarray as xr
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap, BoundaryNorm
from datetime import datetime, timedelta

# --- 1. CONFIGURATION ---
SPORT_FILE = "sport_temp.nc"
OUTPUT_PNG = "static/sport_soil_percentile.png"
OUTPUT_JSON = "static/sport_metadata.json"
BOUNDS = [[24.0, -125.0], [50.0, -66.0]] # Approximate SPoRT CONUS bounds

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) WPC-Hydro-Dashboard'
}

# --- 2. BULLETPROOF DOWNLOAD LOOP ---
found_data = False
target_time = None

# SPoRT runs every 6 hours (00Z, 06Z, 12Z, 18Z). 
# Scan backwards up to 24 hours to find the latest available cycle.
for lag in range(1, 25):
    target_time = datetime.utcnow() - timedelta(hours=lag)
    
    # Only check valid cycle hours
    if target_time.hour not in [0, 6, 12, 18]:
        continue
        
    date_str = target_time.strftime('%Y%m%d')
    hour_str = target_time.strftime('%H')
    
    # Standard SPoRT-LIS NetCDF output structure
    url = f"https://weather.msfc.nasa.gov/pub/sport/lis/conus_hrrr/{date_str}/LIS_HIST_{date_str}{hour_str}00.d01.nc"
    
    print(f"Checking NASA SPoRT for: {date_str} {hour_str}Z...")
    
    try:
        response = requests.get(url, headers=HEADERS, timeout=20)
        if response.status_code == 200:
            print("Success! SPoRT data found. Downloading...")
            with open(SPORT_FILE, 'wb') as f:
                f.write(response.content)
            found_data = True
            break
        else:
            print(f" -> Not yet available (HTTP {response.status_code}).")
    except requests.RequestException as e:
        print(f" -> Connection error: {e}")

if not found_data:
    print("CRITICAL: Could not find any recent SPoRT-LIS data within the last 24 hours.")
    exit(1)

# --- 3. PROCESS NETCDF WITH XARRAY ---
try:
    print("Processing SPoRT-LIS NetCDF file...")
    ds = xr.open_dataset(SPORT_FILE, engine='h5netcdf')
    
    # Extract the 0-100cm Soil Moisture Percentile
    # Variable name varies slightly by SPoRT version, commonly 'SoilMoist_Prcntile' or 'smc_prcntile'
    var_name = 'smc_prcntile' if 'smc_prcntile' in ds.data_vars else list(ds.data_vars)[0]
    percentile = ds[var_name].values[0, :, :] 
        
except Exception as e:
    print(f"Failed to process SPoRT file: {e}")
    if os.path.exists(SPORT_FILE):
        os.remove(SPORT_FILE)
    exit(1)

# --- 4. RENDER TO TRANSPARENT PNG ---
print("Rendering SPoRT Soil Percentile PNG...")
fig = plt.figure(figsize=(16, 10), dpi=150)
ax = plt.Axes(fig, [0., 0., 1., 1.])
ax.set_axis_off()
fig.add_axes(ax)

# Operational breaks: <70 (Transparent), 70-80, 80-90, 90-95, 95-98, >98
# Colors: Transparent -> Yellow -> Gold -> Orange -> Red -> Purple
colors = ["#ffffff00", "#ffff00", "#ffcc00", "#ff6600", "#ff0000", "#cc00cc"]
bounds = [0, 70, 80, 90, 95, 98, 100]
cmap = ListedColormap(colors)
norm = BoundaryNorm(bounds, cmap.N)

# Mask out missing/ocean data
masked_data = np.ma.masked_where((percentile < 0) | np.isnan(percentile), percentile)

# Flip the array vertically so it renders right-side up in Leaflet
masked_data = np.flipud(masked_data)

c = ax.pcolormesh(masked_data, cmap=cmap, norm=norm, shading='auto')

os.makedirs('static', exist_ok=True)
plt.savefig(OUTPUT_PNG, transparent=True, format='png', bbox_inches='tight', pad_inches=0)
plt.close(fig)

# --- 5. EXPORT METADATA ---
metadata = {
    "valid_time": f"SPoRT-LIS: {target_time.strftime('%b %d, %Y %H')}Z",
    "bounds": BOUNDS
}

with open(OUTPUT_JSON, 'w') as f:
    json.dump(metadata, f)

if os.path.exists(SPORT_FILE):
    os.remove(SPORT_FILE)

print("SPoRT-LIS Real-Time data successfully processed and exported!")
