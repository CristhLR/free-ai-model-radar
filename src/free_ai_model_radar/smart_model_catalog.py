from __future__ import annotations

import os
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path

DEFAULT_DB = Path(os.environ.get("APPDATA", "")) / "FreeLLMAPI" / "freeapi.db"
BLOCKED_MARKERS = (
    "embed", "embedding", "rerank", "tts", "speech", "transcrib",
    "moderation", "safety", "image-gen", "image_generation",
)

@dataclass(frozen=True)
class ModelInfo:
    model_id: str
    display_name: str
    platforms: tuple[str, ...]
    size_label: str
    intelligence_rank: int | None
    speed_rank: int | None
    context_window: int
    supports_vision: bool
    supports_tools: bool

class FreeLLMModelCatalog:
    def __init__(self, db_path: Path | None = None, cache_ttl: float = 45.0) -> None:
        self.db_path = db_path or DEFAULT_DB
        self.cache_ttl = cache_ttl
        self.lock = threading.RLock()
        self._models: list[ModelInfo] = []
        self._loaded_at = 0.0
        self.last_error: str | None = None

    def _query(self) -> list[sqlite3.Row]:
        uri = self.db_path.resolve().as_uri() + "?mode=ro"
        con = sqlite3.connect(uri, uri=True, timeout=.25)
        con.row_factory = sqlite3.Row
        try:
            return con.execute("""
                SELECT platform, model_id, display_name, intelligence_rank,
                       speed_rank, size_label, context_window,
                       supports_vision, supports_tools
                FROM models WHERE enabled = 1
            """).fetchall()
        finally:
            con.close()

    def models(self) -> list[ModelInfo]:
        now = time.monotonic()
        with self.lock:
            if self._models and now - self._loaded_at < self.cache_ttl:
                return list(self._models)
        if not self.db_path.exists():
            with self.lock:
                self.last_error = f"catalog db not found: {self.db_path}"
            return []
        try:
            grouped: dict[str, list[sqlite3.Row]] = {}
            for row in self._query():
                model_id = str(row["model_id"] or "").strip()
                text = (model_id + " " + str(row["display_name"] or "")).lower()
                if not model_id or any(x in text for x in BLOCKED_MARKERS):
                    continue
                grouped.setdefault(model_id, []).append(row)
            tier = {"Frontier": 0, "Large": 1, "Medium": 2, "Small": 3}
            result: list[ModelInfo] = []
            for model_id, rows in grouped.items():
                best = min(rows, key=lambda r: (
                    tier.get(str(r["size_label"]), 4),
                    int(r["intelligence_rank"] or 999),
                ))
                ranks = [int(r["intelligence_rank"]) for r in rows if r["intelligence_rank"]]
                speeds = [int(r["speed_rank"]) for r in rows if r["speed_rank"]]
                contexts = [int(r["context_window"] or 0) for r in rows]
                result.append(ModelInfo(
                    model_id=model_id,
                    display_name=str(best["display_name"] or model_id),
                    platforms=tuple(sorted({str(r["platform"]) for r in rows})),
                    size_label=str(best["size_label"] or ""),
                    intelligence_rank=min(ranks) if ranks else None,
                    speed_rank=min(speeds) if speeds else None,
                    context_window=max(contexts) if contexts else 0,
                    supports_vision=any(bool(r["supports_vision"]) for r in rows),
                    supports_tools=any(bool(r["supports_tools"]) for r in rows),
                ))
            with self.lock:
                self._models = result
                self._loaded_at = now
                self.last_error = None
            return list(result)
        except Exception as exc:
            with self.lock:
                self.last_error = f"{type(exc).__name__}: {exc}"[:300]
                return list(self._models)

    def status(self) -> dict[str, object]:
        models = self.models()
        return {
            "source": str(self.db_path),
            "models": len(models),
            "cache_ttl_sec": self.cache_ttl,
            "last_error": self.last_error,
        }
