#!/usr/bin/env python3
"""RTMA fills, HRRR sea-level pressure and independently timed METAR reports.

NOMADS and NOAA NODD/AWS use their own inventories and byte offsets. All inputs
use validated native grids. Each component retains its previous assets on failure.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import requests
from PIL import Image
# Load GDAL/PROJ before the ecCodes wheel's bundled native dependencies.
from pyproj import CRS, Transformer
from rasterio.enums import Resampling
from rasterio.transform import Affine, from_bounds
from rasterio.warp import reproject
from eccodes import codes_new_from_message, codes_get, codes_get_array, codes_release
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from surface_analysis import (REVISION, PRESSURE_REVISION, LEGACY_KEYS, V2_KEYS, RTMA_KEYS, BOUNDS, PRODUCTS, SOURCE_FIELDS, ANALYSIS_WARN_MINUTES,
                              ANALYSIS_HIDE_MINUTES, STATION_HIDE_MINUTES,
                              colorize, display_values, iso, parse_time, parse_metars,
                              derive_products)
from surface_sampling import pack_grid, unpack_grid
from surface_pressure import blend_pressure
from surface_contours import smooth_masked, contour_collection, validate_collection

UTC = timezone.utc
METAR_URL = "https://aviationweather.gov/data/cache/metars.cache.csv.gz"
WIDTH = 3600
PRESSURE_FIELD = {**PRODUCTS["mslp"], "type": "meanSea", "grib": (0,3,198), "source_units": "Pa"}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def session():
    s = requests.Session()
    s.headers["User-Agent"] = "WPC-Hydrometeorological-Dashboard-Surface/1.0"
    s.mount("https://", HTTPAdapter(max_retries=Retry(total=2, backoff_factor=.5,
            status_forcelist=[429, 500, 502, 503, 504])))
    return s


def inventory(text, cycle, fields=None):
    rows = [line.split(":") for line in text.splitlines() if line.strip()]
    offsets = [int(r[1]) for r in rows]
    if offsets != sorted(set(offsets)):
        raise ValueError("Invalid analysis inventory offsets")
    result = {}
    for key, p in (SOURCE_FIELDS if fields is None else fields).items():
        level = "mean sea level" if p["type"] == "meanSea" else f'{p["level"]} m above ground'
        found = [i for i, r in enumerate(rows) if len(r) >= 6 and
                 r[2] == "d=" + cycle.strftime("%Y%m%d%H") and r[3] == p["parameter"] and
                 r[4] == level and r[5] == "anl"]
        if len(found) != 1 or found[0] == len(rows) - 1:
            raise ValueError(f"Missing/ambiguous analysis field: {key}")
        i = found[0]
        result[key] = (offsets[i], offsets[i+1] - 1)
    return result


def fetch_range(s, url, start, end):
    r = s.get(url, headers={"Range": f"bytes={start}-{end}"}, timeout=(10, 60))
    r.raise_for_status()
    if r.status_code != 206 or not r.headers.get("Content-Range", "").startswith(f"bytes {start}-{end}/"):
        raise ValueError("Server did not honor analysis byte range")
    raw = r.content
    if len(raw) != end-start+1 or raw[:4] != b"GRIB" or raw[7] != 2 or raw[-4:] != b"7777" or int.from_bytes(raw[8:16], "big") != len(raw):
        raise ValueError("Truncated or unexpected GRIB2 message")
    return raw


def decode(raw, key, cycle):
    h = codes_new_from_message(raw)
    try:
        get = lambda k: codes_get(h, k)
        p = PRESSURE_FIELD if key == "mslp" else SOURCE_FIELDS[key]
        grib = tuple(int(get(k)) for k in ("discipline","parameterCategory","parameterNumber"))
        if grib != p["grib"] or get("typeOfLevel") != p["type"] or get("level") != p["level"]:
            raise ValueError(f"Wrong analysis parameter/level for {key}: {get('shortName')}")
        if get("units") != p["source_units"]:
            raise ValueError("Unexpected analysis source units")
        for prefix in ("data", "validity"):
            if int(get(prefix+"Date")) != int(cycle.strftime("%Y%m%d")) or int(get(prefix+"Time")) != cycle.hour * 100:
                raise ValueError("Analysis GRIB valid time differs from inventory")
        if get("step") != 0 or get("gridType") != "lambert" or get("jPointsAreConsecutive") or get("alternativeRowScanning"):
            raise ValueError("Unexpected analysis grid or forecast lead")
        nx, ny = int(get("Nx")), int(get("Ny"))
        dx, dy = float(get("DxInMetres")), float(get("DyInMetres"))
        expected = (1799,1059,3000) if key == "mslp" else (2345,1597,2539.703)
        if (nx,ny) != expected[:2] or abs(dx-expected[2]) > 1 or abs(dy-dx) > .1:
            raise ValueError("Unexpected CONUS native grid")
        crs = CRS.from_proj4(f"+proj=lcc +lat_1={get('Latin1InDegrees')} +lat_2={get('Latin2InDegrees')} +lat_0={get('LaDInDegrees')} +lon_0={get('LoVInDegrees')} +R={get('radius')} +units=m")
        x, y = Transformer.from_crs(4326, crs, always_xy=True).transform(get("longitudeOfFirstGridPointInDegrees"), get("latitudeOfFirstGridPointInDegrees"))
        sx = -dx if get("iScansNegatively") else dx
        sy = dy if get("jScansPositively") else -dy
        transform = Affine(sx, 0, x-sx/2, 0, sy, y-sy/2)
        a = codes_get_array(h, "values").reshape(ny, nx).astype("float32")
        a[a == get("missingValue")] = np.nan
        return display_values(key, a), transform, crs, get("md5GridSection"), [ny, nx]
    finally:
        codes_release(h)


def project_fields(fields, transform, crs, target, width, height):
    """Bilinearly reproject scalar fields before colorization."""
    def project(a):
        output = np.full((height,width),np.nan,dtype="float32")
        reproject(a,output,src_transform=transform,src_crs=crs,dst_transform=target,
                  dst_crs="EPSG:3857",src_nodata=np.nan,dst_nodata=np.nan,resampling=Resampling.bilinear)
        return output
    result={key:project(a) for key,a in fields.items()}
    if any(np.isfinite(a).mean()<.85 for a in result.values()):
        raise ValueError("Incomplete analysis display coverage")
    return result


def display_grid():
    merc = Transformer.from_crs(4326,3857,always_xy=True)
    west,south=merc.transform(BOUNDS[0][1],BOUNDS[0][0]);east,north=merc.transform(BOUNDS[1][1],BOUNDS[1][0])
    height=round(WIDTH*(north-south)/(east-west))
    return from_bounds(west,south,east,north,WIDTH,height),height


def write_products(root, dest, display, target, cycle, centers=()):
    dest.mkdir(parents=True,exist_ok=True)
    products={}
    for key,output in display.items():
        path=dest/(key+".png")
        Image.fromarray(colorize(key,output)).save(path,optimize=True)
        products[key]={**PRODUCTS[key],"path":path.relative_to(root).as_posix(),"sha256":sha(path.read_bytes()),
                       "applicable_pixels":int(np.isfinite(output).sum()),"resampling":"bilinear scalar display"}
        sample_path=dest/(key+"_samples.bin.gz")
        sample_path.write_bytes(pack_grid(key,output,iso(cycle)))
        products[key]["sampling"]={"path":sample_path.relative_to(root).as_posix(),"sha256":sha(sample_path.read_bytes()),"encoding":"gzip-int16-v1"}
        contours=contour_collection(key,output,target,iso(cycle),centers if key=="mslp" else ())
        validate_collection(contours,key,iso(cycle))
        contour_path=dest/(key+"_contours.geojson")
        contour_path.write_text(json.dumps(contours,separators=(",",":"),allow_nan=False))
        products[key]["contours"]={"path":contour_path.relative_to(root).as_posix(),"sha256":sha(contour_path.read_bytes()),
                                    "interval":PRODUCTS[key]["contour_interval"],"feature_count":len(contours["features"])}
    return products


def build_analysis(s, root, now, previous):
    errors = []
    # Search completed hours, newest first, including the previous UTC day.
    for lag in range(5):
        cycle = now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=lag)
        if (now-cycle).total_seconds() >= ANALYSIS_HIDE_MINUTES * 60:
            continue
        old = previous.get("analysis")
        if old and parse_time(old["valid_time"]) > cycle:
            break  # Never regress an already validated analysis.
        if old and old["revision"] == REVISION and parse_time(old["valid_time"]) == cycle:
            return old, "Retained current complete hourly analysis"
        name = f"rtma2p5.{cycle:%Y%m%d}/rtma2p5.t{cycle:%H}z.2dvaranl_ndfd.grb2_wexp"
        for provider, base in (("NOAA NODD/AWS", "https://noaa-rtma-pds.s3.amazonaws.com/"),
                               ("NOMADS", "https://nomads.ncep.noaa.gov/pub/data/nccf/com/rtma/prod/")):
            url = base + name
            try:
                r = s.get(url + ".idx", timeout=(10, 25)); r.raise_for_status()
                ranges = inventory(r.text, cycle)
                fields, provenance, grid = {}, [], None
                for key, (start, end) in ranges.items():
                    raw = fetch_range(s, url, start, end)
                    a, transform, crs, grid_id, shape = decode(raw, key, cycle)
                    if grid is not None and grid != grid_id:
                        raise ValueError("RTMA fields use different native grids")
                    grid = grid_id; fields[key] = a
                    provenance.append({"key": key, "provider": provider, "url": url,
                                       "byte_range": [start, end], "sha256": sha(raw)})
                    print("Decoded", cycle.isoformat(), key, provider, flush=True)
                gen = cycle.strftime("%Y%m%d%H") + "-" + sha((REVISION+json.dumps(provenance)).encode())[:16]
                dest = root / "generations" / gen
                target,height = display_grid()
                display = derive_products(project_fields(fields,transform,crs,target,WIDTH,height))
                products = write_products(root,dest,display,target,cycle)
                return {"valid_time": iso(cycle), "revision": REVISION, "generation": gen,
                        "native_spacing_km": 2.5, "native_shape": shape, "grid_id": grid,
                        "width": WIDTH, "height": height, "bounds": BOUNDS, "crs": "EPSG:3857",
                        "resampling": "bilinear scalar display", "products": products,
                        "sources": provenance}, "Complete hourly analysis"
            except Exception as e:
                message = f"{cycle:%Y%m%d%H} {provider}: {e}"
                errors.append(message); print(message, flush=True)
    raise RuntimeError("; ".join(errors[-4:]) or "No non-regressing RTMA analysis available")


def build_pressure_analysis(s, root, now, previous, points=()):
    """Native HRRR f00 MSLMA, never terrain PRES or an altimeter substitution."""
    errors=[]
    old=previous.get("pressure_analysis")
    for lag in range(5):
        cycle=now.replace(minute=0,second=0,microsecond=0)-timedelta(hours=lag)
        if (now-cycle).total_seconds()>=ANALYSIS_HIDE_MINUTES*60:
            continue
        if old and parse_time(old["valid_time"])>cycle:
            break
        if old and old["revision"]==PRESSURE_REVISION and parse_time(old["valid_time"])==cycle and old.get("objective_analysis",{}).get("accepted_stations",0)>0:
            return old,"Retained current complete pressure analysis"
        name=f"hrrr.{cycle:%Y%m%d}/conus/hrrr.t{cycle:%H}z.wrfsfcf00.grib2"
        for provider,base in (("NOAA NODD/AWS","https://noaa-hrrr-bdp-pds.s3.amazonaws.com/"),
                              ("NOMADS","https://nomads.ncep.noaa.gov/pub/data/nccf/com/hrrr/prod/")):
            url=base+name
            try:
                r=s.get(url+".idx",timeout=(10,25));r.raise_for_status()
                start,end=inventory(r.text,cycle,{"mslp":PRESSURE_FIELD})["mslp"]
                raw=fetch_range(s,url,start,end)
                a,transform,crs,grid,shape=decode(raw,"mslp",cycle)
                a,objective=blend_pressure(a,transform,crs,points,cycle,now)
                a=smooth_masked(a,PRODUCTS["mslp"]["smoothing_km"]*1000/abs(transform.a))
                provenance=[{"key":"mslp","provider":provider,"url":url,"byte_range":[start,end],"sha256":sha(raw)}]
                provenance.append({"key":"reported_mslp","provider":"AWC METAR","url":METAR_URL,
                                   "sha256":sha(json.dumps(list(points),sort_keys=True).encode())})
                gen=cycle.strftime("%Y%m%d%H")+"-"+sha((PRESSURE_REVISION+json.dumps(provenance)).encode())[:16]
                target,height=display_grid()
                products=write_products(root,root/"pressure"/gen,project_fields({"mslp":a},transform,crs,target,WIDTH,height),target,cycle)
                print("Decoded",cycle.isoformat(),"mslp",provider,flush=True)
                return {"valid_time":iso(cycle),"revision":PRESSURE_REVISION,"generation":gen,
                        "native_spacing_km":3,"native_shape":shape,"grid_id":grid,
                        "width":WIDTH,"height":height,"bounds":BOUNDS,"crs":"EPSG:3857",
                        "resampling":"bilinear scalar display","products":products,"sources":provenance,
                        "objective_analysis":objective},"Complete hourly pressure analysis"
            except Exception as e:
                message=f"{cycle:%Y%m%d%H} {provider}: {e}"
                errors.append(message);print(message,flush=True)
    raise RuntimeError("; ".join(errors[-4:]) or "No non-regressing pressure analysis available")


def validate_package(root, metadata=None):
    m = metadata if metadata is not None else json.loads((root / "metadata.json").read_text())
    if m.get("schema") != "surface-suite-v1" or m.get("policy") != {"analysis_warn_minutes": 150, "analysis_hide_minutes": 240, "station_hide_minutes": 90}:
        raise ValueError("Wrong surface schema")
    a = m.get("analysis")
    expected={"rtma-surface-v1":set(LEGACY_KEYS),"rtma-surface-v2":set(V2_KEYS),"rtma-surface-v3":set(RTMA_KEYS),"rtma-surface-v4":set(RTMA_KEYS),REVISION:set(RTMA_KEYS)}
    if a and (set(a["products"]) != expected.get(a["revision"]) or
              a["bounds"] != BOUNDS or a["crs"] != "EPSG:3857" or
              (a["width"], a["height"]) != (3600, 2024)):
        raise ValueError("Incomplete RTMA surface suite/grid")
    pressure=m.get("pressure_analysis")
    if pressure and (pressure.get("revision") not in ("hrrr-mslp-v1","hrrr-mslp-v2","hrrr-mslp-v3",PRESSURE_REVISION) or set(pressure.get("products",{}))!={"mslp"} or
                     pressure.get("native_spacing_km")!=3 or pressure.get("bounds")!=BOUNDS or
                     pressure.get("crs")!="EPSG:3857" or (pressure.get("width"),pressure.get("height"))!=(3600,2024)):
        raise ValueError("Invalid HRRR pressure analysis")
    if pressure and pressure["revision"] == PRESSURE_REVISION:
        o = pressure.get("objective_analysis", {})
        count = o.get("accepted_stations")
        if not isinstance(count, int) or not 0 <= count <= 10000 or o.get("mode") != ("observation-adjusted" if count else "HRRR background only"):
            raise ValueError("Invalid pressure observation diagnostics")
    for obj in (m.get("analysis"), pressure, m.get("observations")):
        if not obj:
            continue
        assets = obj["products"].values() if "products" in obj else [obj]
        if "products" in obj:
            for key,p in obj["products"].items():
                sample=p.get("sampling")
                if obj["revision"] in (REVISION,"hrrr-mslp-v3",PRESSURE_REVISION) and not sample:
                    raise ValueError("Missing numeric sample grid")
                if sample:
                    prefix="pressure" if key=="mslp" else "generations"
                    rel=Path(sample["path"])
                    if rel.as_posix()!=f'{prefix}/{obj["generation"]}/{key}_samples.bin.gz' or sample.get("encoding")!="gzip-int16-v1" or sha((root/rel).read_bytes())!=sample["sha256"]:
                        raise ValueError("Sample grid path/checksum mismatch")
                    unpack_grid((root/rel).read_bytes(),key,obj["valid_time"])
                contour=p.get("contours")
                if obj["revision"] in ("rtma-surface-v4","hrrr-mslp-v2","hrrr-mslp-v3",REVISION,PRESSURE_REVISION) and not contour:
                    raise ValueError("Missing surface contour asset")
                if contour:
                    rel=Path(contour["path"])
                    prefix="pressure" if key=="mslp" else "generations"
                    if rel.as_posix()!=f'{prefix}/{obj["generation"]}/{key}_contours.geojson' or sha((root/rel).read_bytes())!=contour["sha256"]:
                        raise ValueError("Contour asset path/checksum mismatch")
                    data=validate_collection(json.loads((root/rel).read_text()),key,obj["valid_time"])
                    if contour.get("feature_count")!=len(data["features"]) or contour.get("interval")!=PRODUCTS[key]["contour_interval"]:
                        raise ValueError("Contour asset count/interval mismatch")
        for p in assets:
            rel = Path(p["path"])
            if rel.is_absolute() or ".." in rel.parts or sha((root/rel).read_bytes()) != p["sha256"]:
                raise ValueError("Surface asset path/checksum mismatch")
            if rel.suffix == ".png":
                with Image.open(root/rel) as im:
                    if im.size != (obj["width"], obj["height"]) or im.mode != "RGBA":
                        raise ValueError("Surface image size/mode mismatch")
                    im.verify()
            elif rel.suffix == ".json":
                reports = json.loads((root/rel).read_text())
                if reports.get("schema") != "surface-stations-v1" or len(reports.get("points", [])) != obj["count"] or reports.get("fetched_at") != obj["fetched_at"]:
                    raise ValueError("METAR package count/time mismatch")
    return m


def build(root, now, clock=None):
    root.mkdir(parents=True, exist_ok=True)
    previous = validate_package(root) if (root/"metadata.json").exists() else {}
    m = {**previous, "schema": "surface-suite-v1", "updated_at": iso(now),
         "policy": {"analysis_warn_minutes": ANALYSIS_WARN_MINUTES,
                    "analysis_hide_minutes": ANALYSIS_HIDE_MINUTES,
                    "station_hide_minutes": STATION_HIDE_MINUTES}, "last_attempt": {}}
    s = session()
    try:
        m["analysis"], message = build_analysis(s, root, now, previous)
        m["last_attempt"]["analysis"] = {"ok": True, "message": message}
    except Exception as e:
        m["last_attempt"]["analysis"] = {"ok": False, "message": str(e)}
        print("Retaining previous RTMA:", e, flush=True)
    try:
        r = s.get(METAR_URL, timeout=(10, 45)); r.raise_for_status()
        raw = r.content
        text = (gzip.decompress(raw) if raw[:2] == b"\x1f\x8b" else raw).decode("utf-8-sig")
        # Rendering the expanded suite can span a few minutes. Check reports
        # against retrieval time, not the earlier RTMA processing start time.
        observed_now=clock() if clock else now
        points = parse_metars(text, observed_now)
        if len(points) < 500:
            raise ValueError("METAR cache has fewer than 500 usable CONUS reports")
        data = json.dumps({"schema": "surface-stations-v1", "fetched_at": iso(observed_now), "points": points}, separators=(",", ":")).encode()
        path = root / "stations" / (observed_now.strftime("%Y%m%d%H%M%S")+"-"+sha(data)[:16]+".json")
        path.parent.mkdir(exist_ok=True); path.write_bytes(data)
        m["observations"] = {"path": path.relative_to(root).as_posix(), "sha256": sha(data),
                             "count": len(points), "fetched_at": iso(observed_now), "source": METAR_URL}
        m["last_attempt"]["observations"] = {"ok": True}
        print("METAR observations:", len(points), flush=True)
    except Exception as e:
        m["last_attempt"]["observations"] = {"ok": False, "message": str(e)}
        print("Retaining previous station observations:", e, flush=True)
    pressure_points = []
    if m.get("observations"):
        pressure_points = json.loads((root/m["observations"]["path"]).read_text())["points"]
    try:
        m["pressure_analysis"],message=build_pressure_analysis(s,root,clock() if clock else now,previous,pressure_points)
        m["last_attempt"]["pressure_analysis"]={"ok":True,"message":message}
    except Exception as e:
        m["last_attempt"]["pressure_analysis"]={"ok":False,"message":str(e)}
        print("Retaining previous pressure analysis:",e,flush=True)
    if not any(m.get(k) for k in ("analysis","pressure_analysis","observations")):
        raise RuntimeError("No validated surface products to publish")
    validate_package(root, m)
    tmp = root / "metadata.tmp"; tmp.write_text(json.dumps(m, indent=2)); tmp.replace(root/"metadata.json")
    validate_package(root)
    # Keep current plus two previous immutable packages for cached readers.
    for directory in (root/"generations", root/"pressure", root/"stations"):
        items = sorted(directory.glob("*"), key=lambda p: p.name, reverse=True)
        active = (m.get("analysis" if directory.name=="generations" else "pressure_analysis",{}).get("generation")
                  if directory.name!="stations" else Path(m.get("observations",{}).get("path","")).name)
        keep = {active}
        keep.update(p.name for p in [p for p in items if p.name != active][:2])
        for old in items:
            if old.name in keep:
                continue
            if old.is_dir(): shutil.rmtree(old)
            else: old.unlink()
    validate_package(root)
    return m


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    if args.validate_only:
        validate_package(args.output); print("Surface package verified")
    else:
        build(args.output, datetime.now(UTC), clock=lambda:datetime.now(UTC))
