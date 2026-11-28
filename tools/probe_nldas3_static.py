#!/usr/bin/env python3
"""Probe NASA NLDAS-3 static NetCDF files without assuming category values.

This diagnostic is intentionally read-only. It records dimensions, variables,
attributes, coordinate ranges, and light strided samples of selected numeric
fields. Category mappings are accepted only after the live values are checked
against the documented NASA/LIS classification schemes.
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

SAMPLED_FIELDS = {
    "Landcover_inst",
    "Soiltype_inst",
    "DOMAINMASK",
    "LANDMASK",
    "HYMAP_basin",
    "HYMAP_basin_mask",
    "HYMAP_river_flow_type",
}


def clean(value: Any) -> Any:
    if isinstance(value, np.generic):
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


def strided_sample(da: xr.DataArray, target_per_dim: int = 96) -> np.ndarray:
    indexers = {}
    for dim, size in da.sizes.items():
        step = max(1, int(size) // target_per_dim)
        indexers[dim] = slice(None, None, step)
    return np.asarray(da.isel(indexers).load().values)


def summarize_numeric_sample(da: xr.DataArray) -> dict[str, Any] | None:
    if da.ndim == 0 or da.dtype.kind not in "iufb":
        return None
    sampled = strided_sample(da)
    sampled = sampled[np.isfinite(sampled)]
    if sampled.size == 0:
        return {"sample_count": 0, "unique_values": []}

    unique = np.unique(sampled)
    summary: dict[str, Any] = {
        "sample_count": int(sampled.size),
        "sample_min": clean(sampled.min()),
        "sample_max": clean(sampled.max()),
        "unique_count": int(unique.size),
        "unique_values": [clean(v) for v in unique[:128]],
        "unique_values_truncated": bool(unique.size > 128),
    }

    if da.dtype.kind == "f":
        rounded = np.rint(sampled)
        summary["all_sampled_values_integer_like"] = bool(
            np.allclose(sampled, rounded, rtol=0.0, atol=1.0e-6)
        )
    return summary


def coordinate_summary(da: xr.DataArray) -> dict[str, Any]:
    item = {
        "dims": list(da.dims),
        "shape": list(da.shape),
        "dtype": str(da.dtype),
        "attributes": attrs_dict(dict(da.attrs)),
    }
    sampled = summarize_numeric_sample(da)
    if sampled is not None:
        item["sample"] = sampled
    return item


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
            out["coordinates"][cname] = coordinate_summary(ds[cname])

        # Some LIS files expose lat/lon as ordinary data variables rather than
        # xarray coordinates, so those are sampled explicitly too.
        for vname in ds.data_vars:
            da = ds[vname]
            item: dict[str, Any] = {
                "dims": list(da.dims),
                "shape": list(da.shape),
                "dtype": str(da.dtype),
                "attributes": attrs_dict(dict(da.attrs)),
            }
            if vname in SAMPLED_FIELDS or vname.lower() in {"lat", "lon"}:
                sampled = summarize_numeric_sample(da)
                if sampled is not None:
                    item["sample"] = sampled
            out["variables"][vname] = item
        ds.close()

    print(
        f"{name}: {len(out['variables'])} data variables; dims={out['dimensions']}",
        flush=True,
    )
    for vname in ("Landcover_inst", "Soiltype_inst", "LANDMASK", "HYMAP_basin"):
        sample = out["variables"].get(vname, {}).get("sample")
        if sample:
            print(
                f"  {vname}: min={sample.get('sample_min')} "
                f"max={sample.get('sample_max')} "
                f"unique={sample.get('unique_count')}",
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
