#!/usr/bin/env python3
"""Probe NASA NLDAS-3 static NetCDF files without assuming variable names.

This diagnostic is intentionally read-only.  It records dimensions, variables,
attributes, and a light strided sample of integer-like 2-D fields so the
dashboard implementation can map categorical codes only after inspecting the
actual source metadata.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import s3fs
import xarray as xr

UTC = timezone.utc

SOURCES = {
    "dominant_soil_vegetation": (
        "nasa-waterinsight/NLDAS3/static/NLDAS-3_dominant-soil-vegetation.nc"
    ),
    "lis_hymap_static": (
        "nasa-waterinsight/NLDAS3/static/lis_input.nldas3.noahmp401.1km.hymap.nc"
    ),
}


def clean(value: Any) -> Any:
    if isinstance(value, (np.generic,)):
        return value.item()
    if isinstance(value, np.ndarray):
        if value.size <= 64:
            return value.tolist()
        return {
            "shape": list(value.shape),
            "dtype": str(value.dtype),
            "note": "attribute array omitted because it is large",
        }
    if isinstance(value, (bytes, bytearray)):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value[:64]]
    return str(value)


def attrs_dict(attrs: dict[str, Any]) -> dict[str, Any]:
    return {str(k): clean(v) for k, v in attrs.items()}


def sample_integer_field(da: xr.DataArray) -> dict[str, Any] | None:
    if da.ndim < 2 or da.dtype.kind not in "iub":
        return None
    indexers = {}
    for dim, size in da.sizes.items():
        step = max(1, int(size) // 80)
        indexers[dim] = slice(None, None, step)
    sampled = np.asarray(da.isel(indexers).load().values)
    if sampled.size == 0:
        return None
    sampled = sampled[np.isfinite(sampled)]
    if sampled.size == 0:
        return {"sample_count": 0, "unique_values": []}
    unique = np.unique(sampled)
    return {
        "sample_count": int(sampled.size),
        "sample_min": clean(unique.min()),
        "sample_max": clean(unique.max()),
        "unique_values": [clean(v) for v in unique[:128]],
        "unique_values_truncated": bool(unique.size > 128),
    }


def inventory_one(s3: s3fs.S3FileSystem, name: str, key: str) -> dict[str, Any]:
    print(f"Opening s3://{key}", flush=True)
    with s3.open(key, "rb") as fh:
        ds = xr.open_dataset(
            fh,
            engine="h5netcdf",
            decode_times=False,
            mask_and_scale=False,
            chunks=None,
        )
        out: dict[str, Any] = {
            "source": f"s3://{key}",
            "dimensions": {k: int(v) for k, v in ds.sizes.items()},
            "global_attributes": attrs_dict(dict(ds.attrs)),
            "coordinates": {},
            "variables": {},
        }
        for cname in ds.coords:
            da = ds[cname]
            out["coordinates"][cname] = {
                "dims": list(da.dims),
                "shape": list(da.shape),
                "dtype": str(da.dtype),
                "attributes": attrs_dict(dict(da.attrs)),
            }
        for vname in ds.data_vars:
            da = ds[vname]
            item: dict[str, Any] = {
                "dims": list(da.dims),
                "shape": list(da.shape),
                "dtype": str(da.dtype),
                "attributes": attrs_dict(dict(da.attrs)),
            }
            sampled = sample_integer_field(da)
            if sampled is not None:
                item["integer_sample"] = sampled
            out["variables"][vname] = item
        ds.close()
    print(
        f"{name}: {len(out['variables'])} data variables; dims={out['dimensions']}",
        flush=True,
    )
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("diagnostics/nldas3_static_inventory.json"),
    )
    args = parser.parse_args()

    s3 = s3fs.S3FileSystem(anon=True, client_kwargs={"region_name": "us-west-2"})
    payload = {
        "generated_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "purpose": "NLDAS-3 static source schema inventory for WPC hydro dashboard",
        "sources": {},
    }
    for name, key in SOURCES.items():
        payload["sources"][name] = inventory_one(s3, name, key)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Wrote {args.output}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
