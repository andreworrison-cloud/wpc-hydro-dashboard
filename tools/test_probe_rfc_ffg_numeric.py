import unittest
from datetime import datetime, timezone
import numpy as np
from probe_rfc_ffg_numeric import band_contract, checked_array, snapshot_names, validate_grib


def tags(hours=3):
    p = [0]*29
    p[21], p[25], p[26] = 1, 1, hours
    return {'GRIB_ELEMENT':'FFLDG', 'GRIB_UNIT':'[kg/(m^2)]',
            'GRIB_IDS':'CENTER=7(US-NCEP) SUBCENTER=5(Hydrometeorological Prediction Center)',
            'GRIB_PDS_PDTN':'8', 'GRIB_PDS_TEMPLATE_ASSEMBLED_VALUES':' '.join(map(str,p)),
            'GRIB_REF_TIME':'1792238400', 'GRIB_VALID_TIME':str(1792238400+hours*3600),
            'GRIB_FORECAST_SECONDS':'0'}

class NumericContractTests(unittest.TestCase):
    def test_duration_from_metadata_not_band_position(self):
        self.assertEqual([band_contract(tags(h))[0] for h in (6,1,3)], [6,1,3])

    def test_hourly_missing_subcenter_is_recorded_not_misidentified(self):
        t=tags();t['GRIB_IDS']='CENTER=7(US-NCEP) SUBCENTER=255'
        self.assertEqual(band_contract(t)[0],3)
        t['GRIB_IDS']='CENTER=8(Other) SUBCENTER=255'
        with self.assertRaises(ValueError):band_contract(t)

    def test_wrong_units_or_quantity_rejected(self):
        for key, value in [('GRIB_UNIT','[inches]'),('GRIB_ELEMENT','APCP')]:
            t=tags();t[key]=value
            with self.assertRaises(ValueError):band_contract(t)

    def test_time_mismatch_rejected(self):
        t=tags();t['GRIB_VALID_TIME']=str(1792238400+3600)
        with self.assertRaises(ValueError):band_contract(t)

    def test_multiple_time_ranges_rejected(self):
        t=tags();p=t['GRIB_PDS_TEMPLATE_ASSEMBLED_VALUES'].split();p[21]='2'
        t['GRIB_PDS_TEMPLATE_ASSEMBLED_VALUES']=' '.join(p)
        with self.assertRaises(ValueError):band_contract(t)

    def test_nodata_is_preserved_not_zero(self):
        a=np.ma.array([25.4,9999.0],mask=[False,True]);b=checked_array(a)
        self.assertTrue(b.mask[1]);self.assertEqual(float(b[0]/25.4),1.0)

    def test_invalid_numeric_data_rejected(self):
        for a in (np.ma.array([np.nan]),np.ma.array([0]),np.ma.array([-1]),np.ma.masked_all(2)):
            with self.assertRaises(ValueError):checked_array(a)

    def test_snapshot_listing_excludes_cycle_files_and_future(self):
        html=''.join(f'<a href="{n}">' for n in ['5kmffg_2026101713.g2','5kmffg_2026101712.grb2','5kmffg_2026101718.g2'])
        self.assertEqual(snapshot_names(html,datetime(2026,10,17,14,tzinfo=timezone.utc)),['5kmffg_2026101713.g2'])

    def test_grib_truncation_or_html_rejected(self):
        message=b'GRIB'+b'\0\0\1\2'+(20).to_bytes(8,'big')+b'7777'
        self.assertEqual(validate_grib(message*3),3)
        for raw in (b'<html>Error</html>',message[:-1],b'',message+b'junk'):
            with self.assertRaises(ValueError):validate_grib(raw)
