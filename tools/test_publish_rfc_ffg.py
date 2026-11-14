import json
from pathlib import Path
import subprocess
import tempfile
import sys
import unittest
from publish_rfc_ffg import restore,publish,git,BRANCH

class DurablePublishTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.remote=self.root/'remote.git';self.repo=self.root/'code'
        subprocess.run(['git','init','--bare',str(self.remote)],check=True,capture_output=True)
        subprocess.run(['git','init',str(self.repo)],check=True,capture_output=True)
        git(self.repo,'remote','add','origin',str(self.remote))
        self.data=self.root/'data';self.state=self.root/'state.json'
        restore(self.repo,self.data,self.state)
    def write(self,state='unavailable'):
        (self.data/'public').mkdir(exist_ok=True)
        (self.data/'public/metadata.json').write_text(json.dumps({'schema_version':1,'state':state,'active':None}))
    def test_atomic_restore_and_no_cache(self):
        self.write();head=publish(self.repo,self.data,self.state)
        fresh=self.root/'fresh';state=self.root/'fresh-state.json'
        self.assertEqual(restore(self.repo,fresh,state),head)
        self.assertEqual((fresh/'public/metadata.json').read_bytes(),(self.data/'public/metadata.json').read_bytes())
        self.assertEqual(git(self.repo,'ls-remote','--heads','origin').split()[1],f'refs/heads/{BRANCH}')
        self.assertEqual(publish(self.repo,fresh,state),head)
    def test_conflicting_writer_rejected(self):
        self.write();publish(self.repo,self.data,self.state)
        with self.assertRaisesRegex(ValueError,'Concurrent'):publish(self.repo,self.data,self.state)
    def test_invalid_product_keeps_remote(self):
        self.write();head=publish(self.repo,self.data,self.state)
        fresh=self.root/'fresh';state=self.root/'fresh-state.json';restore(self.repo,fresh,state)
        (fresh/'public/metadata.json').write_text('{}')
        with self.assertRaises(ValueError):publish(self.repo,fresh,state)
        self.assertEqual(git(self.repo,'ls-remote','--heads','origin').split()[0],head)
    def test_production_cli_isolates_branch(self):
        prod=self.root/'production';state=self.root/'production-state.json'
        script=Path(__file__).with_name('publish_rfc_ffg.py')
        def cli(action):
            subprocess.run([sys.executable,str(script),action,'--production','--repo',str(self.repo),'--data-dir',str(prod),'--state-file',str(state)],check=True,capture_output=True)
        cli('restore')
        self.assertEqual(json.loads(state.read_text())['branch'],'data/rfc-ffg')
        (prod/'public').mkdir(exist_ok=True)
        (prod/'public/metadata.json').write_text(json.dumps({'schema_version':1,'state':'unavailable','active':None}))
        cli('publish')
        self.assertEqual(git(self.repo,'ls-remote','--heads','origin').split()[1],'refs/heads/data/rfc-ffg')
        self.assertEqual(json.loads((prod/'RFC_FFG_DATA_BRANCH.json').read_text())['purpose'],'RFC FFG production data')

    def test_nonempty_restore_rejected(self):
        self.write()
        with self.assertRaises(ValueError):restore(self.repo,self.data,self.state)

if __name__=='__main__':unittest.main()
