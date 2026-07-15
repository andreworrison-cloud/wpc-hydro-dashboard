import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import requests
import xarray as xr
from affine import Affine
from PIL import Image
from pyproj import CRS as PyprojCRS
from rasterio.crs import CRS as RasterioCRS
from rasterio.transform import array_bounds, from_origin
from rasterio.warp import (
    Resampling,
    calculate_default_transform,
    reproject,
    transform_bounds,
)
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


NWM_FILE = Path("nwm_temp.nc")
OUTPUT_PNG = Path("static/nwm_soil_saturation.png")
OUTPUT_JSON = Path("static/nwm_metadata.json")

LOOKBACK_HOURS = 12
MAX_OUTPUT_DIMENSION = 3000

HEADERS = {
    "User-Agent": (
        "WPC-Hydro-Dashboard/1.0 "
        "(GitHub Actions; NOAA NWM retrieval)"
    ),
    "Accept": "application/x-netcdf,application/octet-stream,*/*",
}


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


def is_netcdf_or_hdf5(path):
    try:
        with path.open("rb") as file:
            magic = file.read(8)

        return (
            magic.startswith(b"CDF\x01")
            or magic.startswith(b"CDF\x02")
            or magic == b"\x89HDF\r\n\x1a\n"
        )
    except OSError:
        return False


def download_latest_nwm():
    session = build_session()
    search_start = datetime.now(timezone.utc) - timedelta(hours=1)

    for hour_lag in range(LOOKBACK_HOURS + 1):
        target_time = (
            search_start - timedelta(hours=hour_lag)
        ).replace(
            minute=0,
            second=0,
            microsecond=0,
        )

        date_string = target_time.strftime("%Y%m%d")
        hour_string = target_time.strftime("%H")

        url = (
            "https://nomads.ncep.noaa.gov/pub/data/"
            "nccf/com/nwm/prod/"
            f"nwm.{date_string}/analysis_assim/"
            f"nwm.t{hour_string}z.analysis_assim."
            "land.tm00.conus.nc"
        )

        print(
            f"Checking NOAA NWM for "
            f"{date_string} {hour_string}Z..."
        )

        try:
            with session.get(
                url,
                stream=True,
                timeout=(20, 300),
            ) as response:
                if response.status_code == 404:
                    print(" -> Product not posted.")
                    continue

                if response.status_code != 200:
                    print(
                        f" -> HTTP {response.status_code}; "
                        "trying an older analysis."
                    )
                    continue

                with NWM_FILE.open("wb") as file:
                    for chunk in response.iter_content(
                        chunk_size=1024 * 1024
                    ):
                        if chunk:
                            file.write(chunk)

            if not is_netcdf_or_hdf5(NWM_FILE):
                print(
                    " -> Download was not a valid NetCDF/HDF5 file; "
                    "trying an older analysis."
                )
                NWM_FILE.unlink(missing_ok=True)
                continue

            print(
                "Success: downloaded NWM analysis "
                f"{date_string} {hour_string}Z"
            )
            return target_time, url

        except requests.RequestException as error:
            print(f" -> Connection error: {error}")

    raise RuntimeError(
        "No recent NWM analysis-assimilation land file "
        f"was found in the last {LOOKBACK_HOURS + 1} hours."
    )


def plain_python(value):
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    return value


def projection_attrs_from_dataset(dataset, data_array):
    candidates = []

    grid_mapping_name = data_array.attrs.get("grid_mapping")
    if grid_mapping_name:
        candidates.append(str(grid_mapping_name))

    candidates.extend(
        [
            "ProjectionCoordinateSystem",
            "crs",
            "spatial_ref",
            "Lambert_Conformal",
        ]
    )

    for name, variable in dataset.variables.items():
        if "grid_mapping_name" in variable.attrs:
            candidates.append(name)

    seen = set()

    for name in candidates:
        if name in seen or name not in dataset.variables:
            continue

        seen.add(name)

        attrs = {
            key: plain_python(value)
            for key, value in dataset[name].attrs.items()
        }

        if attrs:
            print(f"Using NWM projection metadata variable: {name}")
            return attrs

    return {}


def determine_source_crs(dataset, data_array):
    attrs = projection_attrs_from_dataset(
        dataset,
        data_array,
    )

    if attrs:
        for key in (
            "crs_wkt",
            "spatial_ref",
            "esri_pe_string",
        ):
            wkt = attrs.get(key)
            if isinstance(wkt, str) and wkt.strip():
                try:
                    crs = PyprojCRS.from_wkt(wkt)
                    return RasterioCRS.from_wkt(crs.to_wkt())
                except Exception:
                    pass

        try:
            crs = PyprojCRS.from_cf(attrs)
            return RasterioCRS.from_wkt(crs.to_wkt())
        except Exception as error:
            print(
                "Could not build CRS from the file's CF metadata: "
                f"{error}"
            )

    print(
        "WARNING: Falling back to the standard NWM CONUS "
        "Lambert conformal definition."
    )

    fallback = PyprojCRS.from_proj4(
        "+proj=lcc "
        "+lat_1=30 +lat_2=60 "
        "+lat_0=40 +lon_0=-97 "
        "+R=6370000 "
        "+units=m +no_defs"
    )

    return RasterioCRS.from_wkt(fallback.to_wkt())


