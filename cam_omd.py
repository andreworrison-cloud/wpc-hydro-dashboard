"""Read native OMD REFS neighborhood probabilities, with checked fallbacks.

The operational AWS indexes permit small exact byte-range transfers. A full
GRIB fallback supports the former NOMADS parallel feed without index files.
"""
import io
import json
import logging
import re
from pathlib import Path

import eccodes as ec
import numpy as np
import requests
from rasterio.io import MemoryFile

from cam_member_io import Grid, atomic_json, digest, grib_framing

LOG = logging.getLogger(__name__)
THRESHOLDS_MM = (12.7, 25.4, 50.8, 76.2)


def product_urls(init, product, fxx):
    rel = (f"refs.{init:%Y%m%d}/{init:%H}/ensprod/"
           f"refs.t{init:%H}z.{product}.f{fxx:02d}.conus.grib2")
    return [
        "https://noaa-rrfs-ops-pds.s3.amazonaws.com/" + rel,
        "https://nomads.ncep.noaa.gov/pub/data/nccf/com/refs/prod/" + rel,
        "https://nomads.ncep.noaa.gov/pub/data/nccf/com/refs/para/" + rel,
        "https://noaa-rrfs-pds.s3.amazonaws.com/refs/v1.0/" + rel,
    ]


def selected_ranges(index, init, fxx, product, durations=()):
    rows = []
    for line in index.splitlines():
        p = [x.strip() for x in line.split(":")]
        if len(p) > 2 and p[1].isdigit():
            rows.append((int(p[1]), p))
    if not rows or rows[0][0] != 0 or any(b[0] < a[0] for a, b in zip(rows, rows[1:])):
        raise ValueError("Invalid OMD GRIB index")
    offsets = sorted(set(x[0] for x in rows))
    ends = dict(zip(offsets, [x-1 for x in offsets[1:]] + [None]))
    targets = THRESHOLDS_MM if product == "prob" else tuple(durations)
    matched = {k: [] for k in targets}
    for start, parts in rows:
        if f"d={init:%Y%m%d%H}" not in parts or "surface" not in parts:
            continue
        if "Neighborhood Probability" not in parts:
            continue
        parameter = "APCP" if product == "prob" else "PPFFG"
        if parameter not in parts:
            continue
        for key in targets:
            duration = 1 if product == "prob" else key
            timing = {f"{fxx-duration}-{fxx} hour acc fcst", f"{fxx-duration}-{fxx} hr acc fcst"}
            if fxx == duration:
                timing |= {f"{duration} hour acc fcst", f"{duration} hr acc fcst"}
            limit = key if product == "prob" else duration
            if any(t in parts for t in timing) and any(
                re.fullmatch(r"prob\s*>\s*" + re.escape(f"{limit:g}"), p) for p in parts
            ):
                matched[key].append((start, ends[start]))
    if any(len(v) != 1 or v[0][1] is None for v in matched.values()):
        raise ValueError(f"Missing, ambiguous or unbounded OMD {product} fields")
    return [v[0] for v in matched.values()]


def decode(raw, init, fxx, product, durations, expected_grid=None):
    """Validate probability identity before decoding in GDAL's north-up order."""
    grib_framing(raw)
    targets = THRESHOLDS_MM if product == "prob" else tuple(durations)
    fields, grid = {}, expected_grid
    with io.BytesIO(raw) as stream:
        while True:
            # ecCodes requires a real file descriptor; new_from_message below
            # uses the exact framing offsets and does not require a disk file.
            offset = stream.tell()
            head = stream.read(16)
            if not head:
                break
            size = int.from_bytes(head[8:16], "big")
            message = head + stream.read(size-16)
            gid = ec.codes_new_from_message(message)
            try:
                get = lambda key: ec.codes_get(gid, key)
                parameter = (get("discipline"), get("parameterCategory"), get("parameterNumber"))
                if parameter != ((0, 1, 8) if product == "prob" else (1, 1, 194)):
                    continue
                start, end = get("startStep"), get("endStep")
                duration = end - start
                if end != fxx or (duration != 1 if product == "prob" else duration not in targets):
                    continue
                if get("probabilityType") != 1:
                    continue
                upper = float(get("upperLimit"))
                key = next((x for x in targets if abs(upper-x) < .001), None)
                if key is None or (product == "ffri" and key != duration):
                    continue
                expected = {"dataDate": int(init.strftime("%Y%m%d")), "dataTime": init.hour*100,
                            "stepUnits": 1, "typeOfLevel": "surface",
                            "typeOfGeneratingProcess": 194, "generatingProcessIdentifier": 136,
                            "productDefinitionTemplateNumber": 9,
                            "totalNumberOfForecastProbabilities": 14}
                if any(get(k) != v for k, v in expected.items()):
                    raise ValueError("Wrong OMD cycle, model, duration units or neighborhood probability process")
                if key in fields:
                    raise ValueError("Duplicate OMD probability field")
                with MemoryFile(message) as mem:
                    with mem.open() as src:
                        current = Grid.from_source(src)
                        if grid is None:
                            grid = current
                        if not grid.matches(src):
                            raise ValueError("OMD/SPC native grids differ; new mapping must be qualified")
                        arr = src.read(1, masked=True).filled(np.nan).astype("float32")
                # The operational PPFFG product encodes unavailable RFC
                # coverage as -10, without a GRIB bitmap. Packing perturbs
                # that sentinel and zero by about 1e-5 percentage points.
                if product == "ffri":
                    # Native interpolation at the missing-domain boundary
                    # also produces intermediate negative values. None is a
                    # physical probability; retain all as unavailable.
                    arr[arr < -.001] = np.nan
                finite = arr[np.isfinite(arr)]
                if not finite.size or np.any(finite < -.001) or np.any(finite > 100.001):
                    raise ValueError("Invalid OMD probability values")
                arr = np.clip(arr, 0, 100)
                fields[key] = arr
            finally:
                ec.codes_release(gid)
    if set(fields) != set(targets):
        raise ValueError(f"Missing checked OMD {product} fields: {set(targets)-set(fields)}")
    return fields, grid


