"""Analytic pressure fields test isolines, masking and automated center selection."""
import copy
import sys
import unittest
from pathlib import Path

import numpy as np
from pyproj import Transformer
from rasterio.transform import Affine, from_bounds

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from surface_analysis import BOUNDS
from surface_contours import smooth_masked, pressure_centers, contour_collection, validate_collection

TIME='2026-10-26T00:00:00Z'


class CartographyTests(unittest.TestCase):
    def test_smoothing_preserves_missing_support_and_constant(self):
        a=np.full((40,60),1024,dtype='float32');a[:,20:30]=np.nan
        result=smooth_masked(a,3)
        self.assertTrue(np.isnan(result[:,20:30]).all())
        np.testing.assert_allclose(result[np.isfinite(result)],1024,atol=.001)

    def test_smoothed_pressure_reduces_small_scale_noise(self):
        a=np.full((80,80),1020,dtype='float32');a[40,40]=1040
        result=smooth_masked(a,6)
        self.assertLess(result.max(),1020.2)
        self.assertAlmostEqual(float(result.mean()),float(a.mean()),places=3)

    @staticmethod
    def native_field():
        cx,cy=Transformer.from_crs(4326,3857,always_xy=True).transform(-96,38)
        spacing=7500;size=401
        transform=Affine(spacing,0,cx-size*spacing/2,0,-spacing,cy+size*spacing/2)
        x=(np.arange(size)-size//2)*spacing;y=x.copy();xx,yy=np.meshgrid(x,y)
        return transform,xx,yy

    def test_closed_high_and_low_have_correct_sign_location_and_pressure(self):
        t,x,y=self.native_field()
        a=1016+12*np.exp(-((x+600000)**2+y*y)/(2*180000**2))-12*np.exp(-((x-600000)**2+y*y)/(2*180000**2))
        found=pressure_centers(a,t,'EPSG:3857')
        self.assertEqual(sorted(f['properties']['symbol'] for f in found),['H','L'])
        high=next(f for f in found if f['properties']['symbol']=='H');low=next(f for f in found if f['properties']['symbol']=='L')
        self.assertGreater(high['properties']['value'],1027);self.assertLess(low['properties']['value'],1005)
        self.assertLess(high['geometry']['coordinates'][0],low['geometry']['coordinates'][0])
        self.assertTrue(all(f['properties']['prominence_hpa']>=1 for f in found))

    def test_flat_field_open_ridge_and_domain_edge_do_not_create_centers(self):
        t,x,y=self.native_field()
        for a in [np.full(x.shape,1020.),1016+x/100000,1016+10*np.exp(-x*x/(2*150000**2)),
                  1016+10*np.exp(-((x+1400000)**2+y*y)/(2*100000**2))]:
            self.assertEqual(pressure_centers(a,t,'EPSG:3857'),[])

    def test_missing_ring_rejects_center(self):
        t,x,y=self.native_field();a=1016+10*np.exp(-(x*x+y*y)/(2*150000**2));a[195:205,220:225]=np.nan
        self.assertEqual(pressure_centers(a,t,'EPSG:3857'),[])

    @staticmethod
    def display_grid(width=600,height=400):
        p=Transformer.from_crs(4326,3857,always_xy=True)
        west,south=p.transform(BOUNDS[0][1],BOUNDS[0][0]);east,north=p.transform(BOUNDS[1][1],BOUNDS[1][0])
        return from_bounds(west,south,east,north,width,height)

    def test_pressure_isobars_are_four_mb_and_match_analytic_gradient(self):
        width,height=600,400;t=self.display_grid(width,height)
        a=np.broadcast_to(np.linspace(1000,1040,width),(height,width))
        data=contour_collection('mslp',a,t,TIME)
        validate_collection(data,'mslp',TIME)
        self.assertEqual(sorted(set(f['properties']['value'] for f in data['features'])),list(range(1004,1040,4)))
        contour=next(f for f in data['features'] if f['properties']['value']==1020)
        self.assertAlmostEqual(contour['geometry']['coordinates'][0][0],-95.5,places=2)
        self.assertTrue(all(len(f['geometry']['coordinates'])>=2 for f in data['features']))

    def test_missing_corridor_does_not_get_bridged(self):
        width,height=600,400;t=self.display_grid(width,height)
        a=np.broadcast_to(np.linspace(1000,1040,height)[:,None],(height,width)).copy();a[:,250:350]=np.nan
        data=contour_collection('mslp',a,t,TIME);validate_collection(data,'mslp',TIME)
        self.assertGreater(len(data['features']),5)
        for f in data['features']:
            lons=[p[0] for p in f['geometry']['coordinates']]
            self.assertFalse(min(lons)<-101 and max(lons)>-90,'a contour must stop at the missing corridor')

    def test_empty_domains_and_freezing_isotherm(self):
        t=self.display_grid();empty=contour_collection('heat_index',np.full((400,600),np.nan),t,TIME)
        self.assertEqual(empty['features'],[]);validate_collection(empty,'heat_index',TIME)
        a=np.broadcast_to(np.linspace(0,60,600),(400,600))
        data=contour_collection('temperature',a,t,TIME)
        self.assertIn(32,[f['properties']['value'] for f in data['features']])
        validate_collection(data,'temperature',TIME)

    def test_wrong_times_units_coordinates_and_intervals_are_rejected(self):
        a=np.broadcast_to(np.linspace(1000,1040,600),(400,600));data=contour_collection('mslp',a,self.display_grid(),TIME)
        for change in ['time','interval','unit','coordinate','level']:
            bad=copy.deepcopy(data)
            if change=='time':bad['valid_time']='2026-10-25T23:00:00Z'
            elif change=='interval':bad['interval']=2
            elif change=='unit':bad['features'][0]['properties']['unit']='Pa'
            elif change=='coordinate':bad['features'][0]['geometry']['coordinates'][0]=[0,0]
            else:bad['features'][0]['properties']['value']=1003
            with self.assertRaises(ValueError):validate_collection(bad,'mslp',TIME)


if __name__=='__main__':unittest.main()