def prepare_source_grid(dataset):
    if "SOILSAT_TOP" not in dataset.data_vars:
        raise RuntimeError(
            "SOILSAT_TOP was not found in the NWM land file."
        )

    if "x" not in dataset.coords or "y" not in dataset.coords:
        raise RuntimeError(
            "NWM file does not contain the expected x and y coordinates."
        )

    data_array = dataset["SOILSAT_TOP"].squeeze(drop=True)

    if "x" not in data_array.dims or "y" not in data_array.dims:
        raise RuntimeError(
            f"Unexpected SOILSAT_TOP dimensions: {data_array.dims}"
        )

    data_array = data_array.transpose("y", "x")

    soil_saturation = np.asarray(
        data_array.values,
        dtype=np.float32,
    )

    x = np.asarray(
        dataset["x"].values,
        dtype=np.float64,
    )
    y = np.asarray(
        dataset["y"].values,
        dtype=np.float64,
    )

    x_units = str(
        dataset["x"].attrs.get("units", "")
    ).strip().lower()
    y_units = str(
        dataset["y"].attrs.get("units", "")
    ).strip().lower()

    kilometer_units = {
        "km",
        "kilometer",
        "kilometers",
        "kilometre",
        "kilometres",
    }

    if x_units in kilometer_units:
        x *= 1000.0

    if y_units in kilometer_units:
        y *= 1000.0

    if x.ndim != 1 or y.ndim != 1:
        raise RuntimeError(
            "Expected one-dimensional NWM x and y coordinates."
        )

    if soil_saturation.shape != (y.size, x.size):
        raise RuntimeError(
            "SOILSAT_TOP shape does not match the x/y coordinate sizes: "
            f"{soil_saturation.shape} versus {(y.size, x.size)}."
        )

    finite = soil_saturation[np.isfinite(soil_saturation)]

    if finite.size == 0:
        raise RuntimeError("SOILSAT_TOP contains no finite values.")

    raw_max = float(np.nanmax(finite))

    if raw_max <= 1.5:
        soil_saturation *= 100.0
    elif raw_max <= 100.5:
        print(
            "SOILSAT_TOP appears already scaled to percent; "
            "not multiplying by 100."
        )
    else:
        raise RuntimeError(
            "SOILSAT_TOP has an unexpected maximum value "
            f"of {raw_max}."
        )

    soil_saturation[
        ~np.isfinite(soil_saturation)
        | (soil_saturation < 0.0)
        | (soil_saturation > 100.0)
    ] = np.nan

    if x[0] > x[-1]:
        x = x[::-1]
        soil_saturation = soil_saturation[:, ::-1]

    if y[0] < y[-1]:
        y = y[::-1]
        soil_saturation = soil_saturation[::-1, :]

    dx = float(np.median(np.diff(x)))
    dy = float(np.median(np.abs(np.diff(y))))

    if dx <= 0.0 or dy <= 0.0:
        raise RuntimeError(
            f"Invalid NWM grid spacing: dx={dx}, dy={dy}"
        )

    if not np.allclose(
        np.diff(x),
        dx,
        rtol=0.0,
        atol=max(1.0e-4, abs(dx) * 1.0e-6),
    ):
        raise RuntimeError("NWM x coordinates are not regularly spaced.")

    if not np.allclose(
        np.abs(np.diff(y)),
        dy,
        rtol=0.0,
        atol=max(1.0e-4, abs(dy) * 1.0e-6),
    ):
        raise RuntimeError("NWM y coordinates are not regularly spaced.")

    source_transform = from_origin(
        west=float(x[0] - dx / 2.0),
        north=float(y[0] + dy / 2.0),
        xsize=dx,
        ysize=dy,
    )

    source_crs = determine_source_crs(
        dataset,
        data_array,
    )

    print(f"NWM source shape: {soil_saturation.shape}")
    print(f"NWM source CRS: {source_crs}")
    print(f"NWM source grid spacing: dx={dx}, dy={dy}")

    valid_values = soil_saturation[
        np.isfinite(soil_saturation)
    ]

    print(
        "NWM valid saturation range: "
        f"{float(np.nanmin(valid_values)):.1f}% to "
        f"{float(np.nanmax(valid_values)):.1f}%"
    )

    return soil_saturation, source_transform, source_crs


