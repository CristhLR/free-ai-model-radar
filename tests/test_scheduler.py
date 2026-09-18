import unittest
from datetime import datetime, timezone

from src.free_ai_model_radar.scheduler import is_due, next_check_time

NOW = datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc)

class SchedulerTests(unittest.TestCase):
    def test_stable_source_backs_off(self):
        source = {"kind":"changelog","base_interval_hours":6,"max_interval_hours":72}
        planned, interval = next_check_time(source, 3, changed=False, now=NOW)
        self.assertEqual(interval, 48)
        self.assertEqual((planned - NOW).total_seconds() / 3600, 48)

    def test_known_change_can_hold_check_until_preflight(self):
        source = {
            "kind":"pricing","expected_change_at":"2026-10-01T00:00:00Z",
            "preflight_hours":24,"hold_until_expected_change":True,
        }
        planned, _ = next_check_time(source, 0, changed=False, now=NOW)
        self.assertEqual(planned.isoformat(), "2026-09-30T00:00:00+00:00")

    def test_due(self):
        self.assertTrue(is_due("2026-09-18T11:00:00Z", NOW))
        self.assertFalse(is_due("2026-09-18T13:00:00Z", NOW))

if __name__ == "__main__":
    unittest.main()
