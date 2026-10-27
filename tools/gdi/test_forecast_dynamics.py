"""Check physical smoothing scale, CAM projection, and exact blend/time support."""
import copy
import datetime as dt
import unittest
import numpy as np
from pyproj import Transformer
from dynamics import filtered
from dynamics_contract import DEFINITIONS
from forecast_dynamics_contract import SCHEMA,RECIPE,contexts,verify_metadata
from guidance_contract import equal_model_mean
from render_forecast_dynamics import native_coordinates


def fixture():
    start = dt.datetime(2026,10,27,2,tzinfo=dt.timezone.utc)
    times = [(start+dt.timedelta(hours=h)).isoformat() for h in range(7)]
    runs,sources = [],[]
    for model,age,grid in [('hrrr',1,'a'*32),('rrfs',2,'b'*32)]:
        cycle = (start-dt.timedelta(hours=age)).isoformat()
        samples = [{'cycle':cycle,'lead':h+age,'grid_md5':grid,'valid_time':v} for h,v in enumerate(times)]
        runs.append({'model':model,'cycle':cycle,'samples':samples})
        sources += [{**{k:s[k] for k in ('cycle','lead','grid_md5')},'model':model,
                     'recipe':RECIPE,'smoothing_sigma_km':20.,'sources':[{'variable':'PRES'}],
                     'sha256':'c'*64,'projection':{'lat_1':38.5}} for s in samples]
    frames = contexts({'sample_times':times,'source_metadata':runs})
    m = {'schema':SCHEMA,'recipe':RECIPE,'model':'hrrr_rrfs','smoothing_sigma_km':20.,
         'base_selection_signature':'d'*64,'definitions':copy.deepcopy(DEFINITIONS),
         'window_start':times[0],'window_end':times[-1],'expires_at':times[-1],'sample_times':times,
         'cycle':runs[0]['cycle'],'frame_contexts':frames,'source_metadata':sources,
         'products':{name+'_'+k:{'field':name,'frame':k,'valid_time':c['valid_time']} for name in DEFINITIONS for k,c in frames.items()},
         'generation':'2026102701-aaaaaaaaaaaa-v1','width':2400,'height':1360,'bounds':[[24,-125],[50,-66]],
         'crs':'EPSG:3857','resampling':'masked_bilinear'}
    m['assets'] = {k:{'path':f"generations/{m['generation']}/{k}.png",'sha256':'a'*64} for k in m['products']}
    return m


class ForecastDynamics(unittest.TestCase):
    def test_3km_filter_preserves_mesoscale_and_suppresses_grid_noise(self):
        # A 12-km oscillation is suppressed; a 200-km feature remains visible.
        x = np.arange(301)*3.
        small = np.tile(np.cos(2*np.pi*x/12.),(201,1))
        broad = np.tile(np.cos(2*np.pi*x/200.),(201,1))
        a,b = filtered(small,(20/3,20/3)),filtered(broad,(20/3,20/3))
        s = (slice(60,-60),slice(60,-60))
        self.assertLess(np.std(a[s])/np.std(small[s]),.001)
        self.assertGreater(np.std(b[s])/np.std(broad[s]),.75)
        self.assertLess(np.std(b[s])/np.std(broad[s]),.9)

    def test_cam_projection_and_reversed_native_scans(self):
        p = {'lat_1':38.5,'lat_2':38.5,'lat_0':38.5,'lon_0':262.5,'radius':6371229.}
        projection = '+proj=lcc +lat_1=38.5 +lat_2=38.5 +lat_0=38.5 +lon_0=262.5 +R=6371229 +units=m'
        gx,gy = np.meshgrid(np.arange(61)*3000.-300000.,np.arange(46)*3000.+100000.)
        lon,lat = Transformer.from_crs(projection,4326,always_xy=True).transform(gx,gy)
        iy,ix = np.indices(lon.shape)
        for reverse in (False,True):
            lo,la = (lon[::-1,::-1],lat[::-1,::-1]) if reverse else (lon,lat)
            xx,yy = native_coordinates(lo,la,lo,la,p)
            np.testing.assert_allclose(xx,ix,atol=1e-8)
            np.testing.assert_allclose(yy,iy,atol=1e-8)

    def test_same_valid_time_different_actual_model_leads(self):
        m = fixture();verify_metadata(m)
        self.assertEqual(len(m['assets']),126)
        self.assertEqual(m['frame_contexts']['blend0']['sources'][0]['lead'],1)
        self.assertEqual(m['frame_contexts']['blend0']['sources'][1]['lead'],2)

    def test_incomplete_or_misaligned_support_rejected(self):
        good = fixture()
        for mutate in [lambda m:m['frame_contexts']['blend0']['sources'].pop(),
                       lambda m:m['frame_contexts']['hrrr0'].update(valid_time=m['sample_times'][1]),
                       lambda m:m['source_metadata'][0].update(grid_md5='c'*32),
                       lambda m:m['assets'].pop('pw_rrfs6'),
                       lambda m:m['assets']['mfc_blend0'].update(path='../wrong.png'),
                       lambda m:m['definitions']['div'].update(levels=[1,2,3]),
                       lambda m:m.update(smoothing_sigma_km=3),
                       lambda m:m.update(expires_at=m['sample_times'][5])]:
            with self.subTest(mutate=mutate):
                m = copy.deepcopy(good);mutate(m)
                with self.assertRaises(ValueError):verify_metadata(m)

    def test_blend_requires_both_models_and_averages_earth_wind_components(self):
        a = np.array([2.,np.nan,6.]);b = np.array([4.,10.,np.nan])
        result = equal_model_mean(a,b)
        np.testing.assert_allclose(result[:1],[3.])
        self.assertTrue(np.isnan(result[1:]).all())
        # Opposing equal earth-relative winds cancel; averaging speeds would not.
        np.testing.assert_allclose(equal_model_mean(np.array([20.]),np.array([-20.])),0.)


if __name__ == '__main__':unittest.main()
