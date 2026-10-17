import hashlib,json,subprocess,tempfile,unittest
from pathlib import Path
from datetime import datetime,timezone
from PIL import Image
from tools import publish_sport as p,sport_suite,sport_rsm_suite

class PublishTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.remote=self.root/'remote.git';self.repo=self.root/'repo'
        for args in [('init','--bare',str(self.remote)),('init',str(self.repo))]:subprocess.run(['git',*args],check=True,capture_output=True)
        p.git(self.repo,'remote','add','origin',str(self.remote));self.data=self.root/'data';self.state=self.root/'state.json';p.restore(self.repo,self.data,self.state)
        png=self.root/'image.png';Image.new('RGBA',(4000,2538),(80,170,255,150)).save(png);raw=png.read_bytes();sha=hashlib.sha256(raw).hexdigest()
        for key,fixture,module in [('percentile','sport_suite_ingest_evidence.json',sport_suite),('rsm','sport_rsm_ingest_evidence.json',sport_rsm_suite)]:
            m=json.loads((Path('review')/fixture).read_text());m['policy']=module.POLICY;root=self.data/'public'/key;root.mkdir(parents=True)
            for item in m['active']['products'].values():
                image=root/item['image']['path'];image.parent.mkdir(parents=True,exist_ok=True);image.write_bytes(raw);item['image']['sha256']=sha
                # The public export must not copy original scientific files.
                (root/item['source']['path']).write_bytes(b'original fixture bytes')
            (root/'metadata.json').write_text(json.dumps(m))
    def restored(self):
        root=self.root/'restored';state=self.root/'restored.json';p.restore(self.repo,root,state);return root,state
    def test_atomic_roundtrip_and_source_exclusion(self):
        head=p.publish(self.repo,self.data,self.state);root,state=self.restored();p.verify(root)
        self.assertFalse(list(root.rglob('*.tif')));self.assertEqual(len(list(root.rglob('*.png'))),6)
        self.assertEqual(p.publish(self.repo,root,state),head)
        self.assertEqual(p.git(self.repo,'ls-remote','--heads','origin').split()[1],'refs/heads/data/sport-lis')
    def test_concurrent_writer_rejected(self):
        p.publish(self.repo,self.data,self.state)
        with self.assertRaisesRegex(ValueError,'Concurrent'):p.publish(self.repo,self.data,self.state)
    def test_corrupt_image_never_published(self):
        head=p.publish(self.repo,self.data,self.state);root,state=self.restored();next(root.rglob('*.png')).write_bytes(b'broken')
        with self.assertRaises(ValueError):p.publish(self.repo,root,state)
        self.assertEqual(p.remote_head(self.repo),head)
    def test_public_restore_survives_upstream_failure(self):
        p.publish(self.repo,self.data,self.state);root,state=self.restored()
        for key,module in [('percentile',sport_suite),('rsm',sport_rsm_suite)]:
            suite=root/'public'/key;before=json.loads((suite/'metadata.json').read_text())['active']
            result=module.ingest(suite,source_dir=self.root/'missing',date='20261017',now=datetime(2026,10,17,20,tzinfo=timezone.utc))
            self.assertEqual(result,1);after=json.loads((suite/'metadata.json').read_text());self.assertEqual(after['active'],before);self.assertEqual(after['state'],'retained')
        p.publish(self.repo,root,state)
    def test_nonempty_restore_refused(self):
        with self.assertRaises(ValueError):p.restore(self.repo,self.data,self.state)
    def test_export_prunes_unreferenced_generations(self):
        for key in ('percentile','rsm'):
            root=self.data/'public'/key/'generations'
            for name in ['20261014-old','20261015-old','20261016-old']:
                d=root/name;d.mkdir();Image.new('RGBA',(1,1)).save(d/'old.png')
        export=self.root/'export';export.mkdir();p.export_public(self.data,export)
        for key in ('percentile','rsm'):self.assertEqual(len(list((export/'public'/key/'generations').iterdir())),2)
if __name__=='__main__':unittest.main()
