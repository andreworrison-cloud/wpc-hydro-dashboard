"""Destructive cleanup must fail before mutation if any protected scope changes."""
import copy
import json
import unittest
from execute_reviewed_ffg_cleanup import (EXPECTED_BYTES, EXPECTED_COUNT, PLAN_PATH,
                                        RETAINED_ID, REPOSITORY_ID, execute, load_plan)


class FakeAPI:
    def __init__(self, plan):
        self.rows = {}
        self.calls = []
        for row in plan['candidates'] + plan['retained_legacy_artifacts']:
            self.rows[row['id']] = {'id': row['id'], 'name': row['name'], 'size_in_bytes': row['bytes'],
                                    'created_at': row['created_utc'], 'expires_at': row['expires_utc'],
                                    'expired': False, 'workflow_run': {'id': row['run_id'], 'head_branch': 'main',
                                    'repository_id': REPOSITORY_ID, 'head_repository_id': REPOSITORY_ID}}
        self.rows[1] = {'id': 1, 'name': 'unrelated-review', 'size_in_bytes': 500}

    def request(self, path, method='GET'):
        self.calls.append((method, path))
        if '?' in path:
            page = int(path.split('page=')[-1])
            rows = list(self.rows.values())[(page - 1)*100:page*100]
            return 200, {'total_count': len(self.rows), 'artifacts': copy.deepcopy(rows)}
        artifact_id = int(path.rsplit('/', 1)[-1])
        if artifact_id not in self.rows:
            return 404, None
        if method == 'DELETE':
            del self.rows[artifact_id]
            return 204, None
        return 200, copy.deepcopy(self.rows[artifact_id])


class CleanupTests(unittest.TestCase):
    def setUp(self):
        self.raw = PLAN_PATH.read_bytes()
        self.plan = load_plan(self.raw)
        self.api = FakeAPI(self.plan)

    def run_cleanup(self, **kwargs):
        return execute(self.api, self.plan, pause=lambda _: None, **kwargs)

    def test_read_only_by_default(self):
        r = self.run_cleanup()
        self.assertEqual(r['preflight_validated_count'], EXPECTED_COUNT)
        self.assertFalse(any(method == 'DELETE' for method, _ in self.api.calls))

    def test_only_fixed_ids_deleted_and_retained_package_survives(self):
        r = self.run_cleanup(delete=True)
        self.assertEqual(r['status'], 'COMPLETE_VERIFIED')
        self.assertEqual(r['deleted_count'], EXPECTED_COUNT)
        self.assertEqual(r['deleted_bytes'], EXPECTED_BYTES)
        self.assertEqual(set(self.api.rows), {1, RETAINED_ID})

    def test_any_identity_change_stops_all_deletion(self):
        # Put the bad candidate at the end: no earlier candidate may be deleted.
        row = self.api.rows[self.plan['candidates'][-1]['id']]
        for key, value in [('name', 'other-science'), ('size_in_bytes', 1), ('created_at', '2026-11-05T00:00:00Z')]:
            with self.subTest(key=key):
                original = row[key]
                row[key] = value
                with self.assertRaises(ValueError):
                    self.run_cleanup(delete=True)
                self.assertFalse(any(method == 'DELETE' for method, _ in self.api.calls))
                row[key] = original

    def test_pr_branch_or_other_repository_stops_all_deletion(self):
        row = self.api.rows[self.plan['candidates'][-1]['id']]['workflow_run']
        for key, value in [('head_branch', 'review'), ('repository_id', 7), ('head_repository_id', 7)]:
            with self.subTest(key=key):
                original = row[key]
                row[key] = value
                with self.assertRaises(ValueError):
                    self.run_cleanup(delete=True)
                self.assertFalse(any(method == 'DELETE' for method, _ in self.api.calls))
                row[key] = original

    def test_missing_retained_package_stops_all_deletion(self):
        del self.api.rows[RETAINED_ID]
        with self.assertRaises(ValueError):
            self.run_cleanup(delete=True)
        self.assertFalse(any(method == 'DELETE' for method, _ in self.api.calls))

    def test_already_expired_candidate_does_not_expand_scope(self):
        del self.api.rows[self.plan['candidates'][0]['id']]
        r = self.run_cleanup(delete=True)
        self.assertEqual(r['deleted_count'], EXPECTED_COUNT - 1)
        self.assertEqual(r['already_absent'], [self.plan['candidates'][0]['id']])
        self.assertEqual(set(self.api.rows), {1, RETAINED_ID})

    def test_edited_plan_cannot_expand_deletion(self):
        changed = json.loads(self.raw)
        changed['candidates'][0]['id'] = RETAINED_ID
        with self.assertRaisesRegex(ValueError, 'checksum'):
            load_plan(json.dumps(changed).encode())

    def test_second_execution_cannot_delete_new_artifacts(self):
        self.run_cleanup(delete=True)
        self.api.rows[2] = {'id': 2, 'name': 'rfc-ffg-ingest-999999-1', 'size_in_bytes': 999999999}
        r = self.run_cleanup(delete=True)
        self.assertEqual(r['deleted_count'], 0)
        self.assertEqual(len(r['already_absent']), EXPECTED_COUNT)
        self.assertEqual(set(self.api.rows), {1, 2, RETAINED_ID})


if __name__ == '__main__':
    unittest.main(verbosity=2)
