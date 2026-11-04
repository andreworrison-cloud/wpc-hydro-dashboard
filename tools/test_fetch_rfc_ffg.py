import copy
from datetime import datetime,timedelta,timezone
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
import rasterio
from rasterio.transform import from_origin
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import fetch_rfc_ffg as ingest

NOW=datetime(2026,10,17,14,50,tzinfo=timezone.utc)
AFFINE=from_origin(-100,40,1,1)
CRS=rasterio.crs.CRS.from_epsg(4326)
RAW=b'GRIB'+b'\0\0\1\2'+(20).to_bytes(8,'big')+b'7777'


def fields():
    return {h:np.ma.array(np.full((2,4),h*25.4),mask=np.zeros((2,4),dtype=bool)) for h in (1,3,6)}


def baseline():
    return {'baseline_type':'test','shape':[2,4],'crs_wkt':CRS.to_wkt(),
            'affine':list(AFFINE)[:6],'tile_size':2,
            'durations':{str(h):{'valid_cells':8,'tiles':[[4,4]]} for h in (1,3,6)}}


class IngestTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.public=self.root/'public';self.science=self.root/'science'
        self.arrays=fields();self.reference=NOW.replace(hour=12,minute=0)
        self.policy=dict(ingest.POLICY,small_tile_tolerance_cells=0)
        self.read_patch=patch.object(ingest,'read_fields',side_effect=lambda p:(
            self.arrays,CRS,AFFINE,self.reference,{str(h):(self.reference+timedelta(hours=h)).isoformat() for h in (1,3,6)}))
        self.preview_patch=patch.object(ingest,'preview',side_effect=self.preview)
        self.read_patch.start();self.preview_patch.start()
        self.addCleanup(self.read_patch.stop);self.addCleanup(self.preview_patch.stop);self.addCleanup(self.tmp.cleanup)

    def preview(self,a,crs,affine,path,**kwargs):
        rgba=np.full((4,2,4),255,dtype='uint8')
        with rasterio.open(path,'w',driver='PNG',width=4,height=2,count=4,dtype='uint8',crs=crs,transform=affine) as d:d.write(rgba)
        return {'units':'inches'}

    def fetcher(self,hour=14,raw=RAW):
        name=f'5kmffg_20261017{hour:02}.g2'
        def fetch(url):
            if url==ingest.SOURCE:return f'<a href="{name}">'.encode(),{'url':url}
            return raw,{'url':url,'retrieved_at':NOW.isoformat(),
                        'http_last_modified':f'Sat, 17 Oct 2026 {hour:02}:38:00 GMT'}
        return fetch

    def run_ingest(self,fetch=None,current=NOW):
        return ingest.ingest(self.public,self.science,current,fetch or self.fetcher(),self.policy,baseline())

    def assert_retained(self,old,result):
        self.assertFalse(result['last_attempt']['ok']);self.assertEqual(result['active'],old['active'])
        ingest.verify_active(self.public,result['active'])
        p=self.science/result['active']['science']['path']
        self.assertEqual(ingest.digest(p),old['active']['science']['sha256'])

    def test_success_then_same_snapshot_is_unchanged(self):
        first=self.run_ingest();self.assertEqual(first['state'],'updated');self.assertTrue(first['usable'])
        second=self.run_ingest();self.assertEqual(second['state'],'unchanged')
        self.assertEqual(first['active'],second['active'])

    def test_network_failure_retains_last_good(self):
        old=self.run_ingest()
        def fail(url):raise OSError('simulated upstream outage')
        result=self.run_ingest(fail);self.assert_retained(old,result)
        self.assertEqual(result['state'],'retained');self.assertTrue(result['stale']);self.assertTrue(result['usable'])

    def test_first_failure_is_unavailable(self):
        result=self.run_ingest(lambda url:(_ for _ in ()).throw(OSError('offline')))
        self.assertEqual(result['state'],'unavailable');self.assertIsNone(result['active'])

    def test_old_snapshot_does_not_replace_new(self):
        old=self.run_ingest();result=self.run_ingest(self.fetcher(13));self.assert_retained(old,result)

    def test_bad_grib_does_not_replace_good(self):
        old=self.run_ingest();result=self.run_ingest(self.fetcher(raw=b'<html>error</html>'));self.assert_retained(old,result)

    def test_regional_coverage_loss_is_rejected(self):
        old=self.run_ingest();self.arrays[3].mask[0,0]=True
        result=self.run_ingest();self.assert_retained(old,result)
        self.assertIn('coverage',result['last_attempt']['error'])

    def test_coverage_tile_detects_loss_when_total_check_would_pass(self):
        self.policy['max_total_mask_change_fraction']=1
        self.arrays[1].mask[0,0]=True
        result=self.run_ingest();self.assertIn('regional coverage',result['last_attempt']['error'])

    def test_expired_retention_is_not_usable(self):
        old=self.run_ingest();result=self.run_ingest(current=NOW+timedelta(hours=5))
        self.assert_retained(old,result);self.assertEqual(result['state'],'expired');self.assertFalse(result['usable'])

    def test_old_reference_rejected_even_with_recent_snapshot(self):
        self.reference=NOW-timedelta(hours=10)
        result=self.run_ingest();self.assertFalse(result['usable']);self.assertIn('too old',result['last_attempt']['error'])

    def test_same_filename_changed_bytes_creates_new_generation(self):
        old=self.run_ingest();self.arrays[1].data[:]=30
        result=self.run_ingest(self.fetcher(raw=RAW*2))
        self.assertEqual(result['state'],'updated');self.assertNotEqual(old['active']['generation'],result['active']['generation'])
        ingest.verify_active(self.public,old['active'])

    def test_interrupted_publication_keeps_old_pointer(self):
        old=self.run_ingest();rename=ingest.os.rename
        def fail_public(src,dst):
            if Path(src).parent==self.public:raise OSError('simulated interrupted publication')
            return rename(src,dst)
        with patch.object(ingest.os,'rename',side_effect=fail_public):
            result=self.run_ingest(self.fetcher(raw=RAW*2))
        self.assert_retained(old,result)
        self.assertEqual(json.loads((self.public/'metadata.json').read_text())['active'],old['active'])

    def test_corrupt_retained_asset_cannot_be_called_usable(self):
        old=self.run_ingest();path=self.public/old['active']['assets']['1']['path'];path.write_bytes(b'corrupt')
        result=self.run_ingest();self.assertFalse(result['usable']);self.assertIsNone(result['active'])

    def test_future_reference_rejected(self):
        self.reference=NOW+timedelta(hours=1)
        result=self.run_ingest();self.assertFalse(result['usable']);self.assertIn('inconsistent',result['last_attempt']['error'])

    def test_scientific_files_cannot_be_inside_public_root(self):
        with self.assertRaises(ValueError):ingest.ingest(self.public,self.public/'science',NOW,self.fetcher(),baseline=baseline())


if __name__=='__main__':unittest.main()

class FreshnessBoundaryTests(unittest.TestCase):
    def test_exact_cutoff_is_expired(self):
        active={'snapshot_time':'2026-10-17T14:00:00+00:00','reference_time':'2026-10-17T12:00:00+00:00'}
        self.assertTrue(ingest.freshness(active,ingest.dt('2026-10-17T17:00:00+00:00'),ingest.POLICY)['expired'])
    def test_missing_duration_is_rejected(self):
        with self.assertRaises(ValueError):ingest.verify_active(Path('.'),{'assets':{}})
