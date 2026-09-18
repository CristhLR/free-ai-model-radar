from __future__ import annotations

import hashlib, re
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .config import USER_AGENT
from .scheduler import next_check_time

class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._hidden = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in {"script", "style", "noscript", "svg"}:
            self._hidden += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg"} and self._hidden:
            self._hidden -= 1

    def handle_data(self, data: str) -> None:
        if not self._hidden:
            self.parts.append(data)

def _fingerprint(body: bytes, content_type: str | None) -> str:
    if content_type and "text/html" in content_type.lower():
        parser = _VisibleTextParser()
        parser.feed(body.decode("utf-8", errors="replace"))
        normalized = re.sub(r"\s+", " ", " ".join(parser.parts)).strip()
        body = normalized.encode("utf-8")
    return hashlib.sha256(body).hexdigest()

def _previous(con, source_id: str):
    return con.execute(
        """SELECT etag,last_modified,content_hash,last_changed,stable_runs,
        consecutive_failures,volatility_score FROM source_checks WHERE source_id=?""",
        (source_id,),
    ).fetchone()

def _store(con, source: dict, *, etag, modified, digest, status, error,
           changed: bool, stable_runs: int, failures: int, volatility: float,
           now: datetime) -> dict:
    planned, interval = next_check_time(
        source, failures if error else stable_runs, changed=changed, failed=bool(error), now=now
    )
    previous_changed = con.execute(
        "SELECT last_changed FROM source_checks WHERE source_id=?", (source["id"],)
    ).fetchone()
    last_changed = now.isoformat() if changed else (previous_changed[0] if previous_changed else None)
    con.execute(
        """INSERT INTO source_checks(
        source_id,url,etag,last_modified,content_hash,last_checked,last_changed,status_code,error,
        next_check_at,expected_change_at,stable_runs,consecutive_failures,check_interval_hours,volatility_score)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(source_id) DO UPDATE SET
        url=excluded.url,etag=excluded.etag,last_modified=excluded.last_modified,
        content_hash=excluded.content_hash,last_checked=excluded.last_checked,last_changed=excluded.last_changed,
        status_code=excluded.status_code,error=excluded.error,next_check_at=excluded.next_check_at,
        expected_change_at=excluded.expected_change_at,stable_runs=excluded.stable_runs,
        consecutive_failures=excluded.consecutive_failures,check_interval_hours=excluded.check_interval_hours,
        volatility_score=excluded.volatility_score""",
        (source["id"],source["url"],etag,modified,digest,now.isoformat(),last_changed,status,error,
         planned.isoformat(),source.get("expected_change_at"),stable_runs,failures,interval,volatility),
    )
    con.commit()
    return {
        "source": source["id"], "status": status, "changed": changed,
        "next_check_at": planned.isoformat(), "interval_hours": round(interval, 2),
        "stable_runs": stable_runs, "failures": failures,
    }

def check_source(con, source: dict) -> dict:
    row = _previous(con, source["id"])
    headers = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    if row:
        if row[0]: headers["If-None-Match"] = row[0]
        if row[1]: headers["If-Modified-Since"] = row[1]

    now = datetime.now(timezone.utc)
    previous_hash = row[2] if row else None
    previous_stable = int(row[4] or 0) if row else 0
    previous_volatility = float(row[6] or 0) if row else 0.0

    try:
        req = Request(source["url"], headers=headers)
        with urlopen(req, timeout=float(source.get("timeout_seconds", 12))) as response:
            body = response.read()
            digest = _fingerprint(body, response.headers.get("Content-Type"))
            changed = previous_hash is None or previous_hash != digest
            stable_runs = 0 if changed else previous_stable + 1
            volatility = min(1.0, previous_volatility * 0.7 + 0.3) if changed else max(0.0, previous_volatility * 0.8 - 0.02)
            result = _store(
                con, source, etag=response.headers.get("ETag"),
                modified=response.headers.get("Last-Modified"), digest=digest,
                status=response.status, error=None, changed=changed,
                stable_runs=stable_runs, failures=0, volatility=volatility, now=now,
            )
            result["bytes"] = len(body)
            return result
    except HTTPError as exc:
        if exc.code == 304 and row:
            stable_runs = previous_stable + 1
            volatility = max(0.0, previous_volatility * 0.8 - 0.02)
            result = _store(
                con, source, etag=row[0], modified=row[1], digest=row[2],
                status=304, error=None, changed=False, stable_runs=stable_runs,
                failures=0, volatility=volatility, now=now,
            )
            result["bytes"] = 0
            return result
        return _record_error(con, source, row, exc.code, str(exc), now)
    except (URLError, TimeoutError, OSError) as exc:
        return _record_error(con, source, row, None, str(exc), now)

def _record_error(con, source: dict, row, status: int | None, message: str, now: datetime) -> dict:
    failures = (int(row[5] or 0) if row else 0) + 1
    stable_runs = int(row[4] or 0) if row else 0
    volatility = min(1.0, (float(row[6] or 0) if row else 0.0) + 0.15)
    result = _store(
        con, source, etag=row[0] if row else None, modified=row[1] if row else None,
        digest=row[2] if row else None, status=status, error=message, changed=False,
        stable_runs=stable_runs, failures=failures, volatility=volatility, now=now,
    )
    result["error"] = message
    result["bytes"] = 0
    return result
