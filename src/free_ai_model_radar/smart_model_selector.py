from __future__ import annotations

import math
import os
import threading
from dataclasses import asdict, dataclass
from typing import Any

from .smart_model_catalog import FreeLLMModelCatalog, ModelInfo
from .smart_router_engine import Decision, Features, extract_features

STRONG_DOMAINS = {
    "coding", "reasoning", "research", "vision",
    "data_analysis", "troubleshooting",
}
DOMAIN_HINTS: dict[str, tuple[tuple[str, float], ...]] = {
    "coding": (("coder", .30), ("codestral", .30), ("code", .16), ("deepseek", .13), ("qwen", .10), ("kimi", .08), ("glm", .06)),
    "reasoning": (("reason", .24), ("thinking", .22), ("r1", .20), ("nemotron", .14), ("deepseek", .13), ("qwen", .10), ("glm", .08)),
    "research": (("kimi", .14), ("gemini", .12), ("deepseek", .08), ("glm", .07), ("qwen", .06)),
    "vision": (("vision", .28), ("-vl", .24), ("vl-", .24), ("gemini", .16), ("omni", .14)),
    "data_analysis": (("coder", .16), ("reason", .12), ("deepseek", .10), ("qwen", .09), ("gemini", .08), ("glm", .07)),
    "troubleshooting": (("coder", .18), ("code", .12), ("deepseek", .11), ("qwen", .08), ("glm", .07)),
}

@dataclass
class SelectionPlan:
    apply: bool
    mode: str
    selected_model: str | None
    fallback_route: str
    confidence: float
    reason: str
    candidates: list[dict[str, Any]]
    requirements: dict[str, Any]
    source: str = "catalog-multifactor-v1"

    def public_dict(self) -> dict[str, Any]:
        return asdict(self)

