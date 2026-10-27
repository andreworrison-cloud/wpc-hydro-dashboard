"""Observation corrections, temporal QC, density and missing-data regressions."""
import sys
import unittest
from pathlib import Path
from datetime import datetime, timezone, timedelta
import numpy as np
from pyproj import Transformer
from rasterio.transform import Affine
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from surface_pressure import blend_pressure


class PressureTests(unittest.TestCase):
    def setUp(self):
        self.cycle = datetime(2026, 10, 27, 0, tzinfo=timezone.utc)
        x, y = Transformer.from_crs(4326, 3857, always_xy=True).transform(-96, 38)
        self.t = Affine(5000, 0, x-502500, 0, -5000, y+502500)
        self.a = np.full((201, 201), 1016, dtype='float32')

    def point(self, value=1020, **kw):
        return dict(id='KTEST', lat=38, lon=-96, mslp=value, time=self.cycle.isoformat(), **kw)

    def run_blend(self, points):
        return blend_pressure(self.a, self.t, 3857, points, self.cycle, self.cycle+timedelta(minutes=30))

    def test_increment_is_smooth_local_and_background_remains(self):
        a, d = self.run_blend([self.point()])
        self.assertEqual(d['accepted_stations'], 1)
        self.assertGreater(a[100,100],1018)
        self.assertLess(a[100,100],1020)
        self.assertEqual(a[0,0],1016)
        self.assertLess(np.abs(np.diff(a[100])).max(),.15)
        self.assertGreater(a[100,100],a[100,120])

    def test_no_valid_observations_preserves_background_and_mask(self):
        self.a[10:20,10:20]=np.nan
        bad=[self.point(None), {**self.point(), 'id':'OLD','time':(self.cycle-timedelta(hours=2)).isoformat()},
             {**self.point(), 'id':'SPIKE','mslp':1050}, {**self.point(),'id':'FUTURE','time':(self.cycle+timedelta(hours=2)).isoformat()}]
        a,d=self.run_blend(bad)
        np.testing.assert_equal(a,self.a)
        self.assertEqual(d['accepted_stations'],0)

    def test_temporal_weight_and_duplicate_cluster(self):
        fresh,_=self.run_blend([self.point()])
        older,_=self.run_blend([{**self.point(),'time':(self.cycle-timedelta(minutes=60)).isoformat()}])
        self.assertLess(older[100,100],fresh[100,100])
        clustered,_=self.run_blend([{**self.point(),'id':f'K{i}'} for i in range(20)])
        np.testing.assert_allclose(clustered,fresh,atol=.001)

    def test_buddy_rejects_isolated_outlier(self):
        points=[{**self.point(1017),'id':f'K{i}','lon':-96+i*.1} for i in range(4)]
        points.append({**self.point(1026),'id':'BAD'})
        a,d=self.run_blend(points)
        self.assertEqual(d['accepted_stations'],4)
        self.assertLess(a.max(),1017)

    def test_correction_is_bounded_and_does_not_fill_missing_cells(self):
        self.a[10:20,10:20]=np.nan
        a,d=self.run_blend([self.point(1028)])
        self.assertLessEqual(d['max_correction_hpa'],6)
        self.assertTrue(np.isnan(a[10:20,10:20]).all())


if __name__=='__main__': unittest.main()
