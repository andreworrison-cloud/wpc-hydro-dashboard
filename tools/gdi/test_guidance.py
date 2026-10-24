"""Engineering checks for time alignment, mean-of-maxima, and TLE recurrence."""
import datetime as dt
import json
import pathlib
import tempfile
import unittest
from unittest import mock
import numpy as np
import build_guidance as build
import model_source
from guidance_contract import (UTC, THRESHOLDS, MemberAccumulator, cam_ero_contract,
    equal_model_mean, tle_fields, verify_spec, disk_sum, footprint)

NOW = dt.datetime(2026, 10, 23, 17, 31, 27, tzinfo=UTC)


def cam(hour=12, refs=None, day=23):
    h = dt.datetime(2026, 10, day, hour, tzinfo=UTC)
    r = h.replace(hour=hour if refs is None else refs)
    start = h if hour == 18 else h.replace(hour=12)
    end = h.replace(hour=12) + dt.timedelta(hours=24)
    ranges = {0: list(range(13, 37)), 6: list(range(7, 31)),
              12: list(range(1, 25)), 18: list(range(1, 19))}
    return {'href_init_utc': h.isoformat(), 'refs_init_utc': r.isoformat(),
            'ero_start_utc': start.isoformat(), 'ero_end_utc': end.isoformat(),
            'href_forecast_hours': ranges[h.hour], 'refs_forecast_hours': ranges[r.hour],
            'ero_coverage_hours': int((end-start).total_seconds()/3600)}


class Source:
    def __init__(self, model, cycle):
        self.model = model
        self.cycle = dt.datetime.strptime(cycle, '%Y%m%d%H').replace(tzinfo=UTC)

    def tasks(self, lead):
        if lead < 0 or lead > build.horizon(self.model, self.cycle):
            raise ValueError('Out of horizon')
        return []


def fake_frame(model, cycle, lead, cache, grids):
    lat, lon = np.mgrid[:40, :40]
    grids[model] = (lat, lon, 'test')
    field = np.full((40, 40), 45 if model == 'hrrr' else 20, dtype='float32')
    return field, {'cycle': cycle.isoformat(), 'grid_md5': 'test', 'sha256': '0'*64,
                   'humidity_inputs': ['test'], 'sources': []}