class ModelPreferenceSelector:
    def __init__(self, catalog: FreeLLMModelCatalog | None = None) -> None:
        self.catalog = catalog or FreeLLMModelCatalog()
        self.lock = threading.RLock()
        self.selections = 0
        self.applied = 0
        self.selector_fallbacks = 0

    @staticmethod
    def _tier(label: str) -> float:
        return {"frontier": 1., "large": .84, "medium": .66, "small": .48}.get((label or "").lower(), .58)

    @staticmethod
    def _rank(value: int | None) -> float:
        return .55 if not value or value <= 0 else 1. / (1. + .11 * max(0, value - 1))

    @staticmethod
    def _speed(value: int | None) -> float:
        return .55 if not value or value <= 0 else max(.10, 1. - (min(value, 10) - 1) / 10.)

    @staticmethod
    def _context(value: int) -> float:
        if value <= 0:
            return .45
        return min(1., .45 + math.log2(max(1., value / 32768.)) * .10)

    @staticmethod
    def _affinity(model: ModelInfo, domain: str, features: Features) -> float:
        text = f"{model.model_id} {model.display_name}".lower()
        score = .42 + sum(bonus for marker, bonus in DOMAIN_HINTS.get(domain, ()) if marker in text)
        if features.has_tools:
            score += .12 if model.supports_tools else -1.
            if "thinking" in text:
                score -= .18

            explicit_code = domain == "coding" or features.code_signal >= .55
            if not explicit_code and any(x in text for x in ("coder", "codestral")):
                score -= .26

            for marker, bonus in (
                ("gemini", .16),
                ("deepseek", .08),
                ("glm", .06),
                ("mimo", .05),
                ("compound", .05),
            ):
                if marker in text:
                    score += bonus
        if domain == "research" and model.context_window >= 200000:
            score += .10
        if domain == "vision" and model.supports_vision:
            score += .18
        if domain == "coding" and any(x in text for x in ("coder", "codestral")):
            score += .08
        return max(0., min(1., score))

    @staticmethod
    def _required_context(body: dict[str, Any], features: Features) -> int:
        try:
            output = int(body.get("max_tokens") or 4096)
        except (TypeError, ValueError):
            output = 4096
        return max(8192, features.estimated_tokens + max(512, output) + 2048)

    def _score(self, model: ModelInfo, decision: Decision, features: Features) -> tuple[float, list[str]]:
        affinity = self._affinity(model, decision.domain, features)
        axes = (self._tier(model.size_label), self._rank(model.intelligence_rank), self._speed(model.speed_rank), affinity, self._context(model.context_window))
        if decision.complexity == "hard":
            weights = (.43, .11, .06, .31, .09)
        elif decision.complexity == "simple":
            weights = (.30, .08, .24, .27, .11)
        else:
            weights = (.37, .10, .13, .30, .10)
        total = sum(a * w for a, w in zip(axes, weights))
        reasons = [f"tier={model.size_label or 'unknown'}", f"affinity={affinity:.2f}", f"context={model.context_window}"]
        return max(0., min(1., total)), reasons

    def select(self, body: dict[str, Any], decision: Decision) -> SelectionPlan:
        features = extract_features(body)
        required = self._required_context(body, features)
        req = {"tools": features.has_tools, "vision": features.has_images or decision.domain == "vision", "context_tokens": required}
        if decision.route.startswith("fusion:"):
            return SelectionPlan(False, "bypass-fusion", None, decision.route, 1., "fusion owns model coordination", [], req)

        scored: list[tuple[float, ModelInfo, list[str]]] = []
        for model in self.catalog.models():
            if model.context_window and model.context_window < required:
                continue
            if req["vision"] and not model.supports_vision:
                continue
            if req["tools"] and not model.supports_tools:
                continue
            score, reasons = self._score(model, decision, features)
            if score > .25:
                scored.append((score, model, reasons))
        scored.sort(key=lambda x: (-x[0], x[1].model_id.lower()))
        top = scored[:8]
        candidates = [{"model": m.model_id, "score": round(s, 4), "display_name": m.display_name, "platforms": list(m.platforms), "supports_tools": m.supports_tools, "supports_vision": m.supports_vision, "context_window": m.context_window, "reasons": r} for s, m, r in top]

        strong = decision.domain in STRONG_DOMAINS or features.has_tools or req["vision"] or decision.complexity == "hard"
        enabled = os.environ.get("SMART_SELECTOR_MODE", "apply").strip().lower() not in {"off", "observe", "shadow"}
        if not top or not strong:
            plan = SelectionPlan(False, "observe" if top else "fallback", None, decision.route, .55 if top else 0., "route alias remains better for this request class" if top else "no eligible candidates", candidates, req)
        else:
            gap = max(0., top[0][0] - (top[1][0] if len(top) > 1 else 0.))
            confidence = min(.93, .62 + min(.18, gap * 3.))
            apply = enabled and confidence >= .58
            plan = SelectionPlan(apply, "apply" if apply else "observe", top[0][1].model_id if apply else None, decision.route, round(confidence, 4), "hard eligibility + deterministic multi-factor ranking", candidates, req)

        with self.lock:
            self.selections += 1
            self.applied += int(plan.apply)
        return plan

    def record_fallback(self) -> None:
        with self.lock:
            self.selector_fallbacks += 1

    def status(self) -> dict[str, Any]:
        with self.lock:
            return {
                "engine": "model-preference-v1",
                "mode": os.environ.get("SMART_SELECTOR_MODE", "apply"),
                "selections": self.selections,
                "applied": self.applied,
                "selector_fallbacks": self.selector_fallbacks,
                "catalog": self.catalog.status(),
                "principles": ["hard-eligibility-before-ranking", "deterministic-multifactor-selector", "backend-health-left-to-freellmapi", "fail-open-to-original-route"],
            }

_SELECTOR: ModelPreferenceSelector | None = None
_SELECTOR_LOCK = threading.Lock()

def get_model_selector() -> ModelPreferenceSelector:
    global _SELECTOR
    if _SELECTOR is None:
        with _SELECTOR_LOCK:
            if _SELECTOR is None:
                _SELECTOR = ModelPreferenceSelector()
    return _SELECTOR
