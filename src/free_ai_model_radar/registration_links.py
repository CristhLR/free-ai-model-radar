from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

from .config import ROOT, USER_AGENT

KEYWORDS = {
    "sign up": 100,
    "signup": 100,
    "register": 95,
    "create account": 95,
    "get api key": 90,
    "api key": 80,
    "console": 65,
    "dashboard": 60,
    "get started": 50,
    "playground": 35,
}
BAD = {"github.com", "youtube.com", "x.com", "twitter.com", "linkedin.com", "discord.com"}

class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag == "a":
            self._href = dict(attrs).get("href")
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._href:
            self.links.append((self._href, " ".join(self._text).strip()))
            self._href = None
            self._text = []

def _score(url: str, text: str) -> int:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or parsed.netloc.lower() in BAD:
        return -1
    haystack = f"{text} {url}".lower()
    score = 0
    for key, points in KEYWORDS.items():
        if key in haystack:
            score = max(score, points)
    if "login" in haystack or "sign in" in haystack:
        score = max(score, 20)
    if re.search(r"(pricing|blog|changelog|docs?$)", parsed.path.rstrip("/").lower()):
        score -= 20
    return score

def find_registration_url(docs_url: str, timeout: float = 10.0) -> str | None:
    req = Request(docs_url, headers={"User-Agent": USER_AGENT, "Accept": "text/html"})
    with urlopen(req, timeout=timeout) as response:
        content_type = response.headers.get("Content-Type", "")
        if "html" not in content_type.lower():
            return None
        html = response.read().decode("utf-8", errors="replace")
    parser = _LinkParser()
    parser.feed(html)
    candidates: list[tuple[int, str]] = []
    for href, text in parser.links:
        url = urljoin(docs_url, href)
        score = _score(url, text)
        if score >= 50:
            candidates.append((score, url))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (-item[0], len(item[1])))
    return candidates[0][1]

def resolve_for_provider(con, slug: str) -> dict:
    row = con.execute(
        "SELECT docs_url,registration_url FROM provider_candidates WHERE slug=?",
        (slug,),
    ).fetchone()
    if not row:
        raise ValueError(f"unknown provider: {slug}")
    docs_url, existing = row
    if existing:
        return {"provider": slug, "registration_url": existing, "resolved": True, "cached": True}
    if not docs_url:
        return {"provider": slug, "registration_url": None, "resolved": False, "cached": False}
    try:
        found = find_registration_url(docs_url)
    except Exception as exc:
        return {"provider": slug, "registration_url": docs_url, "resolved": False, "error": str(exc)}
    chosen = found or docs_url
    con.execute(
        "UPDATE provider_candidates SET registration_url=? WHERE slug=?",
        (chosen, slug),
    )
    con.execute(
        "UPDATE user_actions SET action_url=? WHERE provider_slug=? AND status='pending'",
        (chosen, slug),
    )
    con.commit()
    return {
        "provider": slug,
        "registration_url": chosen,
        "resolved": bool(found),
        "cached": False,
    }


def apply_overrides(con, path=None) -> dict:
    path = path or (ROOT / "config" / "registration_overrides.json")
    if not path.exists():
        return {"updated": 0, "path": str(path)}
    overrides = json.loads(path.read_text(encoding="utf-8"))
    updated = 0
    for slug, url in overrides.items():
        row = con.execute("SELECT 1 FROM provider_candidates WHERE slug=?", (slug,)).fetchone()
        if not row:
            continue
        con.execute("UPDATE provider_candidates SET registration_url=? WHERE slug=?", (url, slug))
        con.execute("UPDATE user_actions SET action_url=? WHERE provider_slug=? AND status='pending'", (url, slug))
        updated += 1
    con.commit()
    return {"updated": updated, "path": str(path)}
