from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

ENDPOINT = "https://api.typesafe.ai/v1/systemone"
MODEL = "jev-latest"
DEFAULT_ENV_PATH = Path.home() / ".dsh" / ".env"

DOMAIN_CRITERIA = {
    "quick": "A simple short factual request or brief definition.",
    "coding": "Software engineering, programming, debugging, implementation, or tests.",
    "reasoning": "Mathematical, logical, proof, derivation, or deep reasoning.",
    "research": "Research, current information, source comparison, or fact verification.",
    "writing": "Writing, rewriting, summarization, drafting, or style improvement.",
    "data_analysis": "Datasets, statistics, spreadsheets, metrics, or quantitative analysis.",
    "troubleshooting": "Diagnosing technical failures, configuration, networking, or installation problems.",
    "planning": "Planning, roadmaps, strategies, priorities, or decision support.",
    "translation": "Translation between languages.",
    "general": "General conversation or explanation that does not fit another category.",
}
COMPLEXITY_CRITERIA = {
    "simple": "Low reasoning effort, direct answer, definition, or small transformation.",
    "moderate": "Several steps or normal analysis, but not deep multi-step reasoning.",
    "hard": "Deep multi-step reasoning, difficult debugging, proof, research, or many constraints.",
}


@dataclass(frozen=True)
class JevJudgment:
    domain: str
    domain_confidence: float
    complexity: str
    complexity_confidence: float
    model: str
    latency_ms: float
    cached: bool = False

    def public_dict(self) -> dict[str, Any]:
        return asdict(self)


class JevJudge:
    def __init__(
        self,
        *,
        timeout: float = 1.4,
        env_path: Path | None = None,
        cache_ttl: float = 300.0,
    ) -> None:
        self.timeout = timeout
        self.env_path = env_path or DEFAULT_ENV_PATH
        self.cache_ttl = cache_ttl
        self.lock = threading.RLock()
        self._cache: dict[str, tuple[float, JevJudgment]] = {}
        self.attempts = 0
        self.successes = 0
        self.failures = 0
        self.cache_hits = 0
        self.failure_streak = 0
        self.disabled_until = 0.0
        self.total_latency_ms = 0.0
        self.last_error: str | None = None
        self.last_model: str | None = None

    @property
    def mode(self) -> str:
        return os.environ.get("SMART_JEV_MODE", "ambiguity").strip().lower()

    def _load_key(self) -> str | None:
        value = os.environ.get("TYPESAFE_API_KEY", "").strip()
        if value:
            return value
        try:
            for line in self.env_path.read_text(encoding="utf-8").splitlines():
                if not line.startswith("TYPESAFE_API_KEY="):
                    continue
                value = line.split("=", 1)[1].strip()
                return value or None
        except OSError:
            return None
        return None

    @property
    def enabled(self) -> bool:
        if self.mode in {"off", "disabled", "false", "0"}:
            return False
        return bool(self._load_key())

    @staticmethod
    def _cache_key(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()[:24]
    def _cached(self, text: str) -> JevJudgment | None:
        key = self._cache_key(text)
        now = time.monotonic()
        with self.lock:
            item = self._cache.get(key)
            if not item or now - item[0] > self.cache_ttl:
                if item:
                    self._cache.pop(key, None)
                return None
            self.cache_hits += 1
            value = item[1]
        return JevJudgment(**{**asdict(value), "cached": True})

    def _remember(self, text: str, judgment: JevJudgment) -> None:
        key = self._cache_key(text)
        with self.lock:
            if len(self._cache) >= 128:
                oldest = min(self._cache.items(), key=lambda item: item[1][0])[0]
                self._cache.pop(oldest, None)
            self._cache[key] = (time.monotonic(), judgment)

    @staticmethod
    def _payload(text: str) -> dict[str, Any]:
        return {
            "model": MODEL,
            "state": {"request": text[:3000]},
            "questions": {
                "domain": {
                    "type": "choice",
                    "instructions": "Choose the primary task type for the user's request.",
                    "criteria": DOMAIN_CRITERIA,
                },
                "complexity": {
                    "type": "choice",
                    "instructions": "Choose the reasoning effort needed to answer the request well.",
                    "criteria": COMPLEXITY_CRITERIA,
                },
            },
        }

    def _post(self, payload: dict[str, Any], api_key: str) -> dict[str, Any]:
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        request = urllib.request.Request(
            ENDPOINT,
            data=raw,
            method="POST",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return json.loads(response.read())

    @staticmethod
    def _choice(
        data: dict[str, Any],
        question_id: str,
        allowed: set[str],
    ) -> tuple[str, float] | None:
        answer = (data.get("answers") or {}).get(question_id)
        if not isinstance(answer, dict) or answer.get("type") != "choice":
            return None
        choice = str(answer.get("choice") or "")
        if choice not in allowed:
            return None
        try:
            confidence = float(answer.get("confidence") or 0.0)
        except (TypeError, ValueError):
            confidence = 0.0
        return choice, max(0.0, min(1.0, confidence))

    def judge(self, text: str) -> JevJudgment | None:
        text = (text or "").strip()
        if not text or not self.enabled:
            return None
        cached = self._cached(text)
        if cached:
            return cached
        if time.monotonic() < self.disabled_until:
            return None
        api_key = self._load_key()
        if not api_key:
            return None

        started = time.perf_counter()
        with self.lock:
            self.attempts += 1
        try:
            data = self._post(self._payload(text), api_key)
            domain = self._choice(data, "domain", set(DOMAIN_CRITERIA))
            complexity = self._choice(data, "complexity", set(COMPLEXITY_CRITERIA))
            if not domain or not complexity:
                raise ValueError("invalid Jev answer shape")
            latency_ms = (time.perf_counter() - started) * 1000
            judgment = JevJudgment(
                domain=domain[0],
                domain_confidence=domain[1],
                complexity=complexity[0],
                complexity_confidence=complexity[1],
                model=str(data.get("model") or MODEL),
                latency_ms=round(latency_ms, 1),
            )
            self._remember(text, judgment)
            with self.lock:
                self.successes += 1
                self.failure_streak = 0
                self.total_latency_ms += latency_ms
                self.last_error = None
                self.last_model = judgment.model
            return judgment
        except Exception as exc:
            if isinstance(exc, urllib.error.HTTPError):
                error = f"HTTP {exc.code}"
            else:
                error = f"{type(exc).__name__}: {exc}"
            with self.lock:
                self.failures += 1
                self.failure_streak += 1
                self.last_error = error[:200]
                if self.failure_streak >= 2:
                    self.disabled_until = time.monotonic() + 60.0
            return None

    def status(self) -> dict[str, Any]:
        with self.lock:
            avg = self.total_latency_ms / self.successes if self.successes else 0.0
            remaining = max(0.0, self.disabled_until - time.monotonic())
            return {
                "enabled": self.enabled,
                "mode": self.mode,
                "endpoint": ENDPOINT,
                "model": MODEL,
                "timeout_ms": int(self.timeout * 1000),
                "attempts": self.attempts,
                "successes": self.successes,
                "failures": self.failures,
                "cache_hits": self.cache_hits,
                "failure_streak": self.failure_streak,
                "cooldown_remaining_sec": round(remaining, 1),
                "avg_latency_ms": round(avg, 1),
                "last_model": self.last_model,
                "last_error": self.last_error,
            }
