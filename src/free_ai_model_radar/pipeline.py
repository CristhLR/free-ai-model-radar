from __future__ import annotations

from .config import DB_PATH, FREE_ONLY
from .db import connect, sync_provider
from .sources.openrouter import OpenRouterSource

SOURCES = {"openrouter": OpenRouterSource}

def scan(source_name: str) -> dict:
    if not FREE_ONLY:
        raise RuntimeError("MVP requires FREE_ONLY=true")
    try:
        source_cls = SOURCES[source_name]
    except KeyError as exc:
        raise ValueError(f"Unknown source: {source_name}") from exc
    source = source_cls()
    items = source.fetch()
    with connect(DB_PATH) as con:
        diff = sync_provider(con, source.name, items)
    return {"source": source.name, "active": len(items), "diff": diff}
