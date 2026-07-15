import os
import json
import s3fs
import xarray as xr
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap
from datetime import datetime, timedelta

# --- 1. CONFIGURATION & CLOUD PATHS ---
# NLDAS-3 operates with reduced latency compared to NLDAS-2. 
# We target 2 days ago to ensure the data is processed and available.
target_date = datetime.utcnow() - timedelta(days=2)
yyyymm = target_date.strftime('%Y%m')
yyyymmdd = target_date.strftime('%Y%m%d')

# Expected NASA AWS S3 path for NLDAS-3 LSM outputs
# Note: Adjust 'lsm/hourly/' and file prefix based on the final NASA release schema
S3_FILE_URL = f"nasa-waterinsight/NLDAS3/lsm/hourly/{yyyymm}/NLDAS_LSM0010_H.A{yyyymmdd}.030.beta.nc"

OUTPUT_PNG = "static/nldas_soil_moisture.png"
OUTPUT_JSON = "static/nldas_metadata.json"

# NLDAS-3 Domain Bounds (North & Central America)
BOUNDS = [[7.0, -169.0], [72.0, -52.0]]

# --- 2. VIRTUAL S3 CONNECTION & DATA EXTRACTION ---
print(f"Connecting to AWS S3 for NLDAS-3 data: {yyyymmdd}...")
try:
    fs = s3fs.S3FileSystem(anon=True) # Anonymous read access
    
    # Open the NetCDF file directly from the cloud without downloading the whole file
    with fs.open(S3_FILE_URL) as f:
        # Load exactly what we need using xarray
        ds = xr.open_dataset(f, engine='h5netcdf')
        
        # NLDAS-3 Noah-MP top layer soil moisture is expected as 'SoilMoist_tavg' or similar
        var_name = 'SoilMoist_tavg' if 'SoilMoist_tavg' in ds.data_vars else list(ds.data_vars)[0]
        
        # Extract the 0-10cm top layer slice and load it into numpy
        # Assuming the first depth index (0) is the surface layer
        soil_moisture = ds[var_name].isel(depth=0).values 
        
        lats = ds.lat.values
        lons = ds.lon.values
        
        print("Successfully extracted 1-km soil moisture array from the cloud.")
        
except Exception as e:
    print(f"Failed to fetch or read NLDAS-3 data from AWS: {e}")
    exit(1)

# --- 3. RENDER TO TRANSPARENT PNG ---
print("Rendering High-Resolution Soil Moisture PNG...")
fig = plt.figure(figsize=(16, 12), dpi=200) # Higher DPI for the 1-km resolution
ax = plt.Axes(fig, [0., 0., 1., 1.])
ax.set_axis_off()
fig.add_axes(ax)

# Create a custom Brown (Dry) -> Light Green -> Dark Blue (Saturated) Colormap
colors = ["#8b5a2b", "#d2b48c", "#e0eee0", "#90ee90", "#3cb371", "#00ced1", "#1e90ff", "#00008b"]
cmap = LinearSegmentedColormap.from_list("NLDAS3_Soil", colors, N=256)

# Mask out missing data, oceans, and invalid points
masked_data = np.ma.masked_where((soil_moisture < 0) | np.isnan(soil_moisture), soil_moisture)

# Plot the 1-km data array
c = ax.pcolormesh(lons, lats, masked_data, cmap=cmap, vmin=0.05, vmax=0.45, shading='auto')

# Save as transparent PNG
os.makedirs('static', exist_ok=True)
plt.savefig(OUTPUT_PNG, transparent=True, format='png', bbox_inches='tight', pad_inches=0)
plt.close(fig)

# --- 4. EXPORT METADATA FOR APP.JS ---
metadata = {
    "valid_time": f"NLDAS-3: {target_date.strftime('%b %d, %Y')}",
    "bounds": BOUNDS
}

with open(OUTPUT_JSON, 'w') as f:
    json.dump(metadata, f)

print("NLDAS-3 successfully processed and exported!")
