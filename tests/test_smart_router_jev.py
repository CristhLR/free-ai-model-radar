import unittest

from src.free_ai_model_radar.smart_jev import JevJudgment
from src.free_ai_model_radar.smart_router_engine import SmartRouterEngine


def body(text, *, tools=None):
    out = {
        "model": "smart",
        "messages": [{"role": "user", "content": text}],
    }
    if tools:
        out["tools"] = tools
    return out


class FakeModels:
    def __init__(self, domain=None, difficulty=None, nli=None):
        self._domain = domain or {}
        self._difficulty = difficulty or {}
        self._nli = nli or {}
        self.semantic_ready = bool(domain or difficulty)
        self.nli_ready = bool(nli)

    def semantic_scores(self, text, kind="domain"):
        return dict(self._domain if kind == "domain" else self._difficulty)

    def nli_scores(self, text, labels, template):
        return {k: v for k, v in self._nli.items() if k in labels}

    def status(self):
        return {"semantic_ready": self.semantic_ready, "nli_ready": self.nli_ready}
class FakeJev:
    def __init__(self, judgment=None, mode="ambiguity"):
        self.enabled = True
        self.mode = mode
        self.judgment = judgment
        self.calls = 0

    def judge(self, text):
        self.calls += 1
        return self.judgment

    def status(self):
        return {
            "enabled": self.enabled,
            "mode": self.mode,
            "attempts": self.calls,
        }


class SmartRouterJevTests(unittest.TestCase):
    def test_jev_can_override_ambiguous_domain(self):
        engine = SmartRouterEngine(preload=False)
        engine.models = FakeModels(
            domain={"general": 0.40, "research": 0.39},
            difficulty={"moderate": 0.52, "hard": 0.45},
        )
        engine.jev = FakeJev(
            JevJudgment(
                domain="research",
                domain_confidence=0.96,
                complexity="moderate",
                complexity_confidence=0.50,
                model="jev-test",
                latency_ms=25.0,
            ),
            mode="always",
        )
        decision = engine.decide(
            body("Trace the evidence behind this claim and reconcile conflicting reports.")
        )
        self.assertTrue(decision.jev_used)
        self.assertEqual(decision.domain, "research")
        self.assertEqual(decision.route, "auto:smart")
        self.assertEqual(decision.jev_model, "jev-test")
        self.assertGreaterEqual(decision.confidence, 0.88)

    def test_high_confidence_rule_skips_jev_in_ambiguity_mode(self):
        engine = SmartRouterEngine(preload=False)
        fake = FakeJev(
            JevJudgment(
                domain="general",
                domain_confidence=1.0,
                complexity="hard",
                complexity_confidence=1.0,
                model="jev-test",
                latency_ms=10.0,
            ),
            mode="ambiguity",
        )
        engine.jev = fake
        decision = engine.decide(body("Translate this sentence to Spanish: Hello world."))
        self.assertEqual(decision.domain, "translation")
        self.assertFalse(decision.jev_used)
        self.assertEqual(fake.calls, 0)

    def test_jev_failure_keeps_local_decision(self):
        engine = SmartRouterEngine(preload=False)
        engine.jev = FakeJev(None, mode="always")
        decision = engine.decide(body("Corrige este bug en app.py: traceback exception"))
        self.assertEqual(decision.domain, "coding")
        self.assertEqual(decision.route, "auto:smart")
        self.assertFalse(decision.jev_used)

    def test_low_complexity_confidence_does_not_change_complexity(self):
        engine = SmartRouterEngine(preload=False)
        engine.models = FakeModels(
            domain={"general": 0.48, "quick": 0.44},
            difficulty={"moderate": 0.60, "hard": 0.41},
        )
        engine.jev = FakeJev(
            JevJudgment(
                domain="general",
                domain_confidence=0.90,
                complexity="hard",
                complexity_confidence=0.20,
                model="jev-test",
                latency_ms=15.0,
            ),
            mode="always",
        )
        decision = engine.decide(body("Explain the tradeoffs between these two normal options."))
        self.assertTrue(decision.jev_used)
        self.assertNotEqual(decision.complexity, "hard")


if __name__ == "__main__":
    unittest.main()
