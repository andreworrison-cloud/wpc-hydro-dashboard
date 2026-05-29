import geopandas as gpd
import pandas as pd
import requests
import zipfile
import io
import os

# Define WPC Data URLs
ERO_DAY1_URL = "https://www.wpc.ncep.noaa.gov/qpf/ero_day1.zip"
OUTPUT_FILENAME = "wpc_data.geojson"

def fetch_and_process_ero():
    """
    Fetches the WPC Day 1 Excessive Rainfall Outlook (ERO) shapefile,
    converts it to a lightweight GeoJSON, and standardizes properties.
    """
    print("Fetching WPC Day 1 ERO...")
    response = requests.get(ERO_DAY1_URL)
    
    if response.status_code != 200:
        print(f"Failed to download ERO data. HTTP Status: {response.status_code}")
        return None

    # Extract the shapefile from the downloaded ZIP archive in memory
    with zipfile.ZipFile(io.BytesIO(response.content)) as z:
        z.extractall("/tmp/ero_shapefile")

    # Load the shapefile using geopandas
    shapefile_path = [os.path.join("/tmp/ero_shapefile", f) for f in os.listdir("/tmp/ero_shapefile") if f.endswith(".shp")][0]
    gdf = gpd.read_file(shapefile_path)

    # Standardize projection to WGS84 (standard for Leaflet/web mapping)
    gdf = gdf.to_crs("EPSG:4326")

    # Filter out empty geometries and keep only necessary columns to ensure lightweight output
    gdf = gdf[~gdf.geometry.is_empty]
    
    # We add an identifier so the frontend knows how to style these specific polygons
    gdf["dataType"] = "ERO"
    
    # Keep only the risk category (e.g., MRGL, SLGT, MDT, HIGH) and our new identifier
    columns_to_keep = ["OUTLOOK", "dataType", "geometry"]
    gdf = gdf[[col for col in columns_to_keep if col in gdf.columns]]

    return gdf

def main():
    print("Starting WPC data processing...")
    
    # Fetch ERO data
    ero_gdf = fetch_and_process_ero()
    
    if ero_gdf is not None and not ero_gdf.empty:
        # Overwrite and export to a single wpc_data.geojson file
        ero_gdf.to_file(OUTPUT_FILENAME, driver="GeoJSON")
        print(f"Successfully wrote {OUTPUT_FILENAME} with {len(ero_gdf)} features.")
    else:
        print("No valid data processed. GeoJSON not updated.")

if __name__ == "__main__":
    main()
