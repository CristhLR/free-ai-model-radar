from __future__ import annotations

import json
from pathlib import Path

from .config import ROOT

DEFAULT_PATH = ROOT / "config" / "sources.json"

def load_sources(path: Path = DEFAULT_PATH) -> list[dict]:
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, list):
        raise ValueError("sources registry must be a JSON array")
    seen: set[str] = set()
    for row in data:
        sid = row.get("id")
        url = row.get("url")
        if not sid or not url:
            raise ValueError("each source needs id and url")
        if sid in seen:
            raise ValueError(f"duplicate source id: {sid}")
        seen.add(sid)
    return data

def get_source(source_id: str, path: Path = DEFAULT_PATH) -> dict:
    for row in load_sources(path):
        if row["id"] == source_id:
            return row
    raise KeyError(source_id)

def watch_sources(con, source_id: str | None = None) -> list[dict]:
    from .watcher import check_url
    rows = load_sources()
    if source_id is not None:
        rows = [row for row in rows if row["id"] == source_id]
        if not rows:
            raise KeyError(source_id)
    results = []
    for row in rows:
        result = check_url(con, row["id"], row["url"])
        result["kind"] = row.get("kind")
        result["priority"] = row.get("priority")
        results.append(result)
    return results
