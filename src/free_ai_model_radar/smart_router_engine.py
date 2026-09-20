from __future__ import annotations

import hashlib
import json
import math
import os
import re
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .config import ROOT

EMBED_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
NLI_MODEL = "MoritzLaurer/multilingual-MiniLMv2-L6-mnli-xnli"
TELEMETRY_PATH = ROOT / "data" / "smart-router-decisions.jsonl"

CONTINUATIONS = {
    "sigue", "continua", "continúa", "dale", "hazlo", "ya", "si", "sí",
    "ok", "okay", "listo", "sigue con eso", "continua con eso",
}

DOMAIN_PROTOTYPES: dict[str, list[str]] = {
    "quick": [
        "answer a simple short factual question", "give a brief definition",
        "what does this word mean", "dime rápidamente qué significa esto",
        "respuesta corta y sencilla", "convert a small value or explain a basic fact",
    ],
    "coding": [
        "debug this program and fix the code", "implement a software feature",
        "review this repository architecture", "write Python TypeScript Java code",
        "encuentra el bug y corrige el código", "implementa esta función o API",
    ],
    "reasoning": [
        "solve a difficult logic problem step by step", "prove a mathematical result",
        "derive the answer carefully", "resuelve este problema matemático complejo",
        "demuestra por qué esto es cierto", "reason through several interacting constraints",
    ],
    "research": [
        "research a topic using multiple sources and verify claims",
        "compare evidence and check current information",
        "investiga este tema a fondo y verifica fuentes",
        "busca información actual y compara varias fuentes",
        "fact check a claim with evidence", "deep research and source synthesis",
    ],
    "vision": [
        "analyze an image screenshot chart or photograph",
        "inspect what is visible in this picture", "read this screenshot and explain it",
        "analiza esta imagen o captura de pantalla", "describe a diagram from an image",
        "understand visual content and text together",
    ],
    "writing": [
        "rewrite this text with better style", "draft an email or document",
        "improve grammar while preserving the meaning",
        "redacta o mejora este texto", "resume y organiza este contenido",
        "write a clear explanation for an audience",
    ],
    "data_analysis": [
        "analyze a dataset spreadsheet or statistics", "find patterns in numerical data",
        "calculate statistics and interpret the results",
        "analiza estos datos y encuentra patrones", "trabaja con Excel CSV o una tabla",
        "compare metrics and quantify the differences",
    ],
    "troubleshooting": [
        "diagnose why a computer or application is failing",
        "investigate an error and propose a fix",
        "soluciona este problema técnico paso a paso",
        "por qué no funciona este programa o dispositivo",
        "debug a configuration networking or installation issue",
        "find the root cause of an unexpected technical behavior",
    ],
    "planning": [
        "make a detailed plan with constraints and tradeoffs",
        "design a project roadmap or workflow", "choose among options using criteria",
        "haz un plan completo con pasos y prioridades",
        "organiza un proyecto y toma decisiones entre alternativas",
        "build an itinerary or execution strategy",
    ],
    "translation": [
        "translate this text faithfully to another language",
        "traduce este texto al inglés o al español", "translate a sentence",
        "preserve meaning while translating", "convert this passage to another language",
        "give the equivalent phrase in another language",
    ],
    "general": [
        "explain a normal topic clearly", "answer a general knowledge question",
        "have a normal conversation", "explica este tema de forma clara",
        "responde una pregunta general", "help with an everyday non-specialized request",
    ],
}

DIFFICULTY_PROTOTYPES: dict[str, list[str]] = {
    "simple": [
        "simple direct question with an obvious short answer",
        "basic definition or small transformation",
        "pregunta sencilla que requiere poco razonamiento",
        "short translation or formatting task",
    ],
    "moderate": [
        "normal explanation requiring some reasoning",
        "compare a few options and explain tradeoffs",
        "tarea normal con varios pasos pero sin análisis profundo",
        "write or analyze something with moderate detail",
    ],
    "hard": [
        "complex multi-step reasoning with many constraints",
        "deep debugging research architecture or mathematical proof",
        "tarea difícil que requiere análisis profundo y varios pasos",
        "verify competing hypotheses and synthesize evidence",
    ],
}

