import os
import json
import requests
import xarray as xr
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap
from datetime import datetime, timedelta

# --- 1. CONFIGURATION ---
GRIB_FILE = "nldas_temp.grb2"
OUTPUT_PNG = "static/nldas_soil_moisture.png"
OUTPUT_JSON = "static/nldas_metadata.json"
BOUNDS = [[25.0, -125.0], [53.0, -67.0]]

# --- 2. BULLETPROOF DOWNLOAD LOOP ---
# NLDAS-2 typically has a 4-day lag. We will scan backwards from 3 to 8 days 
# to guarantee we find the absolute latest available processed run.
found_data = False
target_date = None

for lag in range(3, 9):
    target_date = datetime.utcnow() - timedelta(days=lag)
    date_str = target_date.strftime('%Y%m%d')
    
    # NCEP NOMADS standard URL for the NLDAS-2 Noah LSM (12Z run)
    url = f"https://nomads.ncep.noaa.gov/pub/data/nccf/com/nldas/prod/nldas.{date_str}/nldas.t12z.noah.grb2"
    print(f"Checking NOAA servers for: {date_str} 12Z...")
    
    try:
        response = requests.get(url, timeout=15)
        if response.status_code == 200:
            print("Success! Data found. Downloading...")
            with open(GRIB_FILE, 'wb') as f:
                f.write(response.content)
            found_data = True
            break
        else:
            print(f" -> Not yet available (HTTP {response.status_code}).")
    except requests.RequestException as e:
        print(f" -> Connection error: {e}")

if not found_data:
    print("CRITICAL: Could not find any recent NLDAS-2 data within the last 8 days.")
    exit(1)

# --- 3. PROCESS GRIB2 WITH XARRAY ---
try:
    print("Processing GRIB2 file...")
    # NLDAS-2 Volumetric Soil Moisture is mapped as 'soilw' in cfgrib
    # Using filter_by_keys to isolate the correct depth variable
    ds = xr.open_dataset(GRIB_FILE, engine='cfgrib', backend_kwargs={'filter_by_keys': {'shortName': 'soilw'}})
    
    var_name = 'soilw'
    
    # If the array has a depth dimension, slice the top layer (index 0)
    if len(ds[var_name].dims) >= 3:
        soil_moisture = ds[var_name].values[0, :, :]
    else:
        soil_moisture = ds[var_name].values
        
    lats = ds.latitude.values
    lons = ds.longitude.values
    
    # Convert longitudes from 0..360 to -180..180 for Leaflet mapping
    if lons.max() > 180:
        lons = np.where(lons > 180, lons - 360, lons)
        
except Exception as e:
    print(f"Failed to process GRIB file: {e}")
    if os.path.exists(GRIB_FILE):
        os.remove(GRIB_FILE)
    exit(1)

# --- 4. RENDER TO TRANSPARENT PNG ---
print("Rendering Soil Moisture PNG...")
fig = plt.figure(figsize=(12, 8), dpi=150)
ax = plt.Axes(fig, [0., 0., 1., 1.])
ax.set_axis_off()
fig.add_axes(ax)

# Custom Brown (Dry) -> Light Green -> Dark Blue (Saturated) Colormap
colors = ["#8b5a2b", "#d2b48c", "#e0eee0", "#90ee90", "#3cb371", "#00ced1", "#1e90ff", "#00008b"]
cmap = LinearSegmentedColormap.from_list("NLDAS_Soil", colors, N=256)

masked_data = np.ma.masked_where(soil_moisture < 0, soil_moisture)
c = ax.pcolormesh(lons, lats, masked_data, cmap=cmap, vmin=0.05, vmax=0.45, shading='auto')

os.makedirs('static', exist_ok=True)
plt.savefig(OUTPUT_PNG, transparent=True, format='png', bbox_inches='tight', pad_inches=0)
plt.close(fig)

# --- 5. EXPORT METADATA ---
metadata = {
    "valid_time": f"NLDAS-2: {target_date.strftime('%b %d, %Y')} 12Z",
    "bounds": BOUNDS
}

with open(OUTPUT_JSON, 'w') as f:
    json.dump(metadata, f)

if os.path.exists(GRIB_FILE):
    os.remove(GRIB_FILE)

print("NLDAS-2 successfully processed and exported!")
