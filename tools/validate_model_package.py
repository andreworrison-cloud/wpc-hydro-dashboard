#!/usr/bin/env python3
"""Validate operational model dashboard packages before publication.

The model workflows restore the last complete live snapshot before fetching new
guidance. This validator allows short upstream delays to retain a still-valid
package, while refusing expired, mixed-generation, or incomplete packages.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

UTC = timezone.utc

CAM_FILES = [
    *(f"cam_ffg_{window}_{model}.png"
      for window in ("3h_to_9h", "9h_to_15h")
      for model in ("href", "refs", "super")),
    *(f"cam_qpf_{window}_{threshold}_inch_{model}.png"
      for window in ("3h_to_9h", "9h_to_15h")
      for threshold in ("0.5", "1", "2", "3")
      for model in ("href", "refs", "super")),
]

ERO_FILES = [
    *(f"ero_ffg_{model}.png" for model in ("href", "refs", "super")),
    *(f"ero_qpf_{threshold}_inch_{model}.png"
      for threshold in ("0.5", "1", "2", "3")
      for model in ("href", "refs", "super")),
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


def validate_cam(root: Path, now: datetime) -> None:
    meta = load_json(root / "cam_metadata.json")
    href = parse_time(meta.get("href_init_utc"), "CAM HREF initialization")
    refs = parse_time(meta.get("refs_init_utc"), "CAM REFS initialization")
    if href != refs:
        raise ValueError(
            f"CAM HREF/REFS cycles are not aligned: {href.isoformat()} vs {refs.isoformat()}"
        )
    valid_end = href + timedelta(hours=15)
    if now >= valid_end:
        raise ValueError(
            f"CAM retained package expired at {valid_end.isoformat()} "
            f"(now {now.isoformat()})"
        )
    contract = meta.get("window_contract") or {}
    if set(contract) != {"3h_to_9h", "9h_to_15h"}:
        raise ValueError("CAM metadata does not contain both required nowcast windows")
    require_files(root, CAM_FILES, "CAM")
    print(
        f"CAM package PASS: aligned {href:%Y-%m-%d %HZ}; "
        f"{len(CAM_FILES)} PNGs; valid through {valid_end:%Y-%m-%d %HZ}."
    )


def validate_ero(root: Path, now: datetime) -> None:
    meta = load_json(root / "ero_cam_metadata.json")
    href = parse_time(meta.get("href_init_utc"), "ERO HREF initialization")
    refs = parse_time(meta.get("refs_init_utc"), "ERO REFS initialization")
    start = parse_time(meta.get("ero_start_utc"), "ERO window start")
    end = parse_time(meta.get("ero_end_utc"), "ERO window end")
    if start >= end:
        raise ValueError("ERO window start/end are invalid")
    if now >= end:
        raise ValueError(
            f"ERO CAM retained package expired at {end.isoformat()} "
            f"(now {now.isoformat()})"
        )
    window_type = meta.get("ero_window_type")
    if window_type not in {"full_day1", "18z_update"}:
        raise ValueError(f"Unexpected ERO window type: {window_type!r}")
    if window_type == "18z_update" and href != refs:
        raise ValueError("18Z ERO update requires matching HREF/REFS initializations")
    coverage = int(meta.get("ero_coverage_hours", -1))
    expected = int((end - start).total_seconds() // 3600)
    if coverage != expected:
        raise ValueError(
            f"ERO coverage metadata mismatch: declared {coverage} h, expected {expected} h"
        )
    require_files(root, ERO_FILES, "ERO CAM")
    print(
        f"ERO CAM package PASS: {window_type}; HREF {href:%HZ}; REFS {refs:%HZ}; "
        f"{len(ERO_FILES)} PNGs; valid through {end:%Y-%m-%d %HZ}."
    )


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
    parser.add_argument("product", choices=("cam", "ero", "rap", "hrrr-tle"))
    parser.add_argument("--root", type=Path, default=Path("static"))
    args = parser.parse_args()
    now = datetime.now(UTC)
    validators = {
        "cam": validate_cam,
        "ero": validate_ero,
        "rap": validate_rap,
        "hrrr-tle": validate_hrrr_tle,
    }
    validators[args.product](args.root, now)


if __name__ == "__main__":
    main()
