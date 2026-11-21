"""Publication cannot report fresh radar solely because its build succeeded."""
from datetime import datetime, timedelta, timezone
import unittest
from validate_mrms_rala_loop import publication_freshness

UTC=timezone.utc


class PublicationFreshnessTests(unittest.TestCase):
    def setUp(self):
        self.valid=datetime(2026,11,4,22,30,tzinfo=UTC)
        self.manifest={'latest_valid_time_utc':self.valid.isoformat(),
                       'generated_utc':(self.valid+timedelta(minutes=25)).isoformat(),
                       'frames':[{'valid_time_utc':self.valid.isoformat()}]}

    def test_fresh_and_boundary_observations(self):
        for age in (0,10,20):
            receipt=publication_freshness(self.manifest,20,self.valid+timedelta(minutes=age))
            self.assertEqual(receipt['age_minutes'],age)

    def test_long_postprocessing_cannot_relabel_an_old_observation(self):
        publication_freshness(self.manifest,20,self.valid+timedelta(minutes=10))
        with self.assertRaisesRegex(ValueError,'old at publication'):
            publication_freshness(self.manifest,20,self.valid+timedelta(minutes=25))

    def test_over_boundary_and_future_data_are_rejected(self):
        for checked in (self.valid+timedelta(minutes=20,seconds=1),self.valid-timedelta(minutes=3)):
            with self.assertRaises(ValueError):publication_freshness(self.manifest,20,checked)

    def test_final_frame_identity_and_explicit_time_zone_are_required(self):
        self.manifest['frames'][0]['valid_time_utc']='2026-11-04T22:20:00Z'
        with self.assertRaises(ValueError):publication_freshness(self.manifest,20,self.valid)
        self.manifest['latest_valid_time_utc']='2026-11-04T22:30:00'
        self.manifest['frames'][0]['valid_time_utc']=self.manifest['latest_valid_time_utc']
        with self.assertRaisesRegex(ValueError,'offset'):publication_freshness(self.manifest,20,self.valid)


if __name__=='__main__':unittest.main(verbosity=2)
