import tempfile, unittest
from datetime import datetime, timezone
from pathlib import Path

from src.free_ai_model_radar.api_schedule import record_api_failure, record_api_success
from src.free_ai_model_radar.db import connect

NOW = datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc)

class ApiScheduleTests(unittest.TestCase):
    def test_known_change_defers_expensive_api_check(self):
        with tempfile.TemporaryDirectory() as td:
            con = connect(Path(td) / "radar.db")
            result = record_api_success(
                con, "provider", "model",
                expected_change_at="2026-10-01T00:00:00Z",
                now=NOW, preflight_hours=24,
            )
            self.assertEqual(result["next_check_at"], "2026-09-30T00:00:00+00:00")
            con.close()

    def test_failures_retry_soon(self):
        with tempfile.TemporaryDirectory() as td:
            con = connect(Path(td) / "radar.db")
            first = record_api_failure(con, "provider", "model", "timeout", now=NOW)
            second = record_api_failure(con, "provider", "model", "timeout", now=NOW)
            self.assertEqual(first["interval_hours"], 1.0)
            self.assertEqual(second["interval_hours"], 2.0)
            con.close()

if __name__ == "__main__":
    unittest.main()
