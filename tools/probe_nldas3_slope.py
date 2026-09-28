#!/usr/bin/env python3
"""Diagnostic for NASA NLDAS-3 / MERIT static terrain slope over CONUS.

This is intentionally a QA/statistics step only. It does not publish a dashboard
raster and does not define runoff-risk thresholds. The goal is to inspect the
actual source field before choosing a scientifically defensible display contract.

Source:
s3://nasa-waterinsight/NLDAS3/static/lis_input.nldas3.noahmp401.1km.hymap.nc

NASA's NLDAS-3 variable inventory identifies static `slope` as surface slope
(m m-1). The NetCDF variable used here is `SLOPE`, whose source attribute is
"MERIT '1K' slope".
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import s3fs
import xarray as xr

UTC = timezone.utc

SOURCE_KEY = "nasa-waterinsight/NLDAS3/static/lis_input.nldas3.noahmp401.1km.hymap.nc"
SOURCE_URL = f"s3://{SOURCE_KEY}"
VARIABLE = "SLOPE"
DEFAULT_EXTENT = (-125.0, -66.5, 23.0, 50.5)  # west, east, south, north
EXPECTED_DX = 0.01
EXPECTED_DY = 0.01
MISSING = -9999.0


def center_index(value: float, first_center: float, step: float) -> int:
    return int(round((value - first_center) / step))


def subset_slices(
    west: float,
    east: float,
    south: float,
    north: float,
    sw_lon: float,
    sw_lat: float,
    dx: float,
    dy: float,
    nx: int,
    ny: int,
) -> tuple[slice, slice]:
    # Include one source cell of guard area around the requested dashboard extent.
    x0 = max(0, center_index(west, sw_lon, dx) - 1)
    x1 = min(nx, center_index(east, sw_lon, dx) + 2)
    y0 = max(0, center_index(south, sw_lat, dy) - 1)
    y1 = min(ny, center_index(north, sw_lat, dy) + 2)
    if not (x1 > x0 and y1 > y0):
        raise RuntimeError("Requested extent does not intersect NLDAS-3 grid")
    return slice(y0, y1), slice(x0, x1)


def percentile_key(q: float) -> str:
    if float(q).is_integer():
        return f"p{int(q):02d}"
    return "p" + str(q).replace(".", "_")


def finite_percentiles(values: np.ndarray, qs: list[float]) -> dict[str, float]:
    return {
        percentile_key(q): float(np.percentile(values, q))
        for q in qs
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("diagnostics/nldas3_slope_diagnostic.json"),
    )
    parser.add_argument(
        "--extent",
        type=float,
        nargs=4,
        metavar=("WEST", "EAST", "SOUTH", "NORTH"),
        default=DEFAULT_EXTENT,
    )
    args = parser.parse_args()

    s3 = s3fs.S3FileSystem(anon=True, client_kwargs={"region_name": "us-west-2"})
    print(f"Opening {SOURCE_URL}", flush=True)

    with s3.open(SOURCE_KEY, "rb") as fh:
        ds = xr.open_dataset(
            fh,
            engine="h5netcdf",
            decode_times=False,
            mask_and_scale=False,
            chunks=None,
        )

        if VARIABLE not in ds.variables:
            raise RuntimeError(f"Source missing required {VARIABLE} variable")

        dx = float(ds.attrs.get("DX", np.nan))
        dy = float(ds.attrs.get("DY", np.nan))
        sw_lat = float(ds.attrs.get("SOUTH_WEST_CORNER_LAT", np.nan))
        sw_lon = float(ds.attrs.get("SOUTH_WEST_CORNER_LON", np.nan))
        if not all(np.isfinite(v) for v in (dx, dy, sw_lat, sw_lon)):
            raise RuntimeError("Missing NLDAS-3 grid geometry metadata")
        if abs(dx - EXPECTED_DX) > 1e-5 or abs(dy - EXPECTED_DY) > 1e-5:
            raise RuntimeError(f"Unexpected NLDAS-3 grid spacing DX={dx}, DY={dy}")

        da = ds[VARIABLE]
        if tuple(da.dims) != ("north_south", "east_west"):
            raise RuntimeError(f"Unexpected {VARIABLE} dimensions: {da.dims}")

        ny = int(ds.sizes["north_south"])
        nx = int(ds.sizes["east_west"])
        west, east, south, north = map(float, args.extent)
        ys, xs = subset_slices(
            west, east, south, north,
            sw_lon, sw_lat, dx, dy, nx, ny,
        )

        print(
            f"Loading {VARIABLE} subset y={ys.start}:{ys.stop} x={xs.start}:{xs.stop}",
            flush=True,
        )
        raw = np.asarray(da.isel(north_south=ys, east_west=xs).load().values, dtype=np.float64)
        attrs = {str(k): str(v) for k, v in da.attrs.items()}
        source_history = str(ds.attrs.get("history", "Unknown"))
        ds.close()

    valid = np.isfinite(raw) & (raw != MISSING)
    values = raw[valid]
    if values.size == 0:
        raise RuntimeError("No valid NLDAS-3 slope values in CONUS subset")
    if np.any(values < 0):
        raise RuntimeError(f"Negative slope values encountered; minimum={values.min()}")

    qs = [0, 1, 5, 10, 25, 50, 75, 90, 95, 99, 99.5, 99.9, 100]
    raw_stats = finite_percentiles(values, qs)
    pct_values = values * 100.0
    pct_stats = finite_percentiles(pct_values, qs)

    # Coarse diagnostic bins only; these are descriptive distribution bins,
    # not runoff-risk classes and are not yet a dashboard legend contract.
    diagnostic_bins_pct = [0, 1, 2, 5, 10, 20, 30, 45, 60, 100, 200, np.inf]
    counts, _ = np.histogram(pct_values, bins=diagnostic_bins_pct)
    bin_rows = []
    for i, count in enumerate(counts):
        lo = diagnostic_bins_pct[i]
        hi = diagnostic_bins_pct[i + 1]
        bin_rows.append({
            "min_percent_slope": float(lo),
            "max_percent_slope": None if np.isinf(hi) else float(hi),
            "count": int(count),
            "fraction": float(count / values.size),
        })

    payload = {
        "generated_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "purpose": "NLDAS-3 MERIT slope pre-display diagnostic; no risk thresholds",
        "source": SOURCE_URL,
        "source_history": source_history,
        "variable": VARIABLE,
        "variable_attributes": attrs,
        "nasa_variable_inventory_interpretation": "surface slope, dimensionless rise/run (m m-1)",
        "grid": {
            "full_shape": [ny, nx],
            "dx_deg": dx,
            "dy_deg": dy,
            "southwest_center_lat": sw_lat,
            "southwest_center_lon": sw_lon,
            "subset_index_slices": {
                "north_south": [ys.start, ys.stop],
                "east_west": [xs.start, xs.stop],
            },
            "requested_extent": [west, east, south, north],
        },
        "valid_cells": int(values.size),
        "missing_cells": int(raw.size - values.size),
        "valid_fraction": float(values.size / raw.size),
        "raw_slope_fraction_stats": raw_stats,
        "candidate_percent_slope_stats": pct_stats,
        "descriptive_percent_slope_bins": bin_rows,
        "safeguards": [
            "No dashboard raster is published by this diagnostic.",
            "No runoff-risk or flash-flood-risk classes are assigned.",
            "Any future display derivative must remain separate from hourly-FFG scientific inputs.",
            "Future display scaling must be chosen after inspecting these source statistics.",
        ],
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Wrote {args.output}", flush=True)
    print(json.dumps({
        "valid_cells": payload["valid_cells"],
        "valid_fraction": payload["valid_fraction"],
        "percent_slope_stats": pct_stats,
    }, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
