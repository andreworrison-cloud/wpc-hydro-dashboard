"""Numeric round trips, immutable identity, masks and encoding limits."""
import gzip
import json
import struct
import sys
import unittest
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from surface_sampling import pack_grid, unpack_grid

TIME = '2026-10-26T04:00:00Z'


class SamplingTests(unittest.TestCase):
    def test_roundtrip_and_mask(self):
        a = np.full((2024,3600), np.nan)
        a[100,:5] = [-40.04,0,32.06,1013.25,140.16]
        raw = pack_grid('temperature',a,TIME)
        q = unpack_grid(raw,'temperature',TIME)
        np.testing.assert_allclose(q[100,:5]*.1,[-40,0,32.1,1013.2,140.2])
        self.assertEqual(q[0,0],-32768)
        self.assertEqual(raw,pack_grid('temperature',a,TIME))
        for key,time in [('dewpoint',TIME),('temperature','2026-10-26T03:00:00Z')]:
            with self.assertRaises(ValueError):unpack_grid(raw,key,time)
        with self.assertRaises((ValueError,EOFError)):unpack_grid(raw[:-5],'temperature',TIME)

    def test_bounds_and_size(self):
        with self.assertRaises(ValueError):pack_grid('temperature',np.zeros((2,2)),TIME)
        a=np.zeros((2024,3600));a[0,0]=-3276.8
        with self.assertRaises(ValueError):pack_grid('temperature',a,TIME)
        with self.assertRaises(ValueError):unpack_grid(gzip.compress(struct.pack('<I',99999)),'temperature',TIME)

    def test_all_missing_is_valid(self):
        a=np.full((2024,3600),np.nan)
        q=unpack_grid(pack_grid('heat_index',a,TIME),'heat_index',TIME)
        self.assertTrue(np.all(q==-32768))


if __name__=='__main__':unittest.main()
