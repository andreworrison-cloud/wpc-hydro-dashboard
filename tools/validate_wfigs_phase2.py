#!/usr/bin/env python3
"""Validate the Phase WFIGS-2 backend code contract and generated data products."""

from __future__ import annotations

import argparse
import hashlib
import json
import py_compile
import re
import sys
from pathlib import Path
from typing import Any

from shapely.geometry import shape

PROCESSOR_VERSION = "wfigs_phase2_operational_v1_4"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_code(repo_root: Path, errors: list[str]) -> None:
    script = repo_root / "fetch_wfigs_operational.py"
    current_wf = repo_root / ".github/workflows/update_wfigs_current.yml"
    ytd_wf = repo_root / ".github/workflows/update_wfigs_ytd.yml"

    for path in (script, current_wf, ytd_wf):
        if not path.exists():
            errors.append(f"Missing required Phase-2 file: {path}")
    if errors:
        return

    try:
        py_compile.compile(str(script), doraise=True)
    except Exception as exc:
        errors.append(f"fetch_wfigs_operational.py does not compile: {exc}")
        return

    text = script.read_text(encoding="utf-8")
    required_fragments = [
        PROCESSOR_VERSION,
        "attr_IncidentTypeCategory = 'WF'",
        "DISPLAY_GENERALIZATION_DEG = 0.00008",
        "YTD_GRID_DEGREES = 5.0",
        "poly_GISAcres",
        "poly_Acres_AutoCalc_fallback",
        "state_plus_5deg_representative_point",
        "WFIGS polygons represent mapped wildfire extent, not soil burn severity.",
        "active_fire_ids",
        "duplicate_identity_groups_removed",
        "exception-safe polygon repair cascade",
        "repair_polygonal_geometry",
        "make_valid_structure",
        "buffer0",
        "componentwise",
        "repair_method_counts",
        "SEASONAL_ACTIVITY_VERSION = \"wfigs_seasonal_activity_v1_0\"",
        "CONUS_STATE_CODES",
        "build_conus_seasonal_activity",
        "seasonal_activity.json",
    ]
    for fragment in required_fragments:
        if fragment not in text:
            errors.append(f"Missing operational script contract: {fragment}")

    # Scientific guardrail: the authoritative WF source query must not be acreage-filtered.
    # Phase 4.3 intentionally creates a *secondary cartographic overview subset* for
    # national-scale display, so generic names such as ``min_acres`` are no longer
    # evidence of source-record deletion. The complete Current/YTD deliveries remain
    # unfiltered by acreage and are validated separately below.
    where_match = re.search(
        r'^\s*WILDFIRE_WHERE\s*=\s*"([^"]+)"',
        text,
        flags=re.MULTILINE,
    )
    if not where_match:
        errors.append("Could not verify the authoritative WILDFIRE_WHERE source query")
    else:
        wildfire_where = where_match.group(1).strip()
        if wildfire_where != "attr_IncidentTypeCategory = 'WF'":
            errors.append(
                "WILDFIRE_WHERE must select all WF incidents without acreage filtering; "
                f"found: {wildfire_where!r}"
            )
        if re.search(r"acres?|poly_GISAcres|poly_Acres_AutoCalc", wildfire_where, flags=re.IGNORECASE):
            errors.append("Authoritative WILDFIRE_WHERE source query contains an acreage condition")

    # Also guard against obvious per-feature acreage skips in the full-delivery path.
    # The Phase-4.3 overview list-comprehension is intentionally excluded: it writes
    # only overview.geojson and does not alter the complete YTD chunk archive.
    forbidden_patterns = [
        r"if\s+.*mapped_acres\s*[<>]=?\s*\d+.*continue",
        r"if\s+.*gis_acres\s*[<>]=?\s*\d+.*continue",
    ]
    for pattern in forbidden_patterns:
        if re.search(pattern, text, flags=re.IGNORECASE):
            errors.append(f"Potential acreage-based full-delivery filtering found: {pattern}")

    for path, expected_name, expected_timeout in (
        (current_wf, "Update WFIGS Current Wildfire Perimeters", "timeout-minutes: 30"),
        (ytd_wf, "Update WFIGS Year-To-Date Wildfire Perimeters", "timeout-minutes: 75"),
    ):
        wf = path.read_text(encoding="utf-8")
        for fragment in [
            f"name: {expected_name}",
            "workflow_dispatch:",
            "actions/checkout@v6",
            "actions/setup-python@v6",
            "actions/upload-artifact@v6",
            "permissions:",
            "contents: write",
            "group: wfigs-data-publish",
            "cancel-in-progress: false",
            "wfigs-data",
            expected_timeout,
        ]:
            if fragment not in wf:
                errors.append(f"{path.name} missing workflow contract: {fragment}")
        if "schedule:" in wf:
            errors.append(f"{path.name} must not use GitHub schedule; external cron is intentional.")


