import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import rasterio
import requests
from PIL import Image
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# -----------------------------------------------------------------------------
# 1. CONFIGURATION
# -----------------------------------------------------------------------------
BASE_URL = (
    "https://nssrgeo.ndc.nasa.gov/"
    "SPoRT/modeling/lis/conus3km/geotiff/vsm_percentiles"
)

SPORT_FILE = Path("sport_temp.tif")
OUTPUT_PNG = Path("static/sport_soil_percentile.png")
OUTPUT_JSON = Path("static/sport_metadata.json")

LOOKBACK_DAYS = 10

HEADERS = {
    "User-Agent": (
        "WPC-Hydro-Dashboard/1.0 "
        "(GitHub Actions; NASA SPoRT-LIS retrieval)"
    ),
    "Accept": "image/tiff,application/octet-stream,*/*",
}

# -----------------------------------------------------------------------------
# 2. HTTP SESSION
# -----------------------------------------------------------------------------
def build_session():
    retry = Retry(
        total=4,
        connect=4,
        read=4,
        backoff_factor=2.0,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        raise_on_status=False,
    )

    session = requests.Session()
    session.headers.update(HEADERS)
    session.mount("https://", HTTPAdapter(max_retries=retry))

    return session

def is_tiff(path):
    try:
        with path.open("rb") as file:
            magic = file.read(4)

        return magic in (
            b"II*\x00",   
            b"MM\x00*",   
        )
    except OSError:
        return False

# -----------------------------------------------------------------------------
# 3. DOWNLOAD
# -----------------------------------------------------------------------------
def download_latest_sport():
    session = build_session()
    now = datetime.now(timezone.utc)

    for lag_days in range(LOOKBACK_DAYS + 1):
        valid_time = (now - timedelta(days=lag_days)).replace(hour=0, minute=0, second=0, microsecond=0)
        date_string = valid_time.strftime("%Y%m%d")

        filename = f"{date_string}_0000_sport_lis_vsm0-100cm_percentile_conus3km_byteScaled_wgs84.tif"
        url = f"{BASE_URL}/{filename}"

        print(f"Checking NASA SPoRT-LIS 0–100 cm percentile for {date_string} 00Z...")

        try:
            with session.get(url, stream=True, timeout=(20, 180)) as response:
                if response.status_code == 404:
                    print(" -> Product not posted for this date.")
                    continue

                if response.status_code != 200:
                    print(f" -> HTTP {response.status_code}; trying an older date.")
                    continue

                with SPORT_FILE.open("wb") as file:
                    for chunk in response.iter_content(chunk_size=1024 * 1024):
                        if chunk:
                            file.write(chunk)

            if not is_tiff(SPORT_FILE):
                print(" -> Download was not a valid TIFF; trying an older date.")
                SPORT_FILE.unlink(missing_ok=True)
                continue

            print(f"Success: downloaded {filename}")
            return valid_time, url

        except requests.RequestException as error:
            print(f" -> Connection error: {error}")

    raise RuntimeError(f"No SPoRT-LIS 0–100 cm percentile GeoTIFF was found in the last {LOOKBACK_DAYS} days.")

# -----------------------------------------------------------------------------
# 4. PROCESS THE GEOTIFF
# -----------------------------------------------------------------------------
def process_geotiff():
    with rasterio.open(SPORT_FILE) as source:
        percentile = source.read(1, masked=True).astype(np.float32)

        scale = source.scales[0] if source.scales else 1.0
        offset = source.offsets[0] if source.offsets else 0.0

        if scale != 1.0 or offset != 0.0:
            percentile = percentile * scale + offset

        data = np.asarray(percentile.filled(np.nan), dtype=np.float32)

        valid = (
            ~np.ma.getmaskarray(percentile)
            & np.isfinite(data)
            & (data >= 0.0)
            & (data <= 100.0)
        )

        bounds = [
            [float(source.bounds.bottom), float(source.bounds.left)],
            [float(source.bounds.top), float(source.bounds.right)],
        ]
        crs = source.crs.to_string() if source.crs else "unknown"

    return data, valid, bounds, crs

# -----------------------------------------------------------------------------
# 5. CREATE TRANSPARENT PNG
# -----------------------------------------------------------------------------
def create_rgba_image(data, valid):
    palette = np.array(
        [
            [0, 0, 0, 0],          
            [255, 255, 0, 255],    
            [255, 204, 0, 255],    
            [255, 102, 0, 255],    
            [255, 0, 0, 255],      
            [204, 0, 204, 255],    
        ],
        dtype=np.uint8,
    )

    rgba = np.zeros((data.shape[0], data.shape[1], 4), dtype=np.uint8)
    valid_data = data[valid]
    
    class_index = np.digitize(valid_data, bins=[70, 80, 90, 95, 98], right=False)
    rgba[valid] = palette[class_index]

    # THE FIX: Flip the image vertically so North is at the top for Leaflet mapping
    return np.flipud(rgba)

# -----------------------------------------------------------------------------
# 6. MAIN
# -----------------------------------------------------------------------------
def main():
    OUTPUT_PNG.parent.mkdir(parents=True, exist_ok=True)

    try:
        valid_time, source_url = download_latest_sport()
        data, valid, bounds, crs = process_geotiff()
        rgba = create_rgba_image(data, valid)

        Image.fromarray(rgba).save(OUTPUT_PNG, optimize=True)

        retrieval_time = datetime.now(timezone.utc)

        metadata = {
            "valid_time": valid_time.strftime("SPoRT-LIS: %b %d, %Y %HZ"),
            "valid_time_iso": valid_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "retrieved_time": retrieval_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "data_age_hours": round((retrieval_time - valid_time).total_seconds() / 3600.0, 1),
            "bounds": bounds,
            "crs": crs,
            "product": "NASA SPoRT-LIS 0–100 cm Soil Moisture Percentile",
            "depth": "0–100 cm",
            "units": "percentile",
            "source_url": source_url,
        }

        with OUTPUT_JSON.open("w", encoding="utf-8") as file:
            json.dump(metadata, file, indent=2)

        print(f"Wrote {OUTPUT_PNG}")
        print(f"Wrote {OUTPUT_JSON}")
        print("SPoRT-LIS data successfully processed and exported.")

        return 0

    except Exception as error:
        print(f"WARNING: SPoRT-LIS update failed: {error}")
        if OUTPUT_PNG.exists() and OUTPUT_JSON.exists():
            print("Keeping the previous SPoRT-LIS dashboard layer.")
            return 0

        print("No previous SPoRT-LIS output exists; the workflow must fail.")
        return 1

    finally:
        SPORT_FILE.unlink(missing_ok=True)

if __name__ == "__main__":
    sys.exit(main())
