"""Analytic meteorological checks, including spherical metrics and terrain."""
import unittest
import tempfile
import numpy as np
from pyproj import Transformer
from dynamics import Geometry, RADIUS, filtered, layer_mean, calculate, MFC_LEVELS, UPPER_LEVELS, LOWER_LEVELS


class Dynamics(unittest.TestCase):
    def setUp(self):
        self.lon,self.lat = np.meshgrid(np.linspace(-110,-80,161),np.linspace(28,48,121))
        self.geometry = Geometry(self.lon,self.lat)

    def test_spherical_metric_and_analytic_convergence(self):
        # Constant eastward wind has zero divergence. Constant northward wind
        # has the non-zero spherical metric term, unlike a Cartesian shortcut.
        u = np.full_like(self.lon,10.)
        z = np.zeros_like(u)
        np.testing.assert_allclose(self.geometry.divergence(u,z),0.,atol=1e-15)
        expected = -10*np.tan(np.deg2rad(self.lat))/RADIUS
        np.testing.assert_allclose(self.geometry.divergence(z,u),expected,atol=1e-15)
        # u=a*R*cos(phi)*lambda produces uniform divergence a.
        a = -2e-5
        wind = a*RADIUS*np.cos(np.deg2rad(self.lat))*np.deg2rad(self.lon)
        np.testing.assert_allclose(self.geometry.divergence(wind,z)[2:-2,2:-2],a,atol=1e-15)

    def test_grid_wind_rotation_and_reverse_scan(self):
        x,y = np.meshgrid(np.linspace(-1.2e6,1.2e6,151),np.linspace(-.3e6,1.5e6,121))
        projection = '+proj=lcc +lat_1=25 +lat_2=25 +lat_0=25 +lon_0=-95 +R=6371229 +units=m'
        lon,lat = Transformer.from_crs(projection,4326,always_xy=True).transform(x,y)
        for reverse in (False,True):
            lo,la = (lon[::-1,::-1],lat[::-1,::-1]) if reverse else (lon,lat)
            geom = Geometry(lo,la)
            # Convert a known uniform eastward vector into grid coordinates by
            # solving against the basis, then demand exact recovery.
            one,zero = np.ones_like(lo),np.zeros_like(lo)
            ei,ni = geom.earth_wind(one,zero,True,reverse,not reverse)
            ej,nj = geom.earth_wind(zero,one,True,reverse,not reverse)
            det = ei*nj-ej*ni
            ug,vg = 12*nj/det,-12*ni/det
            u,v = geom.earth_wind(ug,vg,True,reverse,not reverse)
            np.testing.assert_allclose(u,12.,atol=1e-12)
            np.testing.assert_allclose(v,0.,atol=1e-12)
            np.testing.assert_allclose(geom.divergence(u,v)[2:-2,2:-2],0.,atol=1e-12)

    def test_filter_preserves_masks_and_rejects_low_support(self):
        a = np.full((41,41),7.)
        a[20,20] = np.nan
        b = filtered(a,(1.5,1.5))
        self.assertTrue(np.isnan(b[20,20]))
        np.testing.assert_allclose(b[np.isfinite(b)],7.)
        self.assertTrue(np.isnan(b[0,0]))

    def test_pressure_weighting_and_no_missing_level_bridge(self):
        a = np.array([1.,3.,5.,9.])[:,None,None]
        mean,depth = layer_mean(a,MFC_LEVELS,100.)
        self.assertEqual(depth.item(),250.)
        self.assertEqual(mean.item(),(2*50+4*50+7*150)/250)
        a[0] = np.nan
        mean,depth = layer_mean(a,MFC_LEVELS,100.)
        self.assertEqual(depth.item(),200.)
        a[2] = np.nan
        mean,depth = layer_mean(a,MFC_LEVELS,100.)
        self.assertEqual(depth.item(),0.)
        self.assertTrue(np.isnan(mean.item()))

    def test_real_grib_subfield_selection(self):
        from eccodes import (codes_grib_new_from_samples,codes_set,codes_get,codes_get_size,codes_get_array,
                             codes_set_values,codes_grib_multi_new,codes_grib_multi_append,
                             codes_grib_multi_write,codes_grib_multi_release,codes_release)
        from model_source import record_handle
        h=codes_grib_new_from_samples('regular_ll_sfc_grib2')
        multi=codes_grib_multi_new()
        try:
            for name,value in [('u',12.),('v',-7.)]:
                codes_set(h,'shortName',name)
                codes_set_values(h,np.full(codes_get_size(h,'values'),value))
                codes_grib_multi_append(h,4,multi)
            with tempfile.TemporaryFile() as f:
                codes_grib_multi_write(multi,f);f.seek(0);raw=f.read()
            for sub,name,value in [(1,'u',12.),(2,'v',-7.)]:
                selected=record_handle(raw,{'submessage':sub})
                try:
                    self.assertEqual(codes_get(selected,'shortName'),name)
                    np.testing.assert_allclose(codes_get_array(selected,'values'),value)
                finally:codes_release(selected)
        finally:
            codes_release(h);codes_grib_multi_release(multi)

    def test_paired_inventory_uses_next_distinct_offset(self):
        from model_source import PressureSource
        variables=[(v,f'{p} mb') for v in ('TMP','RH') for p in (950,850,700,500)]+[('PRES','surface')]
        lines=[f'{i+1}:{i*100}:d=2026102604:{v}:{p}:anl:' for i,(v,p) in enumerate(variables)]
        lines+=['10.1:900:d=2026102604:UGRD:950 mb:anl:','10.2:900:d=2026102604:VGRD:950 mb:anl:','11:1200:d=2026102604:END:surface:anl:']
        with tempfile.TemporaryDirectory() as t:
            source=PressureSource('rap','2026102604',cache=t,transport=lambda *args:'\n'.join(lines).encode())
            records=source.inventory('aws',0)
            self.assertEqual(records['UGRD','950 mb']['end'],1199)
            self.assertEqual(records['VGRD','950 mb']['end'],1199)
            self.assertEqual(records['VGRD','950 mb']['submessage'],2)

    def test_moisture_flux_sign_units_and_terrain(self):
        shape = self.lon.shape
        a = -2e-5
        u = a*RADIUS*np.cos(np.deg2rad(self.lat))*np.deg2rad(self.lon+95)
        q = .01
        fields = {('PRES','surface'):np.full(shape,100000.),('PWAT','column'):np.full(shape,25.4)}
        for p in set(MFC_LEVELS+UPPER_LEVELS+LOWER_LEVELS):
            fields['UGRD',f'{p} mb'] = u
            fields['VGRD',f'{p} mb'] = np.zeros(shape)
        for p in MFC_LEVELS:
            fields['TMP',f'{p} mb'] = np.full(shape,290.)
            fields['SPFH',f'{p} mb'] = np.full(shape,q)
        for p in (400,300):fields['RH',f'{p} mb'] = np.full(shape,70.)
        flags = {'grid_relative':False}
        result = calculate(fields,self.geometry,dx=13000,dy=13000,wind_flags=flags,sigma_km=0.)
        expected = -a*q/(1-q)*3.6e6
        np.testing.assert_allclose(result['mfc'][3:-3,3:-3],expected,atol=1e-10)
        np.testing.assert_allclose(result['div'][3:-3,3:-3],a*1e5,atol=1e-10)
        np.testing.assert_allclose(result['pw'],1.)
        np.testing.assert_allclose(result['rh'],70.)
        # A below-ground level with absurd values must have no influence.
        fields['PRES','surface'][:] = 92500
        fields['UGRD','950 mb'] = np.full(shape,999.)
        result = calculate(fields,self.geometry,dx=13000,dy=13000,wind_flags=flags,sigma_km=0.)
        np.testing.assert_allclose(result['mfc'][3:-3,3:-3],expected,atol=1e-10)
        self.assertEqual(result['mfc_depth_hpa'][50,50],200.)
        fields['PRES','surface'][:] = 80000
        result = calculate(fields,self.geometry,dx=13000,dy=13000,wind_flags=flags,sigma_km=0.)
        self.assertTrue(np.isnan(result['mfc']).all())
        self.assertTrue(np.isfinite(result['div']).all())


if __name__ == '__main__':unittest.main()
