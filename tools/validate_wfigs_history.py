#!/usr/bin/env python3
"""Validate the WFIGS Phase-4 rolling five-year historical delivery."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from shapely.geometry import shape
except Exception as exc:  # pragma: no cover
    raise RuntimeError("Shapely is required for historical geometry validation") from exc

PROCESSOR_VERSION = "wfigs_history_v1_2"
HISTORY_ITEM_ID = "5e72b1699bf74eefb3f3aff6f4ba5511"
EARLIEST_MODERN_WFIGS_YEAR = 2021


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def rolling_years(count: int) -> list[int]:
    newest = datetime.now(timezone.utc).year - 1
    return list(range(newest, newest - count, -1))


def resolve_year_root(data_history: Path, existing_history: Path | None, year: int) -> Path | None:
    candidate = data_history / str(year)
    if (candidate / "manifest.json").exists():
        return candidate
    if existing_history is not None:
        candidate = existing_history / str(year)
        if (candidate / "manifest.json").exists():
            return candidate
    return None


def validate_bbox(bbox: Any, label: str, errors: list[str]) -> None:
    if not isinstance(bbox, list) or len(bbox) != 4:
        errors.append(f"{label}: invalid bbox structure")
        return
    try:
        values = [float(v) for v in bbox]
    except Exception:
        errors.append(f"{label}: bbox values are not numeric")
        return
    if not all(math.isfinite(v) for v in values):
        errors.append(f"{label}: bbox contains non-finite values")
    if values[0] > values[2] or values[1] > values[3]:
        errors.append(f"{label}: bbox min/max order is invalid")


def validate_year(root: Path, year: int, errors: list[str]) -> tuple[int, int]:
    manifest_path = root / "manifest.json"
    try:
        manifest = read_json(manifest_path)
    except Exception as exc:
        errors.append(f"{year}: could not read manifest: {exc}")
        return 0, 0

    if manifest.get("phase") != "WFIGS-4":
        errors.append(f"{year}: phase mismatch")
    if manifest.get("processor_version") != PROCESSOR_VERSION:
        errors.append(f"{year}: processor version mismatch")
    if manifest.get("collection") != "history-year":
        errors.append(f"{year}: collection mismatch")
    if int(manifest.get("year") or -1) != year:
        errors.append(f"{year}: manifest year mismatch")
    if manifest.get("source_item_id") != HISTORY_ITEM_ID:
        errors.append(f"{year}: unexpected WFIGS source item")
    if manifest.get("relative_date_query_used") is not False:
        errors.append(f"{year}: historical build must explicitly prohibit relative-date queries")

    where = str(manifest.get("fixed_where_clause") or "")
    expected_start = f"TIMESTAMP '{year:04d}-01-01 00:00:00'"
    expected_end = f"TIMESTAMP '{year + 1:04d}-01-01 00:00:00'"
    if expected_start not in where or expected_end not in where:
        errors.append(f"{year}: fixed calendar-year query boundaries missing")
    if "CURRENT_TIMESTAMP" in where.upper() or "INTERVAL" in where.upper():
        errors.append(f"{year}: relative date syntax found in fixed historical query")

    chunks = manifest.get("chunks") or []
    if not isinstance(chunks, list) or not chunks:
        errors.append(f"{year}: no chunk inventory")
        return 0, 0
    if len(chunks) != int(manifest.get("chunk_count") or -1):
        errors.append(f"{year}: chunk count mismatch")

    manifest_published = int(manifest.get("published_fire_count") or 0)
    if manifest_published <= 0:
        errors.append(f"{year}: zero published fires")
    dedupe = manifest.get("deduplication") or {}
    canonical_count = int(dedupe.get("unique_identity_count") or 0)
    omitted = (manifest.get("geometry_qa") or {}).get("omitted_features") or []
    if not isinstance(omitted, list):
        errors.append(f"{year}: geometry_qa.omitted_features is not a list")
        omitted = []
    if canonical_count and len(omitted) != canonical_count - manifest_published:
        errors.append(
            f"{year}: omitted-feature provenance count {len(omitted)} != canonical-published "
            f"difference {canonical_count - manifest_published}"
        )
    chunk_feature_sum = 0
    invalid_geometries = 0
    seen_fire_ids: set[str] = set()
    total_bytes = 0

    for chunk in chunks:
        href = str(chunk.get("href") or "")
        path = root / href
        label = f"{year}/{href or '<missing href>'}"
        if not href.startswith("chunks/") or not href.endswith(".geojson"):
            errors.append(f"{label}: malformed chunk href")
            continue
        if not path.exists() or path.stat().st_size <= 0:
            errors.append(f"{label}: missing or empty chunk")
            continue
        if sha256_file(path) != chunk.get("sha256"):
            errors.append(f"{label}: checksum mismatch")
        if path.stat().st_size != int(chunk.get("bytes") or -1):
            errors.append(f"{label}: byte-count mismatch")
        validate_bbox(chunk.get("bbox"), label, errors)

        try:
            collection = read_json(path)
        except Exception as exc:
            errors.append(f"{label}: invalid JSON: {exc}")
            continue
        if collection.get("type") != "FeatureCollection":
            errors.append(f"{label}: not a FeatureCollection")
            continue
        features = collection.get("features") or []
        expected_count = int(chunk.get("feature_count") or 0)
        if len(features) != expected_count:
            errors.append(f"{label}: feature count {len(features)} != manifest {expected_count}")
        chunk_feature_sum += len(features)
        total_bytes += path.stat().st_size

        for feature in features:
            props = feature.get("properties") or {}
            fire_id = str(props.get("fire_id") or "")
            if not fire_id:
                errors.append(f"{label}: feature missing fire_id")
            elif fire_id in seen_fire_ids:
                errors.append(f"{label}: duplicate fire_id across year chunks: {fire_id}")
            else:
                seen_fire_ids.add(fire_id)
            if props.get("source_collection") != f"history-{year}":
                errors.append(f"{label}: unexpected source_collection for {fire_id or 'feature'}")
            discovered = str(props.get("discovery_time_utc") or "")
            if discovered and not discovered.startswith(f"{year:04d}-"):
                errors.append(f"{label}: discovery year does not match archive year for {fire_id}")
            try:
                geom = shape(feature.get("geometry"))
                if geom.is_empty or geom.geom_type not in {"Polygon", "MultiPolygon"} or not geom.is_valid:
                    invalid_geometries += 1
            except Exception:
                invalid_geometries += 1

    if chunk_feature_sum != manifest_published:
        errors.append(f"{year}: chunk feature sum {chunk_feature_sum} != published count {manifest_published}")
    if len(seen_fire_ids) != manifest_published:
        errors.append(f"{year}: unique fire-id count {len(seen_fire_ids)} != published count {manifest_published}")
    if total_bytes != int(manifest.get("total_chunk_bytes") or -1):
        errors.append(f"{year}: total chunk bytes mismatch")
    if invalid_geometries:
        errors.append(f"{year}: {invalid_geometries} serialized geometries are invalid/empty/non-polygonal")

    overview = manifest.get("overview") or {}
    overview_href = str(overview.get("href") or "")
    overview_path = root / overview_href
    if overview_href != "overview.geojson" or not overview_path.exists() or overview_path.stat().st_size <= 0:
        errors.append(f"{year}: historical overview GeoJSON missing/empty")
    else:
        if sha256_file(overview_path) != overview.get("sha256"):
            errors.append(f"{year}: historical overview checksum mismatch")
        if overview_path.stat().st_size != int(overview.get("bytes") or -1):
            errors.append(f"{year}: historical overview byte-count mismatch")
        try:
            payload = read_json(overview_path)
            features = payload.get("features") or []
            if len(features) != int(overview.get("feature_count") if overview.get("feature_count") is not None else -1):
                errors.append(f"{year}: historical overview feature-count mismatch")
            min_acres = float(overview.get("minimum_mapped_acres") or 5000.0)
            for feature in features:
                props = feature.get("properties") or {}
                try:
                    acres = float(props.get("mapped_acres"))
                except (TypeError, ValueError):
                    acres = None
                if acres is None or acres < min_acres:
                    errors.append(f"{year}: overview contains perimeter below mapped-acre threshold")
                    break
                try:
                    geom = shape(feature.get("geometry"))
                    if geom.is_empty or geom.geom_type not in {"Polygon", "MultiPolygon"} or not geom.is_valid:
                        errors.append(f"{year}: overview contains invalid/empty/non-polygon geometry")
                        break
                except Exception:
                    errors.append(f"{year}: overview contains unreadable geometry")
                    break
        except Exception as exc:
            errors.append(f"{year}: invalid overview JSON: {exc}")

    seasonal = manifest.get("seasonal_activity") or {}
    seasonal_href = str(seasonal.get("href") or "")
    seasonal_path = root / seasonal_href
    if seasonal_href != "seasonal_activity.json" or not seasonal_path.exists():
        errors.append(f"{year}: seasonal_activity.json missing")
    else:
        if sha256_file(seasonal_path) != seasonal.get("sha256"):
            errors.append(f"{year}: seasonal activity checksum mismatch")
        try:
            activity = read_json(seasonal_path)
            if activity.get("phase") != "WFIGS-5" or activity.get("collection") != "historical-year-activity":
                errors.append(f"{year}: seasonal activity metadata mismatch")
            if int(activity.get("year") or -1) != year or activity.get("domain") != "CONUS":
                errors.append(f"{year}: seasonal activity year/domain mismatch")
            daily = activity.get("daily_counts") or []
            if len(daily) not in {365, 366}:
                errors.append(f"{year}: seasonal activity daily series length invalid")
            if int(activity.get("complete_through_count") or -1) != sum(int(v) for v in daily):
                errors.append(f"{year}: seasonal activity annual total inconsistent")
            if int(seasonal.get("annual_count") or -1) != int(activity.get("complete_through_count") or -2):
                errors.append(f"{year}: seasonal activity manifest annual_count mismatch")
        except Exception as exc:
            errors.append(f"{year}: invalid seasonal activity JSON: {exc}")

    return manifest_published, len(chunks)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True, help="Build root containing history/")
    parser.add_argument("--existing-root", type=Path, default=None, help="Existing static/wfigs/history root for unchanged years")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    data_history = args.data_root / "history"
    index_path = data_history / "manifest.json"
    errors: list[str] = []
    if not index_path.exists():
        print("WFIGS Phase-4 history validation FAILED: missing history/manifest.json")
        return 1

    try:
        index = read_json(index_path)
    except Exception as exc:
        print(f"WFIGS Phase-4 history validation FAILED: invalid index JSON: {exc}")
        return 1

    if index.get("phase") != "WFIGS-4":
        errors.append("history index phase mismatch")
    if index.get("processor_version") != PROCESSOR_VERSION:
        errors.append("history index processor version mismatch")
    if index.get("collection") != "history-index":
        errors.append("history index collection mismatch")
    if index.get("source_item_id") != HISTORY_ITEM_ID:
        errors.append("history index source item mismatch")
    if int(index.get("rolling_window_years") or 0) != 5:
        errors.append("history index must expose exactly five completed years")

    years = [int(y) for y in (index.get("available_years") or [])]
    expected = rolling_years(5)
    if years != expected:
        errors.append(f"history available_years {years} != expected rolling window {expected}")
    if years and min(years) < EARLIEST_MODERN_WFIGS_YEAR:
        errors.append("history index reaches into pre-2021 WFIGS data")
    if int(index.get("default_year") or -1) != (years[0] if years else -1):
        errors.append("history default year is not newest completed year")
    if "CURRENT_TIMESTAMP" in str(index.get("query_policy") or "").upper():
        # The policy is expected to state that CURRENT_TIMESTAMP is forbidden.
        if "NO CURRENT_TIMESTAMP" not in str(index.get("query_policy") or "").upper():
            errors.append("history query policy ambiguously permits relative CURRENT_TIMESTAMP queries")

    root_seasonal = index.get("seasonal_activity") or {}
    root_seasonal_path = data_history / str(root_seasonal.get("href") or "")
    if root_seasonal.get("href") != "seasonal_activity.json" or not root_seasonal_path.exists():
        errors.append("history root seasonal_activity.json missing")

    entries = index.get("years") or []
    entry_years = [int(entry.get("year") or -1) for entry in entries]
    if entry_years != years:
        errors.append("history index year summaries are missing or out of order")

    total_features = 0
    total_chunks = 0
    for year in years:
        year_root = resolve_year_root(data_history, args.existing_root, year)
        if year_root is None:
            errors.append(f"{year}: year delivery missing from build and existing roots")
            continue
        features, chunks = validate_year(year_root, year, errors)
        total_features += features
        total_chunks += chunks

    if errors:
        print("WFIGS Phase-4 history validation FAILED:")
        for error in errors[:100]:
            print(f" - {error}")
        if len(errors) > 100:
            print(f" - ... {len(errors) - 100} additional errors")
        return 1

    print(
        "WFIGS Phase-4 history validation: PASS — "
        f"{len(years)} years, {total_features:,} published fire perimeters, {total_chunks:,} chunks"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
