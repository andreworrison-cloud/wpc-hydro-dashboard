#!/usr/bin/env python3
"""Final-validation check: compare one identical MRMS RALA valid time from NCEP and NODD.

The script independently discovers both official inventories, finds the newest
valid time present in BOTH sources, downloads those exact files, decompresses the
gzip payloads, and requires the GRIB2 byte streams to be identical.  This avoids
a false failure when one provider is a frame or two ahead during dissemination.
Diagnostic only; dashboard outputs are never modified.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path

import fetch_mrms_rala as rala


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fetch_bytes(session, url: str) -> bytes:
    response = session.get(url, timeout=(15, 90))
    response.raise_for_status()
    payload = response.content
    if len(payload) < 10_000:
        raise RuntimeError(f"Downloaded source is implausibly small: {len(payload):,} bytes")
    return payload


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--output", default="diagnostics/mrms_rala/mrms_rala_official_source_parity.json")
    p.add_argument("--max-common-age-minutes", type=float, default=20.0)
    args = p.parse_args()

    session = rala.make_session()
    now = rala.utc_now()
    ncep = rala.discover_ncep(session)
    nodd = rala.discover_nodd(session, now)
    if not ncep or not nodd:
        raise SystemExit("FINAL CHECK FAIL: both NCEP and NODD inventories are required")

    ncep_by_time = {item.timestamp: item for item in ncep}
    nodd_by_time = {item.timestamp: item for item in nodd}
    common_times = sorted(set(ncep_by_time).intersection(nodd_by_time))
    if not common_times:
        raise SystemExit("FINAL CHECK FAIL: no common RALA timestamp found between NCEP and NODD inventories")

    stamp = common_times[-1]
    ncep_item = ncep_by_time[stamp]
    nodd_item = nodd_by_time[stamp]
    age_minutes = (now - stamp).total_seconds() / 60.0

    result = {
        "check": "newest_common_timestamp_official_source_payload_parity",
        "checked_utc": rala.iso_z(now),
        "ncep_latest_utc": ncep[-1].iso(),
        "nodd_latest_utc": nodd[-1].iso(),
        "newest_common_timestamp_utc": rala.iso_z(stamp),
        "newest_common_age_minutes": round(age_minutes, 2),
        "max_common_age_minutes": args.max_common_age_minutes,
        "ncep_url": ncep_item.url,
        "nodd_url": nodd_item.url,
        "ncep_candidate_count": len(ncep),
        "nodd_candidate_count": len(nodd),
        "common_timestamp_count": len(common_times),
    }

    if age_minutes > args.max_common_age_minutes:
        result.update({"status": "FAIL", "reason": "Newest common frame is stale."})
        Path(args.output).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result, indent=2))
        raise SystemExit("FINAL CHECK FAIL: newest common NCEP/NODD frame is stale")

    ncep_gz = fetch_bytes(session, ncep_item.url)
    nodd_gz = fetch_bytes(session, nodd_item.url)
    try:
        ncep_grib = gzip.decompress(ncep_gz)
        nodd_grib = gzip.decompress(nodd_gz)
    except OSError as exc:
        raise SystemExit(f"FINAL CHECK FAIL: could not decompress an official MRMS payload: {exc}")

    result.update({
        "ncep_gzip_bytes": len(ncep_gz),
        "nodd_gzip_bytes": len(nodd_gz),
        "ncep_grib2_bytes": len(ncep_grib),
        "nodd_grib2_bytes": len(nodd_grib),
        "ncep_gzip_sha256": sha256(ncep_gz),
        "nodd_gzip_sha256": sha256(nodd_gz),
        "ncep_grib2_sha256": sha256(ncep_grib),
        "nodd_grib2_sha256": sha256(nodd_grib),
        "decompressed_grib2_identical": ncep_grib == nodd_grib,
    })
    result["status"] = "PASS" if result["decompressed_grib2_identical"] else "FAIL"
    Path(args.output).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    if not result["decompressed_grib2_identical"]:
        print(json.dumps(result, indent=2))
        raise SystemExit("FINAL CHECK FAIL: NCEP and NODD served different GRIB2 bytes for the same valid time")

    print("MRMS official-source payload parity PASS")
    print(f"Newest common frame: {rala.iso_z(stamp)} ({age_minutes:.2f} minutes old)")
    print(f"Decompressed GRIB2 SHA256: {result['ncep_grib2_sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