NLI_DOMAIN_LABELS = {
    "quick": "a simple quick factual request",
    "coding": "software engineering or programming",
    "reasoning": "mathematical or logical reasoning",
    "research": "research and fact verification",
    "vision": "image or multimodal analysis",
    "writing": "writing rewriting or summarization",
    "data_analysis": "data analysis statistics or spreadsheets",
    "troubleshooting": "technical troubleshooting or debugging",
    "planning": "planning decision support or project design",
    "translation": "translation between languages",
    "general": "general conversation or explanation",
}
NLI_DIFFICULTY_LABELS = {
    "simple": "simple and low reasoning",
    "moderate": "moderately complex and requiring normal reasoning",
    "hard": "complex and requiring deep multi-step reasoning",
}

@dataclass
class Features:
    last_user: str
    routing_text: str
    total_chars: int
    estimated_tokens: int
    message_count: int
    has_tools: bool
    tool_count: int
    has_images: bool
    has_files: bool
    question_count: int
    code_signal: float
    math_signal: float
    research_signal: float
    verify_signal: float
    fusion_signal: float
    continuation: bool

@dataclass
class Decision:
    route: str
    domain: str
    complexity: str
    difficulty_score: float
    confidence: float
    task_type: str
    reason: str
    semantic_ready: bool
    nli_used: bool
    semantic_domain_score: float = 0.0
    semantic_margin: float = 0.0
    prompt_hash: str = ""

    @property
    def header_value(self) -> str:
        return f"{self.reason}:{self.route}"

    def public_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["header_value"] = self.header_value
        return data
def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        if item.get("type") in {"text", "input_text"}:
            parts.append(str(item.get("text") or item.get("content") or ""))
    return " ".join(parts)

def _contains_media(content: Any) -> tuple[bool, bool]:
    if not isinstance(content, list):
        return False, False
    image = False
    file_ = False
    for item in content:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("type") or "").lower()
        image |= kind in {"image", "image_url", "input_image"}
        file_ |= kind in {"file", "input_file", "document"}
    return image, file_

def _score_patterns(text: str, patterns: list[str], cap: float = 1.0) -> float:
    hits = sum(1 for pattern in patterns if re.search(pattern, text, re.I | re.M))
    return min(cap, hits / max(1.0, len(patterns) * 0.42))

