import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
from tools import sport_rsm_suite as s

class SuiteTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/'output';self.source=Path(self.temp.name)/'source';self.source.mkdir()
        self.now=datetime(2026,10,17,18,tzinfo=timezone.utc)
        for d in s.DEPTHS:(self.source/s.filename('20261017',d)).write_bytes(('original-'+d).encode())
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
        self.assertEqual(self.renderer.call_count,2)
        for call in self.renderer.call_args_list:
            self.assertEqual(call.kwargs,{'max_dimension':4000,'upscale':True,'upper_tolerance':0.0001})
    def test_partial_failure_keeps_whole_generation(self):
        self.run_ingest();before=self.metadata()['active'];next(self.source.glob('*0-2m*')).unlink()
        self.assertEqual(self.run_ingest(),1);m=self.metadata();self.assertEqual(m['active'],before);self.assertEqual(m['state'],'retained')
    def test_interrupted_render_keeps_pointer(self):
        self.run_ingest();before=self.metadata()['active'];next(self.source.glob('*0-10cm*')).write_bytes(b'revision')
        with patch.object(s,'read_and_reproject_geotiff',side_effect=RuntimeError('render failed')):self.assertEqual(self.run_ingest(),1)
        self.assertEqual(self.metadata()['active'],before)
    def test_corrupt_previous_is_not_retained(self):
        self.run_ingest();m=self.metadata();(self.root/m['active']['products']['10']['image']['path']).write_bytes(b'corrupt')
        next(self.source.glob('*0-2m*')).unlink();self.run_ingest();self.assertIsNone(self.metadata()['active'])
    def test_exact_expiry_and_warning(self):
        active={'valid_time':'2026-10-17T00:00:00Z'};base=s.parse(active['valid_time'])
        self.assertEqual(s.freshness(active,base+timedelta(hours=48))['status'],'aging')
        self.assertFalse(s.freshness(active,base+timedelta(hours=72))['usable'])
    def test_future_rejected(self):
        self.assertEqual(self.run_ingest(now=self.now-timedelta(days=1)),1);self.assertIsNone(self.metadata()['active'])
    def test_expired_failure_preserves_files_but_hides(self):
        self.run_ingest();before=self.metadata()['active'];self.run_ingest(now=self.now+timedelta(days=4));m=self.metadata()
        self.assertEqual(m['state'],'expired');self.assertFalse(m['usable']);self.assertEqual(m['active'],before);self.assertTrue(s.verify(self.root,before))
    def test_palette_boundaries(self):
        values=np.array([[0,39.9,40,50,60,70,80,90,95,100,np.nan]])
        rgba=s.create_rgba_image(values)[0]
        np.testing.assert_array_equal(rgba[0],s.COLORS[0])
        np.testing.assert_array_equal(rgba[2:10],s.COLORS[[1,2,3,4,5,6,7,7]])
        self.assertEqual(rgba[-1,3],0)
    def test_inventory_is_depth_specific(self):
        a=s.filename('20261017','10');b=s.filename('20261017','200')
        self.assertEqual(s.inventory(a+b,'10'),{'20261017':{'filename':a}})

class RSMNumericalTests(unittest.TestCase):
    def test_roundoff_and_missing_values_in_reprojection(self):
        import rasterio
        from rasterio.transform import from_bounds
        from rasterio.enums import Resampling
        from fetch_sport import read_and_reproject_geotiff
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'roundoff.tif'
            with rasterio.open(path,'w',driver='GTiff',height=2,width=2,count=1,dtype='float64',crs='EPSG:4326',transform=from_bounds(-100,35,-99,36,2,2)) as ds:
                ds.write(np.array([[100.00000762939453,90],[9999,100.01]]),1)
            out,_=read_and_reproject_geotiff(path,max_dimension=20,upscale=True,resampling=Resampling.nearest,upper_tolerance=0.0001)
            self.assertEqual(float(np.nanmax(out)),100.0)
            self.assertTrue(np.isnan(out).any())
            self.assertEqual(set(np.unique(out[np.isfinite(out)])),{90.,100.})

if __name__=='__main__':unittest.main()
