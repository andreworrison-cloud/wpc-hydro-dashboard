"""Observation corrections, temporal QC, density and missing-data regressions."""
import sys
import unittest
from pathlib import Path
from datetime import datetime, timezone, timedelta
import numpy as np
from pyproj import Transformer
from rasterio.transform import Affine
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from surface_pressure import blend_pressure, filter_small_pressure_features, regional_pressure_centers


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

    def test_small_unsupported_closed_low_is_removed_from_scalar_field(self):
        y,x=np.indices(self.a.shape)
        a=1017-2*np.exp(-((x-100)**2+(y-100)**2)/(2*4**2))
        filtered,d=filter_small_pressure_features(a,self.t,3857,[],set())
        self.assertGreater(filtered.min(),1016.01)
        self.assertGreater(d['removed_features'],0)

    def test_small_closed_low_supported_by_interior_and_surrounding_reports_survives(self):
        y,x=np.indices(self.a.shape)
        a=1017-2*np.exp(-((x-100)**2+(y-100)**2)/(2*4**2))
        to_geo=Transformer.from_crs(3857,4326,always_xy=True)
        points=[]
        for i,(r,c,v) in enumerate([(100,100,1015),(100,120,1017),(120,100,1017)]):
            lon,lat=to_geo.transform(*(self.t*(c+.5,r+.5)))
            points.append({'id':str(i),'lon':lon,'lat':lat,'mslp':v})
        filtered,d=filter_small_pressure_features(a,self.t,3857,points,{'0','1','2'})
        self.assertLess(filtered.min(),1015.1)
        self.assertGreater(d['supported_features'],0)
        rejected,_=filter_small_pressure_features(a,self.t,3857,points,set())
        self.assertGreaterEqual(rejected.min(),1016-.001)

    def test_large_remote_system_and_missing_mask_are_preserved(self):
        y,x=np.indices(self.a.shape)
        a=1017-2*np.exp(-((x-100)**2+(y-100)**2)/(2*30**2));a[:5,:5]=np.nan
        filtered,d=filter_small_pressure_features(a,self.t,3857,[],set())
        np.testing.assert_allclose(filtered,a,atol=.001,equal_nan=True)
        self.assertEqual(d['removed_features'],0)


class RegionalCenterTests(unittest.TestCase):
    def setUp(self):
        x,y=Transformer.from_crs(4326,3857,always_xy=True).transform(-96,38)
        self.t=Affine(5000,0,x-502500,0,-5000,y+502500)
        r,c=np.indices((201,201)); self.r=r; self.c=c
        self.bump=np.exp(-((r-100)**2+(c-100)**2)/(2*20**2))
        to_geo=Transformer.from_crs(3857,4326,always_xy=True)
        self.obs=[]
        for n,(dr,dc) in enumerate([(0,0),(35,35),(-35,35),(-35,-35),(35,-35)]):
            lon,lat=to_geo.transform(*(self.t*(100+dc+.5,100+dr+.5)))
            self.obs.append(dict(id=str(n),time='2026-10-27T00:00:00Z',lon=lon,lat=lat,
                                 mslp=1021+2*self.bump[100+dr,100+dc]))

    def detect(self,a,obs=None,accepted=None):
        obs=self.obs if obs is None else obs
        return regional_pressure_centers(a,self.t,3857,obs,obs if accepted is None else accepted)

    def test_sub_interval_high_low_with_observation_support(self):
        for sign in (1,-1):
            obs=[{**p,'mslp':1021+sign*(p['mslp']-1021)} for p in self.obs]
            found=self.detect(1021+sign*2*self.bump,obs)
            self.assertEqual(len(found),1)
            self.assertEqual(found[0]['properties']['symbol'],'H' if sign>0 else 'L')
            self.assertAlmostEqual(found[0]['properties']['value'],1021+sign*2,places=3)
            self.assertNotIn('enclosing_isobar_hpa',found[0]['properties'])

    def test_no_support_or_stale_report_does_not_certify_regional_center(self):
        a=1021+2*self.bump
        self.assertEqual(self.detect(a,accepted=[]),[])
        stale=[{**p,'time':'2026-10-26T23:00:00Z'} for p in self.obs]
        self.assertEqual(self.detect(a,accepted=stale),[])
        self.assertEqual(self.detect(a,self.obs[:3]),[])
        self.assertEqual(self.detect(a,[{**p,'mslp':1021} for p in self.obs]),[])

    def test_ridge_gradient_noise_and_missing_center_rejected(self):
        for a in [1021+self.c*.01,1021+2*np.exp(-(self.c-100)**2/(2*20**2)),
                  1021+.2*self.bump,np.full((201,201),1021.)]:
            self.assertEqual(self.detect(a),[])
        a=1021+2*self.bump;a[95:105,95:105]=np.nan
        self.assertEqual(self.detect(a),[])


if __name__=='__main__': unittest.main()
