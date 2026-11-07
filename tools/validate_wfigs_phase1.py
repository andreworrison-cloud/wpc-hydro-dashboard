#!/usr/bin/env python3
"""Static/self-test validator for the Phase WFIGS-1 diagnostic package."""

from __future__ import annotations

import py_compile
import runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "diagnose_wfigs.py"
WORKFLOW = ROOT / ".github" / "workflows" / "diagnose_wfigs.yml"
README = ROOT / "README_WFIGS_PHASE1.txt"

errors: list[str] = []

for path in (SCRIPT, WORKFLOW, README):
    if not path.exists():
        errors.append(f"Missing required package file: {path.relative_to(ROOT)}")

if not errors:
    py_compile.compile(str(SCRIPT), doraise=True)
    namespace = runpy.run_path(str(SCRIPT), run_name="wfigs_phase1_validation")

    class Namespace:
        pass
    module = Namespace()
    for key, value in namespace.items():
        setattr(module, key, value)

    if "WFIGS_Interagency_Perimeters_Current" not in module.CURRENT_LAYER_URL:
        errors.append("Current WFIGS service URL contract changed unexpectedly.")
    if "WFIGS_Interagency_Perimeters_YearToDate" not in module.YTD_LAYER_URL:
        errors.append("YTD WFIGS service URL contract changed unexpectedly.")
    if module.WILDFIRE_WHERE != "attr_IncidentTypeCategory = 'WF'":
        errors.append("Wildfire-only candidate filter changed unexpectedly.")
    if module.PRESCRIBED_FIRE_WHERE != "attr_IncidentTypeCategory = 'RX'":
        errors.append("RX diagnostic count filter changed unexpectedly.")

    required = {
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
    if module.REQUIRED_HOVER_FIELDS != required:
        errors.append("Required hover-field contract changed unexpectedly.")

    # Date normalization self-tests.
    if module.epoch_ms_to_iso(0) != "1970-01-01T00:00:00Z":
        errors.append("Epoch-ms date normalization failed.")
    if module.epoch_ms_to_iso(None) is not None:
        errors.append("Null date normalization failed.")

    # Geometry coordinate counting self-test.
    polygon = {
        "type": "Polygon",
        "coordinates": [[[-1, 1], [0, 1], [0, 0], [-1, 1]]],
    }
    if module.coordinate_count(polygon) != 4:
        errors.append("Polygon coordinate-count helper failed.")

    # Normalized feature must expose the future hover/popup contract without preserving the
    # entire IRWIN schema.
    feature = {
        "type": "Feature",
        "geometry": polygon,
        "properties": {
            "OBJECTID": 1,
            "poly_IncidentName": "TEST FIRE",
            "poly_GISAcres": 123.4,
            "attr_IncidentTypeCategory": "WF",
            "attr_POOState": "US-CO",
        },
    }
    normalized = module.normalize_feature(feature, "current")
    props = normalized["properties"]
    for key in (
        "incident_name",
        "gis_acres",
        "state",
        "perimeter_time_utc",
        "unique_fire_identifier",
    ):
        if key not in props:
            errors.append(f"Normalized GeoJSON is missing expected property: {key}")

    # Representative selection must remain deterministic and unique.
    records = [
        {
            "OBJECTID": i,
            "poly_GISAcres": float(i * 20),
            "poly_PolygonDateTime": i * 1000,
        }
        for i in range(1, 30)
    ]
    ids = module.choose_representative_ytd_ids(records)
    if len(ids) != len(set(ids)):
        errors.append("Representative YTD geometry ID selection is not unique.")

    workflow_text = WORKFLOW.read_text(encoding="utf-8")
    for fragment in (
        "workflow_dispatch:",
        "actions/checkout@v6",
        "actions/setup-python@v6",
        "actions/upload-artifact@v6",
        "python tools/validate_wfigs_phase1.py",
        "python diagnose_wfigs.py --output-dir wfigs_phase1_output",
    ):
        if fragment not in workflow_text:
            errors.append(f"Workflow is missing required fragment: {fragment}")
    if "schedule:" in workflow_text:
        errors.append("Phase WFIGS-1 must remain manual diagnostic only; schedule was found.")

if errors:
    print("WFIGS Phase-1 package validation FAILED")
    for error in errors:
        print(f" - {error}")
    raise SystemExit(1)

print("WFIGS Phase-1 package validation PASSED")
