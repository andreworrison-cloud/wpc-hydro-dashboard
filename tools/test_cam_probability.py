"""Scientific and transition regression checks; no network required."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cam_probability import WindowAccumulator, expected_ffg_durations, blend_maxima
from cam_ensemble import windows_for, read_members, remove_legacy_images, load_cycle_ffg
from cam_member_io import Grid, member_urls
from cam_omd import decode, selected_ranges, product_urls

UTC = timezone.utc
INIT = datetime(2026, 11, 3, 12, tzinfo=UTC)


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

    def test_cycle_ffg_does_not_use_later_publication(self):
        grid=Grid((3,3),'EPSG:4326',(1,0,0,0,-1,3))
        calls=[]
        def fake(sources,when,snapshot):
            calls.append(snapshot)
            stamp=INIT-timedelta(hours=0 if snapshot.endswith('12') else 1)
            published=stamp+timedelta(minutes=38)
            meta={'snapshot_time_utc':stamp.isoformat(),'reference_time_utc':INIT.replace(hour=6).isoformat(),
                  'source':{'http_last_modified':published.strftime('%a, %d %b %Y %H:%M:%S GMT')},'grid':grid.metadata()}
            return {d:np.ones((3,3)) for d in (1,3,6)},grid,meta
        with tempfile.TemporaryDirectory() as temp,patch('cam_ensemble.load_ffg',fake):
            class Source:cache=Path(temp)
            _,_,meta=load_cycle_ffg(Source(),INIT)
            self.assertEqual(calls,['2026110312','2026110311'])
            self.assertEqual(meta['snapshot_time_utc'],(INIT-timedelta(hours=1)).isoformat())
            load_cycle_ffg(Source(),INIT);self.assertEqual(len(calls),2)

    def test_index_selection_rejects_wrong_period_and_point_probability(self):
        index='1:0:d=2026110312:APCP:surface:5-6 hour acc fcst:prob >12.7:Neighborhood Probability\n2:100:d=2026110312:TMP:surface:6 hour fcst\n'
        # All four fixed thresholds are required; an individual match is not enough.
        with self.assertRaises(ValueError):selected_ranges(index,INIT,6,'prob')


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
