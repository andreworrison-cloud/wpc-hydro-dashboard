#!/usr/bin/env python3
"""Validate operational model dashboard packages before publication.

The model workflows restore the last complete live snapshot before fetching new
guidance. This validator allows short upstream delays to retain a still-valid
package, while refusing expired, mixed-generation, or incomplete packages.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import struct
import hashlib
from datetime import datetime, timezone, timedelta
from pathlib import Path

UTC = timezone.utc

CAM_FILES = [
    *(f"cam_ffg_{window}_{model}.png"
      for window in ("3h_to_9h", "9h_to_15h")
      for model in ("spc_refs", "omd_refs", "super")),
    *(f"cam_qpf_{window}_{threshold}_inch_{model}.png"
      for window in ("3h_to_9h", "9h_to_15h")
      for threshold in ("0.5", "1", "2", "3")
      for model in ("spc_refs", "omd_refs", "super")),
]

ERO_FILES = [
    *(f"ero_ffg_{model}.png" for model in ("spc_refs", "omd_refs", "super")),
    *(f"ero_qpf_{threshold}_inch_{model}.png"
      for threshold in ("0.5", "1", "2", "3")
      for model in ("spc_refs", "omd_refs", "super")),
]

RAP_FILES = [
    "rap_corfidi_down.png",
    "rap_corfidi_up.png",
    "rap_diff_adv.png",
    "rap_div250.png",
    "rap_eff_shear.png",
    "rap_f850_700.png",
    "rap_f925_850.png",
    "rap_lr_75.png",
    "rap_lr_sfc3.png",
    "rap_mean_wind.png",
    "rap_mfc.png",
    "rap_mlcape.png",
    "rap_mlcape_diff.png",
    "rap_mlcape_f03.png",
    "rap_mucape.png",
    "rap_mucape_diff.png",
    "rap_mucape_f03.png",
    "rap_pwat.png",
    "rap_pwat_diff.png",
    "rap_pwat_f03.png",
    "rap_sbcape.png",
    "rap_sbcape_diff.png",
    "rap_sbcape_f03.png",
    "rap_scp.png",
    "rap_trans700.png",
    "rap_trans850.png",
    "rap_trans850_diff.png",
    "rap_trans850_f03.png",
    "rap_vort500.png",
]


def parse_time(value: object, label: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} is missing")
    text = value.replace("Z", "+00:00")
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def load_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text())
    except Exception as exc:
        raise ValueError(f"Could not read {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def require_files(root: Path, names: list[str], label: str) -> None:
    missing = []
    for name in names:
        path = root / name
        if not path.is_file() or path.stat().st_size <= 0:
            missing.append(name)
    if missing:
        raise ValueError(
            f"{label} package is incomplete; missing/empty files: "
            + ", ".join(missing)
        )


def validate_cam_generation(root: Path, now: datetime, kind: str) -> tuple[dict, datetime]:
    prefix = "cam" if kind == "cam" else "ero_cam"
    meta = load_json(root / (prefix + "_metadata.json"))
    if meta.get("schema") != "wpc-spc-omd-cam-v1":
        raise ValueError("Legacy HREF metadata cannot be published as SPC REFS")
    spc = parse_time(meta.get("spc_refs_init_utc"), "SPC REFS initialization")
    omd = parse_time(meta.get("omd_refs_init_utc"), "OMD REFS initialization")
    if spc != omd or spc.hour not in (0, 6, 12, 18) or any((spc.minute, spc.second, spc.microsecond)):
        raise ValueError("SPC/OMD cycles must be identical whole 00/06/12/18Z initializations")
    if spc > now + timedelta(minutes=15):
        raise ValueError("CAM initialization is in the future")
    members = meta.get("members") or []
    identity = [(m.get("family"), m.get("perturbation"), m.get("lag_hours")) for m in members]
    expected_members = {("HRRR", "control", h) for h in (0, 6, 12)} | {
        ("RRFS", "control", h) for h in (0, 6, 12)} | {
        ("RRFS_ENS", f"m{n:03d}", 0) for n in (1, 2, 3, 5)}
    if len(identity) != 10 or set(identity) != expected_members or meta.get("spc_member_count") != 10 or any(m.get("weight") != 1 for m in members):
        raise ValueError("The fixed ten-member SPC population is incomplete or changed")
    ffg = meta.get("ffg") or {}
    published = ffg.get("source", {}).get("http_last_modified")
    from email.utils import parsedate_to_datetime
    if not published or parsedate_to_datetime(published).astimezone(UTC) > spc:
        raise ValueError("SPC FFG was not demonstrably available at model initialization")
    snap = parse_time(ffg.get("snapshot_time_utc"), "FFG snapshot")
    ref = parse_time(ffg.get("reference_time_utc"), "FFG reference")
    if not timedelta(0) <= spc-snap < timedelta(hours=3) or not timedelta(0) <= spc-ref < timedelta(hours=9):
        raise ValueError("SPC cycle-time FFG snapshot or reference is stale")
    if parse_time(ffg.get("asof_model_init_utc"), "FFG as-of initialization") != spc:
        raise ValueError("FFG baseline belongs to a different model cycle")
    periods = {"3h_to_9h": (3, 9), "9h_to_15h": (9, 15)} if kind == "cam" else {"ero": (max(0, 12-spc.hour), 36-spc.hour)}
    contract = meta.get("window_contract") or {}
    if set(contract) != set(periods):
        raise ValueError("Missing or unexpected CAM valid windows")
    expected_hours = []
    for key, (start, end) in periods.items():
        w = contract[key]
        hours = list(range(start+1, end+1)); expected_hours += hours
        slots = [{"forecast_hour": h, "duration_hours": d} for h in hours
                 for d in (1, 3, 6) if h-d >= start and (d == 1 or h % 3 == 0)]
        if (w.get("forecast_hours") != hours or w.get("ffg_slots") != slots
                or parse_time(w.get("valid_start_utc"), key+" start") != spc+timedelta(hours=start)
                or parse_time(w.get("valid_end_utc"), key+" end") != spc+timedelta(hours=end)):
            raise ValueError("Incomplete or mismatched accumulation window/cadence contract")
    end = spc+timedelta(hours=max(b for a, b in periods.values()))
    if now >= end:
        raise ValueError("CAM retained package has expired")
    sources = load_json(root / (prefix + "_sources.json"))
    if sources.get("schema") != meta["schema"] or parse_time(sources.get("init_utc"), "Source initialization") != spc:
        raise ValueError("Source evidence belongs to a different generation")
    rows = sources.get("spc_member_hours") or []
    expected_keys = {(m["id"], iso_end) for m in members for h in expected_hours
                     for iso_end in [(spc+timedelta(hours=h)).isoformat()]}
    actual_keys = {(r.get("member"), parse_time(r.get("valid_end_utc"), "Member valid end").isoformat()) for r in rows}
    if len(rows) != len(expected_keys) or actual_keys != expected_keys or sources.get("expected_spc_member_hours") != len(expected_keys):
        raise ValueError("Source evidence does not contain all ten members at every required hour")
    by_id = {m["id"]: m for m in members}
    for row in rows:
        member = by_id[row["member"]]
        mi = spc-timedelta(hours=member["lag_hours"])
        valid = parse_time(row["valid_end_utc"], "Member valid end")
        if (parse_time(row.get("init_utc"), "Member init") != mi
                or parse_time(row.get("valid_start_utc"), "Member valid start") != valid-timedelta(hours=1)
                or row.get("native_forecast_hour") != int((valid-mi).total_seconds()/3600)
                or row.get("family") != member["family"] or row.get("perturbation") != member["perturbation"]
                or not re.fullmatch("[0-9a-f]{64}", str(row.get("sha256", "")))):
            raise ValueError("Source member identity, accumulation or hash is invalid")
    omd_rows = sources.get("omd_fields") or []
    if len(omd_rows) != 2*len(expected_hours) or {(r.get("forecast_hour"), r.get("product")) for r in omd_rows} != {(h, p) for h in expected_hours for p in ("prob", "ffri")}:
        raise ValueError("OMD source evidence has missing or duplicate probability products")
    expected_files = CAM_FILES if kind == "cam" else ERO_FILES
    if set(meta.get("expected_files") or []) != set(expected_files):
        raise ValueError("Metadata does not declare the complete new model image set")
    require_files(root, expected_files, kind.upper())
    hashes = meta.get("file_sha256") or {}
    required_hashes = [*expected_files, prefix + "_sources.json"]
    if set(hashes) != set(required_hashes):
        raise ValueError("CAM image/source integrity manifest is incomplete")
    for name in required_hashes:
        if hashlib.sha256((root/name).read_bytes()).hexdigest() != hashes[name]:
            raise ValueError("CAM package mixes generations or has changed bytes: " + name)
    size = meta.get("rendering", {}).get("map_pixel_dimensions")
    if size != [6000, 3600]:
        raise ValueError("CAM product dimensions must remain 6000 x 3600")
    for name in expected_files:
        with (root/name).open("rb") as f:
            header = f.read(24)
        if len(header) != 24 or header[:8] != b"\x89PNG\r\n\x1a\n" or list(struct.unpack(">II", header[16:24])) != size:
            raise ValueError("Invalid or mixed-dimension CAM image: " + name)
    bounds = meta.get("bounds")
    if not isinstance(bounds, list) or len(bounds) != 2 or any(len(p) != 2 or any(not isinstance(x, (int, float)) or not math.isfinite(x) for x in p) for p in bounds):
        raise ValueError("Invalid CAM geographic bounds")
    if not (-90 <= bounds[0][0] < bounds[1][0] <= 90 and -180 <= bounds[0][1] < bounds[1][1] <= 180):
        raise ValueError("CAM geographic bounds are out of range")
    return meta, spc


def validate_cam(root: Path, now: datetime) -> None:
    meta, init = validate_cam_generation(root, now, "cam")
    print(f"CAM package PASS: aligned SPC/OMD {init:%Y-%m-%d %HZ}; 120/120 member-hours; {len(CAM_FILES)} PNGs.")


def validate_ero(root: Path, now: datetime) -> None:
    meta, init = validate_cam_generation(root, now, "ero")
    expected_type = "18z_update" if init.hour == 18 else "full_day1"
    start = max(0, 12-init.hour); end = 36-init.hour
    if (meta.get("ero_window_type") != expected_type or meta.get("ero_coverage_hours") != end-start
            or parse_time(meta.get("ero_start_utc"), "ERO start") != init+timedelta(hours=start)
            or parse_time(meta.get("ero_end_utc"), "ERO end") != init+timedelta(hours=end)):
        raise ValueError("Invalid cycle-relative Day 1 ERO coverage")
    print(f"ERO CAM package PASS: {expected_type}; aligned SPC/OMD {init:%HZ}; {10*(end-start)} member-hours; {len(ERO_FILES)} PNGs.")


def validate_rap(root: Path, now: datetime) -> None:
    meta = load_json(root / "rap_metadata.json")
    analysis = parse_time(meta.get("analysis_init_utc"), "RAP analysis initialization")
    forecast = parse_time(meta.get("forecast_valid_utc"), "RAP +3 h valid time")
    comparison = parse_time(meta.get("comparison_init_utc"), "RAP T-3 initialization")
    if forecast - analysis != timedelta(hours=3):
        raise ValueError("RAP forecast metadata is not +3 hours from analysis")
    if analysis - comparison != timedelta(hours=3):
        raise ValueError("RAP comparison metadata is not T-3 from analysis")
    age = (now - analysis).total_seconds() / 3600.0
    if age < -0.25 or age > 4.0:
        raise ValueError(
            f"RAP analysis age {age:.2f} h is outside the operational 0-4 h window"
        )
    require_files(root, RAP_FILES, "RAP")
    print(
        f"RAP package PASS: analysis {analysis:%Y-%m-%d %HZ}; "
        f"+3 h {forecast:%HZ}; T-3 {comparison:%HZ}; "
        f"{len(RAP_FILES)} PNGs; age {age:.2f} h."
    )


def validate_nwm(root: Path, now: datetime) -> None:
    meta = load_json(root / "nwm_metadata.json")
    valid = parse_time(meta.get("valid_time_iso"), "NWM valid time")
    policy = meta.get("freshness_policy") or {}
    hide_hours = float(policy.get("hide_hours", 6))
    age = (now - valid).total_seconds() / 3600.0
    if age < -0.25 or age >= hide_hours:
        raise ValueError(
            f"NWM retained package age {age:.2f} h exceeds the "
            f"{hide_hours:g} h usable window"
        )
    require_files(root, ["nwm_soil_saturation.png"], "NWM")
    status = str(meta.get("update_status") or "unknown")
    print(
        f"NWM package PASS: valid {valid:%Y-%m-%d %HZ}; age {age:.2f} h; "
        f"status {status}; hide threshold {hide_hours:g} h."
    )


def validate_hrrr_tle(root: Path, now: datetime) -> None:
    manifest = load_json(root / "hrrr_tle_manifest.json")
    meta = load_json(root / "hrrr_tle_metadata.json")
    if manifest.get("metadata_mode") != "hrrr_tle_dashboard_manifest_v1":
        raise ValueError("Unexpected HRRR-TLE manifest contract")
    latest = parse_time(manifest.get("latest_cycle_utc"), "HRRR-TLE latest cycle")
    valid_end = parse_time(
        manifest.get("common_valid_end_utc"), "HRRR-TLE common valid end"
    )
    if now >= valid_end:
        raise ValueError(
            f"HRRR-TLE package expired at {valid_end.isoformat()} "
            f"(now {now.isoformat()})"
        )
    if meta.get("latest_cycle_utc") != manifest.get("latest_cycle_utc"):
        raise ValueError("HRRR-TLE metadata/manifest cycle mismatch")
    layers = manifest.get("layers") or {}
    if len(layers) != 20:
        raise ValueError(f"HRRR-TLE requires 20 synchronized layers; found {len(layers)}")
    files = []
    for key, item in layers.items():
        name = (item or {}).get("file")
        if not isinstance(name, str) or not name:
            raise ValueError(f"HRRR-TLE layer {key} has no file")
        files.append(name)
    files += ["hrrr_tle_manifest.json", "hrrr_tle_metadata.json"]
    require_files(root, files, "HRRR-TLE")
    print(
        f"HRRR-TLE package PASS: anchor {latest:%Y-%m-%d %HZ}; "
        f"20 synchronized overlays; valid through {valid_end:%Y-%m-%d %HZ}."
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("product", choices=("cam", "ero", "rap", "hrrr-tle", "nwm"))
    parser.add_argument("--root", type=Path, default=Path("static"))
    args = parser.parse_args()
    now = datetime.now(UTC)
    validators = {
        "cam": validate_cam,
        "ero": validate_ero,
        "rap": validate_rap,
        "hrrr-tle": validate_hrrr_tle,
        "nwm": validate_nwm,
    }
    validators[args.product](args.root, now)


if __name__ == "__main__":
    main()

