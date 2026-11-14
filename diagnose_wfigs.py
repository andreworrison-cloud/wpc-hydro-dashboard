#!/usr/bin/env python3
"""Phase WFIGS-1 source-discovery diagnostic for the WPC Hydro Dashboard.

This is intentionally backend-only. It does not modify dashboard assets and does not
publish operational data. It characterizes the authoritative NIFC/WFIGS Current and
Year-To-Date perimeter services with an operational flash-flood / burn-scar use case
in mind.

Outputs:
  * wfigs_phase1_report.json
  * wfigs_phase1_summary.txt
  * wfigs_current_wildfires.geojson (complete current WF geometry when safely sized;
    otherwise a representative sample)
  * wfigs_ytd_geometry_sample.geojson (representative YTD wildfire geometry sample)
  * wfigs_ytd_wildfire_attributes.json (lean attribute inventory, no geometry)

The diagnostic deliberately filters the candidate dashboard perimeter data to IRWIN
incident type WF (Wildfire). Prescribed fire (RX) is counted for source awareness but
is not mixed into the wildfire/burn-scar candidate layer.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

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

WILDFIRE_WHERE = "attr_IncidentTypeCategory = 'WF'"
PRESCRIBED_FIRE_WHERE = "attr_IncidentTypeCategory = 'RX'"

# Only fields with a plausible operational hydro-dashboard use are retained.
# The live WFIGS source contains many more IRWIN attributes.
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

# Fields required for a useful hover/popup experience. The diagnostic fails loudly if
# these disappear from the authoritative schema.
REQUIRED_HOVER_FIELDS = {
    "poly_IncidentName",
    "poly_GISAcres",
    "poly_PolygonDateTime",
    "attr_IncidentSize",
    "attr_PercentContained",
    "attr_POOState",
    "attr_POOCounty",
    "attr_FireDiscoveryDateTime",
    "attr_IncidentTypeCategory",
}

DATE_FIELDS = {
    "poly_DateCurrent",
    "poly_PolygonDateTime",
    "attr_FireDiscoveryDateTime",
    "attr_ContainmentDateTime",
    "attr_ControlDateTime",
    "attr_FireOutDateTime",
    "attr_ModifiedOnDateTime_dt",
}

# A full-current wildfire GeoJSON is very useful for a later Leaflet hover prototype,
# but guard against unexpectedly huge source growth. If exceeded, a representative
# sample is written instead of stressing the public service or the artifact pipeline.
CURRENT_FULL_GEOMETRY_LIMIT = 2500
ATTRIBUTE_BATCH_SIZE = 500
GEOMETRY_BATCH_SIZE = 250

# Representative YTD geometry sample design. This is not a hydrologic threshold; it is
# only for Phase-1 geometry/performance characterization.
YTD_NEWEST_SAMPLE = 150
YTD_LARGEST_SAMPLE = 100
YTD_PER_ACREAGE_BIN = 25
ACREAGE_BINS = [
    ("lt_10", None, 10.0),
    ("10_100", 10.0, 100.0),
    ("100_1000", 100.0, 1000.0),
    ("1000_10000", 1000.0, 10000.0),
    ("ge_10000", 10000.0, None),
]

USER_AGENT = (
    "WPC-Hydro-Dashboard-WFIGS-Phase1/1.0 "
    "(source discovery; GitHub Actions; no operational publishing)"
)


@dataclass(frozen=True)
class SourceConfig:
    key: str
    label: str
    layer_url: str
    item_id: str


SOURCES = [
    SourceConfig(
        "current",
        "WFIGS Current Interagency Fire Perimeters",
        CURRENT_LAYER_URL,
        SOURCE_ITEM_IDS["current"],
    ),
    SourceConfig(
        "ytd",
        "WFIGS Wildland Fire Perimeters Year To Date",
        YTD_LAYER_URL,
        SOURCE_ITEM_IDS["ytd"],
    ),
]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def epoch_ms_to_iso(value: Any) -> str | None:
    """Normalize ArcGIS date values to UTC ISO-8601 when possible."""
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        if not math.isfinite(float(value)):
            return None
        # ArcGIS date fields are milliseconds from Unix epoch.
        try:
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
        # Accept already-normalized values without pretending to know a missing TZ.
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


def layer_metadata(session: requests.Session, source: SourceConfig) -> dict[str, Any]:
    return request_json(session, "GET", source.layer_url, params={"f": "pjson"})


def arcgis_query(
    session: requests.Session,
    source: SourceConfig,
    payload: dict[str, Any],
    *,
    timeout: tuple[int, int] = (20, 180),
) -> dict[str, Any]:
    data = dict(payload)
    data.setdefault("f", "json")
    return request_json(session, "POST", source.layer_url + "/query", data=data, timeout=timeout)


def count_features(session: requests.Session, source: SourceConfig, where: str) -> int:
    payload = arcgis_query(
        session,
        source,
        {"where": where, "returnCountOnly": "true", "f": "json"},
    )
    return int(payload.get("count", 0))


def object_ids(session: requests.Session, source: SourceConfig, where: str) -> list[int]:
    payload = arcgis_query(
        session,
        source,
        {"where": where, "returnIdsOnly": "true", "f": "json"},
    )
    ids = payload.get("objectIds") or []
    return sorted(int(value) for value in ids)


def chunks(values: Sequence[int], size: int) -> Iterator[list[int]]:
    for start in range(0, len(values), size):
        yield list(values[start : start + size])


def fetch_attributes(
    session: requests.Session,
    source: SourceConfig,
    ids: Sequence[int],
    fields: Sequence[str],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    if not ids:
        return records
    out_fields = ",".join(fields)
    batches = list(chunks(ids, ATTRIBUTE_BATCH_SIZE))
    for index, batch in enumerate(batches, start=1):
        payload = arcgis_query(
            session,
            source,
            {
                "objectIds": ",".join(map(str, batch)),
                "outFields": out_fields,
                "returnGeometry": "false",
                "outSR": "4326",
                "f": "json",
            },
        )
        for feature in payload.get("features", []):
            attrs = feature.get("attributes") or {}
            records.append(attrs)
        if index == 1 or index == len(batches) or index % 10 == 0:
            print(f"  {source.key}: attributes {index}/{len(batches)} batches")
        time.sleep(0.03)
    return records


def fetch_geojson_features(
    session: requests.Session,
    source: SourceConfig,
    ids: Sequence[int],
    fields: Sequence[str],
) -> list[dict[str, Any]]:
    if not ids:
        return []
    features: list[dict[str, Any]] = []
    out_fields = ",".join(fields)
    batches = list(chunks(ids, GEOMETRY_BATCH_SIZE))
    for index, batch in enumerate(batches, start=1):
        # f=geojson returns a FeatureCollection directly.
        response = session.post(
            source.layer_url + "/query",
            data={
                "objectIds": ",".join(map(str, batch)),
                "outFields": out_fields,
                "returnGeometry": "true",
                "outSR": "4326",
                "f": "geojson",
            },
            timeout=(20, 240),
        )
        response.raise_for_status()
        try:
            payload = response.json()
        except ValueError as exc:
            raise RuntimeError(
                f"Non-GeoJSON response from {source.layer_url}/query: {response.text[:500]!r}"
            ) from exc
        if isinstance(payload, dict) and "error" in payload:
            raise RuntimeError(f"ArcGIS error from {source.layer_url}/query: {payload['error']}")
        if payload.get("type") != "FeatureCollection":
            raise RuntimeError(f"Unexpected GeoJSON payload type for {source.key}: {payload.get('type')!r}")
        features.extend(payload.get("features") or [])
        if index == 1 or index == len(batches) or index % 5 == 0:
            print(f"  {source.key}: geometry {index}/{len(batches)} batches")
        time.sleep(0.05)
    return features


def choose_name(props: dict[str, Any]) -> str | None:
    for key in ("poly_IncidentName", "attr_IncidentName"):
        value = props.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def normalize_feature(feature: dict[str, Any], source_key: str) -> dict[str, Any]:
    props = feature.get("properties") or {}
    normalized: dict[str, Any] = {
        "source_collection": source_key,
        "source_objectid": props.get("OBJECTID"),
        "incident_name": choose_name(props),
        "incident_type": props.get("attr_IncidentTypeCategory"),
        "gis_acres": props.get("poly_GISAcres"),
        "auto_acres": props.get("poly_Acres_AutoCalc"),
        "reported_acres": props.get("attr_IncidentSize"),
        "percent_contained": props.get("attr_PercentContained"),
        "state": props.get("attr_POOState"),
        "county": props.get("attr_POOCounty"),
        "discovery_time_utc": epoch_ms_to_iso(props.get("attr_FireDiscoveryDateTime")),
        "perimeter_time_utc": epoch_ms_to_iso(props.get("poly_PolygonDateTime")),
        "perimeter_edit_time_utc": epoch_ms_to_iso(props.get("poly_DateCurrent")),
        "incident_modified_time_utc": epoch_ms_to_iso(props.get("attr_ModifiedOnDateTime_dt")),
        "containment_time_utc": epoch_ms_to_iso(props.get("attr_ContainmentDateTime")),
        "control_time_utc": epoch_ms_to_iso(props.get("attr_ControlDateTime")),
        "fire_out_time_utc": epoch_ms_to_iso(props.get("attr_FireOutDateTime")),
        "fire_cause": props.get("attr_FireCause"),
        "fire_cause_general": props.get("attr_FireCauseGeneral"),
        "map_method": props.get("poly_MapMethod"),
        "source_dataset": props.get("poly_Source"),
        "irwin_id": props.get("poly_IRWINID") or props.get("attr_IrwinID"),
        "unique_fire_identifier": props.get("attr_UniqueFireIdentifier"),
        "global_id": props.get("GlobalID"),
    }
    return {
        "type": "Feature",
        "geometry": feature.get("geometry"),
        "properties": normalized,
    }


def coordinate_count(geometry: dict[str, Any] | None) -> int:
    if not geometry:
        return 0

    def visit(node: Any) -> int:
        if not isinstance(node, list):
            return 0
        if len(node) >= 2 and all(isinstance(value, (int, float)) for value in node[:2]):
            return 1
        return sum(visit(child) for child in node)

    return visit(geometry.get("coordinates"))


def geometry_stats(features: Sequence[dict[str, Any]]) -> dict[str, Any]:
    vertex_counts = [coordinate_count(feature.get("geometry")) for feature in features]
    geom_types = Counter(
        (feature.get("geometry") or {}).get("type") or "null" for feature in features
    )
    nonzero = [value for value in vertex_counts if value > 0]
    return {
        "feature_count": len(features),
        "geometry_types": dict(sorted(geom_types.items())),
        "null_or_empty_geometry_count": sum(1 for value in vertex_counts if value == 0),
        "total_coordinate_pairs": int(sum(vertex_counts)),
        "max_coordinate_pairs_per_feature": int(max(vertex_counts, default=0)),
        "median_coordinate_pairs_per_feature": (
            float(statistics.median(nonzero)) if nonzero else None
        ),
        "mean_coordinate_pairs_per_feature": (
            float(statistics.fmean(nonzero)) if nonzero else None
        ),
    }


def safe_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def record_identity(record: dict[str, Any]) -> str | None:
    # Normalize equivalent IRWIN identifiers across polygon/attribute field names so
    # Current-vs-YTD overlap is not underestimated simply because one service populated
    # poly_IRWINID while another populated attr_IrwinID.
    value = record.get("attr_UniqueFireIdentifier")
    if value is not None and str(value).strip():
        return "ufid:" + str(value).strip().upper()

    for key in ("poly_IRWINID", "attr_IrwinID"):
        value = record.get(key)
        if value is not None and str(value).strip():
            normalized = str(value).strip().strip("{}").lower()
            return "irwin:" + normalized

    value = record.get("GlobalID")
    if value is not None and str(value).strip():
        return "global:" + str(value).strip().strip("{}").lower()
    return None


def duplicate_identity_summary(records: Sequence[dict[str, Any]]) -> dict[str, Any]:
    counter = Counter(filter(None, (record_identity(record) for record in records)))
    duplicates = {key: value for key, value in counter.items() if value > 1}
    return {
        "records_with_identity": int(sum(counter.values())),
        "unique_identities": len(counter),
        "duplicate_identity_count": len(duplicates),
        "records_in_duplicate_groups": int(sum(duplicates.values())),
        "largest_duplicate_group": int(max(duplicates.values(), default=1)),
        "example_duplicate_groups": dict(list(sorted(duplicates.items(), key=lambda kv: -kv[1]))[:10]),
    }


def acreage_distribution(records: Sequence[dict[str, Any]]) -> dict[str, Any]:
    values = [safe_float(record.get("poly_GISAcres")) for record in records]
    values = [value for value in values if value is not None and value >= 0]
    if not values:
        return {"non_null_count": 0}
    ordered = sorted(values)

    def percentile(p: float) -> float:
        if len(ordered) == 1:
            return ordered[0]
        index = (len(ordered) - 1) * p
        low = math.floor(index)
        high = math.ceil(index)
        if low == high:
            return ordered[low]
        return ordered[low] * (high - index) + ordered[high] * (index - low)

    bins: dict[str, int] = {}
    for label, low, high in ACREAGE_BINS:
        count = 0
        for value in values:
            if low is not None and value < low:
                continue
            if high is not None and value >= high:
                continue
            count += 1
        bins[label] = count
    return {
        "non_null_count": len(values),
        "minimum": min(values),
        "p25": percentile(0.25),
        "median": percentile(0.50),
        "p75": percentile(0.75),
        "p90": percentile(0.90),
        "p99": percentile(0.99),
        "maximum": max(values),
        "bins": bins,
    }


def date_epoch(record: dict[str, Any], key: str) -> float:
    value = record.get(key)
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return float(value)
    return float("-inf")


def choose_representative_ytd_ids(records: Sequence[dict[str, Any]]) -> list[int]:
    selected: list[int] = []
    seen: set[int] = set()

    def add(record: dict[str, Any]) -> None:
        value = record.get("OBJECTID")
        if value is None:
            return
        oid = int(value)
        if oid not in seen:
            seen.add(oid)
            selected.append(oid)

    newest = sorted(
        records,
        key=lambda record: max(
            date_epoch(record, "poly_PolygonDateTime"),
            date_epoch(record, "poly_DateCurrent"),
        ),
        reverse=True,
    )
    for record in newest[:YTD_NEWEST_SAMPLE]:
        add(record)

    largest = sorted(
        records,
        key=lambda record: safe_float(record.get("poly_GISAcres")) or -1.0,
        reverse=True,
    )
    for record in largest[:YTD_LARGEST_SAMPLE]:
        add(record)

    for _label, low, high in ACREAGE_BINS:
        candidates: list[dict[str, Any]] = []
        for record in records:
            acres = safe_float(record.get("poly_GISAcres"))
            if acres is None:
                continue
            if low is not None and acres < low:
                continue
            if high is not None and acres >= high:
                continue
            candidates.append(record)
        # Most recently mapped examples in each size band; deterministic and operationally relevant.
        candidates.sort(
            key=lambda record: max(
                date_epoch(record, "poly_PolygonDateTime"),
                date_epoch(record, "poly_DateCurrent"),
            ),
            reverse=True,
        )
        for record in candidates[:YTD_PER_ACREAGE_BIN]:
            add(record)

    return selected


def choose_current_sample_ids(records: Sequence[dict[str, Any]], limit: int = 500) -> list[int]:
    return choose_representative_ytd_ids(records)[:limit]


def normalized_attribute_record(record: dict[str, Any]) -> dict[str, Any]:
    output = {key: record.get(key) for key in SOURCE_FIELDS}
    for key in DATE_FIELDS:
        output[key + "_iso_utc"] = epoch_ms_to_iso(record.get(key))
    return output


def schema_summary(metadata: dict[str, Any]) -> dict[str, Any]:
    field_names = [field.get("name") for field in metadata.get("fields", []) if field.get("name")]
    field_set = set(field_names)
    missing_required = sorted(REQUIRED_HOVER_FIELDS - field_set)
    missing_requested = sorted(set(SOURCE_FIELDS) - field_set)
    editing_info = metadata.get("editingInfo") or {}
    advanced = metadata.get("advancedQueryCapabilities") or {}
    return {
        "name": metadata.get("name"),
        "geometry_type": metadata.get("geometryType"),
        "object_id_field": metadata.get("objectIdField"),
        "global_id_field": metadata.get("globalIdField"),
        "max_record_count": metadata.get("maxRecordCount"),
        "supported_query_formats": metadata.get("supportedQueryFormats"),
        "field_count": len(field_names),
        "available_fields": field_names,
        "missing_required_hover_fields": missing_required,
        "missing_requested_fields": missing_requested,
        "supports_pagination": advanced.get("supportsPagination"),
        "supports_order_by": advanced.get("supportsOrderBy"),
        "supports_statistics": advanced.get("supportsStatistics"),
        "last_edit_date_utc": epoch_ms_to_iso(editing_info.get("lastEditDate")),
        "raw_last_edit_date": editing_info.get("lastEditDate"),
    }


def write_json(path: Path, payload: Any, *, compact: bool = False) -> None:
    if compact:
        text = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    else:
        text = json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=False)
    path.write_text(text + "\n", encoding="utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def geojson_payload(features: Sequence[dict[str, Any]], **metadata: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "type": "FeatureCollection",
        "features": list(features),
    }
    # Non-standard top-level metadata is useful for this diagnostic artifact and harmless to
    # GeoJSON readers that ignore unknown members.
    payload["wpc_diagnostic"] = metadata
    return payload


def comparison_overlap(current_records: Sequence[dict[str, Any]], ytd_records: Sequence[dict[str, Any]]) -> dict[str, Any]:
    current_ids = {record_identity(record) for record in current_records}
    ytd_ids = {record_identity(record) for record in ytd_records}
    current_ids.discard(None)
    ytd_ids.discard(None)
    overlap = current_ids & ytd_ids
    return {
        "current_unique_identities": len(current_ids),
        "ytd_unique_identities": len(ytd_ids),
        "overlap_unique_identities": len(overlap),
        "current_identity_overlap_percent": (
            round(100.0 * len(overlap) / len(current_ids), 2) if current_ids else None
        ),
    }


def build_summary_text(report: dict[str, Any]) -> str:
    lines = [
        "WPC Hydro Dashboard — Phase WFIGS-1 Source Discovery",
        "=" * 58,
        "",
        f"Generated: {report['generated_utc']}",
        "Candidate operational data: Wildfire (WF) perimeters only.",
        "Prescribed fire (RX) is counted but intentionally not mixed into the candidate wildfire layer.",
        "",
    ]
    for key in ("current", "ytd"):
        source = report["sources"][key]
        lines.extend(
            [
                source["label"],
                "-" * len(source["label"]),
                f"Wildfire count (WF): {source['wildfire_count']}",
                f"Prescribed-fire count (RX): {source['prescribed_fire_count']}",
                f"IDs returned for WF: {source['wildfire_object_id_count']}",
                f"Schema required-field gaps: {source['schema']['missing_required_hover_fields'] or 'none'}",
                f"Source last edit: {source['schema']['last_edit_date_utc'] or 'not exposed'}",
                f"WF duplicate-identity groups: {source['identity_duplicates']['duplicate_identity_count']}",
                "",
            ]
        )
    current_geo = report["geometry"]["current"]
    ytd_geo = report["geometry"]["ytd_sample"]
    lines.extend(
        [
            "Geometry characterization",
            "-------------------------",
            f"Current geometry mode: {current_geo['mode']}",
            f"Current geometry features: {current_geo['stats']['feature_count']}",
            f"Current total coordinate pairs: {current_geo['stats']['total_coordinate_pairs']}",
            f"Current max coordinates in one feature: {current_geo['stats']['max_coordinate_pairs_per_feature']}",
            f"YTD representative geometry features: {ytd_geo['stats']['feature_count']}",
            f"YTD sample total coordinate pairs: {ytd_geo['stats']['total_coordinate_pairs']}",
            f"YTD sample max coordinates in one feature: {ytd_geo['stats']['max_coordinate_pairs_per_feature']}",
            "",
            "Current/YTD identity comparison",
            "-------------------------------",
            f"Current WF identities represented in YTD: {report['current_ytd_identity_overlap']['current_identity_overlap_percent']}%",
            "",
            "Interpretation for Phase WFIGS-2/3",
            "----------------------------------",
            "* Current WFIGS is the near-real-time operational perimeter source.",
            "* Year-To-Date is required to preserve fire footprints after they fall out of Current.",
            "* WFIGS perimeter geometry is extent, not soil-burn severity. BAER/MTBS remain separate future layers.",
            "* Hover/popup fields were explicitly checked in the authoritative schema.",
            "* No dashboard files were changed by this diagnostic.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        default="wfigs_phase1_output",
        help="Directory for diagnostic artifacts (default: wfigs_phase1_output)",
    )
    args = parser.parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    started = time.time()
    session = build_session()
    report: dict[str, Any] = {
        "phase": "WFIGS-1",
        "purpose": "NIFC/WFIGS source discovery for WPC real-time hydrometeorological dashboard",
        "generated_utc": utc_now_iso(),
        "wildfire_filter": WILDFIRE_WHERE,
        "prescribed_fire_filter_diagnostic_only": PRESCRIBED_FIRE_WHERE,
        "source_fields_requested": SOURCE_FIELDS,
        "required_hover_fields": sorted(REQUIRED_HOVER_FIELDS),
        "sources": {},
        "geometry": {},
        "warnings": [],
    }

    source_records: dict[str, list[dict[str, Any]]] = {}
    source_ids: dict[str, list[int]] = {}
    source_query_fields: dict[str, list[str]] = {}

    for source in SOURCES:
        print(f"Inspecting {source.label} ...")
        metadata = layer_metadata(session, source)
        schema = schema_summary(metadata)
        if schema["geometry_type"] != "esriGeometryPolygon":
            report["warnings"].append(
                f"{source.key}: expected esriGeometryPolygon, found {schema['geometry_type']!r}"
            )
        if schema["missing_required_hover_fields"]:
            raise RuntimeError(
                f"{source.label} is missing required fields: {schema['missing_required_hover_fields']}"
            )
        if schema["missing_requested_fields"]:
            # Keep going because some nice-to-have fields can disappear without invalidating the core layer.
            report["warnings"].append(
                f"{source.key}: requested fields absent from schema: {schema['missing_requested_fields']}"
            )

        available_fields = set(schema["available_fields"])
        if "OBJECTID" not in available_fields:
            raise RuntimeError(f"{source.label} does not expose OBJECTID.")
        query_fields = [field for field in SOURCE_FIELDS if field in available_fields]
        source_query_fields[source.key] = query_fields

        wildfire_count = count_features(session, source, WILDFIRE_WHERE)
        prescribed_count = count_features(session, source, PRESCRIBED_FIRE_WHERE)
        ids = object_ids(session, source, WILDFIRE_WHERE)
        if wildfire_count != len(ids):
            report["warnings"].append(
                f"{source.key}: WF count ({wildfire_count}) != returnIdsOnly count ({len(ids)})"
            )
        print(f"  WF={wildfire_count:,}; RX={prescribed_count:,}; fetching lean WF attributes ...")
        records = fetch_attributes(session, source, ids, query_fields)
        if len(records) != len(ids):
            report["warnings"].append(
                f"{source.key}: attribute records ({len(records)}) != object ID count ({len(ids)})"
            )

        source_ids[source.key] = ids
        source_records[source.key] = records
        report["sources"][source.key] = {
            "label": source.label,
            "layer_url": source.layer_url,
            "item_id": source.item_id,
            "schema": schema,
            "wildfire_count": wildfire_count,
            "prescribed_fire_count": prescribed_count,
            "wildfire_object_id_count": len(ids),
            "wildfire_attribute_record_count": len(records),
            "identity_duplicates": duplicate_identity_summary(records),
            "gis_acres_distribution": acreage_distribution(records),
            "null_field_counts": {
                field: sum(1 for record in records if record.get(field) in (None, ""))
                for field in REQUIRED_HOVER_FIELDS
            },
        }

    # Persist the entire lean YTD WF attribute inventory without geometry. This is the key
    # diagnostic for size/age/identity logic without the cost of pulling every polygon.
    ytd_attributes_path = output_dir / "wfigs_ytd_wildfire_attributes.json"
    write_json(
        ytd_attributes_path,
        {
            "generated_utc": report["generated_utc"],
            "source": "ytd",
            "where": WILDFIRE_WHERE,
            "record_count": len(source_records["ytd"]),
            "records": [normalized_attribute_record(record) for record in source_records["ytd"]],
        },
        compact=True,
    )

    # Current geometry: pull all current WF perimeters if safely sized; otherwise sample.
    current_records = source_records["current"]
    current_ids = source_ids["current"]
    if len(current_ids) <= CURRENT_FULL_GEOMETRY_LIMIT:
        current_geometry_ids = current_ids
        current_mode = "complete_current_wildfire_geometry"
    else:
        current_geometry_ids = choose_current_sample_ids(current_records)
        current_mode = "representative_sample_due_to_safety_limit"
        report["warnings"].append(
            f"current: {len(current_ids)} WF perimeters exceeded full-geometry safety limit "
            f"{CURRENT_FULL_GEOMETRY_LIMIT}; sampled {len(current_geometry_ids)}"
        )

    print(f"Fetching current wildfire geometry ({current_mode}) ...")
    current_raw_features = fetch_geojson_features(
        session, SOURCES[0], current_geometry_ids, source_query_fields["current"]
    )
    current_features = [normalize_feature(feature, "current") for feature in current_raw_features]
    current_geo_path = output_dir / "wfigs_current_wildfires.geojson"
    write_json(
        current_geo_path,
        geojson_payload(
            current_features,
            generated_utc=report["generated_utc"],
            mode=current_mode,
            source_layer_url=CURRENT_LAYER_URL,
            filter=WILDFIRE_WHERE,
            complete=(len(current_geometry_ids) == len(current_ids)),
        ),
        compact=True,
    )
    report["geometry"]["current"] = {
        "mode": current_mode,
        "requested_id_count": len(current_geometry_ids),
        "stats": geometry_stats(current_features),
    }

    # YTD geometry: use a deterministic representative sample. Pulling the entire YTD geometry
    # set is deliberately avoided in Phase 1 because the national service can be very large.
    ytd_records = source_records["ytd"]
    ytd_sample_ids = choose_representative_ytd_ids(ytd_records)
    print(f"Fetching representative YTD wildfire geometry sample ({len(ytd_sample_ids):,} IDs) ...")
    ytd_raw_features = fetch_geojson_features(
        session, SOURCES[1], ytd_sample_ids, source_query_fields["ytd"]
    )
    ytd_features = [normalize_feature(feature, "ytd") for feature in ytd_raw_features]
    ytd_geo_path = output_dir / "wfigs_ytd_geometry_sample.geojson"
    write_json(
        ytd_geo_path,
        geojson_payload(
            ytd_features,
            generated_utc=report["generated_utc"],
            mode="representative_ytd_sample",
            source_layer_url=YTD_LAYER_URL,
            filter=WILDFIRE_WHERE,
            selection={
                "newest": YTD_NEWEST_SAMPLE,
                "largest": YTD_LARGEST_SAMPLE,
                "per_acreage_bin": YTD_PER_ACREAGE_BIN,
                "acreage_bins": ACREAGE_BINS,
            },
        ),
        compact=True,
    )
    report["geometry"]["ytd_sample"] = {
        "mode": "representative_ytd_sample",
        "requested_id_count": len(ytd_sample_ids),
        "stats": geometry_stats(ytd_features),
    }

    report["current_ytd_identity_overlap"] = comparison_overlap(
        source_records["current"], source_records["ytd"]
    )

    report["files"] = {}
    for path in (ytd_attributes_path, current_geo_path, ytd_geo_path):
        report["files"][path.name] = {
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }

    report["elapsed_seconds"] = round(time.time() - started, 2)
    report_path = output_dir / "wfigs_phase1_report.json"
    write_json(report_path, report)
    summary_path = output_dir / "wfigs_phase1_summary.txt"
    summary_path.write_text(build_summary_text(report), encoding="utf-8")

    print("\n" + build_summary_text(report))
    print(f"Diagnostic artifacts written to: {output_dir.resolve()}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        raise SystemExit(130)
    except Exception as exc:
        print(f"WFIGS Phase-1 diagnostic FAILED: {exc}", file=sys.stderr)
        raise