class Contracts(unittest.TestCase):
    def test_fft_neighborhood_matches_exact_spatial_counts(self):
        from scipy.ndimage import convolve
        rng = np.random.default_rng(42)
        a = rng.random((40, 50)) < .05
        kernel = footprint()
        expected = convolve(a.astype('float32'), kernel, mode='constant', cval=0)
        np.testing.assert_array_equal(disk_sum(a, kernel), expected)
        np.testing.assert_array_equal(disk_sum(np.zeros_like(a), kernel), np.zeros_like(a))

    def test_all_cam_cycles_and_native_instantaneous_boundaries(self):
        for hour in (0, 6, 12, 18):
            current = NOW.replace(hour=max(hour+1, 1))
            cycles, start, end, times = cam_ero_contract(cam(hour), current)
            self.assertEqual(start.hour, 18 if hour == 18 else 12)
            self.assertEqual(len(times), 19 if hour == 18 else 25)
            self.assertEqual(times[0], start)
            self.assertEqual(times[-1], end)
            self.assertEqual(cycles['hrrr'][0].hour, hour)

    def test_fallback_cycles_share_full_window(self):
        cycles, start, end, times = cam_ero_contract(cam(12, 6), NOW)
        self.assertEqual(cycles['rrfs'][0].hour, 6)
        self.assertEqual(len(times), 25)
        for broken in (cam(18, 12), cam(12, 18)):
            with self.assertRaises(ValueError):
                cam_ero_contract(broken, NOW.replace(hour=20))
        old = cam(12)
        old['refs_init_utc'] = '2026-10-22T12:00:00Z'
        with self.assertRaises(ValueError):
            cam_ero_contract(old, NOW)

    def test_expired_or_missing_cam_hour_rejected(self):
        with self.assertRaises(ValueError):
            cam_ero_contract(cam(), NOW+dt.timedelta(days=1))
        broken = cam()
        broken['href_forecast_hours'] = broken['href_forecast_hours'][:-1]
        with self.assertRaises(ValueError):
            cam_ero_contract(broken, NOW)

    def test_mean_of_model_maxima_differs_from_maximum_of_blends(self):
        h = np.array([90., 0.])
        r = np.array([0., 90.])
        self.assertEqual(float(equal_model_mean(h.max(), r.max())), 90)
        self.assertEqual(float(equal_model_mean(h, r).max()), 45)
        self.assertTrue(np.isnan(equal_model_mean(np.nan, 40)))

    def test_persistence_requires_same_cell_in_two_of_three_samples(self):
        acc = MemberAccumulator()
        for index in range(5):
            a = np.zeros((40, 40), dtype='float32')
            if index in (0, 3):
                a[20, 20] = 50  # Two distant hits do not qualify.
            if index in (1, 3):
                a[18, 18] = 50  # Two hits within a three-sample group do.
            if index == 1:
                a[25, 25] = 50
            if index == 2:
                a[25, 26] = 50  # Neighborhood-first recurrence would be wrong.
            acc.update(a)
        m = acc.finish(5)
        self.assertFalse(m['persistent'][50][20, 20])
        self.assertTrue(m['persistent'][50][18, 18])
        self.assertFalse(m['persistent'][50][25, 25])
        self.assertFalse(m['persistent'][50][25, 26])
        with self.assertRaises(ValueError):
            acc.finish(6)

    def test_equal_model_weights_and_missing_member_cell(self):
        members = []
        for model in ('hrrr', 'rrfs'):
            for lag in range(6):
                acc = MemberAccumulator()
                for _ in range(12):
                    acc.update(np.full((40, 40), 45 if model == 'hrrr' else 20))
                members.append({**acc.finish(12), 'model': model, 'lag': lag,
                                'cycle': f'{model}-{lag}'})
        f = tle_fields(members)
        self.assertAlmostEqual(float(f['exceedance30'][20, 20]), 50, places=4)
        self.assertAlmostEqual(float(f['persistence30'][20, 20]), 50, places=4)
        self.assertEqual(float(f['persistence50'][20, 20]), 0)
        members[0]['complete'][20, 20] = False
        f = tle_fields(members)
        self.assertTrue(np.isnan(f['exceedance30'][20, 20]))
        self.assertTrue(np.isnan(f['persistence30'][20, 20]))
        with self.assertRaises(ValueError):
            tle_fields(members[:-1])
        members[1]['cycle'] = members[0]['cycle']
        with self.assertRaises(ValueError):
            tle_fields(members)

    def test_build_modes_and_all_member_valid_times(self):
        for mode in ('forecast', 'tle', 'ero'):
            with tempfile.TemporaryDirectory() as temp, \
                    mock.patch.object(model_source, 'PressureSource', Source), \
                    mock.patch.object(build, 'frame', fake_frame), \
                    mock.patch.object(build.subprocess, 'run'):
                root = pathlib.Path(temp)
                spec = build.main(mode, root, root/'public', NOW, cam=cam() if mode=='ero' else None)
                verify_spec(spec, spec['kind'])
                with np.load(root/'render/fields.npz') as f:
                    if mode == 'forecast':
                        self.assertEqual(len(spec['products']), 21)
                        self.assertEqual(float(f['blend3'][20, 20]), 32.5)
                    elif mode == 'ero':
                        self.assertEqual(set(spec['products']), {'hrrr_maximum','rrfs_maximum','blend_maximum'})
                        self.assertEqual(float(f['blend_maximum'][20, 20]), 32.5)
                        self.assertEqual(spec['sample_count'], 25)
                    else:
                        self.assertEqual(spec['member_count'], 12)
                        self.assertEqual(spec['sample_count'], 13)
                        self.assertEqual(spec['window_start'], NOW.replace(minute=0,second=0,microsecond=0).isoformat())
                        self.assertAlmostEqual(float(f['persistence40'][20, 20]), 50, places=4)
                        bad = json.loads(json.dumps(spec))
                        bad['source_metadata'][0]['samples'][0]['lead'] += 1
                        with self.assertRaises(ValueError):
                            verify_spec(bad, 'tle')

    def test_hourly_rrfs_gaps_never_substitute_older_runs(self):
        class ThreeHourly(Source):
            def tasks(self,lead):
                if self.model=='rrfs' and self.cycle.hour%3:raise ValueError('No hourly pressure-level cycle')
                return super().tasks(lead)
        with tempfile.TemporaryDirectory() as temp, mock.patch.object(model_source,'PressureSource',ThreeHourly), mock.patch.object(build,'frame') as decode:
            root=pathlib.Path(temp)
            spec=build.main('tle',root,root/'public',NOW)
            self.assertEqual(spec['status'],'awaiting_hourly_inputs')
            self.assertEqual(spec['products'],{})
            self.assertEqual(spec['assets'],{})
            self.assertIn('RRFS',spec['status_message'])
            decode.assert_not_called()

    def test_current_hour_window_rolls_and_includes_f00(self):
        for now in [NOW,NOW+dt.timedelta(hours=1),NOW.replace(hour=0)]:
            kind,cycles,start,end,times,_=build.select('tle',now,Source)
            self.assertEqual(start,now.replace(minute=0,second=0,microsecond=0))
            self.assertEqual(end-start,dt.timedelta(hours=12))
            self.assertEqual(len(times),13)
            self.assertEqual(times[0],start)
            for model in ('hrrr','rrfs'):
                self.assertEqual(cycles[model],[start-dt.timedelta(hours=h) for h in range(6)])

    def test_frequency_has_one_vote_per_run_without_neighborhood_dilation(self):
        members=[]
        for model in ('hrrr','rrfs'):
            for lag in range(6):
                acc=MemberAccumulator()
                for h in range(13):
                    a=np.zeros((6,6),dtype='float32')
                    if model=='hrrr' and lag==0 and h in (2,3):a[3,3]=50
                    acc.update(a)
                members.append({**acc.finish(13),'model':model,'lag':lag,'cycle':model+str(lag)})
        result=tle_fields(members)
        for key in ('exceedance50','persistence50'):
            self.assertAlmostEqual(float(result[key][3,3]),100/12,places=5)
            self.assertEqual(result[key][3,2],0)
        self.assertEqual(result['exceedance30'][0,0],0)

    def test_model_loops_share_valid_times_and_keep_actual_forecast_leads(self):
        class ThreeHourly(Source):
            def tasks(self,lead):
                if self.model=='rrfs' and self.cycle.hour%3:raise ValueError('No hourly pressure-level cycle')
                return super().tasks(lead)
        def timed_frame(model,cycle,lead,cache,grids):
            field,meta=fake_frame(model,cycle,lead,cache,grids)
            return field+lead,meta
        with tempfile.TemporaryDirectory() as temp, mock.patch.object(model_source,'PressureSource',ThreeHourly), mock.patch.object(build,'frame',timed_frame), mock.patch.object(build.subprocess,'run'):
            root=pathlib.Path(temp);m=build.main('forecast',root,root/'public',NOW)
            start=NOW.replace(minute=0,second=0,microsecond=0)
            for h in range(7):
                for model in ('hrrr','rrfs','blend'):
                    self.assertEqual(m['products'][f'{model}{h}']['valid_time'],(start+dt.timedelta(hours=h)).isoformat())
                self.assertEqual(m['products'][f'hrrr{h}']['forecast_hour'],h)
                self.assertEqual(m['products'][f'rrfs{h}']['forecast_hour'],h+2)
            self.assertEqual(m['products']['rrfs0']['cycle'],start.replace(hour=15).isoformat())
            self.assertEqual(m['expires_at'],m['window_end'])
            with np.load(root/'render/fields.npz') as fields:
                for h in range(7):
                    np.testing.assert_array_equal(fields[f'rrfs{h}'],np.full((40,40),22+h))
                    np.testing.assert_array_equal(fields[f'blend{h}'],np.full((40,40),33.5+h))
            verify_spec(m,'forecast')
            for change in ('valid_time','forecast_hour','cycle'):
                bad=json.loads(json.dumps(m))
                bad['products']['rrfs6'][change] = 6 if change=='forecast_hour' else start.isoformat()
                with self.assertRaises(ValueError):verify_spec(bad,'forecast')

    def test_forecast_skips_run_missing_an_intermediate_hour(self):
        class Partial(Source):
            def tasks(self,lead):
                if self.model=='hrrr' and self.cycle.hour==17 and lead==3:
                    raise ValueError('Intermediate hour missing despite complete endpoints')
                return super().tasks(lead)
        _,cycles,start,end,times,_=build.select('forecast',NOW,Partial)
        self.assertEqual(cycles['hrrr'][0].hour,16)
        self.assertEqual(start,NOW.replace(minute=0,second=0,microsecond=0))
        self.assertEqual(end,start+dt.timedelta(hours=6))
        self.assertEqual(len(times),7)

    def test_forecast_window_rolls_across_utc_midnight(self):
        now=NOW.replace(hour=23)
        _,cycles,start,end,times,_=build.select('forecast',now,Source)
        self.assertEqual(start.hour,23)
        self.assertEqual(end.day,24)
        self.assertEqual(end.hour,5)
        self.assertEqual(len(times),7)

    def test_legacy_forecast_can_only_be_retained_or_restored(self):
        with tempfile.TemporaryDirectory() as temp, mock.patch.object(model_source,'PressureSource',Source), mock.patch.object(build,'frame',fake_frame), mock.patch.object(build.subprocess,'run'):
            root=pathlib.Path(temp);m=build.main('forecast',root,root/'public',NOW)
        m['forecast_sampling']='hourly_f00_f06'
        with self.assertRaises(ValueError):verify_spec(m,'forecast')
        verify_spec(m,'forecast',allow_legacy_forecast=True)

    def test_day1_rejects_reference_changed_during_build(self):
        with tempfile.TemporaryDirectory() as temp, \
                mock.patch.object(model_source, 'PressureSource', Source), \
                mock.patch.object(build, 'frame', fake_frame), \
                mock.patch.object(build, 'read_cam', side_effect=[cam(), cam(12, 6)]), \
                mock.patch.object(build.subprocess, 'run') as render:
            with self.assertRaisesRegex(ValueError, 'changed during processing'):
                build.main('ero', pathlib.Path(temp), pathlib.Path(temp)/'public', NOW)
            render.assert_not_called()


if __name__ == '__main__':
    unittest.main()
