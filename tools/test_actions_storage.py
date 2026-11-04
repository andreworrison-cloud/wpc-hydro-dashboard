"""Exercise retention boundaries and failure paths before any remote deletion."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import io
from contextlib import redirect_stdout
from unittest import TestCase, main
from unittest.mock import patch

import maintain_actions_storage as storage
from check_storage_budget import check

NOW = datetime(2026, 11, 4, 23, tzinfo=timezone.utc)


def artifact(number, *, family='sport-h7-review', hours=4, branch='closed-review', size=10 * 1024**2):
    run = 1000 + number
    name = f'{family}-{run}' + ('-1' if family in ('sport-h7-numeric', 'sport-provenance', 'rfc-ffg-ingest') else '')
    return {'id': number, 'name': name, 'workflow_run': {'id': run, 'head_branch': branch},
            'created_at': (NOW - timedelta(hours=hours)).isoformat(),
            'expired': False, 'size_in_bytes': size}


class FakeAPI:
    def __init__(self, rows, status='completed', workflow='review_sport_changes.yml'):
        self.rows = rows; self.status = status; self.workflow = workflow; self.deleted = []

    def request(self, path, method='GET'):
        if method == 'DELETE':
            self.deleted.append(path); return True
        if path.startswith('/actions/artifacts?'):
            return {'total_count': len(self.rows), 'artifacts': self.rows}
        if path.startswith('/pulls?'):
            return []
        if path.startswith('/actions/runs/'):
            return {'status': self.status, 'path': '.github/workflows/' + self.workflow,
                    'head_branch': 'closed-review', 'repository': {'full_name': storage.REPOSITORY}}
        raise AssertionError(path)


class ArtifactRetentionTests(TestCase):
    def test_newest_two_are_preserved_in_each_exact_family(self):
        rows = [artifact(i, hours=10-i) for i in range(1, 6)]
        keep, obsolete, _ = storage.plan(rows, set(), NOW)
        self.assertEqual({r['id'] for r in keep}, {4, 5})
        self.assertEqual({r['id'] for r in obsolete}, {1, 2, 3})

    def test_one_hour_boundary_and_future_artifacts_are_protected(self):
        rows = [artifact(1, hours=1), artifact(2, hours=0.99), artifact(3, hours=-1), artifact(4, hours=-2)]
        keep, obsolete, _ = storage.plan(rows, set(), NOW)
        self.assertEqual([r['id'] for r in obsolete], [1])
        self.assertIn(2, {r['id'] for r in keep})

    def test_every_open_review_branch_is_protected_even_when_old(self):
        rows = [artifact(1, hours=90, branch='open-review'), artifact(2, hours=5), artifact(3, hours=4)]
        keep, obsolete, _ = storage.plan(rows, {'open-review'}, NOW)
        self.assertFalse(obsolete); self.assertEqual(len(keep), 3)

    def test_unknown_research_and_deployment_artifacts_are_untouched(self):
        rows = [artifact(i, family=name) for i, name in enumerate(
            ('github-pages-not-a-deployment', 'case-study-science', 'reviewed-ffg-cleanup-receipt', 'sport-h7-numeric-not-a-run'), 1)]
        self.assertEqual(storage.plan(rows, set(), NOW), ([], [], {}))

    def test_name_run_mismatch_is_never_admitted(self):
        row = artifact(1); row['workflow_run']['id'] = 999999
        self.assertIsNone(storage.family(row))

    def test_small_provenance_keeps_its_normal_expiration(self):
        for family in ('sport-provenance', 'rfc-ffg-ingest'):
            rows = [artifact(i, family=family, branch='main', size=1024**2) for i in range(1, 8)]
            self.assertFalse(storage.plan(rows, set(), NOW)[1])

    def test_production_backups_on_other_branches_are_untouched(self):
        rows = [artifact(i, family='sport-h7-numeric', branch='unrecognized') for i in range(1, 5)]
        self.assertFalse(storage.plan(rows, set(), NOW)[1])

    def test_missing_timezone_stops_planning(self):
        row = artifact(1); row['created_at'] = '2026-11-04T10:00:00'
        with self.assertRaises(ValueError): storage.plan([row], set(), NOW)

    def test_only_completed_expected_producer_is_deleted(self):
        api = FakeAPI([artifact(1, hours=8), artifact(2, hours=6), artifact(3, hours=4)])
        with redirect_stdout(io.StringIO()): result = storage.maintain(api, apply=True, now=NOW)
        self.assertEqual(api.deleted, ['/actions/artifacts/1'])
        self.assertEqual(result['deleted_bytes'], 10 * 1024**2)

    def test_active_runs_and_unrelated_producers_are_never_deleted(self):
        for status, workflow in [('in_progress', 'review_sport_changes.yml'), ('completed', 'unrelated.yml')]:
            api = FakeAPI([artifact(1, hours=8), artifact(2, hours=6), artifact(3, hours=4)], status, workflow)
            with redirect_stdout(io.StringIO()): storage.maintain(api, apply=True, now=NOW)
            self.assertFalse(api.deleted)

    def test_newly_opened_review_is_rechecked_before_mutation(self):
        api = FakeAPI([artifact(1, hours=8), artifact(2, hours=6), artifact(3, hours=4)])
        with patch.object(storage, 'open_branches', side_effect=[set(), {'closed-review'}]), redirect_stdout(io.StringIO()):
            storage.maintain(api, apply=True, now=NOW)
        self.assertFalse(api.deleted)

    def test_missing_authoritative_numeric_history_aborts_all_deletions(self):
        api = FakeAPI([artifact(i, family='sport-h7-numeric', branch='main', hours=10-i) for i in range(1, 5)])
        with patch.object(storage, 'numeric_guard', side_effect=ValueError('history unavailable')):
            with self.assertRaises(ValueError): storage.maintain(api, apply=True, now=NOW)
        self.assertFalse(api.deleted)

    def test_dry_run_does_not_mutate(self):
        api = FakeAPI([artifact(1, hours=8), artifact(2, hours=6), artifact(3, hours=4)])
        with redirect_stdout(io.StringIO()): result = storage.maintain(api, now=NOW)
        self.assertEqual(result['candidate_count'], 1); self.assertFalse(api.deleted)

    def test_only_old_completed_pages_staging_bundles_are_admitted(self):
        rows=[artifact(i,hours=10-i,branch='pages-live') for i in range(1,5)]
        for row in rows:row['name']='github-pages'
        class PagesAPI(FakeAPI):
            def request(self,path,method='GET'):
                result=super().request(path,method)
                if path.startswith('/actions/runs/'):
                    result.update(path='dynamic/pages/pages-build-deployment',event='dynamic',head_branch='pages-live')
                return result
        for status in ('completed','in_progress'):
            api=PagesAPI(rows,status)
            with redirect_stdout(io.StringIO()):storage.maintain(api,apply=True,now=NOW)
            self.assertEqual(len(api.deleted),2 if status=='completed' else 0)

    def test_pages_named_artifact_from_other_producer_is_preserved(self):
        rows=[artifact(i,hours=10-i) for i in range(1,4)]
        for row in rows:row['name']='github-pages'
        api=FakeAPI(rows)
        with redirect_stdout(io.StringIO()):storage.maintain(api,apply=True,now=NOW)
        self.assertFalse(api.deleted)


class NumericGuardTests(TestCase):
    def api(self):
        digest = 'a' * 64
        class NumericAPI:
            def request(self, path, method='GET'):
                if '/git/ref/' in path: return {'object': {'sha': 'commit'}}
                if '/git/commits/' in path: return {'tree': {'sha': 'tree'}, 'parents': []}
                if '/git/trees/' in path:
                    return {'truncated': False, 'tree': [{'type': 'blob', 'size': 100,
                        'path': 'public/change/numeric-cache/' + digest + '.tif'}]}
                raise AssertionError(path)
            def content(self, path, ref):
                if path == 'SPORT_LIS_DATA_BRANCH.json':
                    return {'schema_version': 1, 'purpose': 'SPoRT-LIS production map data'}
                if path.endswith('metadata.json'): return {'active': {'generation': 'current'}, 'usable': True}
                if path.endswith('index.json'):
                    return {digest: {'sha256': digest, 'valid_time': NOW.isoformat(), 'last_verified_at': NOW.isoformat()}}
                raise AssertionError(path)
        return NumericAPI()

    def test_complete_bounded_authoritative_history_passes(self):
        self.assertEqual(storage.numeric_guard(self.api())['numeric_versions'], 1)

    def test_missing_tiff_or_non_root_publication_blocks_backup_cleanup(self):
        for broken in ('tree', 'parents'):
            api = self.api(); original = api.request
            def request(path, method='GET'):
                result = deepcopy(original(path, method))
                if broken == 'tree' and '/git/trees/' in path: result['tree'] = []
                if broken == 'parents' and '/git/commits/' in path: result['parents'] = [{'sha': 'old'}]
                return result
            api.request = request
            with self.assertRaises(ValueError): storage.numeric_guard(api)


class StorageBudgetTests(TestCase):
    def report(self):
        return {'pages_tree_complete':True,'pages_parent_count':0,'pages_payload_bytes':90*1024**2,
                'cache_inventory_complete':True,'cache_bytes':3_000_000_000,
                'runtime_branch_inventory_complete':True,'artifact_live_bytes_observed':1_000_000_000,
                'runtime_snapshots':[{'branch':'mrms-rala-data','parent_count':0,
                    'tree_complete':True,'payload_bytes':60*1024**2,'radar_archive':{'frame_count':37}}]}

    def test_healthy_bounded_publication_passes(self):
        self.assertEqual(check(self.report()),[])

    def test_hard_alerts_precede_free_cache_threshold_and_site_size_limit(self):
        for key,value in [('cache_bytes',8_000_000_001),('pages_payload_bytes',512*1024**2+1),
                          ('artifact_live_bytes_observed',2_000_000_001),('cache_inventory_complete',False)]:
            report=self.report();report[key]=value
            self.assertTrue(check(report),key)

    def test_history_accumulation_or_oversized_radar_is_rejected(self):
        for key,value in [('parent_count',1),('payload_bytes',512*1024**2+1),('tree_complete',False)]:
            report=self.report();report['runtime_snapshots'][0][key]=value
            self.assertTrue(check(report),key)


if __name__ == '__main__': main(verbosity=2)
