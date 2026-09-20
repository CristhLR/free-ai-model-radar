import os
import tempfile
import time
import unittest
from pathlib import Path

from src.free_ai_model_radar.smart_jev import JevJudge


class FixtureJev(JevJudge):
    def __init__(self, *args, response=None, error=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.response = response
        self.error = error
        self.post_calls = 0

    def _post(self, payload, api_key):
        self.post_calls += 1
        if self.error:
            raise self.error
        return self.response


def valid_response():
    return {
        "model": "jev-1.13.0",
        "answers": {
            "domain": {
                "type": "choice",
                "choice": "coding",
                "confidence": 0.94,
                "probabilities": {"coding": 0.94, "general": 0.06},
            },
            "complexity": {
                "type": "choice",
                "choice": "moderate",
                "confidence": 0.72,
                "probabilities": {"simple": 0.12, "moderate": 0.72, "hard": 0.16},
            },
        },
        "usage": {"input_tokens": 10, "output_tokens": 2},
    }


class JevJudgeTests(unittest.TestCase):
    def setUp(self):
        self.old_key = os.environ.pop("TYPESAFE_API_KEY", None)
        self.old_mode = os.environ.pop("SMART_JEV_MODE", None)
        self.tmp = tempfile.TemporaryDirectory()
        self.env_path = Path(self.tmp.name) / ".env"
        self.env_path.write_text("TYPESAFE_API_KEY=test-key\n", encoding="utf-8")

    def tearDown(self):
        if self.old_key is not None:
            os.environ["TYPESAFE_API_KEY"] = self.old_key
        if self.old_mode is not None:
            os.environ["SMART_JEV_MODE"] = self.old_mode
        self.tmp.cleanup()

    def test_valid_choice_is_parsed(self):
        judge = FixtureJev(env_path=self.env_path, response=valid_response())
        result = judge.judge("Refactor the Python backend.")
        self.assertIsNotNone(result)
        self.assertEqual(result.domain, "coding")
        self.assertEqual(result.complexity, "moderate")
        self.assertAlmostEqual(result.domain_confidence, 0.94)
        self.assertEqual(result.model, "jev-1.13.0")

    def test_cache_avoids_second_provider_call(self):
        judge = FixtureJev(env_path=self.env_path, response=valid_response())
        first = judge.judge("Same request")
        second = judge.judge("Same request")
        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertEqual(judge.post_calls, 1)
        self.assertFalse(first.cached)
        self.assertTrue(second.cached)
        self.assertEqual(judge.cache_hits, 1)

    def test_two_failures_open_circuit_breaker(self):
        judge = FixtureJev(
            env_path=self.env_path,
            response=None,
            error=RuntimeError("provider down"),
        )
        self.assertIsNone(judge.judge("request one"))
        self.assertIsNone(judge.judge("request two"))
        before = judge.post_calls
        self.assertGreater(judge.disabled_until, time.monotonic())
        self.assertIsNone(judge.judge("request three"))
        self.assertEqual(judge.post_calls, before)
        self.assertEqual(judge.failure_streak, 2)

    def test_missing_key_disables_jev(self):
        missing = Path(self.tmp.name) / "missing.env"
        judge = FixtureJev(env_path=missing, response=valid_response())
        self.assertFalse(judge.enabled)
        self.assertIsNone(judge.judge("hello"))
        self.assertEqual(judge.post_calls, 0)

    def test_off_mode_disables_jev(self):
        os.environ["SMART_JEV_MODE"] = "off"
        judge = FixtureJev(env_path=self.env_path, response=valid_response())
        self.assertFalse(judge.enabled)
        self.assertIsNone(judge.judge("hello"))


if __name__ == "__main__":
    unittest.main()
