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

nwm_crs = ccrs.LambertConformal(
    central_longitude=-97.0, 
    central_latitude=40.0, 
    standard_parallels=(30.0, 60.0), 
    globe=ccrs.Globe(semimajor_axis=6370000, semiminor_axis=6370000)
)
plate_carree = ccrs.PlateCarree()

# Calculate precise bounding box of the data array
x_extents = (x.min(), x.max())
y_extents = (y.min(), y.max())
transformed_extents = plate_carree.transform_points(nwm_crs, np.array(x_extents), np.array(y_extents))
lon_min, lon_max = transformed_extents[:, 0].min(), transformed_extents[:, 0].max()
lat_min, lat_max = transformed_extents[:, 1].min(), transformed_extents[:, 1].max()

# Export exact bounds for Leaflet: [[south, west], [north, east]]
exact_bounds = [[float(lat_min), float(lon_min)], [float(lat_max), float(lon_max)]]

# THE FIX: Match the figure aspect ratio EXACTLY to the geographic extent to eliminate all padding
width_deg = lon_max - lon_min
height_deg = lat_max - lat_min
aspect_ratio = width_deg / height_deg

# Dynamically size the figure so no whitespace is generated
fig = plt.figure(figsize=(10 * aspect_ratio, 10), dpi=150)
ax = plt.axes(projection=plate_carree)
ax.set_axis_off()

colors = ["#d2b48c", "#e0eee0", "#90ee90", "#3cb371", "#00ced1", "#1e90ff", "#00008b"]
bounds = [0, 40, 60, 70, 80, 90, 95, 100]
cmap = ListedColormap(colors)
norm = BoundaryNorm(bounds, cmap.N)

masked_data = np.ma.masked_where((soil_sat < 0) | np.isnan(soil_sat), soil_sat)

c = ax.pcolormesh(x, y, masked_data, transform=nwm_crs, cmap=cmap, norm=norm, shading='auto')

ax.set_extent([lon_min, lon_max, lat_min, lat_max], crs=plate_carree)
fig.subplots_adjust(left=0, right=1, bottom=0, top=1)

os.makedirs('static', exist_ok=True)
plt.savefig(OUTPUT_PNG, transparent=True, format='png', pad_inches=0)
plt.close(fig)

# --- 5. EXPORT METADATA ---
metadata = {
    "valid_time": f"NWM Saturation: {target_time.strftime('%b %d, %Y %H')}Z",
    "bounds": exact_bounds
}

with open(OUTPUT_JSON, 'w') as f:
    json.dump(metadata, f)

if os.path.exists(NWM_FILE):
    os.remove(NWM_FILE)

print("NWM Real-Time data successfully reprojected and exported!")