class OMDReader:
    def __init__(self, sources):
        self.sources = sources
        self.records = []

    def probe(self, init, fxx):
        errors = []
        for url in product_urls(init, "prob", fxx):
            try:
                selected_ranges(self.sources.probe_index(url), init, fxx, "prob")
                return {"forecast_hour": fxx, "url": url}
            except Exception as exc:
                errors.append(f"{url}: {exc}")
                # Legacy NOMADS feeds sometimes have no .idx; a bounded
                # one-byte GRIB probe may establish presence only.
                try:
                    with requests.get(url, headers={"Range": "bytes=0-0"}, timeout=(3, 8), stream=True) as response:
                        response.raise_for_status()
                        if next(response.iter_content(1), b"") == b"G":
                            return {"forecast_hour": fxx, "url": url, "probe": "GRIB object"}
                except Exception:
                    pass
        raise ValueError("OMD terminal hour unavailable: " + "; ".join(errors))

    def fetch(self, init, fxx, product, durations=(), grid=None):
        signature = "-".join(str(d) for d in durations) if product == "ffri" else "hourly4"
        folder = self.sources.cache / "omd-native-v1" / init.strftime("%Y%m%d%H")
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{product}_f{fxx:02d}_{signature}.grib2"
        meta_path = path.with_suffix(".json")
        if path.exists() and meta_path.exists():
            try:
                raw = path.read_bytes(); meta = json.loads(meta_path.read_text())
                if digest(raw) != meta["selected_sha256"]:
                    raise ValueError("OMD checkpoint hash mismatch")
                fields, grid = decode(raw, init, fxx, product, durations, grid)
                self.records.append(dict(meta, from_cache=True, transferred_bytes=0))
                return fields, grid
            except Exception:
                path.unlink(missing_ok=True); meta_path.unlink(missing_ok=True)
        errors = []
        for url in product_urls(init, product, fxx):
            try:
                try:
                    ranges = selected_ranges(self.sources.index(url), init, fxx, product, durations)
                    # Requested records are contiguous in operational products.
                    # A bounding range is still small and every message is
                    # inspected; unrelated fields never enter the output.
                    lo, hi = min(x[0] for x in ranges), max(x[1] for x in ranges)
                    raw, transfer = self.sources.get(url, max_bytes=16_000_000, byte_range=(lo, hi))
                    mode = "indexed byte range"
                except Exception as exc:
                    LOG.info("OMD indexed transfer unavailable (%s); trying checked full GRIB", exc)
                    raw, transfer = self.sources.get(url, max_bytes=125_000_000)
                    mode = "full GRIB fallback"
                fields, checked_grid = decode(raw, init, fxx, product, durations, grid)
                meta = {"init_utc": init.isoformat(), "forecast_hour": fxx, "product": product,
                        "durations_hours": list(durations), "url": url, "transfer_mode": mode,
                        "selected_sha256": digest(raw), "source": transfer,
                        "from_cache": False, "transferred_bytes": len(raw)}
                temporary = path.with_suffix(".part"); temporary.write_bytes(raw); temporary.replace(path)
                atomic_json(meta_path, meta)
                self.records.append(meta)
                return fields, checked_grid
            except Exception as exc:
                errors.append(f"{url}: {type(exc).__name__}: {exc}")
        raise RuntimeError("OMD probability unavailable: " + "; ".join(errors))
