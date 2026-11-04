#!/usr/bin/env python3
"""Bound generated Actions bundles; preserve live data, current reviews and backups.

The default is an inventory/plan. --apply is restricted to this repository's
trusted main workflow. No branch, commit, release or deployment is deleted.
"""
from __future__ import annotations

import argparse
import base64
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import time
import urllib.error
import urllib.request

REPOSITORY = 'andreworrison-cloud/wpc-hydro-dashboard'
UTC = timezone.utc
POLICIES = (
    ('sport-h7-review', r'sport-h7-review-(\d+)', 'review_sport_changes.yml'),
    ('sport-dashboard-review', r'sport-dashboard-review-(\d+)', 'review_sport_depths.yml'),
    ('sport-four-depths', r'sport-four-depths-(\d+)', 'review_sport_depths.yml'),
    ('sport-provenance', r'sport-provenance-(\d+)-\d+', 'fetch_sport.yml'),
    ('sport-h7-numeric', r'sport-h7-numeric-(\d+)-\d+', 'fetch_sport.yml'),
    ('rfc-ffg-ingest', r'rfc-ffg-ingest-(\d+)-\d+', 'publish_rfc_ffg.yml'),
)
KEEP_PER_FAMILY = 2
MINIMUM_AGE = timedelta(hours=1)


def stamp(value):
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('Missing timezone in Actions inventory')
    return result.astimezone(UTC)


def family(row):
    if row.get('name') == 'github-pages' and isinstance(row.get('workflow_run', {}).get('id'), int):
        return 'github-pages', 'dynamic/pages/pages-build-deployment'
    for name, expression, workflow in POLICIES:
        match = re.fullmatch(expression, row.get('name', ''))
        if match and int(match[1]) == row.get('workflow_run', {}).get('id'):
            return name, workflow
    return None


def plan(rows, open_branches, now):
    """Select only obsolete large generated bundles, with two recent copies kept."""
    groups = defaultdict(list)
    protected = Counter()
    for row in rows:
        found = family(row)
        if not found or row.get('expired'):
            continue
        groups[found[0]].append(row)
    retained, obsolete = [], []
    for group, entries in sorted(groups.items()):
        entries.sort(key=lambda r: (stamp(r['created_at']), r['id']), reverse=True)
        newest = {r['id'] for r in entries[:KEEP_PER_FAMILY]}
        for row in entries:
            branch = row.get('workflow_run', {}).get('head_branch')
            reason = None
            if row['id'] in newest:
                reason = 'newest-two'
            elif now - stamp(row['created_at']) < MINIMUM_AGE:
                reason = 'recent-or-in-flight'
            elif branch in open_branches:
                reason = 'open-pull-request'
            elif group in ('sport-provenance', 'rfc-ffg-ingest') and row['size_in_bytes'] <= 1024**2:
                reason = 'lightweight-provenance'
            elif group in ('sport-h7-numeric', 'sport-provenance', 'rfc-ffg-ingest') and branch != 'main':
                reason = 'unrecognized-production-branch'
            if reason:
                retained.append(row); protected[reason] += 1
            else:
                obsolete.append(row)
    return retained, obsolete, dict(protected)


class API:
    def __init__(self, token):
        self.base = 'https://api.github.com/repos/' + REPOSITORY
        self.headers = {'Accept': 'application/vnd.github+json',
                        'User-Agent': 'WPC-Bounded-Actions-Storage/1',
                        'X-GitHub-Api-Version': '2022-11-28'}
        if token:
            self.headers['Authorization'] = 'Bearer ' + token
        self.last_delete_at = 0.0

    def request(self, path, method='GET'):
        if not path.startswith('/') or '..' in path:
            raise ValueError('Unexpected API path')
        for attempt in range(3):
            if method == 'DELETE':
                # Stay below GitHub's secondary mutation-rate limit during a
                # large one-time cleanup; each pause is at most one second.
                pause = 1.0 - (time.monotonic() - self.last_delete_at)
                if pause > 0:
                    time.sleep(pause)
                self.last_delete_at = time.monotonic()
            req = urllib.request.Request(self.base + path, headers=self.headers, method=method)
            try:
                with urllib.request.urlopen(req, timeout=30) as response:
                    return json.load(response) if method == 'GET' else True
            except urllib.error.HTTPError as exc:
                if method == 'DELETE' and exc.code == 404:
                    return False
                if (exc.code in (429, 502, 503, 504)
                        or (exc.code == 403 and exc.headers.get('Retry-After'))) and attempt < 2:
                    time.sleep(min(10, max(2, int(exc.headers.get('Retry-After', 2)))))
                    continue
                raise RuntimeError(f'GitHub {method} returned HTTP {exc.code}; maintenance stopped') from None

    def content(self, path, ref):
        result = self.request('/contents/' + path + '?ref=' + ref)
        if result.get('encoding') != 'base64':
            raise ValueError('Unexpected content encoding')
        return json.loads(base64.b64decode(result['content']))


