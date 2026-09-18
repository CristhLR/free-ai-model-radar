import unittest
from src.free_ai_model_radar.sources.openrouter import OpenRouterSource

class OpenRouterTests(unittest.TestCase):
    def test_only_zero_price_models_are_kept(self):
        payload = {"data": [
            {"id":"free/model","name":"Free","context_length":1,"pricing":{"prompt":"0","completion":"0"}},
            {"id":"paid/model","name":"Paid","context_length":1,"pricing":{"prompt":"0.1","completion":"0"}}
        ]}
        got = OpenRouterSource.parse(payload)
        self.assertEqual([m.model_id for m in got], ["free/model"])

if __name__ == "__main__":
    unittest.main()
