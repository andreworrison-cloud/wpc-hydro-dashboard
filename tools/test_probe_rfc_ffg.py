import unittest
from unittest.mock import patch
from probe_rfc_ffg import get_json, footprint, iso_ms, identity, validate_png

class SourceContractTests(unittest.TestCase):
    def test_arcgis_error_inside_http_success_is_failure(self):
        with patch('probe_rfc_ffg.fetch', return_value=(b'{"error":{"code":500}}', {})):
            with self.assertRaises(ValueError):
                get_json('')

    def test_empty_or_truncated_catalog_is_failure(self):
        for data in ({'features': []}, {'features': [{}], 'exceededTransferLimit': True}):
            with patch('probe_rfc_ffg.get_json', return_value={'data': data}):
                with self.assertRaises(ValueError):
                    footprint(2)

    def test_missing_timestamp_remains_unknown(self):
        self.assertIsNone(iso_ms(None))
        self.assertEqual(iso_ms(1792238400000), '2026-10-17T12:00:00+00:00')

    def test_catalog_change_is_detected(self):
        def record(date):
            return {'data': {'features': [{'attributes': {'objectid': 1, 'idp_filedate': date}}]}}
        self.assertNotEqual(identity(record(1)), identity(record(2)))

    def test_html_or_truncated_png_cannot_be_preview(self):
        for raw in (b'<html>Error</html>', b'\x89PNG\r\n\x1a\n'):
            with self.assertRaises(ValueError):
                validate_png(raw)