def validate_feature(feature: dict[str, Any], errors: list[str], context: str) -> None:
    if feature.get("type") != "Feature":
        errors.append(f"{context}: invalid feature type")
        return
    geom = feature.get("geometry") or {}
    if geom.get("type") not in {"Polygon", "MultiPolygon"}:
        errors.append(f"{context}: unexpected geometry type {geom.get('type')!r}")
    else:
        try:
            display_geom = shape(geom)
            if display_geom.is_empty:
                errors.append(f"{context}: empty display geometry")
            elif not display_geom.is_valid:
                errors.append(f"{context}: invalid display geometry after serialization")
        except Exception as exc:
            errors.append(f"{context}: geometry parse failed: {exc}")
    props = feature.get("properties") or {}
    required_props = {
        "fire_id",
        "incident_name",
        "mapped_acres",
        "mapped_acres_source",
        "state",
        "county",
        "discovery_time_utc",
        "source_collection",
    }
    missing = sorted(required_props - set(props))
    if missing:
        errors.append(f"{context}: missing properties {missing}")
    if props.get("source_collection") not in {"current", "ytd"}:
        errors.append(f"{context}: invalid source_collection")


def validate_current(data_root: Path, errors: list[str]) -> None:
    root = data_root / "current"
    manifest_path = root / "manifest.json"
    geojson_path = root / "perimeters.geojson"
    if not manifest_path.exists() or not geojson_path.exists():
        errors.append("Current build is missing manifest.json or perimeters.geojson")
        return
    manifest = load_json(manifest_path)
    if manifest.get("processor_version") != PROCESSOR_VERSION:
        errors.append("Current processor_version mismatch")
    if manifest.get("collection") != "current":
        errors.append("Current collection marker mismatch")
    if manifest.get("science_note") != "WFIGS polygons represent mapped wildfire extent, not soil burn severity.":
        errors.append("Current science note missing/changed")
    if manifest.get("sha256") != sha256_file(geojson_path):
        errors.append("Current GeoJSON checksum mismatch")
    if int(manifest.get("bytes") or -1) != geojson_path.stat().st_size:
        errors.append("Current GeoJSON byte count mismatch")

    payload = load_json(geojson_path)
    features = payload.get("features") or []
    if len(features) != int(manifest.get("published_fire_count") or -1):
        errors.append("Current feature count does not match manifest")
    fire_ids = [((f.get("properties") or {}).get("fire_id")) for f in features]
    if len(fire_ids) != len(set(fire_ids)):
        errors.append("Current delivery contains duplicate fire_id values")
    if sorted(fire_ids) != sorted(manifest.get("active_fire_ids") or []):
        errors.append("Current active_fire_ids do not match GeoJSON")
    for idx, feature in enumerate(features):
        validate_feature(feature, errors, f"current feature {idx}")


