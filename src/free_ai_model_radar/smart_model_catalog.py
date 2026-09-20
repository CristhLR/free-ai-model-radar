from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_DB = Path(os.environ.get("APPDATA", "")) / "FreeLLMAPI" / "freeapi.db"
BLOCKED_MARKERS = (
    "embed", "embedding", "rerank", "tts", "speech", "transcrib",
    "moderation", "safety", "image-gen", "image_generation",
)
TIER_ORDER = {"Frontier": 0, "Large": 1, "Medium": 2, "Small": 3}


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


def _strip_provider_suffix(value: str) -> str:
    text = (value or "").strip()
    while True:
        previous = text
        text = re.sub(r"\s*\([^()]*\)\s*$", "", text).strip()
        text = re.sub(r"\s+free$", "", text, flags=re.I).strip()
        if text == previous:
            return text


def _normalize_group_key(value: str) -> str:
    return re.sub(r"[\s\-_]+", " ", _strip_provider_suffix(value).lower()).strip()


def _slugify_group_label(value: str) -> str:
    slug = re.sub(r"[^a-z0-9.\s-]", "", (value or "").lower())
    slug = re.sub(r"\s+", "-", slug.strip())
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug or "model"


class FreeLLMModelCatalog:
    def __init__(self, db_path: Path | None = None, cache_ttl: float = 45.0) -> None:
        self.db_path = db_path or DEFAULT_DB
        self.cache_ttl = cache_ttl
        self.lock = threading.RLock()
        self._models: list[ModelInfo] = []
        self._loaded_at = 0.0
        self.last_error: str | None = None

    def _query(self) -> tuple[list[sqlite3.Row], dict[str, Any]]:
        uri = self.db_path.resolve().as_uri() + "?mode=ro"
        con = sqlite3.connect(uri, uri=True, timeout=.25)
        con.row_factory = sqlite3.Row
        try:
            rows = con.execute("""
                SELECT id, platform, model_id, display_name, intelligence_rank,
                       speed_rank, size_label, context_window,
                       supports_vision, supports_tools, endpoint_scope
                FROM models
                WHERE enabled = 1
            """).fetchall()
            row = con.execute(
                "SELECT value FROM settings WHERE key = 'model_unify_overrides'"
            ).fetchone()
            overrides: dict[str, Any] = {}
            if row and row["value"]:
                try:
                    parsed = json.loads(str(row["value"]))
                    if isinstance(parsed, dict):
                        overrides = parsed
                except json.JSONDecodeError:
                    overrides = {}
            return rows, overrides
        finally:
            con.close()

    @staticmethod
    def _token_for_row(row: sqlite3.Row, overrides: dict[str, Any]) -> str:
        member = f"{row['platform']}:{row['model_id']}"
        base = _normalize_group_key(str(row["display_name"] or ""))

        for split in overrides.get("splits", []) or []:
            if not isinstance(split, dict) or str(split.get("member") or "") != member:
                continue
            group_key = str(split.get("groupKey") or "").strip()
            return _normalize_group_key(group_key) if group_key else f"__split__:{member}"

        for merge in overrides.get("merges", []) or []:
            if not isinstance(merge, dict):
                continue
            keys = merge.get("keys") or []
            if not isinstance(keys, list):
                continue
            matched = any(
                str(key) == member or _normalize_group_key(str(key)) == base
                for key in keys
            )
            if matched:
                return _normalize_group_key(str(merge.get("into") or base))
        return base

    @staticmethod
    def _representative(rows: list[sqlite3.Row]) -> sqlite3.Row:
        return min(
            rows,
            key=lambda row: (
                int(row["intelligence_rank"] or 999999),
                len(_strip_provider_suffix(str(row["display_name"] or ""))),
                int(row["id"]),
            ),
        )

    def _build_groups(
        self,
        rows: list[sqlite3.Row],
        overrides: dict[str, Any],
    ) -> list[ModelInfo]:
        groups: dict[str, list[sqlite3.Row]] = {}
        for row in rows:
            model_id = str(row["model_id"] or "").strip()
            label = str(row["display_name"] or "")
            low = (model_id + " " + label).lower()
            if not model_id or any(marker in low for marker in BLOCKED_MARKERS):
                continue
            token = self._token_for_row(row, overrides)
            groups.setdefault(token, []).append(row)

        prepared: list[tuple[str, str, list[sqlite3.Row]]] = []
        for group_key, members in groups.items():
            rep = self._representative(members)
            label = _strip_provider_suffix(str(rep["display_name"] or rep["model_id"]))
            prepared.append((group_key, label, members))

        used: set[str] = set()
        canonical_by_key: dict[str, str] = {}
        for group_key, label, _ in sorted(prepared, key=lambda item: item[0]):
            base = _slugify_group_label(label)
            candidate = base
            n = 2
            while candidate in used:
                candidate = f"{base}-{n}"
                n += 1
            used.add(candidate)
            canonical_by_key[group_key] = candidate

        result: list[ModelInfo] = []
        for group_key, label, members in prepared:
            ranks = [int(row["intelligence_rank"]) for row in members if row["intelligence_rank"]]
            speeds = [int(row["speed_rank"]) for row in members if row["speed_rank"]]
            contexts = [int(row["context_window"] or 0) for row in members]
            best_tier = min(
                (str(row["size_label"] or "") for row in members),
                key=lambda value: TIER_ORDER.get(value, 4),
                default="",
            )
            result.append(ModelInfo(
                model_id=canonical_by_key[group_key],
                display_name=label,
                platforms=tuple(sorted({str(row["platform"]) for row in members})),
                size_label=best_tier,
                intelligence_rank=min(ranks) if ranks else None,
                speed_rank=min(speeds) if speeds else None,
                context_window=max(contexts) if contexts else 0,
                supports_vision=any(bool(row["supports_vision"]) for row in members),
                supports_tools=any(bool(row["supports_tools"]) for row in members),
            ))
        return result

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
            rows, overrides = self._query()
            result = self._build_groups(rows, overrides)
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
            "unified_ids": True,
            "last_error": self.last_error,
        }
