"""Scientific regressions against frozen HRRR V3.3 and pooled-member contracts."""
import hashlib
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import warnings

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
import fetch_hrrr_tle as core
import flash_flood_suite as suite
from tools.publish_pages_snapshot import is_model_runtime_owned


class ScienceTests(unittest.TestCase):
    def test_frozen_v33_all_18_fields(self):
        fixture = json.loads(Path(__file__).with_name('flash_flood_v33_fixture.json').read_text())
        rng = np.random.default_rng(fixture['seed'])
        ffg = (rng.uniform(.7, 2, (35,41)), rng.uniform(1.4,3,(35,41)), rng.uniform(2.4,4,(35,41)))
        for f in ffg: f[4:9,2:11] = np.nan
        records = []
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', RuntimeWarning)
            for n in range(6):
                qpf = rng.uniform(0,.2,(12,35,41)).astype('float32')
                qpf[n:n+3,10+n:15+n,20:25] = 1.5+n*.15
                ratios = {k: np.asarray(v,dtype='float32') for k,v in core.compute_run_ratio_fields(qpf,*ffg).items()}
                records.append({'qpf':qpf, 'ratios':ratios})
            fields = core.compute_tle_fields(records, ffg)
        actual = {k: hashlib.sha256(np.asarray(v,dtype='<f4').tobytes()).hexdigest() for k,v in fields.items()}
        self.assertEqual(actual, fixture['sha256_float32_le'])

    def test_blend_precedes_thresholds_and_time_maximum(self):
        h = np.zeros((12,1,1), dtype='float32'); r = h.copy()
        h[0] = 1.5; r[1] = 1.5
        fields = suite.diagnostic_fields([h,r], (np.ones((1,1)), np.full((1,1),999), np.full((1,1),999)))
        self.assertEqual(fields['hrrr_max_ratio'][0,0], .75)
        self.assertEqual(fields['hrrr_ffg_coverage'][0,0], 0)

    def records(self, hits):
        records = []
        for family in ('HRRR','RRFS'):
            for lag in range(6):
                q = np.zeros((12,1,1),dtype='float32')
                if (family,lag) in hits: q[0] = 2
                records.append({'family':family, 'lag_hours':lag,'qpf':q})
        return records

    def test_blend_has_equal_family_weight(self):
        records = self.records({('HRRR',n) for n in range(6)})
        fields = suite.compute_fields(records, (np.ones((1,1)),)*3)
        self.assertEqual(fields['ffg_consensus'][0,0], 50)

    def test_blend_run_change_requires_four_of_six(self):
        hits = {('HRRR',n) for n in range(3)}
        fields = suite.compute_fields(self.records(hits), (np.ones((1,1)),)*3)
        self.assertEqual(fields['latest3'][0,0], 50)
        self.assertEqual(fields['run_change'][0,0], 0)
        hits.add(('RRFS',0))
        fields = suite.compute_fields(self.records(hits), (np.ones((1,1)),)*3)
        self.assertEqual(fields['run_change'][0,0], 3)

    def test_missing_or_duplicate_cycle_rejected(self):
        records = self.records(set())
        with self.assertRaises(ValueError): suite.compute_fields(records[:-1], (np.ones((1,1)),)*3)
        records[-1]['lag_hours'] = 4
        with self.assertRaises(ValueError): suite.compute_fields(records, (np.ones((1,1)),)*3)

    def test_missing_hour_cell_cannot_be_dry(self):
        class Fake:
            workers = 1
            def fetch_hour(self, *args): return np.full((1,1),np.nan), {}
        with self.assertRaisesRegex(ValueError, 'Incomplete'):
            suite.fetch_member(Fake(), 'RRFS', suite.datetime.now(suite.UTC))

    def test_parallel_source_is_excluded(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            src = suite.OperationalSources(tmp)
            with self.assertRaisesRegex(ValueError,'Parallel'):
                src.index('https://nomads.ncep.noaa.gov/rrfs/para/file.grib2')

    def test_subhourly_selector_uses_only_exact_whole_hour_endpoint(self):
        init = suite.datetime(2026,11,4,17,tzinfo=suite.UTC)
        index = '\n'.join([
            '1:0:d=2026110417:REFC:entire atmosphere:675 min fcst:',
            '2:100:d=2026110417:APCP:surface:0-675 min acc fcst:',
            '3:200:d=2026110417:APCP:surface:0-690 min acc fcst:',
            '4:300:d=2026110417:APCP:surface:0-705 min acc fcst:',
            '5:400:d=2026110417:APCP:surface:0-12 hour acc fcst:',
            '6:550:d=2026110417:TSNOWP:surface:0-12 hour acc fcst:',
        ])
        self.assertEqual(suite.cumulative_entry(index,init,12),(400,549))
        with self.assertRaises(ValueError): suite.cumulative_entry(index,init,11)
        with self.assertRaises(ValueError): suite.cumulative_entry(index,init+suite.timedelta(hours=1),12)

    def test_cumulative_reset_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'reset'):
            suite.cumulative_difference(np.array([2.]),np.array([1.]),.001)
        with self.assertRaisesRegex(ValueError, 'complete'):
            suite.cumulative_difference(np.array([2.]),np.array([np.nan]),.001)

    def test_only_documented_packing_roundoff_is_zeroed(self):
        out, evidence = suite.cumulative_difference(np.array([1.,2.]),np.array([.999,2.5]),.002)
        np.testing.assert_array_equal(out, [0,.5])
        self.assertEqual(evidence['negative_cells'],1)
        with self.assertRaises(ValueError): suite.cumulative_difference(np.array([1.]),np.array([.99]),.002)

    def test_all_frequency_palettes_match_actual_counts(self):
        for count in (6,12):
            for key in suite.LAYER_KEYS:
                levels, colors, minimum = suite.render_style(key,count)
                self.assertEqual(len(levels),len(colors)+1,(key,count))
        self.assertAlmostEqual(suite.render_style('evolution_00_03',12)[2],100/3-.1)

    def test_raw_data_are_never_runtime_publications(self):
        self.assertTrue(is_model_runtime_owned('static/rrfs_tle_manifest.json'))
        self.assertTrue(is_model_runtime_owned('static/hrrr_rrfs_tle_manifest.json'))
        self.assertFalse(is_model_runtime_owned('flash_flood_suite.py'))

    def test_renderer_writes_complete_decodable_png_atomically(self):
        import tempfile
        from PIL import Image
        lat,lon = np.meshgrid(np.linspace(28,48,3),np.linspace(-120,-70,4),indexing='ij')
        with tempfile.TemporaryDirectory() as tmp, patch.object(core,'RENDER_WIDTH_PX',256), patch.object(core,'lats',lat,create=True), patch.object(core,'lons',lon,create=True):
            path = Path(tmp)/'overlay.png'
            core.render_overlay(np.full(lat.shape,1.2),path,core.RATIO_LEVELS,core.RATIO_COLORS,mask_below=.75)
            with Image.open(path) as image: image.verify()
            with Image.open(path) as image: image.load(); self.assertEqual(image.mode,'RGBA')
            self.assertTrue(path.read_bytes().endswith(b'IEND\xaeB`\x82'))
            self.assertFalse(path.with_suffix('.png.part').exists())


if __name__ == '__main__': unittest.main(verbosity=2)
