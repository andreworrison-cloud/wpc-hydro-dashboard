#!/usr/bin/env python3
"""
NLDAS-2 Noah RSM feed diagnostic for the WPC Hydrometeorological Dashboard.

This script is intentionally read-only with respect to the repository. It:

1. Finds the newest NOAA/NCEP operational NLDAS-2 directory.
2. Finds the newest Noah hourly GRIB2 file in that directory.
3. Downloads the GRIB2 file and inventories soil-moisture messages.
4. Identifies likely 0-10 cm and 0-100 cm column-integrated soil moisture.
5. Downloads and inventories the official NASA NLDAS Noah soil-parameter file.
6. Writes nldas_rsm_diagnostic.json for review.

It does NOT create dashboard PNGs, modify app.js, or commit anything.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import requests
import xarray as xr
from eccodes import (
    codes_get,
    codes_get_array,
    codes_grib_new_from_file,
    codes_release,
)
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


NLDAS_ROOT = (
    "https://nomads.ncep.noaa.gov/pub/data/nccf/com/nldas/prod"
)
NOAH_SOIL_PARAMETER_URL = (
    "https://ldas.gsfc.nasa.gov/sites/default/files/"
    "ldas/nldas/NLDAS_soil_Noah.nc4"
)

WORK_DIR = Path("nldas_rsm_diagnostic_work")
GRIB_FILE = WORK_DIR / "latest_nldas_noah.grib2"
SOIL_PARAMETER_FILE = WORK_DIR / "NLDAS_soil_Noah.nc4"
OUTPUT_JSON = Path("nldas_rsm_diagnostic.json")

LOOKBACK_DAYS = 20

HEADERS = {
    "User-Agent": (
        "WPC-Hydro-Dashboard/1.0 "
        "(GitHub Actions; NLDAS-2 RSM diagnostic)"
    ),
    "Accept": "text/html,application/octet-stream,*/*",
}


def build_session() -> requests.Session:
    retry = Retry(
        total=5,
        connect=5,
        read=5,
        backoff_factor=2.0,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET", "HEAD"}),
        raise_on_status=False,
    )
    session = requests.Session()
    session.headers.update(HEADERS)
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session


def fetch_text(
    session: requests.Session,
    url: str,
    timeout: tuple[int, int] = (20, 120),
) -> str:
    response = session.get(url, timeout=timeout)
    response.raise_for_status()
    return response.text


def stream_download(
    session: requests.Session,
    url: str,
    output_path: Path,
    timeout: tuple[int, int] = (20, 300),
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(output_path.suffix + ".part")

    with session.get(url, stream=True, timeout=timeout) as response:
        response.raise_for_status()
        with temporary.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    handle.write(chunk)

    temporary.replace(output_path)


def is_grib(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            return handle.read(4) == b"GRIB"
    except OSError:
        return False


def is_netcdf_or_hdf5(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            magic = handle.read(8)
        return (
            magic.startswith(b"CDF\x01")
            or magic.startswith(b"CDF\x02")
            or magic == b"\x89HDF\r\n\x1a\n"
        )
    except OSError:
        return False


def parse_available_dates(html: str) -> list[str]:
    dates = sorted(
        set(re.findall(r"nldas\.(20\d{6})/?", html)),
        reverse=True,
    )
    return dates


def fallback_dates() -> list[str]:
    now = datetime.now(timezone.utc)
    return [
        (now - timedelta(days=lag)).strftime("%Y%m%d")
        for lag in range(LOOKBACK_DAYS + 1)
    ]


def parse_noah_files(html: str) -> list[tuple[int, str]]:
    """
    Accept NOAA filename variants such as:
      noah.t12z.grbf23
      noah.t12z.grbf23.grib2

    Index files and temporary files are ignored.
    """
    matches: list[tuple[int, str]] = []

    pattern = re.compile(
        r'href=["\']([^"\']*noah\.t12z\.grbf(\d{2})'
        r'(?:\.grib2)?)(?:["\'])',
        re.IGNORECASE,
    )

    for filename, forecast_hour in pattern.findall(html):
        name = Path(filename).name
        lowered = name.lower()

        if lowered.endswith((".idx", ".index", ".inv", ".part")):
            continue

        matches.append((int(forecast_hour), name))

    # Directory pages can repeat links. Preserve one entry per filename.
    unique: dict[str, int] = {}
    for forecast_hour, filename in matches:
        unique[filename] = forecast_hour

    return sorted(
        ((forecast_hour, filename) for filename, forecast_hour in unique.items()),
        reverse=True,
    )


def locate_latest_noah_file(
    session: requests.Session,
) -> tuple[str, int, str, str]:
    print(f"Checking NLDAS product root: {NLDAS_ROOT}/")

    try:
        root_html = fetch_text(session, f"{NLDAS_ROOT}/")
        dates = parse_available_dates(root_html)
    except requests.RequestException as error:
        print(f"Root-directory listing failed: {error}")
        dates = []

    if not dates:
        print(
            "No dates were parsed from the root listing; "
            f"falling back to a {LOOKBACK_DAYS}-day date search."
        )
        dates = fallback_dates()

    for date_string in dates[: LOOKBACK_DAYS + 1]:
        directory_url = f"{NLDAS_ROOT}/nldas.{date_string}/"
        print(f"Checking {directory_url}")

        try:
            directory_html = fetch_text(session, directory_url)
        except requests.RequestException as error:
            print(f" -> unavailable: {error}")
            continue

        candidates = parse_noah_files(directory_html)
        if not candidates:
            print(" -> no Noah hourly GRIB files found")
            continue

        forecast_hour, filename = candidates[0]
        file_url = f"{directory_url}{filename}"

        print(
            "Selected latest Noah file: "
            f"date={date_string}, f{forecast_hour:02d}, file={filename}"
        )
        return date_string, forecast_hour, filename, file_url

    raise RuntimeError(
        "Could not find an operational NLDAS-2 Noah GRIB2 file "
        f"within the last {LOOKBACK_DAYS} days."
    )


def safe_codes_get(gid: Any, key: str, default: Any = None) -> Any:
    try:
        return codes_get(gid, key)
    except Exception:
        return default


def scaled_surface_value(
    gid: Any,
    value_key: str,
    scale_key: str,
) -> float | None:
    value = safe_codes_get(gid, value_key)
    scale = safe_codes_get(gid, scale_key)

    if value is None or scale is None:
        return None

    try:
        return float(value) * (10.0 ** (-float(scale)))
    except (TypeError, ValueError, OverflowError):
        return None


def normalize_level_bounds(gid: Any) -> tuple[float | None, float | None]:
    top = safe_codes_get(gid, "topLevel")
    bottom = safe_codes_get(gid, "bottomLevel")

    try:
        if top is not None and bottom is not None:
            return float(top), float(bottom)
    except (TypeError, ValueError):
        pass

    top = scaled_surface_value(
        gid,
        "scaledValueOfFirstFixedSurface",
        "scaleFactorOfFirstFixedSurface",
    )
    bottom = scaled_surface_value(
        gid,
        "scaledValueOfSecondFixedSurface",
        "scaleFactorOfSecondFixedSurface",
    )
    return top, bottom


def is_soil_related(short_name: str, name: str) -> bool:
    text = f"{short_name} {name}".lower()
    tokens = (
        "soil",
        "moisture availability",
        "cisoilm",
        "lsoil",
        "mstav",
    )
    return any(token in text for token in tokens)


def is_column_soil_moisture(short_name: str, name: str) -> bool:
    text = f"{short_name} {name}".lower()
    return (
        "cisoilm" in text
        or "column-integrated soil moisture" in text
        or "soil moisture content" in text
    )


def level_match(
    top: float | None,
    bottom: float | None,
    desired_bottom_m: float,
) -> bool:
    if top is None or bottom is None:
        return False

    # ecCodes commonly exposes these depth bounds in meters, but this
    # tolerance also permits small floating-point representation differences.
    return abs(top - 0.0) <= 0.001 and abs(bottom - desired_bottom_m) <= 0.01


def inventory_grib(path: Path) -> dict[str, Any]:
    soil_messages: list[dict[str, Any]] = []
    selected: dict[str, dict[str, Any] | None] = {
        "rsm_0_10cm_source": None,
        "rsm_0_100cm_source": None,
    }

    message_number = 0

    with path.open("rb") as handle:
        while True:
            gid = codes_grib_new_from_file(handle)
            if gid is None:
                break

            message_number += 1

            try:
                short_name = str(
                    safe_codes_get(gid, "shortName", "")
                )
                name = str(safe_codes_get(gid, "name", ""))
                units = str(safe_codes_get(gid, "units", ""))
                type_of_level = str(
                    safe_codes_get(gid, "typeOfLevel", "")
                )
                top_level, bottom_level = normalize_level_bounds(gid)

                record = {
                    "message_number": message_number,
                    "short_name": short_name,
                    "name": name,
                    "units": units,
                    "type_of_level": type_of_level,
                    "top_level": top_level,
                    "bottom_level": bottom_level,
                    "validity_date": safe_codes_get(
                        gid, "validityDate"
                    ),
                    "validity_time": safe_codes_get(
                        gid, "validityTime"
                    ),
                    "data_date": safe_codes_get(gid, "dataDate"),
                    "data_time": safe_codes_get(gid, "dataTime"),
                    "forecast_time": safe_codes_get(
                        gid, "forecastTime"
                    ),
                    "number_of_points": safe_codes_get(
                        gid, "numberOfPoints"
                    ),
                    "Ni": safe_codes_get(gid, "Ni"),
                    "Nj": safe_codes_get(gid, "Nj"),
                }

                if is_soil_related(short_name, name):
                    soil_messages.append(record)
                    print(
                        "SOIL MESSAGE "
                        f"{message_number:03d}: "
                        f"{short_name} | {name} | "
                        f"{type_of_level} | "
                        f"top={top_level} bottom={bottom_level} | "
                        f"{units}"
                    )

                if is_column_soil_moisture(short_name, name):
                    if level_match(top_level, bottom_level, 0.1):
                        selected["rsm_0_10cm_source"] = record
                    elif level_match(top_level, bottom_level, 1.0):
                        selected["rsm_0_100cm_source"] = record

            finally:
                codes_release(gid)

    if message_number == 0:
        raise RuntimeError("No GRIB messages were decoded.")

    print(f"Decoded {message_number} total GRIB messages.")
    print(f"Found {len(soil_messages)} soil-related messages.")

    return {
        "total_messages": message_number,
        "soil_messages": soil_messages,
        "selected_messages": selected,
    }


def summarize_variable(
    dataset: xr.Dataset,
    variable_name: str,
) -> dict[str, Any]:
    variable = dataset[variable_name]

    summary: dict[str, Any] = {
        "name": variable_name,
        "dims": list(variable.dims),
        "shape": list(variable.shape),
        "dtype": str(variable.dtype),
        "attrs": {
            str(key): str(value)
            for key, value in variable.attrs.items()
        },
    }

    # Avoid forcing large non-numeric arrays into memory.
    if np.issubdtype(variable.dtype, np.number):
        try:
            values = np.asarray(variable.values, dtype=np.float64)
            finite = values[np.isfinite(values)]

            if finite.size:
                summary["minimum"] = float(np.nanmin(finite))
                summary["maximum"] = float(np.nanmax(finite))
                summary["mean"] = float(np.nanmean(finite))
        except Exception as error:
            summary["statistics_error"] = str(error)

    return summary


def find_porosity_candidates(
    dataset: xr.Dataset,
) -> list[dict[str, Any]]:
    tokens = (
        "poros",
        "smcmax",
        "maxsmc",
        "theta_sat",
        "saturation",
    )
    candidates: list[dict[str, Any]] = []

    for variable_name in dataset.data_vars:
        variable = dataset[variable_name]
        searchable = " ".join(
            [
                variable_name,
                str(variable.attrs.get("long_name", "")),
                str(variable.attrs.get("standard_name", "")),
                str(variable.attrs.get("description", "")),
            ]
        ).lower()

        if any(token in searchable for token in tokens):
            candidates.append(
                summarize_variable(dataset, variable_name)
            )

    return candidates


def inventory_soil_parameter_file(path: Path) -> dict[str, Any]:
    open_errors: list[str] = []
    dataset: xr.Dataset | None = None

    for engine in ("h5netcdf", None):
        try:
            kwargs = {"engine": engine} if engine else {}
            dataset = xr.open_dataset(path, **kwargs)
            break
        except Exception as error:
            open_errors.append(f"{engine or 'default'}: {error}")

    if dataset is None:
        raise RuntimeError(
            "Could not open the Noah soil-parameter file. "
            + " | ".join(open_errors)
        )

    try:
        print("NASA Noah soil-parameter dataset dimensions:")
        print(dict(dataset.sizes))

        print("NASA Noah soil-parameter variables:")
        for variable_name in dataset.variables:
            variable = dataset[variable_name]
            print(
                f" - {variable_name}: "
                f"dims={variable.dims}, shape={variable.shape}, "
                f"dtype={variable.dtype}"
            )

        candidates = find_porosity_candidates(dataset)

        print(
            f"Detected {len(candidates)} possible porosity variable(s): "
            + ", ".join(item["name"] for item in candidates)
        )

        return {
            "dimensions": {
                str(key): int(value)
                for key, value in dataset.sizes.items()
            },
            "variables": [
                summarize_variable(dataset, name)
                for name in dataset.variables
            ],
            "porosity_candidates": candidates,
            "global_attributes": {
                str(key): str(value)
                for key, value in dataset.attrs.items()
            },
        }
    finally:
        dataset.close()


def main() -> int:
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    session = build_session()

    diagnostic: dict[str, Any] = {
        "diagnostic_version": "nldas-rsm-diagnostic-v1",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "nldas_root": NLDAS_ROOT,
        "noah_soil_parameter_url": NOAH_SOIL_PARAMETER_URL,
    }

    try:
        (
            directory_date,
            forecast_hour,
            filename,
            grib_url,
        ) = locate_latest_noah_file(session)

        print(f"Downloading {grib_url}")
        stream_download(session, grib_url, GRIB_FILE)

        if not is_grib(GRIB_FILE):
            raise RuntimeError(
                f"Downloaded file is not GRIB: {GRIB_FILE}"
            )

        diagnostic["operational_grib"] = {
            "directory_date": directory_date,
            "forecast_hour": forecast_hour,
            "filename": filename,
            "url": grib_url,
            "size_bytes": GRIB_FILE.stat().st_size,
        }
        diagnostic["grib_inventory"] = inventory_grib(GRIB_FILE)

        print(
            "Downloading official NASA NLDAS Noah soil parameters: "
            f"{NOAH_SOIL_PARAMETER_URL}"
        )
        stream_download(
            session,
            NOAH_SOIL_PARAMETER_URL,
            SOIL_PARAMETER_FILE,
        )

        if not is_netcdf_or_hdf5(SOIL_PARAMETER_FILE):
            raise RuntimeError(
                "Downloaded NASA soil-parameter file is not "
                "NetCDF/HDF5."
            )

        diagnostic["soil_parameter_file"] = {
            "url": NOAH_SOIL_PARAMETER_URL,
            "size_bytes": SOIL_PARAMETER_FILE.stat().st_size,
            "inventory": inventory_soil_parameter_file(
                SOIL_PARAMETER_FILE
            ),
        }

        selected = diagnostic["grib_inventory"][
            "selected_messages"
        ]
        candidates = diagnostic["soil_parameter_file"][
            "inventory"
        ]["porosity_candidates"]

        diagnostic["readiness"] = {
            "found_0_10cm_column_soil_moisture": (
                selected["rsm_0_10cm_source"] is not None
            ),
            "found_0_100cm_column_soil_moisture": (
                selected["rsm_0_100cm_source"] is not None
            ),
            "found_porosity_candidate": bool(candidates),
            "ready_for_operational_fetch_script": (
                selected["rsm_0_10cm_source"] is not None
                and selected["rsm_0_100cm_source"] is not None
                and bool(candidates)
            ),
        }

        OUTPUT_JSON.write_text(
            json.dumps(diagnostic, indent=2, sort_keys=True),
            encoding="utf-8",
        )

        print(f"Wrote diagnostic report: {OUTPUT_JSON}")
        print(
            json.dumps(
                diagnostic["readiness"],
                indent=2,
                sort_keys=True,
            )
        )

        # A missing automatically selected record is not treated as a hard
        # workflow failure because the inventory itself is the diagnostic.
        return 0

    except Exception as error:
        diagnostic["fatal_error"] = str(error)
        OUTPUT_JSON.write_text(
            json.dumps(diagnostic, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        print(f"FATAL: {error}", file=sys.stderr)
        print(
            f"Partial diagnostic report written to {OUTPUT_JSON}",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
