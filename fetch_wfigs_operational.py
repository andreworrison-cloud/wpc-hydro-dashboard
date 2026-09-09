#!/usr/bin/env python3
"""Operational NIFC/WFIGS backend publisher for the WPC Hydro Dashboard.

Phase WFIGS-2 creates lean, browser-ready wildfire perimeter products without
modifying the dashboard frontend.

Modes
-----
current
    Near-real-time WFIGS Current wildfire perimeters. All WF incidents are
    retained, duplicate incident identities are collapsed to one canonical
    record, geometry is display-generalized, and a compact GeoJSON plus
    manifest are produced.

ytd
    WFIGS Year-To-Date wildfire perimeters. All WF incidents are retained after
    identity de-duplication. Geometry is display-generalized and partitioned into
    state + 5-degree geographic chunks for future viewport-driven lazy loading.

Scientific / operational guardrails
-----------------------------------
* WF (wildfire) only. RX (prescribed fire) is not mixed into the burn-scar layer.
* No acreage threshold removes small fires.
* Geometry generalization is display-only. Authoritative WFIGS acreage attributes
  are retained and must be used for acreage reporting.
* WFIGS perimeter = mapped fire extent, not soil burn severity.
* Existing published data are never overwritten unless a complete new build
  succeeds; publication is handled by the GitHub workflow after this script exits.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

try:
    from shapely import make_valid
    from shapely.geometry import GeometryCollection, MultiPolygon, Polygon, mapping, shape
    from shapely.ops import unary_union
except Exception as exc:  # pragma: no cover - workflow dependency guard
    raise RuntimeError(
        "Shapely is required. Install with: pip install 'shapely>=2.0,<3'"
    ) from exc

PROCESSOR_VERSION = "wfigs_phase2_operational_v1_1"
CURRENT_LAYER_URL = (
    "https://services3.arcgis.com/T4QMspbfLg3qTGWY/ArcGIS/rest/services/"
    "WFIGS_Interagency_Perimeters_Current/FeatureServer/0"
)
YTD_LAYER_URL = (
    "https://services3.arcgis.com/T4QMspbfLg3qTGWY/ArcGIS/rest/services/"
    "WFIGS_Interagency_Perimeters_YearToDate/FeatureServer/0"
)
SOURCE_ITEM_IDS = {
    "current": "d1c32af3212341869b3c810f1a215824",
    "ytd": "7c81ab78d8464e5c9771e49b64e834e9",
}
SOURCE_LABELS = {
    "current": "WFIGS Current Interagency Fire Perimeters",
    "ytd": "WFIGS Wildland Fire Perimeters Year To Date",
}
WILDFIRE_WHERE = "attr_IncidentTypeCategory = 'WF'"

# Phase-1 confirmed these fields in both authoritative schemas.
SOURCE_FIELDS = [
    "OBJECTID",
    "GlobalID",
    "poly_IncidentName",
    "poly_MapMethod",
    "poly_GISAcres",
    "poly_DateCurrent",
    "poly_PolygonDateTime",
    "poly_IRWINID",
    "poly_Acres_AutoCalc",
    "poly_Source",
    "attr_IncidentName",
    "attr_IncidentTypeCategory",
    "attr_IncidentSize",
    "attr_PercentContained",
    "attr_POOState",
    "attr_POOCounty",
    "attr_FireDiscoveryDateTime",
    "attr_ContainmentDateTime",
    "attr_ControlDateTime",
    "attr_FireOutDateTime",
    "attr_FireCause",
    "attr_FireCauseGeneral",
    "attr_UniqueFireIdentifier",
    "attr_IrwinID",
    "attr_ModifiedOnDateTime_dt",
]
REQUIRED_FIELDS = {
    "OBJECTID",
    "poly_IncidentName",
    "poly_GISAcres",
    "attr_IncidentTypeCategory",
    "attr_POOState",
    "attr_POOCounty",
    "attr_FireDiscoveryDateTime",
}

# 0.00008 degree is <= ~9 m north/south and finer east/west at higher latitude.
# It is a display tolerance, not a change to the scientific source geometry.
DISPLAY_GENERALIZATION_DEG = 0.00008
COORDINATE_DECIMALS = 6
ATTRIBUTE_BATCH_SIZE = 500
GEOMETRY_BATCH_SIZE = 150
YTD_GRID_DEGREES = 5.0
USER_AGENT = (
    "WPC-Hydro-Dashboard-WFIGS/2.0 "
    "(operational perimeter retrieval; GitHub Actions)"
)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def epoch_ms_to_iso(value: Any) -> str | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        try:
            if not math.isfinite(float(value)):
                return None
            return (
                datetime.fromtimestamp(float(value) / 1000.0, tz=timezone.utc)
                .isoformat(timespec="seconds")
                .replace("+00:00", "Z")
            )
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if text.endswith("Z"):
            return text
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return text
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    return None


def safe_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def build_session() -> requests.Session:
    retry = Retry(
        total=5,
        connect=5,
        read=5,
        status=5,
        backoff_factor=1.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET", "POST"}),
        respect_retry_after_header=True,
        raise_on_status=False,
    )
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json,*/*"})
    adapter = HTTPAdapter(max_retries=retry, pool_connections=4, pool_maxsize=4)
    session.mount("https://", adapter)
    return session


def request_json(
    session: requests.Session,
    method: str,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None,
    timeout: tuple[int, int] = (20, 180),
) -> dict[str, Any]:
    response = session.request(method, url, params=params, data=data, timeout=timeout)
    response.raise_for_status()
    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError(f"Non-JSON response from {url}: {response.text[:500]!r}") from exc
    if isinstance(payload, dict) and "error" in payload:
        raise RuntimeError(f"ArcGIS error from {url}: {payload['error']}")
    if not isinstance(payload, dict):
        raise RuntimeError(f"Unexpected JSON type from {url}: {type(payload).__name__}")
    return payload


def layer_metadata(session: requests.Session, layer_url: str) -> dict[str, Any]:
    return request_json(session, "GET", layer_url, params={"f": "pjson"})


def arcgis_query(
    session: requests.Session,
    layer_url: str,
    payload: dict[str, Any],
    *,
    timeout: tuple[int, int] = (20, 180),
) -> dict[str, Any]:
    data = dict(payload)
    data.setdefault("f", "json")
    return request_json(session, "POST", layer_url + "/query", data=data, timeout=timeout)


def object_ids(session: requests.Session, layer_url: str) -> list[int]:
    payload = arcgis_query(
        session,
        layer_url,
        {"where": WILDFIRE_WHERE, "returnIdsOnly": "true", "f": "json"},
    )
    return sorted(int(v) for v in (payload.get("objectIds") or []))


def chunks(values: Sequence[int], size: int) -> Iterator[list[int]]:
    for start in range(0, len(values), size):
        yield list(values[start : start + size])


def fetch_attributes(
    session: requests.Session,
    layer_url: str,
    ids: Sequence[int],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    batches = list(chunks(ids, ATTRIBUTE_BATCH_SIZE))
    for i, batch in enumerate(batches, start=1):
        payload = arcgis_query(
            session,
            layer_url,
            {
                "objectIds": ",".join(map(str, batch)),
                "outFields": ",".join(SOURCE_FIELDS),
                "returnGeometry": "false",
                "f": "json",
            },
        )
        records.extend((f.get("attributes") or {}) for f in payload.get("features", []))
        if i == 1 or i == len(batches) or i % 10 == 0:
            print(f"  attributes {i}/{len(batches)} batches")
        time.sleep(0.03)
    return records


def fetch_geojson_batch(
    session: requests.Session,
    layer_url: str,
    ids: Sequence[int],
) -> list[dict[str, Any]]:
    response = session.post(
        layer_url + "/query",
        data={
            "objectIds": ",".join(map(str, ids)),
            "outFields": "OBJECTID",
            "returnGeometry": "true",
            "outSR": "4326",
            "maxAllowableOffset": str(DISPLAY_GENERALIZATION_DEG),
            "f": "geojson",
        },
        timeout=(20, 300),
    )
    response.raise_for_status()
    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError(f"Non-GeoJSON WFIGS response: {response.text[:500]!r}") from exc
    if isinstance(payload, dict) and "error" in payload:
        raise RuntimeError(f"ArcGIS WFIGS geometry error: {payload['error']}")
    if payload.get("type") != "FeatureCollection":
        raise RuntimeError(f"Unexpected WFIGS GeoJSON type: {payload.get('type')!r}")
    return payload.get("features") or []


def date_rank(record: dict[str, Any], key: str) -> float:
    value = record.get(key)
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return float(value)
    return float("-inf")


def record_identity(record: dict[str, Any]) -> str:
    value = record.get("attr_UniqueFireIdentifier")
    if value is not None and str(value).strip():
        return "ufid:" + str(value).strip().upper()
    for key in ("poly_IRWINID", "attr_IrwinID"):
        value = record.get(key)
        if value is not None and str(value).strip():
            return "irwin:" + str(value).strip().strip("{}").lower()
    value = record.get("GlobalID")
    if value is not None and str(value).strip():
        return "global:" + str(value).strip().strip("{}").lower()
    return "oid:" + str(record.get("OBJECTID"))


def canonical_rank(record: dict[str, Any]) -> tuple[float, float, float, float, int]:
    # Latest mapped perimeter first; if timestamps are tied/missing, prefer the
    # larger GIS perimeter and then the higher OBJECTID for deterministic output.
    return (
        date_rank(record, "poly_PolygonDateTime"),
        date_rank(record, "poly_DateCurrent"),
        date_rank(record, "attr_ModifiedOnDateTime_dt"),
        safe_float(record.get("poly_GISAcres")) or -1.0,
        int(record.get("OBJECTID") or -1),
    )


def deduplicate_records(records: Sequence[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        groups[record_identity(record)].append(record)
    canonical = [max(group, key=canonical_rank) for group in groups.values()]
    canonical.sort(key=lambda r: int(r.get("OBJECTID") or 0))
    duplicates = {key: group for key, group in groups.items() if len(group) > 1}
    return canonical, {
        "source_record_count": len(records),
        "unique_identity_count": len(groups),
        "duplicate_identity_groups_removed": len(duplicates),
        "duplicate_records_removed": int(sum(len(g) - 1 for g in duplicates.values())),
        "largest_duplicate_group": max((len(g) for g in duplicates.values()), default=1),
    }


def field_schema_guard(metadata: dict[str, Any]) -> None:
    fields = {f.get("name") for f in metadata.get("fields", []) if f.get("name")}
    missing_required = sorted(REQUIRED_FIELDS - fields)
    missing_requested = sorted(set(SOURCE_FIELDS) - fields)
    if missing_required or missing_requested:
        raise RuntimeError(
            "WFIGS schema changed. "
            f"missing required={missing_required}; missing requested={missing_requested}"
        )
    if metadata.get("geometryType") != "esriGeometryPolygon":
        raise RuntimeError(f"Unexpected WFIGS geometry type: {metadata.get('geometryType')!r}")


def source_last_edit_ms(metadata: dict[str, Any]) -> int | None:
    editing = metadata.get("editingInfo") or {}
    value = editing.get("lastEditDate") or editing.get("dataLastEditDate")
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return value if isinstance(value, dict) else None


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, payload: Any, *, compact: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if compact:
        text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    else:
        text = json.dumps(payload, ensure_ascii=False, indent=2)
    path.write_text(text + "\n", encoding="utf-8")


def round_coordinates(node: Any) -> Any:
    if not isinstance(node, (list, tuple)):
        return node
    if len(node) >= 2 and all(isinstance(v, (int, float)) for v in node[:2]):
        return [round(float(v), COORDINATE_DECIMALS) for v in node]
    return [round_coordinates(child) for child in node]


def polygonal_only(geom: Any) -> Polygon | MultiPolygon | None:
    if geom is None or geom.is_empty:
        return None
    if isinstance(geom, (Polygon, MultiPolygon)):
        return geom
    if isinstance(geom, GeometryCollection):
        parts = [g for g in geom.geoms if isinstance(g, (Polygon, MultiPolygon)) and not g.is_empty]
        if not parts:
            return None
        merged = unary_union(parts)
        return merged if isinstance(merged, (Polygon, MultiPolygon)) else None
    return None


def clean_display_geometry(geometry: dict[str, Any] | None) -> tuple[dict[str, Any] | None, tuple[float, float, float, float] | None, tuple[float, float] | None]:
    """Return a valid, compact polygon geometry for browser display.

    Validation is intentionally performed *after* coordinate rounding. Phase-2
    Current verification showed that rounding can collapse a tiny ring to fewer
    than three unique vertices even when the pre-rounding Shapely geometry is
    valid. The post-round repair prevents invalid GeoJSON from reaching Leaflet.
    """
    if not geometry:
        return None, None, None
    geom = shape(geometry)
    if geom.is_empty:
        return None, None, None
    if not geom.is_valid:
        geom = make_valid(geom)
    geom = polygonal_only(geom)
    if geom is None:
        return None, None, None

    geom = geom.simplify(DISPLAY_GENERALIZATION_DEG, preserve_topology=True)
    geom = polygonal_only(geom)
    if geom is None or geom.is_empty:
        return None, None, None

    # Round for payload size, then reconstruct and validate the exact geometry
    # that will be written to GeoJSON. Do not round a second time after repair,
    # because doing so could recreate the same degenerate-ring condition.
    rounded_geo = mapping(geom)
    rounded_geo["coordinates"] = round_coordinates(rounded_geo.get("coordinates"))
    display_geom = shape(rounded_geo)
    if display_geom.is_empty:
        return None, None, None
    if not display_geom.is_valid:
        display_geom = make_valid(display_geom)
    display_geom = polygonal_only(display_geom)
    if display_geom is None or display_geom.is_empty or not display_geom.is_valid:
        return None, None, None

    bounds = tuple(float(v) for v in display_geom.bounds)
    pt = display_geom.representative_point()
    return mapping(display_geom), bounds, (float(pt.x), float(pt.y))


def choose_incident_name(record: dict[str, Any]) -> str | None:
    for key in ("poly_IncidentName", "attr_IncidentName"):
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def normalize_state(value: Any) -> tuple[str | None, str | None]:
    if value is None:
        return None, None
    raw = str(value).strip().upper()
    if not raw:
        return None, None
    if raw.startswith("US-") and len(raw) > 3:
        return raw[3:], raw
    return raw, raw


def normalize_properties(record: dict[str, Any], source_key: str) -> dict[str, Any]:
    gis = safe_float(record.get("poly_GISAcres"))
    auto = safe_float(record.get("poly_Acres_AutoCalc"))
    reported = safe_float(record.get("attr_IncidentSize"))
    # Phase-1/YTD QA showed occasional large GIS-vs-auto inconsistencies. Use the
    # explicit WFIGS GIS acreage first; auto-calculated acreage is only a fallback.
    if gis is not None and gis >= 0:
        mapped = gis
        mapped_source = "poly_GISAcres"
    elif auto is not None and auto >= 0:
        mapped = auto
        mapped_source = "poly_Acres_AutoCalc_fallback"
    else:
        mapped = None
        mapped_source = None
    state, state_raw = normalize_state(record.get("attr_POOState"))
    return {
        "fire_id": record_identity(record),
        "source_collection": source_key,
        "source_objectid": record.get("OBJECTID"),
        "incident_name": choose_incident_name(record),
        "mapped_acres": mapped,
        "mapped_acres_source": mapped_source,
        "gis_acres": gis,
        "auto_acres": auto,
        "reported_acres": reported,
        "percent_contained": safe_float(record.get("attr_PercentContained")),
        "state": state,
        "state_wfigs": state_raw,
        "county": record.get("attr_POOCounty"),
        "discovery_time_utc": epoch_ms_to_iso(record.get("attr_FireDiscoveryDateTime")),
        "perimeter_time_utc": epoch_ms_to_iso(record.get("poly_PolygonDateTime")),
        "perimeter_edit_time_utc": epoch_ms_to_iso(record.get("poly_DateCurrent")),
        "incident_modified_time_utc": epoch_ms_to_iso(record.get("attr_ModifiedOnDateTime_dt")),
        "containment_time_utc": epoch_ms_to_iso(record.get("attr_ContainmentDateTime")),
        "control_time_utc": epoch_ms_to_iso(record.get("attr_ControlDateTime")),
        "fire_out_time_utc": epoch_ms_to_iso(record.get("attr_FireOutDateTime")),
        "fire_cause": record.get("attr_FireCause"),
        "fire_cause_general": record.get("attr_FireCauseGeneral"),
        "map_method": record.get("poly_MapMethod"),
        "source_dataset": record.get("poly_Source"),
        "unique_fire_identifier": record.get("attr_UniqueFireIdentifier"),
        "irwin_id": record.get("poly_IRWINID") or record.get("attr_IrwinID"),
        "global_id": record.get("GlobalID"),
    }


def union_bbox(boxes: Iterable[Sequence[float]]) -> list[float] | None:
    values = [tuple(map(float, box)) for box in boxes if box is not None]
    if not values:
        return None
    return [
        min(v[0] for v in values),
        min(v[1] for v in values),
        max(v[2] for v in values),
        max(v[3] for v in values),
    ]


def delivery_is_complete(mode: str, existing_root: Path, manifest: dict[str, Any] | None) -> bool:
    if not manifest:
        return False
    if mode == "current":
        return (existing_root / "current" / "perimeters.geojson").exists()
    chunks_meta = manifest.get("chunks") or []
    if not chunks_meta:
        return False
    return all((existing_root / "ytd" / str(item.get("href", ""))).exists() for item in chunks_meta)


def should_skip(mode: str, existing_root: Path, source_edit_ms: int | None, force: bool) -> bool:
    if force:
        return False
    manifest = load_json(existing_root / mode / "manifest.json")
    if not manifest or not delivery_is_complete(mode, existing_root, manifest):
        return False
    if manifest.get("processor_version") != PROCESSOR_VERSION:
        return False
    if source_edit_ms is None:
        return False
    return int(manifest.get("source_last_edit_epoch_ms") or -1) == int(source_edit_ms)


def acreage_qa(records: Sequence[dict[str, Any]]) -> dict[str, Any]:
    missing_gis = missing_auto = missing_reported = 0
    ratio_outliers = 0
    compared = 0
    for record in records:
        gis = safe_float(record.get("poly_GISAcres"))
        auto = safe_float(record.get("poly_Acres_AutoCalc"))
        reported = safe_float(record.get("attr_IncidentSize"))
        if gis is None:
            missing_gis += 1
        if auto is None:
            missing_auto += 1
        if reported is None:
            missing_reported += 1
        if gis is not None and auto is not None and gis > 0 and auto > 0:
            compared += 1
            ratio = auto / gis
            if ratio < 0.5 or ratio > 2.0:
                ratio_outliers += 1
    return {
        "missing_gis_acres": missing_gis,
        "missing_auto_acres": missing_auto,
        "missing_reported_acres": missing_reported,
        "gis_vs_auto_compared": compared,
        "gis_vs_auto_factor2_outliers": ratio_outliers,
        "primary_dashboard_mapped_acres_field": "poly_GISAcres",
        "fallback_mapped_acres_field": "poly_Acres_AutoCalc",
    }


def fetch_normalized_features(
    session: requests.Session,
    layer_url: str,
    records: Sequence[dict[str, Any]],
    source_key: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    by_oid = {int(r["OBJECTID"]): r for r in records if r.get("OBJECTID") is not None}
    ids = sorted(by_oid)
    output: list[dict[str, Any]] = []
    invalid_or_empty = 0
    missing_geometry = 0
    batches = list(chunks(ids, GEOMETRY_BATCH_SIZE))
    for i, batch in enumerate(batches, start=1):
        features = fetch_geojson_batch(session, layer_url, batch)
        seen: set[int] = set()
        for feature in features:
            props = feature.get("properties") or {}
            oid = props.get("OBJECTID")
            if oid is None:
                continue
            oid = int(oid)
            seen.add(oid)
            record = by_oid.get(oid)
            if record is None:
                continue
            geometry, bounds, rep = clean_display_geometry(feature.get("geometry"))
            if geometry is None or bounds is None or rep is None:
                invalid_or_empty += 1
                continue
            output.append(
                {
                    "type": "Feature",
                    "geometry": geometry,
                    "properties": normalize_properties(record, source_key),
                    "_bbox": bounds,
                    "_rep": rep,
                }
            )
        missing_geometry += len(set(batch) - seen)
        if i == 1 or i == len(batches) or i % 10 == 0:
            print(f"  geometry {i}/{len(batches)} batches")
        time.sleep(0.04)
    return output, {
        "requested_geometry_count": len(ids),
        "delivered_geometry_count": len(output),
        "invalid_or_empty_geometry_count": invalid_or_empty,
        "missing_geometry_response_count": missing_geometry,
    }


def clean_feature_for_write(feature: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "Feature",
        "geometry": feature["geometry"],
        "properties": feature["properties"],
    }


def format_band(value: float, axis: str) -> str:
    v = int(math.floor(value / YTD_GRID_DEGREES) * YTD_GRID_DEGREES)
    if axis == "lat":
        return ("N" if v >= 0 else "S") + f"{abs(v):02d}"
    return ("E" if v >= 0 else "W") + f"{abs(v):03d}"


def chunk_id_for_feature(feature: dict[str, Any]) -> str:
    props = feature["properties"]
    state = props.get("state") or "UNK"
    lon, lat = feature["_rep"]
    return f"{state}_{format_band(lat, 'lat')}_{format_band(lon, 'lon')}"


def build_current(
    output_root: Path,
    source_meta: dict[str, Any],
    source_edit_ms: int | None,
    raw_records: Sequence[dict[str, Any]],
    canonical_records: Sequence[dict[str, Any]],
    dedupe: dict[str, Any],
    features: Sequence[dict[str, Any]],
    geom_qa: dict[str, Any],
) -> dict[str, Any]:
    out_dir = output_root / "current"
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    geojson_path = out_dir / "perimeters.geojson"
    write_json(
        geojson_path,
        {"type": "FeatureCollection", "features": [clean_feature_for_write(f) for f in features]},
        compact=True,
    )
    bounds = union_bbox(f["_bbox"] for f in features)
    manifest = {
        "phase": "WFIGS-2",
        "processor_version": PROCESSOR_VERSION,
        "collection": "current",
        "label": SOURCE_LABELS["current"],
        "generated_utc": utc_now_iso(),
        "source_layer_url": CURRENT_LAYER_URL,
        "source_item_id": SOURCE_ITEM_IDS["current"],
        "source_last_edit_epoch_ms": source_edit_ms,
        "source_last_edit_utc": epoch_ms_to_iso(source_edit_ms),
        "source_wildfire_record_count": len(raw_records),
        "published_fire_count": len(features),
        "deduplication": dedupe,
        "geometry_qa": geom_qa,
        "acreage_qa": acreage_qa(canonical_records),
        "display_geometry": {
            "purpose": "cartographic display only; not for acreage or burn-severity analysis",
            "generalization_tolerance_degrees": DISPLAY_GENERALIZATION_DEG,
            "coordinate_decimals": COORDINATE_DECIMALS,
            "source_crs": "EPSG:4326",
        },
        "bbox": bounds,
        "href": "perimeters.geojson",
        "bytes": geojson_path.stat().st_size,
        "sha256": sha256_file(geojson_path),
        "active_fire_ids": sorted(f["properties"]["fire_id"] for f in features),
        "science_note": "WFIGS polygons represent mapped wildfire extent, not soil burn severity.",
    }
    write_json(out_dir / "manifest.json", manifest, compact=False)
    return manifest


def build_ytd(
    output_root: Path,
    source_meta: dict[str, Any],
    source_edit_ms: int | None,
    raw_records: Sequence[dict[str, Any]],
    canonical_records: Sequence[dict[str, Any]],
    dedupe: dict[str, Any],
    features: Sequence[dict[str, Any]],
    geom_qa: dict[str, Any],
) -> dict[str, Any]:
    out_dir = output_root / "ytd"
    if out_dir.exists():
        shutil.rmtree(out_dir)
    chunks_dir = out_dir / "chunks"
    chunks_dir.mkdir(parents=True, exist_ok=True)

    chunked: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for feature in features:
        chunked[chunk_id_for_feature(feature)].append(feature)

    chunk_manifest: list[dict[str, Any]] = []
    for chunk_id in sorted(chunked):
        chunk_features = chunked[chunk_id]
        path = chunks_dir / f"{chunk_id}.geojson"
        write_json(
            path,
            {"type": "FeatureCollection", "features": [clean_feature_for_write(f) for f in chunk_features]},
            compact=True,
        )
        chunk_manifest.append(
            {
                "id": chunk_id,
                "href": f"chunks/{chunk_id}.geojson",
                "feature_count": len(chunk_features),
                "bbox": union_bbox(f["_bbox"] for f in chunk_features),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )

    manifest = {
        "phase": "WFIGS-2",
        "processor_version": PROCESSOR_VERSION,
        "collection": "ytd",
        "label": SOURCE_LABELS["ytd"],
        "generated_utc": utc_now_iso(),
        "source_layer_url": YTD_LAYER_URL,
        "source_item_id": SOURCE_ITEM_IDS["ytd"],
        "source_last_edit_epoch_ms": source_edit_ms,
        "source_last_edit_utc": epoch_ms_to_iso(source_edit_ms),
        "source_wildfire_record_count": len(raw_records),
        "published_fire_count": len(features),
        "deduplication": dedupe,
        "geometry_qa": geom_qa,
        "acreage_qa": acreage_qa(canonical_records),
        "display_geometry": {
            "purpose": "cartographic display only; not for acreage or burn-severity analysis",
            "generalization_tolerance_degrees": DISPLAY_GENERALIZATION_DEG,
            "coordinate_decimals": COORDINATE_DECIMALS,
            "source_crs": "EPSG:4326",
        },
        "chunking": {
            "strategy": "state_plus_5deg_representative_point",
            "grid_degrees": YTD_GRID_DEGREES,
            "feature_assignment": "one chunk per fire using representative point",
            "chunk_bbox": "actual union bounds of all full display geometries in the chunk",
            "future_loading": "Phase WFIGS-3 should load only chunks whose bbox intersects the map viewport.",
        },
        "chunk_count": len(chunk_manifest),
        "chunks": chunk_manifest,
        "total_chunk_bytes": int(sum(item["bytes"] for item in chunk_manifest)),
        "science_note": "WFIGS polygons represent mapped wildfire extent, not soil burn severity.",
    }
    write_json(out_dir / "manifest.json", manifest, compact=False)
    return manifest


def validate_manifest_and_files(mode: str, root: Path, manifest: dict[str, Any]) -> None:
    errors: list[str] = []
    if manifest.get("processor_version") != PROCESSOR_VERSION:
        errors.append("processor version mismatch")
    if manifest.get("collection") != mode:
        errors.append("collection mismatch")
    if int(manifest.get("published_fire_count") or 0) <= 0:
        errors.append("no wildfire features were published")
    if mode == "current":
        path = root / "current" / "perimeters.geojson"
        if not path.exists() or path.stat().st_size <= 0:
            errors.append("current perimeters.geojson missing/empty")
        elif sha256_file(path) != manifest.get("sha256"):
            errors.append("current GeoJSON checksum mismatch")
    else:
        chunks_meta = manifest.get("chunks") or []
        if len(chunks_meta) != int(manifest.get("chunk_count") or -1):
            errors.append("YTD chunk count mismatch")
        published = 0
        for item in chunks_meta:
            path = root / "ytd" / str(item.get("href"))
            if not path.exists() or path.stat().st_size <= 0:
                errors.append(f"missing/empty YTD chunk: {path}")
                continue
            published += int(item.get("feature_count") or 0)
            if sha256_file(path) != item.get("sha256"):
                errors.append(f"checksum mismatch: {path.name}")
        if published != int(manifest.get("published_fire_count") or -1):
            errors.append("YTD published feature total does not match chunk sum")
    if errors:
        raise RuntimeError("WFIGS Phase-2 build validation failed: " + "; ".join(errors[:20]))


def append_github_output(path: str | None, values: dict[str, Any]) -> None:
    if not path:
        return
    with open(path, "a", encoding="utf-8") as handle:
        for key, value in values.items():
            handle.write(f"{key}={str(value).lower() if isinstance(value, bool) else value}\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("current", "ytd"), required=True)
    parser.add_argument("--output-root", type=Path, default=Path("_wfigs_build"))
    parser.add_argument(
        "--existing-root",
        type=Path,
        default=Path("_wfigs_existing/static/wfigs"),
        help="Existing rolling-data root used for source-edit skip checks.",
    )
    parser.add_argument("--force", action="store_true", help="Rebuild even when source edit time is unchanged.")
    parser.add_argument("--github-output", default=os.environ.get("GITHUB_OUTPUT"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    mode = args.mode
    layer_url = CURRENT_LAYER_URL if mode == "current" else YTD_LAYER_URL
    print(f"WFIGS Phase-2 operational build: mode={mode}")
    print(f"Processor: {PROCESSOR_VERSION}")

    session = build_session()
    metadata = layer_metadata(session, layer_url)
    field_schema_guard(metadata)
    edit_ms = source_last_edit_ms(metadata)
    print(f"Source last edit: {epoch_ms_to_iso(edit_ms) or 'unknown'}")

    if should_skip(mode, args.existing_root, edit_ms, args.force):
        print("No source change and processor version unchanged; retaining existing published data.")
        append_github_output(
            args.github_output,
            {"changed": False, "mode": mode, "source_last_edit": epoch_ms_to_iso(edit_ms) or "unknown"},
        )
        return 0

    ids = object_ids(session, layer_url)
    if not ids:
        raise RuntimeError("WFIGS returned zero WF object IDs; refusing to publish an empty operational dataset.")
    print(f"WF source object IDs: {len(ids)}")

    records = fetch_attributes(session, layer_url, ids)
    if len(records) < max(1, int(len(ids) * 0.98)):
        raise RuntimeError(f"Attribute retrieval incomplete: got {len(records)} records for {len(ids)} IDs")
    canonical, dedupe = deduplicate_records(records)
    print(
        "Canonical wildfire identities: "
        f"{len(canonical)} (removed {dedupe['duplicate_records_removed']} duplicate records)"
    )

    features, geom_qa = fetch_normalized_features(session, layer_url, canonical, mode)
    if len(features) < max(1, int(len(canonical) * 0.98)):
        raise RuntimeError(
            f"Geometry retrieval incomplete: published {len(features)} of {len(canonical)} canonical records"
        )

    args.output_root.mkdir(parents=True, exist_ok=True)
    if mode == "current":
        manifest = build_current(
            args.output_root, metadata, edit_ms, records, canonical, dedupe, features, geom_qa
        )
    else:
        manifest = build_ytd(
            args.output_root, metadata, edit_ms, records, canonical, dedupe, features, geom_qa
        )
    validate_manifest_and_files(mode, args.output_root, manifest)

    print(f"Published fire features: {manifest['published_fire_count']}")
    if mode == "ytd":
        print(f"YTD chunks: {manifest['chunk_count']}")
        print(f"YTD chunk bytes: {manifest['total_chunk_bytes']}")
    else:
        print(f"Current GeoJSON bytes: {manifest['bytes']}")
    print("WFIGS Phase-2 build validation: PASS")

    append_github_output(
        args.github_output,
        {
            "changed": True,
            "mode": mode,
            "source_last_edit": manifest.get("source_last_edit_utc") or "unknown",
            "published_fire_count": manifest.get("published_fire_count"),
            "chunk_count": manifest.get("chunk_count", 0),
        },
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("Interrupted", file=sys.stderr)
        raise SystemExit(130)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
