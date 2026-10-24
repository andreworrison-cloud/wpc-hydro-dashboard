"""Meaningful surface checks: units, time selection, observed QC, safe retention."""
import csv
import io
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import surface_analysis as science
import fetch_surface_analysis as source

NOW = datetime(2026, 10, 24, 15, tzinfo=timezone.utc)


class SurfaceTests(unittest.TestCase):
    def test_units_and_missing(self):
        np.testing.assert_allclose(science.display_values("temperature", [273.15, 293.15]), [32, 68], atol=.001)
        np.testing.assert_allclose(science.display_values("dewpoint", [263.15]), [14], atol=.001)
        np.testing.assert_allclose(science.display_values("wind_speed", [0, 10]), [0, 19.438445], atol=.001)
        for key in science.PRODUCTS:
            self.assertTrue(np.isnan(science.display_values(key, [np.nan, -999, 999999])).all())
        self.assertTrue(np.isnan(science.display_values("wind_speed", [-1])[0]))

    def test_palette_endpoints_and_no_missing_fill(self):
        for key, p in science.PRODUCTS.items():
            result = science.colorize(key, [p["stops"][0]-100, p["stops"][-1]+100, np.nan])
            self.assertEqual(result[:, 3].tolist(), [255, 255, 0])
            for row, c in zip(result[:2], [p["colors"][0], p["colors"][-1]]):
                self.assertEqual(row[:3].tolist(), [int(c[i:i+2], 16) for i in (1,3,5)])

    def test_metar_qc_latest_report_and_real_time(self):
        fields = ['raw_text','station_id','observation_time','latitude','longitude','temp_c','dewpoint_c','wind_dir_degrees','wind_speed_kt','wind_gust_kt','metar_type']
        stream = io.StringIO(); w = csv.DictWriter(stream, fieldnames=fields);w.writeheader()
        base = dict(raw_text='METAR KTEST', station_id='KAAA', observation_time='2026-10-24T14:00:00Z', latitude=39, longitude=-100, temp_c=10, dewpoint_c=5, wind_speed_kt=0, metar_type='METAR')
        rows = [base, {**base,'temp_c':20,'observation_time':'2026-10-24T14:55:00Z','metar_type':'SPECI'},
                {**base,'station_id':'KFUT','observation_time':'2026-10-24T15:01:00Z'},
                {**base,'station_id':'KOLD','observation_time':'2026-10-24T13:29:59Z'},
                {**base,'station_id':'KQCC','dewpoint_c':50,'wind_speed_kt':999},
                {**base,'station_id':'KMIS','temp_c':'','dewpoint_c':'','wind_speed_kt':8},
                {**base,'station_id':'KOUT','latitude':60},
                {**base,'station_id':'KTAF','metar_type':'TAF'},
                {**base,'station_id':'KLIM','observation_time':'2026-10-24T13:30:00Z'}]
        w.writerows(rows); points = {p['id']:p for p in science.parse_metars('preamble\n'+stream.getvalue(), NOW)}
        self.assertEqual(set(points), {'KAAA','KQCC','KMIS','KLIM'})
        self.assertEqual(points['KAAA']['temperature'],68)
        self.assertEqual(points['KAAA']['wind_speed'],0)
        self.assertIsNone(points['KQCC']['dewpoint']);self.assertIsNone(points['KQCC']['wind_speed'])
        self.assertIsNone(points['KMIS']['temperature']);self.assertEqual(points['KMIS']['wind_speed'],8)
        self.assertEqual(points['KAAA']['time'],'2026-10-24T14:55:00Z')

    def test_provider_specific_inventory(self):
        def inventory(offset):
            return f'1:0:d=2026102415:HGT:surface:anl:\n2:{offset}:d=2026102415:TMP:2 m above ground:anl:\n3:{offset+100}:d=2026102415:DPT:2 m above ground:anl:\n4:{offset+200}:d=2026102415:WIND:10 m above ground:anl:\n5:{offset+300}:d=2026102415:GUST:10 m above ground:anl:\n'
        self.assertEqual(source.inventory(inventory(1000),NOW)['wind_speed'],(1200,1299))
        self.assertEqual(source.inventory(inventory(3000),NOW)['wind_speed'],(3200,3299))
        for bad in [inventory(1000).replace('2 m above ground','surface'), inventory(1000).replace('d=2026102415','d=2026102414'),inventory(1000).replace(':anl:',':1 hour fcst:')]:
            with self.assertRaises(ValueError):source.inventory(bad,NOW)

    def test_midnight_fallback_and_no_regression(self):
        class Missing:
            def __init__(self):self.urls=[]
            def get(self,url,**kwargs):self.urls.append(url);raise RuntimeError('offline')
        s=Missing()
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(RuntimeError):source.build_analysis(s,Path(d),datetime(2026,10,24,0,30,tzinfo=timezone.utc),{})
            self.assertTrue(any('rtma2p5.20261023/rtma2p5.t23z' in u for u in s.urls))
            old={'revision':science.REVISION,'valid_time':science.iso(NOW-timedelta(hours=1))}
            s=Missing();result,_=source.build_analysis(s,Path(d),NOW,{'analysis':old})
            self.assertIs(result,old);self.assertEqual(len(s.urls),2)
            self.assertTrue(all('t15z' in u for u in s.urls))

    def test_failed_update_preserves_previous_station_asset(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);folder=root/'stations';folder.mkdir()
            data=json.dumps({'schema':'surface-stations-v1','fetched_at':science.iso(NOW),'points':[{'id':f'K{i:03}'} for i in range(500)]}).encode();p=folder/'20261024140000-0000000000000000.json';p.write_bytes(data)
            m={'schema':'surface-suite-v1','policy':{'analysis_warn_minutes':150,'analysis_hide_minutes':240,'station_hide_minutes':90},'observations':{'path':str(p.relative_to(root)),'sha256':source.sha(data),'count':500,'fetched_at':science.iso(NOW)}}
            (root/'metadata.json').write_text(json.dumps(m))
            with patch.object(source,'build_analysis',side_effect=RuntimeError('no RTMA')),patch.object(source,'session') as fake:
                fake.return_value.get.side_effect=RuntimeError('no METAR')
                result=source.build(root,NOW)
            self.assertEqual(result['observations'],m['observations'])
            self.assertFalse(result['last_attempt']['analysis']['ok']);self.assertFalse(result['last_attempt']['observations']['ok'])
            self.assertEqual(p.read_bytes(),data)
            p.write_bytes(b'corrupt')
            with self.assertRaises(ValueError):source.validate_package(root)


if __name__=='__main__':unittest.main()
