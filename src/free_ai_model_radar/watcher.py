from __future__ import annotations

import hashlib, re
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from .config import USER_AGENT

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
        text = body.decode("utf-8", errors="replace")
        parser = _VisibleTextParser()
        parser.feed(text)
        normalized = re.sub(r"\s+", " ", " ".join(parser.parts)).strip()
        body = normalized.encode("utf-8")
    return hashlib.sha256(body).hexdigest()

def check_url(con, source_id: str, url: str) -> dict:
    row = con.execute(
        "SELECT etag,last_modified,content_hash FROM source_checks WHERE source_id=?",
        (source_id,),
    ).fetchone()
    headers = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    if row:
        if row[0]: headers["If-None-Match"] = row[0]
        if row[1]: headers["If-Modified-Since"] = row[1]

    now = datetime.now(timezone.utc).isoformat()
    try:
        req = Request(url, headers=headers)
        with urlopen(req, timeout=20) as response:
            body = response.read()
            digest = _fingerprint(body, response.headers.get("Content-Type"))
            previous = row[2] if row else None
            changed = previous is None or previous != digest
            etag = response.headers.get("ETag")
            modified = response.headers.get("Last-Modified")
            status = response.status

    except HTTPError as exc:
        if exc.code == 304 and row:
            con.execute(
                """INSERT INTO source_checks(source_id,url,etag,last_modified,content_hash,last_checked,last_changed,status_code,error)
                VALUES(?,?,?,?,?,?,?,?,NULL)
                ON CONFLICT(source_id) DO UPDATE SET last_checked=excluded.last_checked,status_code=304,error=NULL""",
                (source_id,url,row[0],row[1],row[2],now,None,304),
            )
            con.commit()
            return {"source": source_id, "status": 304, "changed": False, "bytes": 0}
        raise

    last_changed = now if changed else con.execute(
        "SELECT last_changed FROM source_checks WHERE source_id=?", (source_id,)
    ).fetchone()[0] if row else now
    con.execute(
        """INSERT INTO source_checks(source_id,url,etag,last_modified,content_hash,last_checked,last_changed,status_code,error)
        VALUES(?,?,?,?,?,?,?,?,NULL)
        ON CONFLICT(source_id) DO UPDATE SET url=excluded.url,etag=excluded.etag,last_modified=excluded.last_modified,
        content_hash=excluded.content_hash,last_checked=excluded.last_checked,last_changed=excluded.last_changed,
        status_code=excluded.status_code,error=NULL""",
        (source_id,url,etag,modified,digest,now,last_changed,status),
    )
    con.commit()
    return {"source": source_id, "status": status, "changed": changed, "bytes": len(body)}