def reproject_to_web_mercator(
    source_data,
    source_transform,
    source_crs,
):
    source_height, source_width = source_data.shape

    source_bounds = array_bounds(
        source_height,
        source_width,
        source_transform,
    )

    destination_crs = RasterioCRS.from_epsg(3857)

    (
        destination_transform,
        destination_width,
        destination_height,
    ) = calculate_default_transform(
        source_crs,
        destination_crs,
        source_width,
        source_height,
        *source_bounds,
    )

    scale_factor = max(
        destination_width / MAX_OUTPUT_DIMENSION,
        destination_height / MAX_OUTPUT_DIMENSION,
        1.0,
    )

    if scale_factor > 1.0:
        reduced_width = max(
            1,
            int(round(destination_width / scale_factor)),
        )
        reduced_height = max(
            1,
            int(round(destination_height / scale_factor)),
        )

        destination_transform = (
            destination_transform
            * Affine.scale(
                destination_width / reduced_width,
                destination_height / reduced_height,
            )
        )

        destination_width = reduced_width
        destination_height = reduced_height

    destination = np.full(
        (destination_height, destination_width),
        np.nan,
        dtype=np.float32,
    )

    source_valid = np.isfinite(source_data).astype(np.uint8)
    destination_valid = np.zeros(
        (destination_height, destination_width),
        dtype=np.uint8,
    )

    reproject(
        source=source_data,
        destination=destination,
        src_transform=source_transform,
        src_crs=source_crs,
        src_nodata=np.nan,
        dst_transform=destination_transform,
        dst_crs=destination_crs,
        dst_nodata=np.nan,
        resampling=Resampling.bilinear,
        init_dest_nodata=True,
        num_threads=2,
    )

    reproject(
        source=source_valid,
        destination=destination_valid,
        src_transform=source_transform,
        src_crs=source_crs,
        src_nodata=0,
        dst_transform=destination_transform,
        dst_crs=destination_crs,
        dst_nodata=0,
        resampling=Resampling.nearest,
        init_dest_nodata=True,
        num_threads=2,
    )

    destination[destination_valid == 0] = np.nan
    destination[
        (destination < 0.0)
        | (destination > 100.0)
    ] = np.nan

    projected_bounds = array_bounds(
        destination_height,
        destination_width,
        destination_transform,
    )

    west, south, east, north = transform_bounds(
        destination_crs,
        RasterioCRS.from_epsg(4326),
        *projected_bounds,
        densify_pts=21,
    )

    leaflet_bounds = [
        [float(south), float(west)],
        [float(north), float(east)],
    ]

    print(
        "NWM EPSG:3857 output shape: "
        f"{destination.shape}"
    )
    print("NWM image CRS: EPSG:3857")
    print(f"NWM Leaflet bounds: {leaflet_bounds}")

    return destination, leaflet_bounds


def create_rgba_image(data):
    palette = np.array(
        [
            [210, 180, 140, 255],
            [224, 238, 224, 255],
            [144, 238, 144, 255],
            [60, 179, 113, 255],
            [0, 206, 209, 255],
            [30, 144, 255, 255],
            [0, 0, 139, 255],
        ],
        dtype=np.uint8,
    )

    rgba = np.zeros(
        (data.shape[0], data.shape[1], 4),
        dtype=np.uint8,
    )

    valid = np.isfinite(data)

    class_index = np.digitize(
        data,
        bins=[40, 60, 70, 80, 90, 95],
        right=False,
    )

    rgba[valid] = palette[class_index[valid]]
    return rgba


def main():
    OUTPUT_PNG.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    try:
        valid_time, source_url = download_latest_nwm()

        print("Opening and processing NWM NetCDF file...")

        with xr.open_dataset(
            NWM_FILE,
            engine="h5netcdf",
            decode_coords="all",
            mask_and_scale=True,
        ) as dataset:
            (
                source_data,
                source_transform,
                source_crs,
            ) = prepare_source_grid(dataset)

        (
            destination_data,
            leaflet_bounds,
        ) = reproject_to_web_mercator(
            source_data,
            source_transform,
            source_crs,
        )

        rgba = create_rgba_image(destination_data)

        Image.fromarray(rgba).save(
            OUTPUT_PNG,
            optimize=True,
        )

        retrieval_time = datetime.now(timezone.utc)

        metadata = {
            "valid_time": valid_time.strftime(
                "NWM Saturation: %b %d, %Y %HZ"
            ),
            "valid_time_iso": valid_time.strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),
            "retrieved_time": retrieval_time.strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),
            "data_age_hours": round(
                (
                    retrieval_time - valid_time
                ).total_seconds() / 3600.0,
                1,
            ),
            "bounds": leaflet_bounds,
            "crs": "EPSG:3857",
            "image_crs": "EPSG:3857",
            "bounds_crs": "EPSG:4326",
            "product": "NOAA National Water Model SOILSAT_TOP",
            "depth": "top two soil layers, 0-40 cm",
            "units": "percent saturation",
            "source_url": source_url,
        }

        with OUTPUT_JSON.open(
            "w",
            encoding="utf-8",
        ) as file:
            json.dump(
                metadata,
                file,
                indent=2,
            )

        print(f"Wrote {OUTPUT_PNG}")
        print(f"Wrote {OUTPUT_JSON}")
        print(
            "NWM soil saturation successfully "
            "reprojected and exported."
        )
        return 0

    except Exception as error:
        print(f"WARNING: NWM update failed: {error}")

        if OUTPUT_PNG.exists() and OUTPUT_JSON.exists():
            print(
                "Keeping the previous NWM dashboard layer."
            )
            return 0

        print(
            "No previous NWM output exists; "
            "the workflow must fail."
        )
        return 1

    finally:
        NWM_FILE.unlink(missing_ok=True)


if __name__ == "__main__":
    sys.exit(main())
