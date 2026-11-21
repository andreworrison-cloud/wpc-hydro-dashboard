#!/usr/bin/env python3
"""Check observable operational storage budgets; this cannot inspect billing."""
import argparse
import json
from pathlib import Path


def check(report):
    errors=[]
    if not report['pages_tree_complete'] or report['pages_parent_count']!=0:
        errors.append('Pages must be a complete history-free snapshot')
    if report['pages_payload_bytes']>512*1024**2:
        errors.append('Pages exceeds its 512-MiB safety budget')
    if not report['cache_inventory_complete'] or report['cache_bytes']>8_000_000_000:
        errors.append('Derived caches exceed the 8-GB operating budget or inventory is incomplete')
    if not report['runtime_branch_inventory_complete']:
        errors.append('Runtime-branch inventory is incomplete')
    for row in report['runtime_snapshots']:
        if row['parent_count']!=0 or not row['tree_complete']:
            errors.append(row['branch']+': expected a complete history-free snapshot')
        if row['payload_bytes']>512*1024**2:
            errors.append(row['branch']+': snapshot exceeds 512-MiB safety budget')
        radar=row.get('radar_archive')
        if radar and radar['frame_count']>39:
            errors.append('Radar archive exceeds its bounded six-hour frame count')
    if report['artifact_live_bytes_observed']>2_000_000_000:
        errors.append('Actions artifacts exceed the 2-GB operating budget after protected cleanup')
    return errors


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('report',type=Path)
    args=parser.parse_args()
    errors=check(json.loads(args.report.read_text()))
    for message in errors:print('::error::'+message)
    if errors:raise SystemExit(1)
    print('Operational storage budgets PASS. Account billing and bandwidth are not exposed by this inventory.')
