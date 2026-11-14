"""One-time execution of the fixed, user-reviewed 4 November FFG artifact plan.

No age-based selection, branch deletion, cache deletion or future artifact
maintenance is supported here. Default operation is a read-only preflight.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import time
import urllib.error
import urllib.request

REPOSITORY = 'andreworrison-cloud/wpc-hydro-dashboard'
REPOSITORY_ID = 1428539972
PLAN_PATH = Path(__file__).resolve().parents[1] / 'review/rrfs-flash-flood/legacy_ffg_cleanup_plan_20261104.json'
PLAN_SHA256 = 'b6d4eec2cc347f8c72ac75e574a8f0e16b4bb332e56e2f4a61f3320aefb82903'
EXPECTED_COUNT = 335
EXPECTED_BYTES = 108074053606
RETAINED_ID = 13354200688
CUTOFF = '2026-11-04T19:49:45Z'


def load_plan(raw):
    if hashlib.sha256(raw).hexdigest() != PLAN_SHA256:
        raise ValueError('The reviewed plan checksum changed')
    plan = json.loads(raw)
    if plan['repository'] != REPOSITORY:
        raise ValueError('Wrong plan repository')
    rows = plan['candidates']
    retained = plan['retained_legacy_artifacts']
    if len(rows) != EXPECTED_COUNT or plan['candidate_count'] != EXPECTED_COUNT:
        raise ValueError('Wrong fixed candidate count')
    if sum(row['bytes'] for row in rows) != EXPECTED_BYTES or plan['candidate_bytes'] != EXPECTED_BYTES:
        raise ValueError('Wrong fixed candidate bytes')
    ids = [row['id'] for row in rows]
    if len(set(ids)) != len(ids) or not all(type(i) is int and i > 0 for i in ids):
        raise ValueError('Invalid or repeated fixed artifact identifier')
    if [row['id'] for row in retained] != [RETAINED_ID] or RETAINED_ID in ids:
        raise ValueError('Retained full package is not protected')
    for row in rows + retained:
        if not re.fullmatch(r'rfc-ffg-ingest-' + str(row['run_id']) + r'-\d+', row['name']):
            raise ValueError('Artifact name is outside the reviewed FFG namespace')
        if row['bytes'] <= 100 * 1024**2 or row['created_utc'] >= CUTOFF:
            raise ValueError('Artifact is outside the legacy full-package scope')
    return plan


class GitHub:
    def __init__(self, token):
        self.token = token

    def request(self, path, method='GET'):
        if not re.fullmatch(r'/actions/artifacts(?:/\d+|\?per_page=100&page=\d+)?', path):
            raise ValueError('API path outside the fixed artifact operation')
        headers = {'Accept': 'application/vnd.github+json',
                   'Authorization': 'Bearer ' + self.token,
                   'User-Agent': 'WPC-Reviewed-FFG-Cleanup/1',
                   'X-GitHub-Api-Version': '2022-11-28'}
        for attempt in range(4):
            request = urllib.request.Request('https://api.github.com/repos/' + REPOSITORY + path,
                                             headers=headers, method=method)
            try:
                with urllib.request.urlopen(request, timeout=30) as response:
                    return response.status, json.load(response) if method == 'GET' else None
            except urllib.error.HTTPError as exc:
                if exc.code == 404 and re.fullmatch(r'/actions/artifacts/\d+', path):
                    return 404, None
                # Honor a short server retry, without retrying an authorization
                # denial or waiting through a primary hourly rate-limit reset.
                retry = exc.headers.get('Retry-After')
                if exc.code in (403, 429, 502, 503) and attempt < 3:
                    delay = int(retry) if retry and retry.isdigit() else (5 * (attempt + 1) if exc.code >= 500 else 0)
                    if 0 < delay <= 60:
                        time.sleep(delay)
                        continue
                raise


def inventory(api):
    rows = {}
    for page in range(1, 61):
        status, payload = api.request('/actions/artifacts?per_page=100&page=' + str(page))
        if status != 200 or not isinstance(payload, dict):
            raise ValueError('Artifact inventory failed')
        entries = payload['artifacts']
        rows.update({row['id']: row for row in entries})
        if len(entries) < 100:
            return rows
    raise ValueError('Inventory exceeds the bounded 6,000-artifact limit')


def validate_artifact(expected, actual):
    run = actual.get('workflow_run', {})
    observed = {'id': actual['id'], 'name': actual['name'], 'bytes': actual['size_in_bytes'],
                'created_utc': actual['created_at'], 'expires_utc': actual['expires_at'],
                'run_id': run.get('id')}
    if observed != expected:
        raise ValueError('Artifact identity changed: ' + str(expected['id']))
    if run.get('head_branch') != 'main' or run.get('repository_id') != REPOSITORY_ID or run.get('head_repository_id') != REPOSITORY_ID:
        raise ValueError('Artifact run is not from this repository main branch')


def execute(api, plan, *, delete=False, output=None, pause=time.sleep):
    result = {'repository': REPOSITORY, 'plan_sha256': PLAN_SHA256,
              'started_utc': datetime.now(timezone.utc).isoformat(),
              'execution_requested': delete, 'status': 'PREFLIGHT',
              'planned_count': EXPECTED_COUNT, 'planned_bytes': EXPECTED_BYTES,
              'deleted': [], 'already_absent': [], 'retained_ids': [RETAINED_ID]}
    def checkpoint():
        if output:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, indent=2) + '\n')
    try:
        before = inventory(api)
        result['before'] = {'count': len(before), 'nonexpired_bytes': sum(r['size_in_bytes'] for r in before.values() if not r.get('expired'))}
        # A direct read protects the newest full package even if the changing
        # repository inventory had an overlapping pagination boundary.
        status, retained = api.request('/actions/artifacts/' + str(RETAINED_ID))
        if status != 200:
            raise ValueError('Retained full package is unavailable; no deletion allowed')
        validate_artifact(plan['retained_legacy_artifacts'][0], retained)
        available = []
        for row in plan['candidates']:
            actual = before.get(row['id'])
            if actual is None:
                status, actual = api.request('/actions/artifacts/' + str(row['id']))
                if status == 404:
                    result['already_absent'].append(row['id'])
                    continue
            validate_artifact(row, actual)
            available.append(row)
        # All fixed IDs and the retained package pass before the first DELETE.
        result['preflight_validated_count'] = len(available)
        result['status'] = 'PREFLIGHT_PASSED'
        checkpoint()
        if not delete:
            return result
        for index, row in enumerate(available):
            status, _ = api.request('/actions/artifacts/' + str(row['id']), 'DELETE')
            if status == 204:
                result['deleted'].append(row)
            elif status == 404:
                result['already_absent'].append(row['id'])
            else:
                raise ValueError('Unexpected artifact deletion response')
            result['deleted_bytes'] = sum(r['bytes'] for r in result['deleted'])
            checkpoint()
            if (index + 1) % 25 == 0:
                print('Reviewed cleanup progress: ' + str(index + 1) + '/' + str(len(available)), flush=True)
            # Stay below 80 mutation requests per minute.
            pause(0.85)
        after = inventory(api)
        remaining = set(after).intersection(row['id'] for row in plan['candidates'])
        if remaining:
            raise ValueError('Reviewed artifacts remain after cleanup: ' + str(sorted(remaining)))
        status, retained = api.request('/actions/artifacts/' + str(RETAINED_ID))
        if status != 200:
            raise ValueError('Retained full package failed the final readback')
        validate_artifact(plan['retained_legacy_artifacts'][0], retained)
        result['after'] = {'count': len(after), 'nonexpired_bytes': sum(r['size_in_bytes'] for r in after.values() if not r.get('expired'))}
        result['deleted_count'] = len(result['deleted'])
        result['retained_full_package_verified'] = True
        result['status'] = 'COMPLETE_VERIFIED'
        return result
    except Exception as exc:
        result['status'] = 'STOPPED'
        result['error'] = str(exc)
        raise
    finally:
        result['finished_utc'] = datetime.now(timezone.utc).isoformat()
        checkpoint()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute-reviewed-plan', action='store_true')
    parser.add_argument('--output', type=Path, default=Path('reviewed-ffg-cleanup-result.json'))
    args = parser.parse_args()
    if os.environ.get('GITHUB_REPOSITORY') != REPOSITORY or os.environ.get('GITHUB_REF') != 'refs/heads/main':
        raise SystemExit('Execution is restricted to the reviewed repository main branch')
    plan = load_plan(PLAN_PATH.read_bytes())
    report = execute(GitHub(os.environ['GITHUB_TOKEN']), plan, delete=args.execute_reviewed_plan, output=args.output)
    summary = {k: v for k, v in report.items() if k not in ('deleted', 'already_absent')}
    print('CLEANUP_SUMMARY_JSON=' + json.dumps(summary, separators=(',', ':')), flush=True)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        Path(os.environ['GITHUB_STEP_SUMMARY']).write_text('## Reviewed FFG artifact cleanup\n\n```json\n' + json.dumps(summary, indent=2) + '\n```\n')
