import unittest

from src.free_ai_model_radar.smart_router_engine import SmartRouterEngine, extract_features


def body(text, *, tools=None, content=None):
    return {
        "model": "smart",
        "messages": [{"role": "user", "content": content if content is not None else text}],
        **({"tools": tools} if tools else {}),
    }


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


class DisabledJev:
    enabled = False
    mode = "off"

    def judge(self, text):
        return None

    def status(self):
        return {"enabled": False, "mode": "off"}


class SmartRouterTests(unittest.TestCase):
    def engine(self):
        engine = SmartRouterEngine(preload=False)
        engine.jev = DisabledJev()
        return engine

    def test_short_simple_goes_fast(self):
        d = self.engine().decide(body("¿Qué es DNS?"))
        self.assertEqual(d.route, "auto:fast")

    def test_explanation_is_general_not_quick(self):
        d = self.engine().decide(body("Explícame qué es Docker con un ejemplo sencillo."))
        self.assertEqual(d.domain, "general")

    def test_code_goes_smart(self):
        d = self.engine().decide(body("Corrige este bug en app.py: traceback exception"))
        self.assertEqual(d.domain, "coding")
        self.assertEqual(d.route, "auto:smart")
        self.assertEqual(d.task_type, "code")

    def test_refactor_backend_is_coding(self):
        d = self.engine().decide(body("Refactoriza este backend Python, corrige bugs y agrega pruebas unitarias."))
        self.assertEqual(d.domain, "coding")
        self.assertEqual(d.route, "auto:smart")
        self.assertEqual(d.task_type, "code")

    def test_research_goes_smart(self):
        d = self.engine().decide(body("Investiga este tema a fondo y compara varias fuentes actuales."))
        self.assertEqual(d.domain, "research")
        self.assertEqual(d.route, "auto:smart")
    def test_verify_uses_two_models_without_tools(self):
        d = self.engine().decide(body("Verifica y comprueba bien esta afirmación con evidencia."))
        self.assertEqual(d.route, "fusion:best_of")

    def test_explicit_consensus_uses_synthesis_without_tools(self):
        d = self.engine().decide(body("Quiero consenso: compara varias soluciones y sintetiza la explicación."))
        self.assertEqual(d.route, "fusion:synthesize")

    def test_verify_does_not_fuse_when_tools_are_present(self):
        tools = [{"type": "function", "function": {"name": "search", "parameters": {"type": "object"}}}]
        d = self.engine().decide(body("Verifica y comprueba bien esta afirmación con evidencia.", tools=tools))
        self.assertNotIn(d.route, {"fusion:best_of", "fusion:synthesize"})
        self.assertEqual(d.route, "auto:smart")

    def test_continuation_inherits_recent_context(self):
        request = {
            "model": "smart",
            "messages": [
                {"role": "user", "content": "Estoy depurando app.py y tengo un traceback exception en esta función."},
                {"role": "assistant", "content": "Revisaré el flujo."},
                {"role": "user", "content": "sigue"},
            ],
        }
        f = extract_features(request)
        self.assertTrue(f.continuation)
        self.assertIn("app.py", f.routing_text)
        d = self.engine().decide(request)
        self.assertEqual(d.domain, "coding")
        self.assertEqual(d.route, "auto:smart")

    def test_image_forces_vision_smart(self):
        content = [
            {"type": "text", "text": "¿Qué problema ves aquí?"},
            {"type": "image_url", "image_url": {"url": "https://example.invalid/image.png"}},
        ]
        d = self.engine().decide(body("", content=content))
        self.assertEqual(d.domain, "vision")
        self.assertEqual(d.route, "auto:smart")

    def test_semantic_classifier_can_catch_short_hard_query(self):
        e = self.engine()
        e.models = FakeModels(
            domain={"reasoning": 0.82, "quick": 0.41, "general": 0.39},
            difficulty={"hard": 0.81, "moderate": 0.42, "simple": 0.25},
        )
        d = e.decide(body("Find the invariant that makes this construction impossible."))
        self.assertEqual(d.domain, "reasoning")
        self.assertEqual(d.route, "auto:smart")

    def test_nli_resolves_ambiguous_semantic_domain(self):
        e = self.engine()
        e.models = FakeModels(
            domain={"general": 0.40, "research": 0.39},
            difficulty={"moderate": 0.52, "hard": 0.48},
            nli={"research": 0.91, "general": 0.05, "moderate": 0.58, "hard": 0.39},
        )
        d = e.decide(body("Trace the evidence behind this claim and reconcile conflicting reports."))
        self.assertEqual(d.domain, "research")
        self.assertTrue(d.nli_used)


if __name__ == "__main__":
    unittest.main()