def extract_features(body: dict[str, Any]) -> Features:
    messages = body.get("messages") or []
    user_texts: list[str] = []
    total_chars = 0
    has_images = False
    has_files = False
    for msg in messages:
        content = msg.get("content", "") if isinstance(msg, dict) else ""
        text = _content_text(content)
        total_chars += len(text)
        img, fil = _contains_media(content)
        has_images |= img
        has_files |= fil
        if isinstance(msg, dict) and msg.get("role") == "user" and text.strip():
            user_texts.append(text.strip())
    last = user_texts[-1] if user_texts else ""
    normalized = re.sub(r"\s+", " ", last.lower()).strip(" .,!¡¿?")
    continuation = normalized in CONTINUATIONS or (len(last) < 32 and bool(user_texts[:-1]))
    selected = user_texts[-3:] if continuation else user_texts[-2:]
    routing_text = "\n".join(selected)[-6000:]
    code_patterns = [
        r"\x60\x60\x60", r"\b(def|class|function|async|await|import|SELECT|INSERT|UPDATE)\b",
        r"\b(traceback|exception|stack trace|compiler|runtime error|bug)\b",
        r"\.(py|js|ts|tsx|jsx|java|cpp|cs|go|rs|sql|kt|swift)\b",
        r"\b(api|endpoint|repository|repo|git|docker|kubernetes|regex)\b",
        r"\b(python|javascript|typescript|backend|frontend)\b",
        r"\b(refactor(?:iza|izar)?|implementa|corrige|debug|fix|unit tests?|pruebas unitarias)\b",
    ]
    math_patterns = [
        r"\b(prove|proof|derive|theorem|integral|derivative|matrix|probability)\b",
        r"\b(demuestra|prueba|deriva|integral|derivada|matriz|probabilidad)\b",
        r"\b(solve|resolver|ecuaci[oó]n|algoritmo|complejidad)\b",
        r"[$\\][^\n]{2,80}[$\\]", r"\bO\([^)]*\)",
    ]
    research_patterns = [
        r"\b(research|investiga|investigar|busca|buscar|sources?|fuentes?)\b",
        r"\b(latest|current|actual|hoy|today|recent|reciente)\b",
        r"\b(compare|compara|benchmark|evidence|evidencia|fact.?check)\b",
        r"\b(verify|verifica|confirma|comprueba|revisa bien)\b",
    ]
    verify_patterns = [
        r"\b(verify|verifica|comprueba|confirma|double.?check|cross.?check)\b",
        r"\b(aseg[uú]rate|revisa bien|contrasta|segunda opini[oó]n)\b",
    ]
    fusion_patterns = [
        r"\b(consenso|consensus|sintetiza varias|multiple independent)\b",
        r"\b(compara varias soluciones|varios modelos|panel de modelos)\b",
    ]
    return Features(
        last_user=last,
        routing_text=routing_text,
        total_chars=total_chars,
        estimated_tokens=max(1, total_chars // 4),
        message_count=len(messages),
        has_tools=bool(body.get("tools")),
        tool_count=len(body.get("tools") or []),
        has_images=has_images,
        has_files=has_files,
        question_count=routing_text.count("?") + routing_text.count("？"),
        code_signal=_score_patterns(routing_text, code_patterns),
        math_signal=_score_patterns(routing_text, math_patterns),
        research_signal=_score_patterns(routing_text, research_patterns),
        verify_signal=_score_patterns(routing_text, verify_patterns),
        fusion_signal=_score_patterns(routing_text, fusion_patterns),
        continuation=continuation,
    )
class LocalSemanticModels:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.embedding_model: Any = None
        self.nli: Any = None
        self.domain_vectors: dict[str, Any] = {}
        self.difficulty_vectors: dict[str, Any] = {}
        self.loading = False
        self.loaded_at: float | None = None
        self.last_error: str | None = None

    @property
    def semantic_ready(self) -> bool:
        return self.embedding_model is not None and bool(self.domain_vectors)

    @property
    def nli_ready(self) -> bool:
        return self.nli is not None

    def preload_async(self) -> None:
        with self.lock:
            if self.loading or (self.semantic_ready and self.nli_ready):
                return
            self.loading = True
        threading.Thread(target=self._load, daemon=True, name="smart-router-model-loader").start()

    def preload_sync(self) -> None:
        with self.lock:
            if self.semantic_ready and self.nli_ready:
                return
            self.loading = True
        self._load()

    def _load(self) -> None:
        try:
            os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
            from sentence_transformers import SentenceTransformer
            from transformers import pipeline
            import numpy as np
            import torch

            torch.set_num_threads(max(1, min(6, (os.cpu_count() or 4) - 2)))
            model = SentenceTransformer(EMBED_MODEL, device="cpu")
            domain_vectors = self._centroids(model, DOMAIN_PROTOTYPES, np)
            difficulty_vectors = self._centroids(model, DIFFICULTY_PROTOTYPES, np)
            nli = pipeline(
                "zero-shot-classification",
                model=NLI_MODEL,
                device=-1,
            )
            with self.lock:
                self.embedding_model = model
                self.domain_vectors = domain_vectors
                self.difficulty_vectors = difficulty_vectors
                self.nli = nli
                self.loaded_at = time.time()
                self.last_error = None
        except Exception as exc:
            with self.lock:
                self.last_error = f"{type(exc).__name__}: {exc}"[:300]
        finally:
            with self.lock:
                self.loading = False

    @staticmethod
    def _centroids(model: Any, groups: dict[str, list[str]], np: Any) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for name, examples in groups.items():
            vectors = model.encode(examples, normalize_embeddings=True, show_progress_bar=False)
            centroid = np.asarray(vectors, dtype="float32").mean(axis=0)
            norm = float(np.linalg.norm(centroid)) or 1.0
            out[name] = centroid / norm
        return out
    def semantic_scores(self, text: str, kind: str = "domain") -> dict[str, float]:
        if not text or not self.semantic_ready:
            return {}
        try:
            import numpy as np
            with self.lock:
                model = self.embedding_model
                vectors = self.domain_vectors if kind == "domain" else self.difficulty_vectors
            query = model.encode([text[:6000]], normalize_embeddings=True, show_progress_bar=False)[0]
            return {name: float(np.dot(query, vec)) for name, vec in vectors.items()}
        except Exception as exc:
            with self.lock:
                self.last_error = f"{type(exc).__name__}: {exc}"[:300]
            return {}

    def nli_scores(self, text: str, labels: dict[str, str], template: str) -> dict[str, float]:
        if not text or not self.nli_ready:
            return {}
        try:
            keys = list(labels)
            human_labels = [labels[k] for k in keys]
            with self.lock:
                classifier = self.nli
            result = classifier(
                text[:2400],
                candidate_labels=human_labels,
                hypothesis_template=template,
                multi_label=False,
            )
            reverse = {v: k for k, v in labels.items()}
            return {
                reverse[label]: float(score)
                for label, score in zip(result["labels"], result["scores"])
                if label in reverse
            }
        except Exception as exc:
            with self.lock:
                self.last_error = f"{type(exc).__name__}: {exc}"[:300]
            return {}

    def status(self) -> dict[str, Any]:
        with self.lock:
            return {
                "semantic_ready": self.semantic_ready,
                "nli_ready": self.nli_ready,
                "loading": self.loading,
                "embedding_model": EMBED_MODEL,
                "nli_model": NLI_MODEL,
                "loaded_at": self.loaded_at,
                "last_error": self.last_error,
            }


class SmartRouterEngine:
    def __init__(self, preload: bool = True) -> None:
        self.models = LocalSemanticModels()
        if preload:
            self.models.preload_async()
        self.lock = threading.RLock()
        self.counts: dict[str, int] = {}
        self.total_decisions = 0

    @staticmethod
    def _rank(scores: dict[str, float]) -> tuple[str, float, float]:
        if not scores:
            return "general", 0.0, 0.0
        ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        top_name, top_score = ranked[0]
        second = ranked[1][1] if len(ranked) > 1 else 0.0
        return top_name, top_score, top_score - second
    @staticmethod
    def _rule_domain(features: Features) -> tuple[str | None, float]:
        text = features.routing_text.lower()
        if features.has_images:
            return "vision", 1.0
        if features.code_signal >= 0.55:
            return "coding", min(0.98, 0.65 + features.code_signal * 0.3)
        if features.math_signal >= 0.65:
            return "reasoning", min(0.96, 0.62 + features.math_signal * 0.3)
        if features.research_signal >= 0.7:
            return "research", min(0.95, 0.6 + features.research_signal * 0.3)
        if re.search(r"\b(csv|excel|xlsx|spreadsheet|dataset|dataframe|estad[ií]stic|statistics)\b", text):
            return "data_analysis", 0.88
        if re.search(r"\b(error|fall[ao]|no funciona|problema t[eé]cnico|configuraci[oó]n|driver|network|red)\b", text):
            return "troubleshooting", 0.78
        if re.search(r"\b(traduce|translate|translation|traducir)\b", text):
            return "translation", 0.92
        if re.search(r"\b(reescribe|rewrite|redacta|draft|corrige la redacci[oó]n|resume este texto)\b", text):
            return "writing", 0.82
        if re.search(r"\b(plan|planifica|roadmap|itinerario|estrategia|organiza el proyecto)\b", text):
            return "planning", 0.76
        if re.search(
            r"\b(expl[ií]came|explica(?:me)?)\s+qu[eé]\s+es\b"
            r"|\bexplain\s+what\b|\bteach me (?:about|how)\b",
            text,
        ):
            return "general", 0.93
        if len(features.last_user) < 140 and not features.has_tools:
            return "quick", 0.52
        return None, 0.0

    def _choose_domain(self, features: Features) -> tuple[str, float, float, float, bool]:
        rule_domain, rule_conf = self._rule_domain(features)
        semantic = self.models.semantic_scores(features.routing_text, "domain")
        sem_domain, sem_score, sem_margin = self._rank(semantic)
        nli_used = False

        if rule_domain and rule_conf >= 0.9:
            return rule_domain, rule_conf, sem_score, sem_margin, False

        combined = dict(semantic)
        if rule_domain:
            combined[rule_domain] = combined.get(rule_domain, 0.0) + 0.14 * rule_conf
        domain, score, margin = self._rank(combined)

        ambiguous = not combined or score < 0.43 or margin < 0.035
        if ambiguous and self.models.nli_ready:
            nli = self.models.nli_scores(
                features.routing_text,
                NLI_DOMAIN_LABELS,
                "This request is about {}.",
            )
            nli_used = bool(nli)
            if nli:
                all_keys = set(combined) | set(nli)
                merged = {
                    key: 0.42 * combined.get(key, 0.0) + 0.58 * nli.get(key, 0.0)
                    for key in all_keys
                }
                domain, score, margin = self._rank(merged)

        if not combined and not nli_used:
            domain = rule_domain or "general"
            score = rule_conf or 0.35
            margin = 0.0
        confidence = max(0.0, min(1.0, 0.55 + 0.35 * margin + 0.15 * max(0.0, score)))
        return domain, confidence, sem_score, sem_margin, nli_used
    def _difficulty(self, features: Features, domain: str) -> tuple[float, str, bool]:
        score = 0.18
        if len(features.routing_text) > 500:
            score += 0.08
        if len(features.routing_text) > 1500:
            score += 0.12
        if features.estimated_tokens > 6000:
            score += 0.08
        if features.estimated_tokens > 20000:
            score += 0.10
        if features.has_tools:
            score += 0.08
        if features.tool_count >= 4:
            score += 0.05
        if features.question_count >= 3:
            score += 0.08
        score += 0.12 * features.code_signal
        score += 0.16 * features.math_signal
        score += 0.14 * features.research_signal
        score += 0.10 * features.verify_signal

        domain_adjust = {
            "quick": -0.12,
            "translation": -0.08,
            "general": -0.02,
            "writing": 0.00,
            "planning": 0.08,
            "data_analysis": 0.12,
            "troubleshooting": 0.12,
            "coding": 0.14,
            "research": 0.16,
            "vision": 0.10,
            "reasoning": 0.20,
        }
        score += domain_adjust.get(domain, 0.0)

        semantic = self.models.semantic_scores(features.routing_text, "difficulty")
        sem_name, sem_score, sem_margin = self._rank(semantic)
        semantic_map = {"simple": 0.18, "moderate": 0.52, "hard": 0.86}
        if semantic:
            semantic_target = semantic_map.get(sem_name, 0.5)
            semantic_weight = min(0.28, 0.16 + max(0.0, sem_margin))
            score = (1.0 - semantic_weight) * score + semantic_weight * semantic_target

        nli_used = False
        if self.models.nli_ready and (0.34 <= score <= 0.76 or sem_margin < 0.035):
            nli = self.models.nli_scores(
                features.routing_text,
                NLI_DIFFICULTY_LABELS,
                "This request is {}.",
            )
            if nli:
                nli_used = True
                weighted = sum(semantic_map[k] * v for k, v in nli.items())
                score = 0.58 * score + 0.42 * weighted

        score = max(0.0, min(1.0, score))
        if score < 0.34:
            level = "simple"
        elif score < 0.68:
            level = "moderate"
        else:
            level = "hard"
        return score, level, nli_used

    @staticmethod
    def _route_policy(features: Features, domain: str, difficulty: float) -> tuple[str, str]:
        if features.fusion_signal >= 0.45 and not features.has_tools:
            return "fusion:synthesize", "explicit-fusion"
        if features.verify_signal >= 0.45 and difficulty >= 0.48 and not features.has_tools:
            return "fusion:best_of", "explicit-verify"

        strong_domains = {"coding", "reasoning", "research", "vision", "data_analysis", "troubleshooting"}
        if domain in strong_domains:
            return "auto:smart", f"{domain}-smart"
        if difficulty >= 0.68:
            return "auto:smart", "hard"
        if features.has_tools:
            if domain in strong_domains or difficulty >= 0.52:
                return "auto:smart", "tools-smart"
            return "auto:balanced", "tools-balanced"
        if domain in strong_domains and difficulty >= 0.42:
            return "auto:smart", "domain-smart"
        if difficulty < 0.34 and domain in {"quick", "translation", "general", "writing"}:
            return "auto:fast", "simple-fast"
        return "auto:balanced", "balanced"

    def decide(self, body: dict[str, Any]) -> Decision:
        features = extract_features(body)
        domain, confidence, sem_score, sem_margin, nli_domain = self._choose_domain(features)
        difficulty, complexity, nli_difficulty = self._difficulty(features, domain)
        route, policy_reason = self._route_policy(features, domain, difficulty)
        task_type = "code" if domain in {"coding", "troubleshooting"} else "chat"
        if domain in {"vision", "data_analysis", "research", "reasoning"}:
            task_type = "auto"

        source = "hybrid" if self.models.semantic_ready else "rules"
        nli_used = nli_domain or nli_difficulty
        if nli_used:
            source += "-nli"
        prompt_hash = hashlib.sha256(features.routing_text.encode("utf-8")).hexdigest()[:16]
        decision = Decision(
            route=route,
            domain=domain,
            complexity=complexity,
            difficulty_score=round(difficulty, 4),
            confidence=round(confidence, 4),
            task_type=task_type,
            reason=f"{source}-{domain}-{policy_reason}",
            semantic_ready=self.models.semantic_ready,
            nli_used=nli_used,
            semantic_domain_score=round(sem_score, 4),
            semantic_margin=round(sem_margin, 4),
            prompt_hash=prompt_hash,
        )
        with self.lock:
            self.total_decisions += 1
            key = f"{domain}:{route}"
            self.counts[key] = self.counts.get(key, 0) + 1
        return decision

    def record_result(
        self,
        decision: Decision,
        *,
        status: int,
        latency_ms: float,
        routed_via: str | None = None,
        fallback_attempts: str | None = None,
        cache: str | None = None,
        compression: str | None = None,
        selected_model: str | None = None,
        selector_mode: str | None = None,
        selector_confidence: float | None = None,
        selector_fallback: bool = False,
        candidate_models: list[str] | None = None,
    ) -> None:
        event = {
            "ts": int(time.time()),
            "prompt_hash": decision.prompt_hash,
            "domain": decision.domain,
            "complexity": decision.complexity,
            "difficulty_score": decision.difficulty_score,
            "confidence": decision.confidence,
            "route": decision.route,
            "task_type": decision.task_type,
            "semantic_ready": decision.semantic_ready,
            "nli_used": decision.nli_used,
            "status": status,
            "latency_ms": round(latency_ms, 1),
            "routed_via": routed_via,
            "fallback_attempts": fallback_attempts,
            "cache": cache,
            "compression": compression,
            "selected_model": selected_model,
            "selector_mode": selector_mode,
            "selector_confidence": selector_confidence,
            "selector_fallback": selector_fallback,
            "candidate_models": (candidate_models or [])[:8],
        }
        try:
            TELEMETRY_PATH.parent.mkdir(parents=True, exist_ok=True)
            with TELEMETRY_PATH.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
        except OSError:
            pass

    def status(self) -> dict[str, Any]:
        with self.lock:
            counts = dict(sorted(self.counts.items()))
            total = self.total_decisions
        return {
            "engine": "hybrid-semantic-v1",
            "total_decisions": total,
            "decisions": counts,
            "models": self.models.status(),
            "telemetry": str(TELEMETRY_PATH),
        }


_ENGINE: SmartRouterEngine | None = None
_ENGINE_LOCK = threading.Lock()


def get_router_engine() -> SmartRouterEngine:
    global _ENGINE
    if _ENGINE is None:
        with _ENGINE_LOCK:
            if _ENGINE is None:
                _ENGINE = SmartRouterEngine()
    return _ENGINE