def inventory(api):
    first = api.request('/actions/artifacts?per_page=100&page=1')
    count = first['total_count']
    if count > 6000:
        raise ValueError('Artifact inventory exceeds bounded 6000-row maintenance')
    rows = {r['id']: r for r in first['artifacts']}
    with ThreadPoolExecutor(max_workers=4) as pool:
        for result in pool.map(lambda page: api.request('/actions/artifacts?per_page=100&page=' + str(page)),
                               range(2, (count + 99) // 100 + 1)):
            rows.update({r['id']: r for r in result['artifacts']})
    if len(rows) < count:
        raise ValueError('Inventory changed during pagination; retry before deleting')
    return list(rows.values())


def open_branches(api):
    branches = set()
    for page in range(1, 6):
        pulls = api.request(f'/pulls?state=open&per_page=100&page={page}')
        branches.update(p['head']['ref'] for p in pulls)
        if len(pulls) < 100:
            return branches
    raise ValueError('Open-PR inventory exceeds bounded maintenance')


def numeric_guard(api):
    """Confirm a bounded authoritative numeric snapshot before trimming backups."""
    ref = api.request('/git/ref/heads/data/sport-lis')['object']['sha']
    commit = api.request('/git/commits/' + ref)
    tree = api.request('/git/trees/' + commit['tree']['sha'] + '?recursive=1')
    if commit['parents'] or tree.get('truncated'):
        raise ValueError('SPoRT snapshot is not a complete history-free publication')
    total = sum(r.get('size', 0) for r in tree['tree'] if r['type'] == 'blob')
    if total > 512 * 1024**2:
        raise ValueError('SPoRT snapshot exceeds the existing 512-MiB budget')
    marker = api.content('SPORT_LIS_DATA_BRANCH.json', ref)
    if marker != {'schema_version': 1, 'purpose': 'SPoRT-LIS production map data'}:
        raise ValueError('Unrecognized authoritative SPoRT snapshot')
    metadata = api.content('public/change/metadata.json', ref)
    if not metadata.get('active') or metadata.get('usable') is not True:
        raise ValueError('No usable authoritative H7 publication; keep all numeric backups')
    index = api.content('public/change/numeric-cache/index.json', ref)
    if not isinstance(index, dict) or not index:
        raise ValueError('Empty authoritative H7 numeric history')
    paths = {r['path'] for r in tree['tree'] if r['type'] == 'blob'}
    for digest, row in index.items():
        if not re.fullmatch('[a-f0-9]{64}', digest) or row['sha256'] != digest:
            raise ValueError('Invalid authoritative numeric identity')
        stamp(row['valid_time']); stamp(row['last_verified_at'])
        if 'public/change/numeric-cache/' + digest + '.tif' not in paths:
            raise ValueError('Authoritative numeric history is incomplete')
    return {'branch': 'data/sport-lis', 'head': ref, 'snapshot_bytes': total,
            'numeric_versions': len(index), 'history_free': True,
            'qualification': 'The production publisher validates TIFF hashes; maintenance checks the complete committed index and preserves the newest two secondary backups.'}


def maintain(api, apply=False, report_path=None, now=None):
    now = now or datetime.now(UTC)
    rows = inventory(api)
    protected_branches = open_branches(api)
    retained, candidates, protection = plan(rows, protected_branches, now)
    report = {'observed_at_utc': now.isoformat(), 'repository': REPOSITORY,
              'apply': apply, 'artifact_rows': len(rows),
              'protected_open_branches': sorted(protected_branches),
              'protection_counts': protection,
              'retained_known_bundles': len(retained),
              'candidate_count': len(candidates),
              'candidate_bytes': sum(r['size_in_bytes'] for r in candidates),
              'deleted_count': 0, 'deleted_bytes': 0, 'skipped': [], 'deleted': []}
    if any(family(r)[0] == 'sport-h7-numeric' for r in candidates):
        report['numeric_history_guard'] = numeric_guard(api)
    run_cache = {}
    try:
        if apply:
            # Re-read open PRs at the boundary; protect every artifact on a newly opened branch.
            protected_branches |= open_branches(api)
            for row in candidates:
                found = family(row)
                if not found or not isinstance(row['id'], int) or row['id'] <= 0:
                    raise ValueError('Invalid artifact deletion identity')
                run_id = row['workflow_run']['id']
                if run_id not in run_cache:
                    run_cache[run_id] = api.request('/actions/runs/' + str(run_id))
                run = run_cache[run_id]
                path = run.get('path', '').split('@', 1)[0]
                expected_path = (found[1] if found[0] == 'github-pages'
                                 else '.github/workflows/' + found[1])
                if (run.get('status') != 'completed'
                        or path != expected_path
                        or (found[0] == 'github-pages' and (run.get('event') != 'dynamic'
                            or run.get('head_branch') != 'pages-live'))
                        or run.get('head_branch') in protected_branches
                        or run.get('repository', {}).get('full_name') != REPOSITORY):
                    report['skipped'].append({'id': row['id'], 'reason': 'active run, current PR, or unrecognized producer'})
                    continue
                if api.request('/actions/artifacts/' + str(row['id']), method='DELETE'):
                    report['deleted_count'] += 1
                    report['deleted_bytes'] += row['size_in_bytes']
                    report['deleted'].append({'id': row['id'], 'name': row['name'], 'bytes': row['size_in_bytes']})
        return report
    finally:
        if report_path:
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps({k: v for k, v in report.items() if k != 'deleted'}, indent=2), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    token = os.environ.get('GITHUB_TOKEN')
    if args.apply and (not token or os.environ.get('GITHUB_REPOSITORY') != REPOSITORY
                       or os.environ.get('GITHUB_REF') != 'refs/heads/main'
                       or os.environ.get('GITHUB_EVENT_NAME') not in ('push', 'workflow_dispatch', 'workflow_run')):
        raise SystemExit('Artifact cleanup requires this repository\'s trusted main workflow')
    maintain(API(token), apply=args.apply, report_path=args.report)