def validate_ytd(data_root: Path, errors: list[str]) -> None:
    root = data_root / "ytd"
    manifest_path = root / "manifest.json"
    if not manifest_path.exists():
        errors.append("YTD build is missing manifest.json")
        return
    manifest = load_json(manifest_path)
    if manifest.get("processor_version") != PROCESSOR_VERSION:
        errors.append("YTD processor_version mismatch")
    if manifest.get("collection") != "ytd":
        errors.append("YTD collection marker mismatch")
    if (manifest.get("chunking") or {}).get("strategy") != "state_plus_5deg_representative_point":
        errors.append("YTD chunking strategy mismatch")
    chunks = manifest.get("chunks") or []
    if len(chunks) != int(manifest.get("chunk_count") or -1):
        errors.append("YTD chunk count mismatch")

    total_features = 0
    total_bytes = 0
    all_fire_ids: set[str] = set()
    duplicate_fire_ids = 0
    for item in chunks:
        path = root / str(item.get("href", ""))
        if not path.exists():
            errors.append(f"Missing YTD chunk: {path}")
            continue
        if sha256_file(path) != item.get("sha256"):
            errors.append(f"Checksum mismatch for YTD chunk {path.name}")
        if path.stat().st_size != int(item.get("bytes") or -1):
            errors.append(f"Byte-count mismatch for YTD chunk {path.name}")
        payload = load_json(path)
        features = payload.get("features") or []
        if len(features) != int(item.get("feature_count") or -1):
            errors.append(f"Feature-count mismatch for YTD chunk {path.name}")
        total_features += len(features)
        total_bytes += path.stat().st_size
        for feature in features:
            fire_id = (feature.get("properties") or {}).get("fire_id")
            if fire_id in all_fire_ids:
                duplicate_fire_ids += 1
            if fire_id:
                all_fire_ids.add(fire_id)
            validate_feature(feature, errors, f"YTD {path.name} feature")

    if duplicate_fire_ids:
        errors.append(f"YTD delivery contains {duplicate_fire_ids} duplicate fire_id values")
    if total_features != int(manifest.get("published_fire_count") or -1):
        errors.append("YTD feature total does not match manifest")
    if total_bytes != int(manifest.get("total_chunk_bytes") or -1):
        errors.append("YTD byte total does not match manifest")

    overview = manifest.get("overview") or {}
    overview_path = root / str(overview.get("href") or "")
    if not overview.get("href") or not overview_path.exists():
        errors.append("YTD overview GeoJSON is missing")
    else:
        if sha256_file(overview_path) != overview.get("sha256"):
            errors.append("YTD overview checksum mismatch")
        if overview_path.stat().st_size != int(overview.get("bytes") or -1):
            errors.append("YTD overview byte-count mismatch")
        payload = load_json(overview_path)
        features = payload.get("features") or []
        if len(features) != int(overview.get("feature_count") if overview.get("feature_count") is not None else -1):
            errors.append("YTD overview feature-count mismatch")
        min_acres = float(overview.get("minimum_mapped_acres") or 5000.0)
        for feature in features:
            validate_feature(feature, errors, "YTD overview feature")
            acres = (feature.get("properties") or {}).get("mapped_acres")
            try:
                acres = float(acres)
            except (TypeError, ValueError):
                acres = None
            if acres is None or acres < min_acres:
                errors.append("YTD overview contains a perimeter below its mapped-acre threshold")
                break

    seasonal = manifest.get("seasonal_activity") or {}
    seasonal_path = root / str(seasonal.get("href") or "")
    if seasonal.get("href") != "seasonal_activity.json" or not seasonal_path.exists():
        errors.append("YTD seasonal_activity.json is missing")
    else:
        if sha256_file(seasonal_path) != seasonal.get("sha256"):
            errors.append("YTD seasonal activity checksum mismatch")
        payload = load_json(seasonal_path)
        if payload.get("phase") != "WFIGS-5" or payload.get("collection") != "current-year-activity":
            errors.append("YTD seasonal activity metadata mismatch")
        if payload.get("domain") != "CONUS":
            errors.append("YTD seasonal activity domain mismatch")
        year = int(payload.get("year") or 0)
        daily = payload.get("daily_counts") or []
        if len(daily) not in {365, 366}:
            errors.append("YTD seasonal activity daily series length is invalid")
        complete_day = int(payload.get("complete_through_day") or 0)
        if not (0 <= complete_day <= len(daily)):
            errors.append("YTD seasonal activity complete_through_day is invalid")
        if int(payload.get("complete_through_count") or 0) != sum(int(v) for v in daily[:complete_day]):
            errors.append("YTD seasonal activity complete_through_count is inconsistent")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("code", "current", "ytd", "all"), default="code")
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--data-root", type=Path, default=None)
    args = parser.parse_args()

    errors: list[str] = []
    validate_code(args.repo_root, errors)
    if args.mode in {"current", "ytd", "all"}:
        if args.data_root is None:
            errors.append("--data-root is required for generated-data validation")
        else:
            if args.mode in {"current", "all"}:
                validate_current(args.data_root, errors)
            if args.mode in {"ytd", "all"}:
                validate_ytd(args.data_root, errors)

    if errors:
        print("WFIGS Phase-2 validation: FAIL")
        for error in errors:
            print(f" - {error}")
        return 1
    print("WFIGS Phase-2 validation: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
