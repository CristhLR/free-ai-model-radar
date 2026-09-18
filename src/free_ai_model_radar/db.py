from __future__ import annotations

import json, sqlite3
from datetime import datetime, timezone
from pathlib import Path
from .domain import CandidateModel

SCHEMA = """
CREATE TABLE IF NOT EXISTS models (
  provider TEXT NOT NULL, model_id TEXT NOT NULL, endpoint TEXT NOT NULL,
  source_url TEXT NOT NULL, free_type TEXT NOT NULL, evidence TEXT NOT NULL,
  status TEXT NOT NULL, metadata_json TEXT NOT NULL DEFAULT '{}',
  first_seen TEXT NOT NULL, last_seen TEXT NOT NULL,
  PRIMARY KEY(provider, model_id)
);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY, ts TEXT NOT NULL, kind TEXT NOT NULL,
  provider TEXT NOT NULL, model_id TEXT NOT NULL, details_json TEXT NOT NULL DEFAULT '{}'
);
"""

def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.executescript(SCHEMA)
    return con

def sync_provider(con: sqlite3.Connection, provider: str, items: list[CandidateModel]) -> dict[str, list[str]]:
    now = datetime.now(timezone.utc).isoformat()
    old = {r[0]: r[1] for r in con.execute(
        "SELECT model_id, metadata_json FROM models WHERE provider=? AND status='active'", (provider,))}
    current = {m.model_id: m for m in items}
    new, changed = [], []
    for mid, m in current.items():
        meta = json.dumps(m.metadata, sort_keys=True, separators=(',', ':'))
        if mid not in old: new.append(mid)
        elif old[mid] != meta: changed.append(mid)
        con.execute("""INSERT INTO models(provider,model_id,endpoint,source_url,free_type,evidence,status,metadata_json,first_seen,last_seen)
        VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(provider,model_id) DO UPDATE SET
        endpoint=excluded.endpoint,source_url=excluded.source_url,free_type=excluded.free_type,evidence=excluded.evidence,
        status='active',metadata_json=excluded.metadata_json,last_seen=excluded.last_seen""",
        (provider,mid,m.endpoint,m.source_url,m.free_type,m.evidence,m.status,meta,now,now))
    removed = sorted(set(old)-set(current))
    for mid in removed:
        con.execute("UPDATE models SET status='removed', last_seen=? WHERE provider=? AND model_id=?", (now,provider,mid))
    for kind, ids in (("NEW",new),("CHANGED",changed),("REMOVED",removed)):
        con.executemany("INSERT INTO events(ts,kind,provider,model_id) VALUES(?,?,?,?)",
                        [(now,kind,provider,x) for x in ids])
    con.commit()
    return {"NEW":sorted(new),"CHANGED":sorted(changed),"REMOVED":removed}
