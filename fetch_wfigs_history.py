#!/usr/bin/env python3
"""Build the rolling five completed-calendar-year WFIGS wildfire perimeter archive.

This is a companion to fetch_wfigs_operational.py. It intentionally reuses the
proven Phase-2 normalization, geometry repair, display generalization, acreage,
and chunking logic rather than creating a second geometry-processing stack.

The authoritative source is NIFC/WFIGS Interagency Fire Perimeters (full-history
service). Only Wildfire (WF) incidents are selected. Historical year is defined
by attr_FireDiscoveryDateTime in UTC. Queries use fixed TIMESTAMP boundaries;
no relative CURRENT_TIMESTAMP query is used.

Outputs
-------
static/wfigs/history/manifest.json
static/wfigs/history/YYYY/manifest.json
static/wfigs/history/YYYY/chunks/*.geojson

The root history manifest exposes only the previous five completed calendar
years. On 2026-09-09 this is 2025, 2024, 2023, 2022, 2021. On 2027-01-01 it
rolls automatically to 2026 through 2022.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

import fetch_wfigs_operational as core

PROCESSOR_VERSION = "wfigs_history_v1_0"
HISTORY_LAYER_URL = (
    "https://services3.arcgis.com/T4QMspbfLg3qTGWY/arcgis/rest/services/"
    "WFIGS_Interagency_Perimeters/FeatureServer/0"
)
HISTORY_ITEM_ID = "5e72b1699bf74eefb3f3aff6f4ba5511"
HISTORY_LABEL = "WFIGS Interagency Fire Perimeters — Rolling 5-Year History"
DEFAULT_ROLLING_YEARS = 5
EARLIEST_MODERN_WFIGS_YEAR = 2021



def assert_core_compatibility() -> None:
    version = str(getattr(core, "PROCESSOR_VERSION", ""))
    match = re.fullmatch(r"wfigs_phase2_operational_v(\d+)_(\d+)", version)
    if not match or tuple(map(int, match.groups())) < (1, 2):
        raise RuntimeError(
            "fetch_wfigs_history.py requires the Phase-2.2 or newer WFIGS operational "
            "geometry core (wfigs_phase2_operational_v1_2+). Apply the mixed-dimension "
            f"repair patch first; found processor {version!r}."
        )


def rolling_completed_years(count: int, now: datetime | None = None) -> list[int]:
    if count < 1:
        raise ValueError("rolling-year count must be >= 1")
    now = now or datetime.now(timezone.utc)
    newest = now.year - 1
    years = list(range(newest, newest - count, -1))
    if min(years) < EARLIEST_MODERN_WFIGS_YEAR:
        raise RuntimeError(
            f"Requested rolling window reaches {min(years)}, but this operational "
            f"history product intentionally starts at {EARLIEST_MODERN_WFIGS_YEAR} "
            "because the WFIGS full-history service documents pre-2021 data as incomplete."
        )
    return years


def historical_where(year: int) -> str:
    return (
        "attr_IncidentTypeCategory = 'WF' AND "
        f"attr_FireDiscoveryDateTime >= TIMESTAMP '{year:04d}-01-01 00:00:00' AND "
        f"attr_FireDiscoveryDateTime < TIMESTAMP '{year + 1:04d}-01-01 00:00:00'"
    )


def object_ids_for_where(core_session, where: str) -> list[int]:
    payload = core.arcgis_query(
        core_session,
        HISTORY_LAYER_URL,
        {"where": where, "returnIdsOnly": "true", "f": "json"},
    )
    return sorted(int(v) for v in (payload.get("objectIds") or []))


def object_id_sha256(ids: Sequence[int]) -> str:
    digest = hashlib.sha256()
    digest.update(",".join(str(v) for v in ids).encode("ascii"))
    return digest.hexdigest()


def source_year_stats(core_session, where: str) -> dict[str, Any]:
    """Return a light year-specific change signature.

    Object IDs detect inserts/deletes. Max source/incident edit timestamps detect
    corrections to already-existing records. If ArcGIS statistics are unavailable,
    the build still proceeds with the object-ID signature and records that fallback.
    """
    stats = [
        {
            "statisticType": "max",
            "onStatisticField": "poly_DateCurrent",
            "outStatisticFieldName": "max_poly_date_current",
        },
        {
            "statisticType": "max",
            "onStatisticField": "attr_ModifiedOnDateTime_dt",
            "outStatisticFieldName": "max_attr_modified",
        },
    ]
    try:
        payload = core.arcgis_query(
            core_session,
            HISTORY_LAYER_URL,
            {
                "where": where,
                "outStatistics": json.dumps(stats, separators=(",", ":")),
                "returnGeometry": "false",
                "f": "json",
            },
        )
        features = payload.get("features") or []
        attrs = (features[0].get("attributes") or {}) if features else {}
        return {
            "statistics_available": True,
            "max_poly_date_current_epoch_ms": attrs.get("max_poly_date_current"),
            "max_poly_date_current_utc": core.epoch_ms_to_iso(attrs.get("max_poly_date_current")),
            "max_attr_modified_epoch_ms": attrs.get("max_attr_modified"),
            "max_attr_modified_utc": core.epoch_ms_to_iso(attrs.get("max_attr_modified")),
        }
    except Exception as exc:
        print(f"  year statistics unavailable; using ID signature only: {exc}")
        return {
            "statistics_available": False,
            "statistics_error": str(exc),
            "max_poly_date_current_epoch_ms": None,
            "max_poly_date_current_utc": None,
            "max_attr_modified_epoch_ms": None,
            "max_attr_modified_utc": None,
        }


def year_signature(ids: Sequence[int], stats: dict[str, Any]) -> str:
    payload = {
        "object_id_sha256": object_id_sha256(ids),
        "max_poly_date_current_epoch_ms": stats.get("max_poly_date_current_epoch_ms"),
        "max_attr_modified_epoch_ms": stats.get("max_attr_modified_epoch_ms"),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def year_delivery_complete(root: Path, manifest: dict[str, Any] | None) -> bool:
    if not manifest:
        return False
    chunks = manifest.get("chunks") or []
    if not chunks:
        return False
    return all((root / str(manifest.get("year")) / str(item.get("href", ""))).exists() for item in chunks)


def should_skip_year(
    year: int,
    existing_root: Path,
    signature: str,
    force: bool,
) -> bool:
    if force:
        return False
    manifest = core.load_json(existing_root / str(year) / "manifest.json")
    if not year_delivery_complete(existing_root, manifest):
        return False
    return (
        manifest.get("processor_version") == PROCESSOR_VERSION
        and manifest.get("source_year_signature") == signature
    )


def build_year(
    output_history_root: Path,
    year: int,
    where: str,
    source_meta: dict[str, Any],
    source_edit_ms: int | None,
    source_ids: Sequence[int],
    stats: dict[str, Any],
    signature: str,
    raw_records: Sequence[dict[str, Any]],
    canonical_records: Sequence[dict[str, Any]],
    dedupe: dict[str, Any],
    features: Sequence[dict[str, Any]],
    geom_qa: dict[str, Any],
) -> dict[str, Any]:
    out_dir = output_history_root / str(year)
    if out_dir.exists():
        shutil.rmtree(out_dir)
    chunks_dir = out_dir / "chunks"
    chunks_dir.mkdir(parents=True, exist_ok=True)

    chunked: dict[str, list[dict[str, Any]]] = {}
    for feature in features:
        chunk_id = core.chunk_id_for_feature(feature)
        chunked.setdefault(chunk_id, []).append(feature)

    chunk_manifest: list[dict[str, Any]] = []
    for chunk_id in sorted(chunked):
        chunk_features = chunked[chunk_id]
        path = chunks_dir / f"{chunk_id}.geojson"
        core.write_json(
            path,
            {
                "type": "FeatureCollection",
                "features": [core.clean_feature_for_write(f) for f in chunk_features],
            },
            compact=True,
        )
        chunk_manifest.append(
            {
                "id": chunk_id,
                "href": f"chunks/{chunk_id}.geojson",
                "feature_count": len(chunk_features),
                "bbox": core.union_bbox(f["_bbox"] for f in chunk_features),
                "bytes": path.stat().st_size,
                "sha256": core.sha256_file(path),
            }
        )

    manifest = {
        "phase": "WFIGS-4",
        "processor_version": PROCESSOR_VERSION,
        "collection": "history-year",
        "year": year,
        "label": f"NIFC/WFIGS {year} Historical Wildfire Perimeters",
        "generated_utc": core.utc_now_iso(),
        "source_layer_url": HISTORY_LAYER_URL,
        "source_item_id": HISTORY_ITEM_ID,
        "source_service_label": "WFIGS Interagency Fire Perimeters",
        "source_last_edit_epoch_ms": source_edit_ms,
        "source_last_edit_utc": core.epoch_ms_to_iso(source_edit_ms),
        "year_definition": "attr_FireDiscoveryDateTime calendar year in UTC",
        "fixed_where_clause": where,
        "relative_date_query_used": False,
        "source_object_id_count": len(source_ids),
        "source_object_id_sha256": object_id_sha256(source_ids),
        "source_year_signature": signature,
        "source_year_statistics": stats,
        "source_wildfire_record_count": len(raw_records),
        "published_fire_count": len(features),
        "deduplication": dedupe,
        "geometry_qa": geom_qa,
        "acreage_qa": core.acreage_qa(canonical_records),
        "display_geometry": {
            "purpose": "cartographic display only; not for acreage or burn-severity analysis",
            "generalization_tolerance_degrees": core.DISPLAY_GENERALIZATION_DEG,
            "coordinate_decimals": core.COORDINATE_DECIMALS,
            "source_crs": "EPSG:4326",
        },
        "chunking": {
            "strategy": "state_plus_5deg_representative_point",
            "grid_degrees": core.YTD_GRID_DEGREES,
            "feature_assignment": "one chunk per fire using representative point",
            "chunk_bbox": "actual union bounds of all full display geometries in the chunk",
            "future_loading": "Dashboard loads only chunks whose bbox intersects the map viewport.",
        },
        "chunk_count": len(chunk_manifest),
        "chunks": chunk_manifest,
        "total_chunk_bytes": int(sum(item["bytes"] for item in chunk_manifest)),
        "science_note": "WFIGS polygons represent mapped wildfire extent, not soil burn severity.",
        "completeness_note": (
            "This rolling operational history intentionally uses modern WFIGS years only. "
            "NIFC documents full-history records before 2021 as incomplete."
        ),
    }
    core.write_json(out_dir / "manifest.json", manifest, compact=False)
    return manifest


def manifest_summary(manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        "year": int(manifest["year"]),
        "href": f"{manifest['year']}/manifest.json",
        "published_fire_count": int(manifest.get("published_fire_count") or 0),
        "chunk_count": int(manifest.get("chunk_count") or 0),
        "total_chunk_bytes": int(manifest.get("total_chunk_bytes") or 0),
        "generated_utc": manifest.get("generated_utc"),
        "source_year_signature": manifest.get("source_year_signature"),
    }


def load_existing_year_manifest(existing_root: Path, year: int) -> dict[str, Any] | None:
    manifest = core.load_json(existing_root / str(year) / "manifest.json")
    if not manifest or manifest.get("collection") != "history-year" or int(manifest.get("year") or -1) != year:
        return None
    return manifest


def write_history_index(
    output_history_root: Path,
    years: Sequence[int],
    year_manifests: Sequence[dict[str, Any]],
    source_edit_ms: int | None,
) -> dict[str, Any]:
    by_year = {int(m["year"]): m for m in year_manifests}
    missing = [y for y in years if y not in by_year]
    if missing:
        raise RuntimeError(f"Cannot publish rolling history index; missing year manifests: {missing}")

    entries = [manifest_summary(by_year[y]) for y in years]
    index = {
        "phase": "WFIGS-4",
        "processor_version": PROCESSOR_VERSION,
        "collection": "history-index",
        "label": HISTORY_LABEL,
        "generated_utc": core.utc_now_iso(),
        "source_layer_url": HISTORY_LAYER_URL,
        "source_item_id": HISTORY_ITEM_ID,
        "source_last_edit_epoch_ms": source_edit_ms,
        "source_last_edit_utc": core.epoch_ms_to_iso(source_edit_ms),
        "rolling_window_years": len(years),
        "available_years": list(years),
        "default_year": int(years[0]),
        "year_definition": "attr_FireDiscoveryDateTime calendar year in UTC",
        "query_policy": "fixed absolute TIMESTAMP ranges only; no CURRENT_TIMESTAMP or relative-date query",
        "years": entries,
        "science_note": "WFIGS polygons represent mapped wildfire extent, not soil burn severity.",
        "completeness_note": (
            "Rolling window is limited to modern WFIGS years. NIFC documents data before 2021 "
            "in the full-history service as incomplete."
        ),
    }
    core.write_json(output_history_root / "manifest.json", index, compact=False)
    return index


def normalized_json_bytes(payload: dict[str, Any]) -> bytes:
    # generated_utc changes on every run; ignore it when testing whether the
    # semantic index changed enough to require a data-branch commit.
    clone = json.loads(json.dumps(payload))
    clone.pop("generated_utc", None)
    clone.pop("source_last_edit_epoch_ms", None)
    clone.pop("source_last_edit_utc", None)
    return json.dumps(clone, sort_keys=True, separators=(",", ":")).encode("utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rolling-years", type=int, default=DEFAULT_ROLLING_YEARS)
    parser.add_argument("--output-root", type=Path, default=Path("_wfigs_history_build"))
    parser.add_argument(
        "--existing-root",
        type=Path,
        default=Path("_wfigs_existing/static/wfigs/history"),
        help="Existing history root from wfigs-data, used for year-specific skip checks.",
    )
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--github-output", default=os.environ.get("GITHUB_OUTPUT"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    assert_core_compatibility()
    years = rolling_completed_years(args.rolling_years)
    print("WFIGS Phase-4 rolling historical build")
    print(f"Processor: {PROCESSOR_VERSION}")
    print("Rolling completed years: " + ", ".join(map(str, years)))

    session = core.build_session()
    metadata = core.layer_metadata(session, HISTORY_LAYER_URL)
    core.field_schema_guard(metadata)
    supported = str(metadata.get("supportedQueryFormats") or metadata.get("supportedQueryFormats") or "")
    if "geojson" not in supported.lower():
        raise RuntimeError(f"Full-history WFIGS layer does not advertise GeoJSON support: {supported!r}")
    source_edit_ms = core.source_last_edit_ms(metadata)
    print(f"Full-history service last edit: {core.epoch_ms_to_iso(source_edit_ms) or 'unknown'}")

    output_history_root = args.output_root / "history"
    output_history_root.mkdir(parents=True, exist_ok=True)
    changed_years: list[int] = []
    year_manifests: list[dict[str, Any]] = []

    for year in years:
        print(f"\n=== Historical wildfire year {year} ===")
        where = historical_where(year)
        print(f"Fixed query: {where}")
        ids = object_ids_for_where(session, where)
        print(f"WF source object IDs: {len(ids)}")
        if not ids:
            raise RuntimeError(f"WFIGS full-history returned zero WF records for {year}; refusing to publish.")
        stats = source_year_stats(session, where)
        signature = year_signature(ids, stats)

        if should_skip_year(year, args.existing_root, signature, args.force):
            existing = load_existing_year_manifest(args.existing_root, year)
            if existing is None:
                raise RuntimeError(f"Existing {year} history delivery passed skip check but manifest could not be read.")
            print("Year-specific signature unchanged; retaining existing published year.")
            year_manifests.append(existing)
            continue

        records = core.fetch_attributes(session, HISTORY_LAYER_URL, ids)
        if len(records) < max(1, int(len(ids) * 0.98)):
            raise RuntimeError(f"Attribute retrieval incomplete for {year}: got {len(records)} for {len(ids)} IDs")
        canonical, dedupe = core.deduplicate_records(records)
        print(
            f"Canonical wildfire identities: {len(canonical)} "
            f"(removed {dedupe['duplicate_records_removed']} duplicate records)"
        )
        features, geom_qa = core.fetch_normalized_features(
            session, HISTORY_LAYER_URL, canonical, f"history-{year}"
        )
        published_ids = {f["properties"]["fire_id"] for f in features}
        omitted = []
        for record in canonical:
            fire_id = core.record_identity(record)
            if fire_id in published_ids:
                continue
            omitted.append({
                "fire_id": fire_id,
                "incident_name": core.choose_incident_name(record),
                "source_objectid": record.get("OBJECTID"),
            })
        geom_qa = dict(geom_qa)
        geom_qa["omitted_features"] = omitted
        if omitted:
            print(f"Geometry omissions for {year}: {len(omitted)} (recorded in manifest QA)")
        if len(features) < max(1, int(len(canonical) * 0.98)):
            raise RuntimeError(
                f"Geometry retrieval incomplete for {year}: published {len(features)} of {len(canonical)} canonical records"
            )

        manifest = build_year(
            output_history_root,
            year,
            where,
            metadata,
            source_edit_ms,
            ids,
            stats,
            signature,
            records,
            canonical,
            dedupe,
            features,
            geom_qa,
        )
        changed_years.append(year)
        year_manifests.append(manifest)
        print(
            f"Published {manifest['published_fire_count']} fires in {manifest['chunk_count']} chunks "
            f"({manifest['total_chunk_bytes']} bytes)"
        )

    index = write_history_index(output_history_root, years, year_manifests, source_edit_ms)
    existing_index = core.load_json(args.existing_root / "manifest.json")
    index_changed = existing_index is None or normalized_json_bytes(index) != normalized_json_bytes(existing_index)
    any_changed = bool(changed_years) or index_changed

    print("\nWFIGS rolling history build validation gate: PASS")
    print("Changed years: " + (", ".join(map(str, changed_years)) if changed_years else "none"))
    print(f"History index changed: {index_changed}")

    core.append_github_output(
        args.github_output,
        {
            "changed": any_changed,
            "changed_years": ",".join(map(str, changed_years)),
            "available_years": ",".join(map(str, years)),
            "default_year": years[0],
        },
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("Interrupted", file=sys.stderr)
        raise SystemExit(130)
