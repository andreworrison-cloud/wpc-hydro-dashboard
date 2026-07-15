import os
import json
import requests
import xarray as xr
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap, BoundaryNorm
from datetime import datetime, timedelta

# --- 1. CONFIGURATION ---
NWM_FILE = "nwm_temp.nc"
OUTPUT_PNG = "static/nwm_soil_saturation.png"
OUTPUT_JSON = "static/nwm_metadata.json"
BOUNDS = [[21.0, -130.0], [55.0, -65.0]] # Approximate NWM CONUS bounds

# User-Agent required to bypass NCEP NOMADS security blocks
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) WPC-Hydro-Dashboard'
}

# --- 2. BULLETPROOF DOWNLOAD LOOP ---
found_data = False
target_time = None

# Scan backwards from 1 to 6 hours ago to find the latest hourly run
for hour_lag in range(1, 7):
    target_time = datetime.utcnow() - timedelta(hours=hour_lag)
    date_str = target_time.strftime('%Y%m%d')
    hour_str = target_time.strftime('%H')
    
    # NWM Analysis & Assimilation CONUS Land output
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
    print("CRITICAL: Could not find any recent NWM data within the last 6 hours.")
    exit(1)

# --- 3. PROCESS NETCDF WITH XARRAY ---
try:
    print("Processing NWM NetCDF file...")
    ds = xr.open_dataset(NWM_FILE, engine='h5netcdf')
    
    # Extract Fraction of Soil Saturation (Top 2 layers, approx 0-40cm)
    # Convert from fraction (0-1) to percentage (0-100)
    soil_sat = ds['SOILSAT_TOP'].values[0, :, :] * 100.0
        
except Exception as e:
    print(f"Failed to process NWM file: {e}")
    if os.path.exists(NWM_FILE):
        os.remove(NWM_FILE)
    exit(1)

# --- 4. RENDER TO TRANSPARENT PNG ---
print("Rendering NWM Soil Saturation PNG...")
fig = plt.figure(figsize=(16, 10), dpi=150)
ax = plt.Axes(fig, [0., 0., 1., 1.])
ax.set_axis_off()
fig.add_axes(ax)

# Operational Color Scale: 0-40, 40-60, 60-70, 70-80, 80-90, 90-95, 95-100
colors = ["#d2b48c", "#e0eee0", "#90ee90", "#3cb371", "#00ced1", "#1e90ff", "#00008b"]
bounds = [0, 40, 60, 70, 80, 90, 95, 100]
cmap = ListedColormap(colors)
norm = BoundaryNorm(bounds, cmap.N)

# Mask out missing/ocean data 
masked_data = np.ma.masked_where((soil_sat < 0) | np.isnan(soil_sat), soil_sat)

# Flip the array vertically so it renders right-side up in Leaflet
masked_data = np.flipud(masked_data)

c = ax.pcolormesh(masked_data, cmap=cmap, norm=norm, shading='auto')

os.makedirs('static', exist_ok=True)
plt.savefig(OUTPUT_PNG, transparent=True, format='png', bbox_inches='tight', pad_inches=0)
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

print("NWM Real-Time data successfully processed and exported!")
