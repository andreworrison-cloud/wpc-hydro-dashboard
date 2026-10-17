import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
from tools import sport_suite as s

class SuiteTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/'output';self.source=Path(self.temp.name)/'source';self.source.mkdir()
        self.now=datetime(2026,10,17,18,tzinfo=timezone.utc)
        for d in s.DEPTHS:(self.source/f'20261017_0000_sport_lis_vsm0-{d}cm_percentile_conus3km_float_wgs84.tif').write_bytes(('original-'+d).encode())
        self.stats={'shape':[2,2],'transform':[1,0,0,0,-1,2],'crs':'EPSG:4326','valid_cells':4}
        self.addCleanup(patch.stopall)
        patch.object(s,'validate_source',return_value=(self.stats,np.ones((2,2),bool))).start()
        self.renderer=patch.object(s,'read_and_reproject_geotiff',return_value=(np.array([[70.,85.],[96.,99.]]),[[25,-125],[53,-67]])).start()
    def run_ingest(self,**kwargs):return s.ingest(self.root,source_dir=self.source,date='20261017',now=kwargs.pop('now',self.now),**kwargs)
    def metadata(self):return json.loads((self.root/'metadata.json').read_text())
    def test_complete_suite_and_sources(self):
        self.assertEqual(self.run_ingest(),0);m=self.metadata();self.assertEqual(set(m['active']['products']),set(s.DEPTHS));self.assertTrue(s.verify(self.root,m['active']))
        self.assertEqual(self.run_ingest(),0);self.assertEqual(self.metadata()['state'],'unchanged')
    def test_approved_render_configuration(self):
        self.assertEqual(self.run_ingest(),0)
        self.assertEqual(self.renderer.call_count,4)
        for call in self.renderer.call_args_list:
            self.assertEqual(call.kwargs,{'max_dimension':4000,'upscale':True})
    def test_revision_upgrade_and_failure_retention(self):
        with patch.object(s,'REVISION','sport-suite-wet-tail-v1'):
            self.assertEqual(self.run_ingest(),0)
        before=self.metadata()['active']
        with patch.object(s,'read_and_reproject_geotiff',side_effect=RuntimeError('render failed')):
            self.assertEqual(self.run_ingest(),1)
        self.assertEqual(self.metadata()['active'],before)
        self.assertEqual(self.run_ingest(),0)
        self.assertNotEqual(self.metadata()['active']['generation'],before['generation'])
    def test_partial_failure_keeps_whole_generation(self):
        self.run_ingest();before=self.metadata()['active'];next(self.source.glob('*0-200cm*')).unlink()
        self.assertEqual(self.run_ingest(),1);m=self.metadata();self.assertEqual(m['active'],before);self.assertEqual(m['state'],'retained')
    def test_interrupted_render_keeps_pointer(self):
        self.run_ingest();before=self.metadata()['active'];next(self.source.glob('*0-10cm*')).write_bytes(b'revision')
        with patch.object(s,'read_and_reproject_geotiff',side_effect=RuntimeError('render failed')):self.assertEqual(self.run_ingest(),1)
        self.assertEqual(self.metadata()['active'],before)
    def test_corrupt_previous_is_not_retained(self):
        self.run_ingest();m=self.metadata();(self.root/m['active']['products']['10']['image']['path']).write_bytes(b'corrupt')
        next(self.source.glob('*0-200cm*')).unlink();self.run_ingest();self.assertIsNone(self.metadata()['active'])
    def test_exact_expiry_and_warning(self):
        active={'valid_time':'2026-10-17T00:00:00Z'};base=s.parse(active['valid_time'])
        self.assertEqual(s.freshness(active,base+timedelta(hours=48))['status'],'aging')
        self.assertFalse(s.freshness(active,base+timedelta(hours=72))['usable'])
    def test_future_rejected(self):
        self.assertEqual(self.run_ingest(now=self.now-timedelta(days=1)),1);self.assertIsNone(self.metadata()['active'])
    def test_expired_failure_preserves_files_but_hides(self):
        self.run_ingest();before=self.metadata()['active'];self.run_ingest(now=self.now+timedelta(days=4));m=self.metadata()
        self.assertEqual(m['state'],'expired');self.assertFalse(m['usable']);self.assertEqual(m['active'],before);self.assertTrue(s.verify(self.root,before))
if __name__=='__main__':unittest.main()
