"""Display interpolation checks, isolated from the GRIB native library."""
import unittest
import numpy as np

class Display(unittest.TestCase):
    def test_rap_bilinear_display_preserves_bounds_masks_and_native_values(self):
        from render_suite import bilinear_sample
        field=np.array([[0.,10.],[20.,30.]])
        native=field.copy()
        sample=bilinear_sample(field,np.array([[0.,.5,1.]]),np.array([[0.,.5,1.]]))
        np.testing.assert_allclose(sample,[[0.,15.,30.]])
        np.testing.assert_array_equal(field,native)
        field[0,0]=np.nan
        self.assertTrue(np.isnan(bilinear_sample(field,np.array([.5]),np.array([.5]))[0]))
        self.assertTrue(np.isnan(bilinear_sample(native,np.array([-1.]),np.array([.5]))[0]))


if __name__=="__main__":unittest.main()
