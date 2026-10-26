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
        np.testing.assert_allclose(science.display_values("wind_gust", [10]), [19.438445], atol=.001)
        np.testing.assert_allclose(science.display_values("mslp", [101325,102560]), [1013.25,1025.6], atol=.001)
        self.assertTrue(np.isnan(science.display_values("mslp",[70000])[0]),'terrain pressure cannot masquerade as MSLP')
        for key in science.SOURCE_FIELDS:
            self.assertTrue(np.isnan(science.display_values(key, [np.nan, -999, 999999])).all())
        self.assertTrue(np.isnan(science.display_values("wind_speed", [-1])[0]))

    def test_palette_endpoints_and_no_missing_fill(self):
        for key, p in science.PRODUCTS.items():
            probes=[p["stops"][0],p["stops"][-1],np.nan] if p.get("cyclic") else [p["stops"][0]-100,p["stops"][-1]+100,np.nan]
            result = science.colorize(key, probes)
            self.assertEqual(result[:, 3].tolist(), [255, 255, 0])
            for row, c in zip(result[:2], [p["colors"][0], p["colors"][-1]]):
                self.assertEqual(row[:3].tolist(), [int(c[i:i+2], 16) for i in (1,3,5)])

    def test_metar_qc_latest_report_and_real_time(self):
        fields = ['raw_text','station_id','observation_time','latitude','longitude','temp_c','dewpoint_c','wind_dir_degrees','wind_speed_kt','wind_gust_kt','sea_level_pressure_mb','altim_in_hg','metar_type']
        stream = io.StringIO(); w = csv.DictWriter(stream, fieldnames=fields);w.writeheader()
        base = dict(raw_text='METAR KTEST', station_id='KAAA', observation_time='2026-10-24T14:00:00Z', latitude=39, longitude=-100, temp_c=10, dewpoint_c=5, wind_speed_kt=0, wind_dir_degrees=0, sea_level_pressure_mb=1013.2,metar_type='METAR')
        rows = [base, {**base,'temp_c':20,'observation_time':'2026-10-24T14:55:00Z','metar_type':'SPECI'},
                {**base,'station_id':'KFUT','observation_time':'2026-10-24T15:01:00Z'},
                {**base,'station_id':'KOLD','observation_time':'2026-10-24T13:29:59Z'},
                {**base,'station_id':'KQCC','dewpoint_c':50,'wind_speed_kt':999},
                {**base,'station_id':'KMIS','temp_c':'','dewpoint_c':'','wind_speed_kt':8},
                {**base,'station_id':'KOUT','latitude':60},
                {**base,'station_id':'KTAF','metar_type':'TAF'},
                {**base,'station_id':'KLIM','observation_time':'2026-10-24T13:30:00Z'},
                {**base,'station_id':'KDIR','wind_speed_kt':10,'wind_dir_degrees':360,'wind_gust_kt':25},
                {**base,'station_id':'KVRB','wind_speed_kt':10,'wind_dir_degrees':'VRB'},
                {**base,'station_id':'KALT','sea_level_pressure_mb':'','altim_in_hg':30.1}]
        w.writerows(rows); points = {p['id']:p for p in science.parse_metars('preamble\n'+stream.getvalue(), NOW)}
        self.assertEqual(set(points), {'KAAA','KQCC','KMIS','KLIM','KDIR','KVRB','KALT'})
        self.assertEqual(points['KAAA']['temperature'],68)
        self.assertEqual(points['KAAA']['wind_speed'],0)
        self.assertIsNone(points['KQCC']['dewpoint']);self.assertIsNone(points['KQCC']['wind_speed'])
        self.assertIsNone(points['KMIS']['temperature']);self.assertEqual(points['KMIS']['wind_speed'],8)
        self.assertEqual(points['KAAA']['time'],'2026-10-24T14:55:00Z')
        self.assertIsNone(points['KAAA']['wind_direction']);self.assertIsNone(points['KVRB']['wind_direction'])
        self.assertEqual(points['KDIR']['wind_direction'],0);self.assertEqual(points['KDIR']['wind_gust'],25)
        self.assertEqual(points['KDIR']['mslp'],1013.2);self.assertIsNone(points['KALT']['mslp'],'altimeter must not be relabeled MSLP')
        self.assertAlmostEqual(points['KDIR']['relative_humidity'],71.1,places=1)
        self.assertIsNone(points['KAAA']['heat_index']);self.assertIsNone(points['KAAA']['wind_chill'])

    def test_derived_values_and_validity_boundaries(self):
        self.assertAlmostEqual(float(science.relative_humidity(68,50)),52.54132558,places=6)
        self.assertEqual(float(science.relative_humidity(32,32)),100)
        self.assertEqual(float(science.relative_humidity(68,68.5)),100)
        self.assertTrue(np.isnan(science.relative_humidity(68,72)))
        self.assertTrue(np.isnan(science.relative_humidity(np.nan,50)))
        self.assertAlmostEqual(float(science.heat_index(90,70)),105.9220206,places=6)
        self.assertAlmostEqual(float(science.heat_index(100,10)),94.12248266,places=6)
        self.assertAlmostEqual(float(science.heat_index(85,90)),101.7808036,places=6)
        # Independently published NCL/NWS examples (warm, non-adjustment cases).
        for t,r,expected in [(104,55,137.361),(100,65,135.868),(92,60,104.684),(92,90,131.256),(80,75,83.5751)]:
            self.assertAlmostEqual(float(science.heat_index(t,r)),expected,delta=.001)
        self.assertTrue(np.isnan(science.heat_index(70,90)))
        self.assertTrue(np.isnan(science.heat_index(90,np.nan)))
        self.assertTrue(np.isnan(science.heat_index(90,101)))
        # The exact WPC preliminary screen, rather than temperature alone.
        self.assertTrue(np.isfinite(science.heat_index(79,100)))
        mph_to_kt=1/1.1507794480235
        self.assertAlmostEqual(float(science.wind_chill(0,15*mph_to_kt)),-19.39795411,places=6)
        self.assertTrue(np.isnan(science.wind_chill(50.01,15*mph_to_kt)))
        self.assertTrue(np.isnan(science.wind_chill(50,3*mph_to_kt)))
        self.assertTrue(np.isfinite(science.wind_chill(50,3.001*mph_to_kt)))
        self.assertTrue(np.isnan(science.wind_chill(30,np.nan)))
        # No valid heat-index conditions is a valid transparent product.
        fields={k:np.full((2,2),v,dtype='float32') for k,v in [('temperature',40),('dewpoint',32),('wind_speed',10)]}
        derived=science.derive_products(fields)
        self.assertTrue(np.isnan(derived['heat_index']).all());self.assertTrue(np.isfinite(derived['wind_chill']).all())
        self.assertTrue((science.colorize('heat_index',derived['heat_index'])[...,3]==0).all())

    def test_scalar_pressure_reprojection(self):
        from rasterio.transform import from_bounds
        native=from_bounds(0,0,2,2,2,2);target=from_bounds(0,0,2,2,1,1)
        fields={'mslp':np.array([[1000,1020],[1000,1020]],dtype='float32')}
        output=source.project_fields(fields,native,'EPSG:3857',target,1,1)
        self.assertAlmostEqual(float(output['mslp'][0,0]),1010,places=4)

    def test_provider_specific_inventory(self):
        def inventory(offset):
            fields=[('TMP','2 m above ground'),('DPT','2 m above ground'),('WIND','10 m above ground'),('WDIR','10 m above ground'),('GUST','10 m above ground'),('PRES','surface'),('VIS','surface')]
            return '1:0:d=2026102415:HGT:surface:anl:\n'+''.join(f'{i+2}:{offset+i*100}:d=2026102415:{param}:{level}:anl:\n' for i,(param,level) in enumerate(fields))
        self.assertEqual(source.inventory(inventory(1000),NOW)['wind_speed'],(1200,1299))
        self.assertEqual(source.inventory(inventory(3000),NOW)['wind_speed'],(3200,3299))
        for bad in [inventory(1000).replace('2 m above ground','surface'), inventory(1000).replace('d=2026102415','d=2026102414'),inventory(1000).replace(':anl:',':1 hour fcst:')]:
            with self.assertRaises(ValueError):source.inventory(bad,NOW)

    def test_pressure_inventory_rejects_terrain_and_forecasts(self):
        idx='1:0:d=2026102415:PRES:surface:anl:\n2:1000:d=2026102415:MSLMA:mean sea level:anl:\n3:2000:d=2026102415:HGT:1000 mb:anl:\n'
        self.assertEqual(source.inventory(idx,NOW,{'mslp':source.PRESSURE_FIELD}),{'mslp':(1000,1999)})
        for bad in [idx.replace(':MSLMA:',':PRES:'),idx.replace('mean sea level','surface'),idx.replace(':anl:',':1 hour fcst:'),idx.replace('2026102415','2026102414')]:
            with self.assertRaises(ValueError):source.inventory(bad,NOW,{'mslp':source.PRESSURE_FIELD})
        # Decode must check the GRIB parameter/level itself, not just its index.
        for grib,level in [((0,3,0),'surface'),((0,3,198),'surface'),((0,3,1),'meanSea')]:
            values=dict(zip(('discipline','parameterCategory','parameterNumber'),grib),typeOfLevel=level,level=0,shortName='wrong')
            with patch.object(source,'codes_new_from_message',return_value=object()),patch.object(source,'codes_get',side_effect=lambda h,k:values[k]),patch.object(source,'codes_release'):
                with self.assertRaises(ValueError):source.decode(b'not used','mslp',NOW)

    def test_metar_age_uses_retrieval_clock_after_rendering(self):
        rows='raw_text,station_id,observation_time,latitude,longitude,temp_c,dewpoint_c,wind_speed_kt,metar_type\n'
        rows+=''.join(f'METAR,K{i:04},2026-10-24T15:02:00Z,39,-100,20,10,5,METAR\n' for i in range(500))
        class Response:
            content=rows.encode()
            def raise_for_status(self):pass
        with tempfile.TemporaryDirectory() as d,patch.object(source,'build_analysis',side_effect=RuntimeError('no RTMA')),patch.object(source,'session') as fake:
            fake.return_value.get.return_value=Response()
            result=source.build(Path(d),NOW,clock=lambda:NOW+timedelta(minutes=3))
        self.assertEqual(result['observations']['count'],500)
        self.assertEqual(result['observations']['fetched_at'],'2026-10-24T15:03:00Z')

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


    def test_legacy_analysis_survives_failed_expansion(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);generation='2026102414-1234567890abcdef'
            folder=root/'generations'/generation;folder.mkdir(parents=True)
            a={'revision':'rtma-surface-v1','valid_time':'2026-10-24T14:00:00Z','generation':generation,
               'width':3600,'height':2024,'crs':'EPSG:3857','bounds':science.BOUNDS,'products':{}}
            for key in science.LEGACY_KEYS:
                p=folder/(key+'.png');Image.new('RGBA',(3600,2024),(0,0,0,0)).save(p)
                a['products'][key]={'path':str(p.relative_to(root)),'sha256':source.sha(p.read_bytes())}
            old={'schema':'surface-suite-v1','policy':{'analysis_warn_minutes':150,'analysis_hide_minutes':240,'station_hide_minutes':90},'analysis':a}
            (root/'metadata.json').write_text(json.dumps(old));source.validate_package(root)
            with patch.object(source,'session') as fake:
                fake.return_value.get.side_effect=RuntimeError('offline')
                result=source.build(root,NOW)
            self.assertEqual(result['analysis'],a)
            self.assertFalse(result['last_attempt']['analysis']['ok'])
            bad=json.loads(json.dumps(old));bad['analysis']['revision']=science.REVISION
            with self.assertRaises(ValueError):source.validate_package(root,bad)

    def test_pressure_retains_independently_and_never_regresses(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);gen='2026102415-1234567890abcdef';folder=root/'pressure'/gen;folder.mkdir(parents=True)
            path=folder/'mslp.png';Image.new('RGBA',(3600,2024),(1,2,3,255)).save(path)
            pressure={'revision':science.PRESSURE_REVISION,'valid_time':science.iso(NOW),'generation':gen,
                'native_spacing_km':3,'width':3600,'height':2024,'crs':'EPSG:3857','bounds':science.BOUNDS,
                'products':{'mslp':{**science.PRODUCTS['mslp'],'path':str(path.relative_to(root)),'sha256':source.sha(path.read_bytes())}}}
            from surface_contours import contour_collection
            target,_=source.display_grid()
            contour=contour_collection('mslp',np.full((2024,3600),np.nan),target,science.iso(NOW))
            contour_path=folder/'mslp_contours.geojson';contour_path.write_text(json.dumps(contour))
            pressure['products']['mslp']['contours']={'path':str(contour_path.relative_to(root)),'sha256':source.sha(contour_path.read_bytes()),'interval':4,'feature_count':0}
            previous={'schema':'surface-suite-v1','policy':{'analysis_warn_minutes':150,'analysis_hide_minutes':240,'station_hide_minutes':90},'pressure_analysis':pressure}
            sample=folder/'mslp_samples.bin.gz'
            sample.write_bytes(source.pack_grid('mslp',np.full((2024,3600),1013.2),pressure['valid_time']))
            pressure['products']['mslp']['sampling']={'path':sample.relative_to(root).as_posix(),'sha256':source.sha(sample.read_bytes()),'encoding':'gzip-int16-v1'}
            (root/'metadata.json').write_text(json.dumps(previous))
            with patch.object(source,'session') as fake:
                fake.return_value.get.side_effect=RuntimeError('offline')
                result=source.build(root,NOW+timedelta(hours=1))
            self.assertEqual(result['pressure_analysis'],pressure)
            self.assertTrue(result['last_attempt']['pressure_analysis']['ok'])
            self.assertFalse(result['last_attempt']['analysis']['ok'])
            self.assertFalse(result['last_attempt']['observations']['ok'])
            self.assertTrue(path.exists())
            with patch.object(source,'session') as fake:
                fake.return_value.get.side_effect=RuntimeError('offline')
                with self.assertRaises(RuntimeError):source.build_pressure_analysis(fake.return_value,root,NOW-timedelta(hours=1),result)
                fake.return_value.get.assert_not_called()
            bad=json.loads(json.dumps(result));bad['pressure_analysis']['products']={'surface_pressure':pressure['products']['mslp']}
            with self.assertRaises(ValueError):source.validate_package(root,bad)
            # A restored pre-contour pressure generation remains readable.
            legacy=json.loads(json.dumps(result));legacy['pressure_analysis']['revision']='hrrr-mslp-v1'
            del legacy['pressure_analysis']['products']['mslp']['contours'];source.validate_package(root,legacy)
            bad=json.loads(json.dumps(result));del bad['pressure_analysis']['products']['mslp']['contours']
            with self.assertRaises(ValueError):source.validate_package(root,bad)
            contour_path.write_bytes(b'corrupt')
            with self.assertRaises(ValueError):source.validate_package(root,result)


if __name__=='__main__':unittest.main()
