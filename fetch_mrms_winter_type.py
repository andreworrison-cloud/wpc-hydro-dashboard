#!/usr/bin/env python3
"""Supplement the RALA archive with experimental rain/mix/snow/ice images.

Independent optional build: a failed supplement must not interrupt RALA.
Only the completed supplement mutates the RALA manifest, atomically at the end.
Each radar frame is paired to MRMS PrecipFlag within 2 minutes. Winter phase
uses the HRRR one-hour forecast valid at/before that radar frame (<=90 min old).
HRRR f00 phase fields are commonly all zero and are deliberately not assumed
to provide analysis-time precipitation types. Unknown/no-precip model pixels
fall back to the supported MRMS rain/snow class, never to invented mix or ice.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import shutil
import tempfile
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path
from PIL import Image

import numpy as np
import rasterio
from rasterio.io import MemoryFile
from rasterio.enums import Resampling
from rasterio.warp import reproject
import fetch_mrms_rala as rala
import fetch_mrms_rala_loop as loop
import winter_precip as winter
# Load pyproj/GDAL before ecCodes: wheel builds can collide during cleanup.
import eccodes as ec

UTC = timezone.utc
FIELDS = {"CRAIN": 33, "CSNOW": 36, "CICEP": 35, "CFRZR": 34}
ROOTS = ("https://noaa-hrrr-bdp-pds.s3.amazonaws.com",
         "https://nomads.ncep.noaa.gov/pub/data/nccf/com/hrrr/prod")


def request(session, url, **kwargs):
    response = session.get(url, timeout=(10, 30), **kwargs)
    response.raise_for_status()
    return response


def flag_inventory(session, now):
    found, errors = {}, []
    directory = "https://mrms.ncep.noaa.gov/2D/PrecipFlag/"
    try:
        html = request(session, directory).text
        for name, stamp in re.findall(r'(MRMS_PrecipFlag_00\.00_(\d{8}-\d{6})\.grib2\.gz)', html):
            found[("ncep",stamp)] = rala.SourceCandidate("NCEP MRMS HTTPS", datetime.strptime(stamp, "%Y%m%d-%H%M%S").replace(tzinfo=UTC), directory+name, name)
    except Exception as exc:
        errors.append(str(exc))
    # Discover AWS too: NCEP inventories can be shorter than the radar archive.
    for day in sorted({(now-timedelta(hours=7)).strftime("%Y%m%d"), now.strftime("%Y%m%d")}):
        try:
            prefix = f"CONUS/PrecipFlag_00.00/{day}/"
            xml = ET.fromstring(request(session, rala.NODD_ROOT+"/", params={"list-type":"2", "prefix":prefix, "max-keys":1000}).content)
            if any(e.tag.endswith("IsTruncated") and e.text == "true" for e in xml.iter()):
                raise ValueError("Truncated MRMS flag inventory")
            for element in xml.iter():
                if not element.tag.endswith("Key") or not element.text:
                    continue
                key = element.text
                match = re.search(r"MRMS_PrecipFlag_00\.00_(\d{8}-\d{6})\.grib2\.gz$",key)
                if match:
                    stamp = datetime.strptime(match.group(1),"%Y%m%d-%H%M%S").replace(tzinfo=UTC)
                    # Retain both providers at equal times so a download error
                    # on NCEP can fall back to AWS for the same observation.
                    found.setdefault(("aws",stamp.strftime("%Y%m%d-%H%M%S")), rala.SourceCandidate("NOAA NODD MRMS (AWS)", stamp, rala.NODD_ROOT+"/"+key, key))
        except Exception as exc:
            errors.append(str(exc))
    if not found:
        raise RuntimeError("No MRMS PrecipFlag inventory: "+str(errors))
    return list(found.values()), errors


def fetch_flag(session, candidate, radar_time, td):
    name = Path(td)/"flag.grib2"
    raw = gzip.decompress(request(session, candidate.url).content)
    name.write_bytes(raw)
    with name.open("rb") as handle:
        gid = ec.codes_grib_new_from_file(handle)
        try:
            expected = (209, 6, 0)
            actual = tuple(ec.codes_get(gid, k) for k in ("discipline", "parameterCategory", "parameterNumber"))
            if actual != expected:
                raise ValueError("Not MRMS PrecipFlag")
            stamp = datetime.strptime(str(ec.codes_get(gid,"dataDate"))+f'{ec.codes_get(gid,"dataTime"):04d}', "%Y%m%d%H%M").replace(tzinfo=UTC)
            if abs((stamp-candidate.timestamp).total_seconds()) > 60 or abs((stamp-radar_time).total_seconds()) > 120:
                raise ValueError("MRMS PrecipFlag valid-time mismatch")
        finally:
            ec.codes_release(gid)
    data, transform, _ = rala.decode_grib(name)
    allowed = (-3, -1, 0, 1, 3, 6, 7, 10, 91, 96)
    if not np.isin(data[np.isfinite(data)], allowed).all():
        raise ValueError("Unrecognized MRMS precipitation flags")
    return data, transform, hashlib.sha256(raw).hexdigest()


def hrrr_fields(session, valid, cache):
    key = rala.iso_z(valid)
    if key in cache:
        value = cache[key]
        if isinstance(value, Exception):
            raise value
        return value
    cycle = valid-timedelta(hours=1)
    errors = []
    for root in ROOTS:
        try:
            url = root+f"/hrrr.{cycle:%Y%m%d}/conus/hrrr.t{cycle:%H}z.wrfsfcf01.grib2"
            lines = request(session, url+".idx").text.strip().splitlines()
            records = {}
            for a, b in zip(lines, lines[1:]):
                x, y = a.split(":"), b.split(":")
                if x[3] in FIELDS and x[4] == "surface":
                    if x[2] != f"d={cycle:%Y%m%d%H}" or x[3] in records or int(y[1]) <= int(x[1]):
                        raise ValueError("Invalid HRRR inventory")
                    records[x[3]] = (int(x[1]), int(y[1])-1)
            if set(records) != set(FIELDS):
                raise ValueError("Missing HRRR winter fields")
            fields, provenance, signature, grid = {}, [], None, None
            for variable, (start, end) in records.items():
                response = request(session, url, headers={"Range":f"bytes={start}-{end}"})
                raw = response.content
                if response.status_code != 206 or not response.headers.get("Content-Range", "").startswith(f"bytes {start}-{end}/") or len(raw) != end-start+1:
                    raise ValueError("HRRR byte-range mismatch")
                if raw[:4] != b"GRIB" or raw[-4:] != b"7777" or int.from_bytes(raw[8:16],"big") != len(raw):
                    raise ValueError("Truncated HRRR record")
                gid = ec.codes_new_from_message(raw)
                try:
                    keys = ("dataDate", "dataTime", "endStep", "discipline", "parameterCategory", "parameterNumber", "typeOfLevel")
                    actual = tuple(ec.codes_get(gid,k) for k in keys)
                    expected = (int(cycle.strftime("%Y%m%d")), cycle.hour*100, 1, 0, 1, FIELDS[variable], "surface")
                    if actual != expected:
                        raise ValueError(f"HRRR field/time mismatch {variable}: {actual}")
                    if (ec.codes_get(gid,"validityDate"),ec.codes_get(gid,"validityTime")) != (int(valid.strftime("%Y%m%d")),valid.hour*100):
                        raise ValueError("HRRR validity time mismatch")
                    sig = ec.codes_get(gid,"md5Section3")
                    if signature is not None and sig != signature:
                        raise ValueError("HRRR phase grids differ")
                    signature = sig
                finally:
                    ec.codes_release(gid)
                with MemoryFile(raw) as mem, mem.open() as ds:
                    a = ds.read(1, masked=True).astype("float32").filled(np.nan)
                    if a.shape != (1059,1799) or not np.isin(a[np.isfinite(a)],(0,1)).all():
                        raise ValueError("Invalid HRRR phase grid or values")
                    fields[variable] = a
                    grid = (ds.transform, ds.crs)
                provenance.append({"variable":variable,"url":url,"start":start,"end":end,"sha256":hashlib.sha256(raw).hexdigest()})
            result = fields, grid, {"cycle_utc":rala.iso_z(cycle),"valid_time_utc":key,"forecast_hour":1,"records":provenance,"fallback_errors":errors}
            cache[key] = result
            return result
        except Exception as exc:
            errors.append(f"{root}: {exc}")
    error = RuntimeError("No valid HRRR phase fields: "+str(errors))
    cache[key] = error
    raise error


def warp(data, transform, crs, shape, target):
    out = np.full(shape, np.nan, dtype="float32")
    reproject(data, out, src_transform=transform, src_crs=crs, src_nodata=np.nan,
              dst_transform=target, dst_crs="EPSG:3857", dst_nodata=np.nan,
              resampling=Resampling.nearest, num_threads=2)
    return out


def validate_frame(frame, name, metadata, output, display):
    stamp = loop.parse_time(frame["valid_time_utc"])
    if name != f"winter_frames/winter_{stamp:%Y%m%dT%H%M%SZ}.png":
        raise ValueError("Invalid winter image path")
    image_path = output/name
    if hashlib.sha256(image_path.read_bytes()).hexdigest() != metadata["image_sha256"]:
        raise ValueError("Winter image checksum mismatch")
    with Image.open(image_path) as image:
        if image.size != (display["image_width_px"],display["image_height_px"]) or image.mode != "RGBA":
            raise ValueError("Winter image dimensions/format mismatch")
        image.verify()
    flag_time = loop.parse_time(metadata["flag_valid_time_utc"])
    if abs((stamp-flag_time).total_seconds())>120:
        raise ValueError("Winter flag time mismatch")
    model = metadata.get("hrrr")
    if model:
        valid, cycle = (loop.parse_time(model[k]) for k in ("valid_time_utc","cycle_utc"))
        if not 0 <= (stamp-valid).total_seconds() <= 90*60 or valid-cycle != timedelta(hours=1) or model["forecast_hour"] != 1:
            raise ValueError("Winter model time mismatch")


def build(args):
    output, cache_dir = Path(args.output_dir), Path(args.cache_dir)
    path = output/loop.MANIFEST_NAME
    manifest = json.loads(path.read_text())
    cached = {}
    try:
        prior = json.loads((cache_dir/loop.MANIFEST_NAME).read_text())
        if prior.get("winter_type",{}).get("revision") == winter.REVISION and prior.get("display") == manifest["display"]:
            cached = {f["valid_time_utc"]:f for f in prior["frames"] if f.get("ptype_png")}
    except (OSError, ValueError, KeyError):
        pass
    session, models, errors = rala.make_session(), {}, []
    # Bound retries for an optional supplement; the base radar has its own job.
    session.mount("https://", __import__("requests").adapters.HTTPAdapter(max_retries=1))
    flags, discovery_errors = flag_inventory(session, loop.parse_time(manifest["latest_valid_time_utc"]))
    pending, projected_model_cache = [], None
    for i, frame in enumerate(manifest["frames"]):
        stamp = loop.parse_time(frame["valid_time_utc"])
        old = cached.get(frame["valid_time_utc"])
        if old:
            try:
                validate_frame(frame,old["ptype_png"],old["ptype"],cache_dir,manifest["display"])
            except (OSError,ValueError,KeyError):
                old = None
        if old:
            dest = output/old["ptype_png"]
            dest.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(cache_dir/old["ptype_png"], dest)
            pending.append((frame, old["ptype_png"], old["ptype"]))
            print(f"Winter type [{i+1}/{len(manifest['frames'])}] reuse {stamp}", flush=True)
            continue
        print(f"Winter type [{i+1}/{len(manifest['frames'])}] build {stamp}", flush=True)
        try:
            candidates = sorted((f for f in flags if abs((f.timestamp-stamp).total_seconds())<=120), key=lambda f:(abs((f.timestamp-stamp).total_seconds()), f.timestamp>stamp))
            if not candidates:
                raise ValueError("No MRMS flag within two minutes")
            with tempfile.TemporaryDirectory(prefix="winter_type_") as td:
                selected = None
                for candidate in candidates:
                    try:
                        flag, flag_transform, flag_hash = fetch_flag(session,candidate,stamp,td)
                        selected = candidate
                        break
                    except Exception as exc:
                        errors.append(f"{stamp} flag: {exc}")
                if selected is None:
                    raise ValueError("No decodable MRMS flag")
                radar_candidate = rala.SourceCandidate(frame["source_provider"],stamp,frame["source_url"],frame["source_key"])
                gz, raw = Path(td)/"radar.gz", Path(td)/"radar.grib2"
                rala.download_file(session,radar_candidate,gz)
                rala.gunzip_file(gz,raw)
                radar, transform, _ = rala.decode_grib(raw)
                dbz, target, bounds = rala.reproject_dbz(radar,transform,manifest["display"]["image_width_px"])
                if rala.leaflet_bounds_from_mercator(bounds) != manifest["display"]["leaflet_bounds"]:
                    raise ValueError("Radar/type display bounds mismatch")
                projected_flag = warp(flag,flag_transform,"EPSG:4326",dbz.shape,target)
                model_classes, model_meta = None, None
                # Do not select future-valid guidance or carry older guidance indefinitely.
                for age_hours in (0,1):
                    valid = stamp.replace(minute=0,second=0,microsecond=0)-timedelta(hours=age_hours)
                    if (stamp-valid).total_seconds()>90*60:
                        continue
                    try:
                        native, (model_transform,model_crs), model_meta = hrrr_fields(session,valid,models)
                        if projected_model_cache is not None and projected_model_cache[0] == valid:
                            model_classes = projected_model_cache[1]
                        else:
                            shape = native["CRAIN"].shape
                            phase, support = winter.classify(np.ones(shape,dtype=np.uint8), *(native[v] for v in ("CRAIN","CSNOW","CICEP","CFRZR")))
                            phase[~support] = 0
                            model_classes = warp(phase.astype("float32"),model_transform,model_crs,dbz.shape,target)
                            projected_model_cache = valid,model_classes
                        break
                    except Exception as exc:
                        errors.append(f"{stamp} model: {exc}")
                classes, supported = winter.classify(projected_flag)
                if model_classes is not None:
                    supported = (classes>0) & np.isin(model_classes,(1,2,3,4))
                    classes[supported] = model_classes[supported].astype(np.uint8)
                rgba = winter.colorize(dbz,classes)
                name = f"winter_frames/winter_{stamp:%Y%m%dT%H%M%SZ}.png"
                loop.save_rgba_png(rgba,output/name)
                visible = rgba[...,3]>0
                metadata = {"flag_valid_time_utc":selected.iso(),"flag_source_url":selected.url,"flag_sha256":flag_hash,
                            "hrrr":model_meta,"model_supported_visible_pixels":int(np.count_nonzero(supported & visible)),
                            "mrms_fallback_visible_pixels":int(np.count_nonzero(~supported & visible)),
                            "class_visible_pixels":{winter.LABELS[c]:int(np.count_nonzero(visible & (classes==c))) for c in winter.COLORS}}
                metadata["image_sha256"] = hashlib.sha256((output/name).read_bytes()).hexdigest()
                validate_frame(frame,name,metadata,output,manifest["display"])
                pending.append((frame,name,metadata))
        except Exception as exc:
            errors.append(f"{stamp}: {type(exc).__name__}: {exc}")
            print(f"Winter type unavailable: {errors[-1]}",flush=True)
    # A partial supplement is not advertised as a complete loop.
    if len(pending) != len(manifest["frames"]):
        raise RuntimeError(f"Winter supplement incomplete: {len(pending)}/{len(manifest['frames'])}; {errors[-5:]}")
    for frame,name,meta in pending:
        frame.update(ptype_png=name,ptype=meta)
    manifest["winter_type"] = {"revision":winter.REVISION,"experimental":True,"method":"MRMS radar + HRRR 1-h forecast precipitation type",
        "classes":[{"id":c,"label":winter.LABELS[c],"color":winter.COLORS[c]} for c in winter.COLORS],
        "max_flag_offset_minutes":2,"max_model_age_minutes":90,"model_grid_km":3,"radar_grid_km":1,
        "fallback":"MRMS rain/snow only where HRRR phase is unavailable or dry; no inferred transition band",
        "errors":discovery_errors+errors}
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(manifest,indent=2)+"\n")
    temp.replace(path)
    print(f"Winter precipitation type PASS: {len(pending)} frames",flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir",required=True)
    parser.add_argument("--cache-dir",default="__no_cache__")
    build(parser.parse_args())
