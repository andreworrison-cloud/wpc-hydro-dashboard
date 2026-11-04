"""Protect current products and cache namespaces during storage maintenance."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from prune_gdi_dynamics_cache import prune
from prune_actions_caches import plan


class CacheTests(unittest.TestCase):
    def fixture(self,root):
        cache=root/'cam-dynamics/native';runs=[]
        for model in ('hrrr','rrfs'):
            samples=[]
            for lead in range(7):
                path=cache/model/'2026110418'/f'F{lead:03d}.npz';path.parent.mkdir(parents=True,exist_ok=True)
                path.write_bytes(b'complete-derived-checkpoint')
                row={'cycle':'2026-11-04T18:00:00+00:00','lead':lead,'grid_md5':'grid'}
                path.with_suffix('.json').write_text(json.dumps(dict(row,model=model,recipe='cam_gdi_dynamics_v1',sha256=hashlib.sha256(path.read_bytes()).hexdigest())))
                samples.append(row)
            runs.append({'model':model,'samples':samples})
        base=root/'base.json';base.write_text(json.dumps({'source_metadata':runs}))
        old=cache/'hrrr/2026110412/F000.npz';old.parent.mkdir();old.write_bytes(b'old-rebuildable-cache')
        return cache,base,old

    def test_only_current_frames_are_kept(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache,base,old=self.fixture(Path(tmp));r=prune(base,cache)
            self.assertFalse(old.exists());self.assertTrue(r['save_cache']);self.assertEqual(r['retained_frames'],14)
            self.assertEqual(len(list(cache.rglob('*.npz'))),14)

    def test_bad_selection_does_not_remove_old_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache,base,old=self.fixture(Path(tmp));(cache/'hrrr/2026110418/F002.npz').write_bytes(b'corrupt')
            with self.assertRaises(ValueError):prune(base,cache)
            self.assertTrue(old.exists())

    def test_oversized_checkpoint_is_not_uploaded(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache,base,old=self.fixture(Path(tmp));self.assertFalse(prune(base,cache,budget=1)['save_cache'])

    def test_unrelated_cache_and_pr_namespace_are_never_deleted(self):
        rows=[{'id':i,'key':key,'ref':ref,'created_at':f'2026-11-04T{hour:02d}:00:00Z'} for i,key,ref,hour in (
            (1,'cam-gdi-dynamics-v1-111','refs/heads/main',18),
            (2,'cam-gdi-dynamics-v1-222','refs/heads/main',19),
            (3,'cam-gdi-dynamics-v1-333','refs/pull/35/merge',17),
            (4,'rap-gdi-dynamics-111','refs/heads/main',17),
            (5,'setup-python-pip','refs/heads/main',17))]
        keep,delete=plan(rows);self.assertEqual([r['id'] for r in keep],[2]);self.assertEqual([r['id'] for r in delete],[1])

    def test_single_or_empty_cache_never_removes_newest(self):
        self.assertEqual(plan([]),([],[]))
        one={'id':1,'key':'cam-gdi-dynamics-v1-1','ref':'refs/heads/main','created_at':'2026-11-04T18:00:00Z'}
        self.assertEqual(plan([one]),([one],[]))


if __name__=='__main__':unittest.main(verbosity=2)
