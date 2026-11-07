#!/usr/bin/env python3
"""Validate WFIGS Phase-5 CONUS seasonal wildfire activity trend products."""

from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any

SEASONAL_ACTIVITY_VERSION = "wfigs_seasonal_activity_v1_0"


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def expected_day_count(year: int) -> int:
    start = datetime(year, 1, 1, tzinfo=timezone.utc)
    end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    return (end - start).days


def validate_nonnegative_ints(values: Any, label: str, errors: list[str]) -> list[int]:
    if not isinstance(values, list):
        errors.append(f"{label}: expected list")
        return []
    output: list[int] = []
    for i, value in enumerate(values):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
            errors.append(f"{label}[{i}]: non-numeric value")
            continue
        if float(value) < 0 or float(value) != int(value):
            errors.append(f"{label}[{i}]: expected non-negative integer")
            continue
        output.append(int(value))
    return output


def validate_current(path: Path, errors: list[str]) -> None:
    if not path.exists():
        errors.append(f"Current-year seasonal activity file missing: {path}")
        return
    payload = read_json(path)
    if payload.get("phase") != "WFIGS-5":
        errors.append("Current-year activity phase mismatch")
    if payload.get("processor_version") != SEASONAL_ACTIVITY_VERSION:
        errors.append("Current-year activity processor version mismatch")
    if payload.get("collection") != "current-year-activity":
        errors.append("Current-year activity collection mismatch")
    if payload.get("metric") != "unique_wildfire_discoveries":
        errors.append("Current-year activity metric mismatch")
    if payload.get("domain") != "CONUS":
        errors.append("Current-year activity domain mismatch")
    year = int(payload.get("year") or 0)
    if year < 2021:
        errors.append("Current-year activity year is invalid")
    daily = validate_nonnegative_ints(payload.get("daily_counts"), "current daily_counts", errors)
    if daily and len(daily) != expected_day_count(year):
        errors.append(f"Current-year daily count length {len(daily)} != {expected_day_count(year)}")
    complete_day = int(payload.get("complete_through_day") or 0)
    if not (0 <= complete_day <= len(daily)):
        errors.append("Current-year complete_through_day out of range")
    expected_total = sum(daily[:complete_day]) if daily else 0
    if int(payload.get("complete_through_count") or 0) != expected_total:
        errors.append("Current-year complete_through_count does not match daily series")
    weekly = payload.get("weekly_completed") or []
    prior_end = 0
    prior_cumulative = 0
    for row in weekly:
        start = int(row.get("start_day") or 0)
        end = int(row.get("end_day") or 0)
        count = int(row.get("count") or 0)
        cumulative = int(row.get("cumulative") or 0)
        if start != prior_end + 1 or end < start or end - start + 1 > 7:
            errors.append("Current-year weekly period boundaries are invalid")
            break
        if end > complete_day:
            errors.append("Current-year weekly series includes an incomplete period")
            break
        if count != sum(daily[start - 1:end]):
            errors.append("Current-year weekly count does not match daily series")
            break
        if cumulative != prior_cumulative + count:
            errors.append("Current-year weekly cumulative count is inconsistent")
            break
        prior_end = end
        prior_cumulative = cumulative
    qa = payload.get("qa") or {}
    counted = int(qa.get("counted_conus_discoveries") or 0)
    if counted != sum(daily):
        errors.append("Current-year QA counted_conus_discoveries does not match annual daily total")


def validate_history(path: Path, errors: list[str]) -> None:
    if not path.exists():
        errors.append(f"Historical seasonal baseline file missing: {path}")
        return
    payload = read_json(path)
    if payload.get("phase") != "WFIGS-5":
        errors.append("Historical activity phase mismatch")
    if payload.get("processor_version") != SEASONAL_ACTIVITY_VERSION:
        errors.append("Historical activity processor version mismatch")
    if payload.get("collection") != "historical-baseline":
        errors.append("Historical activity collection mismatch")
    if payload.get("metric") != "unique_wildfire_discoveries":
        errors.append("Historical activity metric mismatch")
    if payload.get("domain") != "CONUS":
        errors.append("Historical activity domain mismatch")
    years = [int(y) for y in (payload.get("historical_years") or [])]
    if len(years) != 5 or len(set(years)) != 5:
        errors.append("Historical activity must contain exactly five unique years")
    weekly = payload.get("weekly_baseline") or []
    if len(weekly) != 53:
        errors.append(f"Historical weekly baseline should contain 53 Jan-1-anchored periods, found {len(weekly)}")
    for i, row in enumerate(weekly, start=1):
        if int(row.get("period") or 0) != i:
            errors.append(f"Historical weekly period {i} has wrong period number")
            break
        values = [float(row.get(k)) for k in ("min", "median", "max")]
        if not (values[0] <= values[1] <= values[2]):
            errors.append(f"Historical weekly period {i} min/median/max order invalid")
            break
        cum = [float(row.get(k)) for k in ("cumulative_min", "cumulative_median", "cumulative_max")]
        if not (cum[0] <= cum[1] <= cum[2]):
            errors.append(f"Historical weekly period {i} cumulative min/median/max order invalid")
            break
    daily = payload.get("daily_cumulative_baseline") or []
    if len(daily) not in {365, 366}:
        errors.append(f"Historical daily cumulative baseline has unexpected length {len(daily)}")
    prior = {"min": -1.0, "median": -1.0, "max": -1.0}
    for i, row in enumerate(daily, start=1):
        if int(row.get("day") or 0) != i:
            errors.append(f"Historical cumulative day {i} has wrong day index")
            break
        values = {k: float(row.get(k)) for k in ("min", "median", "max")}
        if not (values["min"] <= values["median"] <= values["max"]):
            errors.append(f"Historical cumulative day {i} min/median/max order invalid")
            break
        if any(values[k] < prior[k] for k in prior):
            errors.append(f"Historical cumulative baseline decreases at day {i}")
            break
        prior = values
    totals = payload.get("historical_year_totals") or {}
    if years and set(totals) != {str(y) for y in years}:
        errors.append("Historical year-total inventory does not match historical_years")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--current", type=Path, default=None)
    parser.add_argument("--history", type=Path, default=None)
    args = parser.parse_args()
    if args.current is None and args.history is None:
        parser.error("provide --current and/or --history")
    errors: list[str] = []
    try:
        if args.current is not None:
            validate_current(args.current, errors)
        if args.history is not None:
            validate_history(args.history, errors)
    except Exception as exc:
        errors.append(f"validation exception: {exc}")
    if errors:
        print("WFIGS Phase-5 seasonal activity validation: FAIL")
        for error in errors[:100]:
            print(f" - {error}")
        return 1
    print("WFIGS Phase-5 seasonal activity validation: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
