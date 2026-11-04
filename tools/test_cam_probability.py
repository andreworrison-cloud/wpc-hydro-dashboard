"""Scientific and transition regression checks; no network required."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import rasterio

import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cam_probability import WindowAccumulator, ProducerWindowAccumulator, ProducerNeighborhood, expected_ffg_durations, blend_maxima
from cam_ensemble import windows_for, read_members, remove_legacy_images, load_cycle_ffg, require_cycle_ffg
from cam_member_io import Grid, member_urls, load_ffg
from cam_omd import decode, selected_ranges, product_urls

UTC = timezone.utc
INIT = datetime(2026, 11, 3, 12, tzinfo=UTC)


def official_cycle_meta(init,grid):
    return {'snapshot_time_utc':init.isoformat(),'reference_time_utc':init.isoformat(),
            'model_cycle_utc':init.isoformat(),'ffg_cycle_policy':'official_synoptic_model_cycle',
            'source':{'http_last_modified':(init+timedelta(minutes=38)).strftime('%a, %d %b %Y %H:%M:%S GMT'),
                      'sha256':'a'*64},'grid':grid.metadata()}


def official_ffg_fixture(cache,init,reference=None):
    # Mock only transport/container I/O; run the actual FFG band/time qualification.
    reference=reference or init
    class Source:
        def __init__(self):self.cache=cache
        def get(self,url,**kwargs):
            if url.endswith('/'):
                return f'<a href="5kmffg_{init:%Y%m%d%H}.g2">official</a>'.encode(),{}
            return b'fixture',{'sha256':'a'*64,'http_last_modified':
                              (init+timedelta(minutes=38)).strftime('%a, %d %b %Y %H:%M:%S GMT')}
    class Dataset:
        indexes=(1,3,6)
        shape=(3,3)
        crs=rasterio.crs.CRS.from_epsg(4326)
        transform=rasterio.Affine(1,0,0,0,-1,3)
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def tags(self,d):
            p=[0]*29
            p[21]=p[25]=1;p[26]=d
            return {'GRIB_ELEMENT':'FFLDG','GRIB_UNIT':'[kg/(m^2)]',
                    'GRIB_IDS':'CENTER=7(US-NCEP) SUBCENTER=5(HPC)','GRIB_PDS_PDTN':'8',
                    'GRIB_PDS_TEMPLATE_ASSEMBLED_VALUES':' '.join(map(str,p)),
                    'GRIB_REF_TIME':str(int(reference.timestamp())),
                    'GRIB_VALID_TIME':str(int((reference+timedelta(hours=d)).timestamp())),
                    'GRIB_FORECAST_SECONDS':'0'}
        def read(self,d,masked=True):return np.ma.array(np.ones((3,3),np.float32)*25.4)
    return Source(),Dataset()


class ProbabilityTests(unittest.TestCase):
    def make(self, *, start=0, end=6, radius=0):
        shape=(9, 9)
        ffg={1: np.full(shape, 10.), 3: np.full(shape, 1000.), 6: np.full(shape, 1000.)}
        return WindowAccumulator(start,end,np.ones(10),ffg,(1,1),radius)

    def test_peak_does_not_union_different_members_over_time(self):
        a=self.make()
        for f in range(1,7):
            q=np.zeros((10,9,9),np.float32)
            if f==1:q[:5,4,4]=20
            if f==6:q[5:,4,4]=20
            a.add(f,q)
        result=a.finish()
        self.assertEqual(result['QPF'][0,4,4],50)
        self.assertEqual(result['FFG_MAX'][4,4],50)

    def test_local_ffg_comparison_precedes_neighborhood(self):
        a=self.make(radius=1)
        a.ffg[1][:]=1; a.ffg[1][4,5]=10
        for f in range(1,7):
            q=np.zeros((10,9,9),np.float32)
            if f==1:q[:,4,5]=8
            a.add(f,q)
        self.assertEqual(a.finish()['FFG_MAX'][4,4],0)

    def test_single_neighborhood_counts_member_once(self):
        a=self.make(radius=1)
        for f in range(1,7):
            q=np.zeros((10,9,9),np.float32)
            if f==1:q[0,4,3]=20;q[0,4,5]=20
            a.add(f,q)
        self.assertEqual(a.finish()['FFG_MAX'][4,4],10)

    def test_missing_member_is_not_removed_from_denominator(self):
        a=self.make()
        with self.assertRaises(ValueError):a.add(1,np.zeros((9,9,9)))

    def test_missing_hour_cannot_publish(self):
        a=self.make()
        with self.assertRaises(ValueError):a.add(2,np.zeros((10,9,9)))
        with self.assertRaises(ValueError):a.finish()

    def test_missing_pixel_remains_unknown_in_window_max(self):
        a=self.make()
        for f in range(1,7):
            q=np.zeros((10,9,9),np.float32)
            if f==6:q[0,4,4]=np.nan
            a.add(f,q)
        result=a.finish()
        self.assertTrue(np.isnan(result['QPF'][:,4,4]).all())
        self.assertTrue(np.isnan(result['FFG_MAX'][4,4]))

    def test_strict_exceedance(self):
        a=self.make()
        for f in range(1,7):
            q=np.zeros((10,9,9),np.float32);q[:,4,4]=10 if f==1 else 0
            a.add(f,q)
        self.assertEqual(a.finish()['FFG_MAX'][4,4],0)

    def test_rolling_sums_accumulate_distinct_hours(self):
        a=self.make();a.ffg[3][:]=15
        for f in range(1,7):
            q=np.zeros((10,9,9),np.float32)
            if f<=3:q[0,4,4]=6
            a.add(f,q)
        self.assertEqual(a.finish()['FFG_MAX'][4,4],10)

    def test_dashboard_ffg_cadence_and_containment(self):
        self.assertEqual(expected_ffg_durations(4,3),(1,))
        self.assertEqual(expected_ffg_durations(6,3),(1,3))
        self.assertEqual(expected_ffg_durations(9,3),(1,3,6))
        self.assertEqual(expected_ffg_durations(8,3),(1,))
        for start,end in [(0,24),(12,36),(6,30),(0,18),(3,9),(9,15)]:
            for f in range(start+1,end+1):
                for d in expected_ffg_durations(f,start):self.assertGreaterEqual(f-d,start)

    def test_ero_windows_all_cycles(self):
        expected={0:(12,36),6:(6,30),12:(0,24),18:(0,18)}
        for cycle,period in expected.items():
            self.assertEqual(windows_for('ero',INIT.replace(hour=cycle)),{'ero':period})
        self.assertEqual(windows_for('cam',INIT),{'3h_to_9h':(3,9),'9h_to_15h':(9,15)})

    def test_blend_is_equal_suite_maxima_and_requires_both(self):
        a=blend_maxima([0,20,np.nan],[100,40,60])
        np.testing.assert_array_equal(a[:2],[50,30]);self.assertTrue(np.isnan(a[2]))
        with self.assertRaises(ValueError):blend_maxima([10],[10,20])

    def test_roster_and_backup_order(self):
        members=read_members();self.assertEqual(len(members),10)
        self.assertEqual(sum(m['family']=='HRRR' for m in members),3)
        for m in members:
            urls=member_urls(m,INIT,1)
            self.assertIn('s3.amazonaws.com',urls[0]);self.assertIn('nomads',urls[1])
        self.assertIn('noaa-rrfs-ops-pds',product_urls(INIT,'prob',6)[0])
        self.assertIn('/prod/',product_urls(INIT,'prob',6)[1])

    def test_cleanup_never_deletes_new_refs_names(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            for n in ['cam_test_href.png','cam_test_refs.png','cam_test_spc_refs.png','cam_test_omd_refs.png','cam_test_super.png','ero_test_href.png']:(root/n).write_bytes(b'x')
            remove_legacy_images(root,'cam_')
            self.assertEqual({p.name for p in root.iterdir()}, {'cam_test_spc_refs.png','cam_test_omd_refs.png','cam_test_super.png','ero_test_href.png'})

    def test_official_cycle_ffg_allows_publication_after_initialization(self):
        grid=Grid((3,3),rasterio.crs.CRS.from_epsg(4326).to_wkt(),(1,0,0,0,-1,3))
        for hour in (0,6,12,18):
            init=INIT.replace(hour=hour)
            calls=[]
            def fake(sources,when,snapshot,expected_cycle):
                calls.append(snapshot)
                self.assertEqual(expected_cycle,init)
                meta=official_cycle_meta(init,grid)
                return {d:np.ones((3,3)) for d in (1,3,6)},grid,meta
            with self.subTest(cycle=hour),tempfile.TemporaryDirectory() as temp,patch('cam_ensemble.load_ffg',fake):
                class Source:cache=Path(temp)
                _,_,meta=load_cycle_ffg(Source(),init)
                self.assertEqual(calls,[init.strftime('%Y%m%d%H')])
                self.assertEqual(meta['reference_time_utc'],init.isoformat())
                _,_,cached=load_cycle_ffg(Source(),init)
                self.assertTrue(cached['from_cycle_cache'])
                self.assertEqual(len(calls),1)

    def test_cycle_ffg_never_substitutes_an_earlier_snapshot(self):
        calls=[]
        def unavailable(sources,when,snapshot,expected_cycle):
            calls.append(snapshot)
            raise ValueError('official cycle not posted yet')
        with tempfile.TemporaryDirectory() as temp,patch('cam_ensemble.load_ffg',unavailable):
            class Source:cache=Path(temp)
            with self.assertRaisesRegex(RuntimeError,'no earlier FFG substitution'):
                load_cycle_ffg(Source(),INIT)
        self.assertEqual(calls,['2026110312'])

    def test_cycle_ffg_rejects_prior_hour_or_older_encoded_reference(self):
        grid=Grid((3,3),'EPSG:4326',(1,0,0,0,-1,3))
        for key in ('snapshot_time_utc','reference_time_utc','model_cycle_utc'):
            bad=official_cycle_meta(INIT,grid)
            bad[key]=(INIT-timedelta(hours=1)).isoformat()
            with self.subTest(key=key),self.assertRaises(ValueError):
                require_cycle_ffg(bad,INIT)

    def test_cycle_ffg_ignores_prior_policy_cache(self):
        grid=Grid((3,3),rasterio.crs.CRS.from_epsg(4326).to_wkt(),(1,0,0,0,-1,3))
        with tempfile.TemporaryDirectory() as temp:
            class Source:cache=Path(temp)
            for version in ('cycle-ffg-v1','cycle-ffg-v2'):
                folder=Path(temp)/version/INIT.strftime('%Y%m%d%H')
                folder.mkdir(parents=True)
                bad=official_cycle_meta(INIT,grid)
                bad['snapshot_time_utc']=(INIT-timedelta(hours=1)).isoformat()
                (folder/'metadata.json').write_text(json.dumps(bad))
                np.savez(folder/'ffg.npz',**{f'ffg_{d}':np.full((3,3),99) for d in (1,3,6)})
            def fake(sources,when,snapshot,expected_cycle):
                return {d:np.ones((3,3)) for d in (1,3,6)},grid,official_cycle_meta(INIT,grid)
            with patch('cam_ensemble.load_ffg',side_effect=fake) as fetch:
                fields,_,meta=load_cycle_ffg(Source(),INIT)
                self.assertEqual(fetch.call_count,1)
                self.assertFalse(meta['from_cycle_cache'])
                self.assertEqual(float(fields[1][0,0]),1)

    def test_official_ffg_loader_uses_cycle_not_publication_cutoff(self):
        for hour in (0,6,12,18):
            init=INIT.replace(hour=hour)
            with self.subTest(cycle=hour),tempfile.TemporaryDirectory() as temp:
                source,dataset=official_ffg_fixture(Path(temp),init)
                with patch('cam_member_io.rasterio.open',return_value=dataset),patch('cam_member_io.grib_framing'):
                    _,_,meta=load_ffg(source,init+timedelta(hours=1),expected_cycle=init)
                self.assertEqual(meta['snapshot_time_utc'],init.isoformat())
                self.assertEqual(meta['reference_time_utc'],init.isoformat())
                self.assertIsNone(meta['expires_at_utc'])

    def test_official_ffg_loader_rejects_stale_reference_inside_current_filename(self):
        with tempfile.TemporaryDirectory() as temp:
            source,dataset=official_ffg_fixture(Path(temp),INIT,reference=INIT-timedelta(hours=6))
            with patch('cam_member_io.rasterio.open',return_value=dataset),patch('cam_member_io.grib_framing'):
                with self.assertRaisesRegex(ValueError,'encoded reference must equal'):
                    load_ffg(source,INIT+timedelta(hours=1),expected_cycle=INIT)

    def test_index_selection_rejects_wrong_period_and_point_probability(self):
        index='1:0:d=2026110312:APCP:surface:5-6 hour acc fcst:prob >12.7:Neighborhood Probability\n2:100:d=2026110312:TMP:surface:6 hour fcst\n'
        # All four fixed thresholds are required; an individual match is not enough.
        with self.assertRaises(ValueError):selected_ranges(index,INIT,6,'prob')



class ProducerProbabilityTests(unittest.TestCase):
    def make(self,shape=(41,41),**kwargs):
        ffg={d:np.full(shape,1000.) for d in (1,3,6)}
        return ProducerWindowAccumulator(0,6,np.ones(10),ffg,(1,1),**kwargs)

    def test_circular_maximum_matches_direct_disk_filter(self):
        from scipy.ndimage import maximum_filter
        rng=np.random.default_rng(412)
        values=rng.uniform(0,100,(3,31,47))
        for radius in (0,1,2,3,7,13):
            op=ProducerNeighborhood(values.shape[1:],(1,1),radius,0,0)
            actual,_=op.maximum(values)
            off=np.arange(-radius,radius+1)
            yy,xx=np.meshgrid(off,off,indexing='ij')
            expected=maximum_filter(values,footprint=((xx*xx+yy*yy)<=radius*radius)[None,:,:],
                                    mode='constant',cval=-np.inf)
            with self.subTest(radius=radius):np.testing.assert_array_equal(actual,expected)

    def test_ffg_uses_neighborhood_rainfall_then_center_threshold(self):
        a=self.make(radius=1,sigma=0,half_width=0)
        a.ffg[1][:]=100
        a.ffg[1][20,21]=1
        for hour in range(1,7):
            q=np.zeros((10,41,41),np.float32)
            if hour==1:q[:,20,21]=2
            a.add(hour,q)
        p=a.finish()['FFG_MAX']
        self.assertEqual(p[20,21],100)
        self.assertEqual(p[20,20],0)

    def test_gaussian_matches_explicit_two_dimensional_kernel(self):
        from scipy.signal import convolve2d
        op=ProducerNeighborhood((41,51),(3000,3000))
        p=np.random.default_rng(10).uniform(0,100,(41,51))
        offsets=np.arange(-8,9)
        yy,xx=np.meshgrid(offsets,offsets,indexing='ij')
        weights=np.exp(-.5*(xx*xx+yy*yy)/25)
        expected=convolve2d(p,weights,mode='same')/convolve2d(np.ones(p.shape),weights,mode='same')
        np.testing.assert_allclose(op.smooth(p),expected,rtol=1e-6,atol=1e-5)

    def test_smoothing_each_slot_precedes_period_maximum(self):
        a=self.make(radius=0,sigma=1,half_width=2)
        p1=np.zeros((41,41));p2=p1.copy()
        p1[20,18]=100;p2[20,22]=100
        for hour in range(1,7):
            q=np.zeros((10,41,41),np.float32)
            if hour==1:q[:,20,18]=20
            if hour==6:q[:,20,22]=20
            a.add(hour,q)
        result=a.finish()['QPF'][0]
        expected=np.maximum(a.producer.smooth(p1),a.producer.smooth(p2))
        np.testing.assert_allclose(result,expected,atol=1e-5)
        self.assertLess(result[20,20],a.producer.smooth(np.maximum(p1,p2))[20,20])

    def test_missing_member_does_not_reduce_denominator(self):
        a=self.make(radius=0,sigma=0,half_width=0)
        for hour in range(1,7):
            q=np.zeros((10,41,41),np.float32)
            if hour==1:q[0,20,20]=np.nan
            a.add(hour,q)
        result=a.finish()
        self.assertTrue(np.isnan(result['QPF'][:,20,20]).all())
        self.assertTrue(np.isnan(result['FFG_MAX'][20,20]))

    def test_distinct_hour_rolling_sum(self):
        a=self.make(radius=0,sigma=0,half_width=0)
        a.ffg[3][:]=15
        for hour in range(1,7):
            q=np.zeros((10,41,41),np.float32)
            if hour<=3:q[0,20,20]=6
            a.add(hour,q)
        self.assertEqual(a.finish()['FFG_MAX'][20,20],10)

    def test_missing_ffg_center_stays_masked_after_smoothing(self):
        a=self.make(radius=0,sigma=1,half_width=2)
        for d in (1,3,6):a.ffg[d][20,20]=np.nan
        for hour in range(1,7):
            q=np.full((10,41,41),20,np.float32)
            a.add(hour,q)
        self.assertTrue(np.isnan(a.finish()['FFG_MAX'][20,20]))

    def test_dashboard_uses_producer_accumulator(self):
        from cam_ensemble import WindowAccumulator as dashboard_accumulator
        self.assertIs(dashboard_accumulator,ProducerWindowAccumulator)

    def test_native_settings_and_smoothed_ten_member_values(self):
        op=ProducerNeighborhood((41,41),(3000,3000))
        self.assertEqual(op.cells,13)
        self.assertEqual(op.operator.radius,39000)
        self.assertEqual(op.sigma,5)
        self.assertEqual(op.half_width,8)
        p=np.zeros((41,41));p[20,20]=10
        self.assertGreater(op.smooth(p)[20,20],0)
        self.assertLess(op.smooth(p)[20,20],10)

    def test_strict_exceedance_at_equal_ffg(self):
        a=self.make(radius=0,sigma=0,half_width=0)
        a.ffg[1][:]=10
        for hour in range(1,7):
            q=np.zeros((10,41,41),np.float32)
            if hour==1:q[:,20,20]=10
            a.add(hour,q)
        self.assertEqual(a.finish()['FFG_MAX'][20,20],0)


def synthetic_message(parameter,upper,values,init=INIT,process=194):
    import eccodes as ec
    g=ec.codes_grib_new_from_samples('regular_ll_sfc_grib2')
    try:
        for k,v in {'Ni':3,'Nj':3,'latitudeOfFirstGridPointInDegrees':2,'longitudeOfFirstGridPointInDegrees':0,
                    'latitudeOfLastGridPointInDegrees':0,'longitudeOfLastGridPointInDegrees':2,
                    'iDirectionIncrementInDegrees':1,'jDirectionIncrementInDegrees':1,
                    'dataDate':int(init.strftime('%Y%m%d')),'dataTime':init.hour*100,
                    'productDefinitionTemplateNumber':9,'discipline':0 if parameter==8 else 1,
                    'parameterCategory':1,'parameterNumber':parameter,'typeOfGeneratingProcess':process,
                    'generatingProcessIdentifier':136,'totalNumberOfForecastProbabilities':14,
                    'probabilityType':1,'upperLimit':upper,'stepUnits':1,'startStep':5,'endStep':6}.items():ec.codes_set(g,k,v)
        ec.codes_set_values(g,np.asarray(values,dtype=float).ravel())
        return ec.codes_get_message(g)
    finally:ec.codes_release(g)


class DecoderTests(unittest.TestCase):
    def test_omd_missing_ffg_and_packing_noise(self):
        raw=synthetic_message(194,1,[-10,-5,0,0,10,20,30,40,50])
        fields,_=decode(raw,INIT,6,'ffri',(1,))
        self.assertEqual(np.isnan(fields[1]).sum(),2)
        self.assertEqual(float(np.nanmax(fields[1])),50)

    def test_omd_rejects_wrong_cycle(self):
        raw=synthetic_message(194,1,np.zeros(9),init=INIT-timedelta(hours=6))
        with self.assertRaises(ValueError):decode(raw,INIT,6,'ffri',(1,))

    def test_omd_rejects_point_probability(self):
        raw=synthetic_message(194,1,np.zeros(9),process=5)
        with self.assertRaises(ValueError):decode(raw,INIT,6,'ffri',(1,))

    def test_omd_rejects_truncated_grib(self):
        raw=synthetic_message(194,1,np.zeros(9))
        with self.assertRaises(ValueError):decode(raw[:-10],INIT,6,'ffri',(1,))

    def test_omd_qpf_all_four_thresholds(self):
        raw=b''.join(synthetic_message(8,t,np.full(9,20)) for t in (12.7,25.4,50.8,76.2))
        fields,_=decode(raw,INIT,6,'prob',())
        self.assertEqual(set(fields),{12.7,25.4,50.8,76.2})


if __name__ == '__main__':unittest.main()
