import os
import json
import requests
import xarray as xr
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap
from datetime import datetime, timedelta

# --- 1. CONFIGURATION ---
# NOMADS typically holds 2 days of rolling NLDAS-2 data. 
# We target 2 days ago to ensure the file is fully processed and available.
target_date = datetime.utcnow() - timedelta(days=2)
date_str = target_date.strftime('%Y%m%d')

# NCEP NOMADS URL for the NLDAS-2 Noah LSM (Grabbing 12Z forecast hour 00)
URL = f"https://nomads.ncep.noaa.gov/pub/data/nccf/com/nldas/prod/nldas.{date_str}/noah.t12z.grb2f00"
GRIB_FILE = "nldas_temp.grb2"
OUTPUT_PNG = "static/nldas_soil_moisture.png"
OUTPUT_JSON = "static/nldas_metadata.json"

# NLDAS-2 CONUS Bounds
BOUNDS = [[25.0, -125.0], [53.0, -67.0]]

# --- 2. DOWNLOAD GRIB2 FILE ---
print(f"Fetching NLDAS-2 data for {date_str} 12Z...")
try:
    response = requests.get(URL, timeout=30)
    response.raise_for_status()
    with open(GRIB_FILE, 'wb') as f:
        f.write(response.content)
    print("Download successful.")
except Exception as e:
    print(f"Failed to download NLDAS-2 data. URL checked: {URL}")
    print(f"Error: {e}")
    exit(1)

# --- 3. PROCESS GRIB2 WITH XARRAY ---
try:
    # NLDAS-2 Volumetric Soil Moisture is mapped as 'soilw' in cfgrib
    ds = xr.open_dataset(GRIB_FILE, engine='cfgrib', backend_kwargs={'filter_by_keys': {'shortName': 'soilw'}})
    
    # We want the top soil layer (0-10 cm)
    var_name = 'soilw'
    
    # If the array has a depth dimension, slice the top layer (index 0)
    if len(ds[var_name].dims) >= 3:
        soil_moisture = ds[var_name].values[0, :, :]
    else:
        soil_moisture = ds[var_name].values
        
    lats = ds.latitude.values
    lons = ds.longitude.values
    
    # Convert longitudes from 0..360 to -180..180 for Leaflet map mapping
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
