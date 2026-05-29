import geopandas as gpd
import requests

# Official NOAA REST API Endpoint for Day 1 ERO
ERO_DAY1_URL = "https://mapservices.weather.noaa.gov/vector/rest/services/hazards/wpc_precip_hazards/MapServer/0/query?where=1=1&outFields=OUTLOOK&f=geojson"
OUTPUT_FILENAME = "wpc_data.geojson"

def fetch_and_process_ero():
    print("Fetching WPC Day 1 ERO via NOAA REST API...")
    try:
        response = requests.get(ERO_DAY1_URL)
        response.raise_for_status()
        
        # Load directly into GeoPandas
        gdf = gpd.read_file(response.text, driver="GeoJSON")
        
        if gdf.empty or gdf.geometry.is_empty.all():
            print("No active ERO polygons found.")
            return None
            
        # Filter out empty geometries
        gdf = gdf[~gdf.geometry.is_empty]
        
        # Add identifier for frontend styling
        gdf["dataType"] = "ERO"
        
        return gdf
        
    except Exception as e:
        print(f"Failed to fetch or process ERO data: {e}")
        return None

def main():
    print("Starting WPC data processing...")
    ero_gdf = fetch_and_process_ero()
    
    if ero_gdf is not None and not ero_gdf.empty:
        # Overwrite and export to a single wpc_data.geojson file
        ero_gdf.to_file(OUTPUT_FILENAME, driver="GeoJSON")
        print(f"Successfully wrote {OUTPUT_FILENAME} with {len(ero_gdf)} features.")
    else:
        print("No valid data processed. GeoJSON not updated.")

if __name__ == "__main__":
    main()
