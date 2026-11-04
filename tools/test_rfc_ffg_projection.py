"""Independent Mercator geometry and nearest-neighbor display checks."""
import math
from pathlib import Path
import tempfile
import unittest
import numpy as np
import rasterio
from rasterio.transform import from_bounds
from probe_rfc_ffg_numeric import preview

class ProjectionTests(unittest.TestCase):
    def test_mercator_geometry_and_values(self):
        # Geographic source split at a known latitude; the split must move in Mercator.
        source=np.ma.array(np.full((260,600),25.4,dtype='float32'),mask=False)
        source[:100,:]=127  # 40N boundary, 5 inches northward
        source.mask=np.zeros(source.shape,dtype=bool);source.mask[:,0:30]=True
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'test.png'
            meta=preview(source,'EPSG:4326',from_bounds(-126,24,-66,50,600,260),path,width=1200,height=660,target_crs='EPSG:3857')
            radius=6378137
            merc_y=lambda lat:radius*math.log(math.tan(math.pi/4+math.radians(lat)/2))
            with rasterio.open(path) as image:
                self.assertEqual(image.crs.to_epsg(),3857)
                self.assertAlmostEqual(image.bounds.top,merc_y(50),places=6)
                self.assertAlmostEqual(image.bounds.bottom,merc_y(24),places=6)
                for lat,expected in [(45,[44,127,184,255]),(35,[253,141,60,255])]:
                    row,col=image.index(radius*math.radians(-100),merc_y(lat))
                    self.assertEqual(image.read()[:,row,col].tolist(),expected)
                row,col=image.index(radius*math.radians(-125),merc_y(35))
                self.assertEqual(int(image.read(4)[row,col]),0)
                # 40N is NOT at its geographic linear image fraction.
                row,_=image.index(radius*math.radians(-100),merc_y(40))
                self.assertGreater(abs(row-660*(50-40)/26),20)
                self.assertEqual(meta['bounds_wsen'],[-126,24,-66,50])
    def test_reject_unknown_display_crs(self):
        with self.assertRaises(ValueError):
            preview(np.ma.ones((2,2)),'EPSG:4326',from_bounds(-126,24,-66,50,2,2),'unused.png',target_crs='EPSG:9999')

if __name__=='__main__':unittest.main()
