import os
import unittest

from src.free_ai_model_radar.smart_model_catalog import ModelInfo
from src.free_ai_model_radar.smart_model_selector import ModelPreferenceSelector
from src.free_ai_model_radar.smart_router_engine import Decision


def request(text="Do the task", *, tools=None, content=None, max_tokens=4096):
    body = {
        "model": "smart",
        "messages": [{"role": "user", "content": content if content is not None else text}],
        "max_tokens": max_tokens,
    }
    if tools:
        body["tools"] = tools
    return body


def decision(domain, *, route="auto:smart", complexity="moderate", task_type="auto"):
    return Decision(
        route=route,
        domain=domain,
        complexity=complexity,
        difficulty_score=0.62,
        confidence=0.88,
        task_type=task_type,
        reason="test",
        semantic_ready=True,
        nli_used=False,
    )


class FakeCatalog:
    def __init__(self, models):
        self._models = models

    def models(self):
        return list(self._models)

    def status(self):
        return {"models": len(self._models), "source": "fake"}


def model(
    model_id,
    *,
    name=None,
    tier="Frontier",
    intelligence=3,
    speed=5,
    context=262144,
    vision=False,
    tools=True,
    platforms=("test",),
):
    return ModelInfo(
        model_id=model_id,
        display_name=name or model_id,
        platforms=platforms,
        size_label=tier,
        intelligence_rank=intelligence,
        speed_rank=speed,
        context_window=context,
        supports_vision=vision,
        supports_tools=tools,
    )


class SmartModelSelectorTests(unittest.TestCase):
    def setUp(self):
        self.previous_mode = os.environ.get("SMART_SELECTOR_MODE")
        os.environ["SMART_SELECTOR_MODE"] = "apply"

    def tearDown(self):
        if self.previous_mode is None:
            os.environ.pop("SMART_SELECTOR_MODE", None)
        else:
            os.environ["SMART_SELECTOR_MODE"] = self.previous_mode

    def test_coding_prefers_coder_model(self):
        selector = ModelPreferenceSelector(FakeCatalog([
            model("generic-frontier", name="Generic Frontier", intelligence=1, speed=2),
            model("Qwen/Qwen3-Coder-480B-A35B-Instruct", name="Qwen3 Coder", intelligence=3, speed=7),
            model("deepseek-ai/DeepSeek-V4-Flash", name="DeepSeek V4 Flash", intelligence=3, speed=5),
        ]))
        plan = selector.select(
            request("Refactor this Python backend and add unit tests."),
            decision("coding", task_type="code"),
        )
        self.assertTrue(plan.apply)
        self.assertEqual(plan.selected_model, "Qwen/Qwen3-Coder-480B-A35B-Instruct")
        self.assertGreaterEqual(plan.confidence, 0.58)

    def test_vision_hard_filters_text_only_models(self):
        selector = ModelPreferenceSelector(FakeCatalog([
            model("deepseek-text", tools=True, vision=False, intelligence=1),
            model("gemini-vision", name="Gemini Vision", vision=True, intelligence=3),
        ]))
        content = [
            {"type": "text", "text": "Analyze this screenshot."},
            {"type": "image_url", "image_url": {"url": "https://example.invalid/a.png"}},
        ]
        plan = selector.select(
            request(content=content),
            decision("vision"),
        )
        self.assertTrue(plan.apply)
        self.assertEqual(plan.selected_model, "gemini-vision")
        self.assertTrue(all(c["supports_vision"] for c in plan.candidates))

    def test_tools_hard_filters_models_without_tool_support(self):
        selector = ModelPreferenceSelector(FakeCatalog([
            model("reasoning-no-tools", name="Reasoning Thinking", tools=False, intelligence=1),
            model("agent-capable", name="Agent Capable", tools=True, intelligence=3),
        ]))
        tools = [{"type": "function", "function": {"name": "shell", "parameters": {"type": "object"}}}]
        plan = selector.select(
            request("Fix the repository.", tools=tools),
            decision("coding", task_type="code"),
        )
        self.assertTrue(plan.apply)
        self.assertEqual(plan.selected_model, "agent-capable")
        self.assertTrue(all(c["supports_tools"] for c in plan.candidates))

    def test_context_window_is_hard_eligibility_gate(self):
        selector = ModelPreferenceSelector(FakeCatalog([
            model("tiny-coder", name="Tiny Coder", context=8192, intelligence=1),
            model("large-context", name="Large Context", context=262144, intelligence=4),
        ]))
        long_text = "x" * 60000
        plan = selector.select(
            request(long_text, max_tokens=4096),
            decision("coding", task_type="code"),
        )
        self.assertTrue(plan.apply)
        self.assertEqual(plan.selected_model, "large-context")
        self.assertNotIn("tiny-coder", [c["model"] for c in plan.candidates])

    def test_simple_quick_request_stays_on_route_alias(self):
        selector = ModelPreferenceSelector(FakeCatalog([
            model("fast-model", speed=1, intelligence=2),
            model("smart-model", speed=7, intelligence=1),
        ]))
        plan = selector.select(
            request("What is DNS?"),
            decision("quick", route="auto:fast", complexity="simple", task_type="chat"),
        )
        self.assertFalse(plan.apply)
        self.assertIsNone(plan.selected_model)
        self.assertEqual(plan.fallback_route, "auto:fast")
        self.assertEqual(plan.mode, "observe")

    def test_fusion_bypasses_concrete_model_selector(self):
        selector = ModelPreferenceSelector(FakeCatalog([
            model("best-model", intelligence=1),
        ]))
        plan = selector.select(
            request("Verify this with multiple independent answers."),
            decision("research", route="fusion:best_of"),
        )
        self.assertFalse(plan.apply)
        self.assertEqual(plan.mode, "bypass-fusion")
        self.assertEqual(plan.candidates, [])

    def test_observe_mode_never_pins_model(self):
        os.environ["SMART_SELECTOR_MODE"] = "observe"
        selector = ModelPreferenceSelector(FakeCatalog([
            model("Qwen/Qwen3-Coder-480B-A35B-Instruct", name="Qwen3 Coder", intelligence=1),
            model("generic", intelligence=4),
        ]))
        plan = selector.select(
            request("Implement this Python API and tests."),
            decision("coding", task_type="code"),
        )
        self.assertFalse(plan.apply)
        self.assertEqual(plan.mode, "observe")
        self.assertIsNone(plan.selected_model)
        self.assertTrue(plan.candidates)

    def test_status_exposes_fail_open_metrics(self):
        selector = ModelPreferenceSelector(FakeCatalog([
            model("coder-model", name="Coder Model", intelligence=2),
        ]))
        selector.record_fallback()
        status = selector.status()
        self.assertEqual(status["selector_fallbacks"], 1)
        self.assertIn("backend-health-left-to-freellmapi", status["principles"])


if __name__ == "__main__":
    unittest.main()
