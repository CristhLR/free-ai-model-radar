from __future__ import annotations

import json, sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .config import ROOT
from .scheduler import is_due

DEFAULT_PATH = ROOT / "config" / "sources.json"

def load_sources(path: Path = DEFAULT_PATH) -> list[dict]:
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, list):
        raise ValueError("sources registry must be a JSON array")
    seen: set[str] = set()
    for row in data:
        sid, url = row.get("id"), row.get("url")
        if not sid or not url:
            raise ValueError("each source needs id and url")
        if sid in seen:
            raise ValueError(f"duplicate source id: {sid}")
        seen.add(sid)
        if row.get("base_interval_hours", 1) <= 0:
            raise ValueError(f"invalid cadence for {sid}")
    return data

def get_source(source_id: str, path: Path = DEFAULT_PATH) -> dict:
    for row in load_sources(path):
        if row["id"] == source_id:
            return row
    raise KeyError(source_id)

def schedule_status(con) -> list[dict]:
    checks = {
        row[0]: row[1:] for row in con.execute(
            """SELECT source_id,next_check_at,last_checked,last_changed,stable_runs,
            consecutive_failures,check_interval_hours,volatility_score,error FROM source_checks"""
        )
    }
    out = []
    for source in load_sources():
        state = checks.get(source["id"])
        next_at = state[0] if state else None
        out.append({
            "id": source["id"], "provider": source.get("provider"),
            "kind": source.get("kind"), "priority": source.get("priority"),
            "due": is_due(next_at), "next_check_at": next_at,
            "last_checked": state[1] if state else None,
            "last_changed": state[2] if state else None,
            "stable_runs": state[3] if state else 0,
            "failures": state[4] if state else 0,
            "interval_hours": state[5] if state else None,
            "volatility": state[6] if state else 0,
            "error": state[7] if state else None,
            "expected_change_at": source.get("expected_change_at"),
        })
    return out

def due_sources(con) -> list[dict]:
    status = {row["id"]: row for row in schedule_status(con)}
    return [source for source in load_sources() if status[source["id"]]["due"]]

def watch_sources(con, source_id: str | None = None, *, force: bool = False) -> list[dict]:
    from .watcher import check_source

    if source_id and source_id != "all":
        rows = [get_source(source_id)]
    elif source_id == "all" or force:
        rows = load_sources()
    else:
        rows = due_sources(con)

    if not rows:
        return []

    db_path = con.execute("PRAGMA database_list").fetchone()[2]

    def run(source: dict) -> dict:
        if len(rows) == 1 or not db_path:
            result = check_source(con, source)
        else:
            worker = sqlite3.connect(db_path, timeout=30)
            worker.execute("PRAGMA busy_timeout=30000")
            try:
                result = check_source(worker, source)
            finally:
                worker.close()
        result["kind"] = source.get("kind")
        result["provider"] = source.get("provider")
        result["priority"] = source.get("priority")
        return result

    if len(rows) == 1 or not db_path:
        return [run(source) for source in rows]

    workers = min(6, len(rows))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(run, rows))
