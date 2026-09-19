from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .config import ROOT

HOST = "127.0.0.1"
PORT = 3002
UPSTREAM = "http://127.0.0.1:3001"
JEV_URL = "https://api.typesafe.ai/v1/systemone"
MAX_OUTPUT_TOKENS = 4096

def _secret(name: str) -> str | None:
    value = os.environ.get(name)
    if value:
        return value.strip()
    path = ROOT / ".env.local"
    if not path.exists():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith(name + "="):
            value = line.split("=", 1)[1].strip()
            return value or None
    return None

def _last_user_text(body: dict) -> str:
    for msg in reversed(body.get("messages") or []):
        if msg.get("role") != "user":
            continue
        content = msg.get("content", "")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    parts.append(str(item.get("text", "")))
            return " ".join(parts)
    return ""

def _heuristic_route(body: dict) -> tuple[str, str]:
    text = _last_user_text(body)
    low = text.lower()
    has_tools = bool(body.get("tools"))
    code = bool(re.search(r"\b(function|class|def |traceback|exception|\.py\b|\.ts\b|\.js\b)", text, re.I))
    hard = any(k in low for k in (
        "investiga", "research", "analiza", "debug", "arquitectura",
        "compara", "verifica", "security", "vulnerab", "optimiza"
    ))
    if has_tools:
        return ("auto:smart" if hard or code else "auto:balanced", "heuristic-tools")
    if len(text) < 280 and not hard and not code:
        return "auto:fast", "heuristic-fast"
    if hard or code or len(text) > 1800:
        return "auto:smart", "heuristic-smart"
    return "auto:balanced", "heuristic-balanced"

def _jev_route(body: dict) -> tuple[str, str] | None:
    key = _secret("TYPESAFE_API_KEY")
    if not key:
        return None
    text = _last_user_text(body)[:2500]
    state = json.dumps({
        "request": text,
        "has_tools": bool(body.get("tools")),
        "message_count": len(body.get("messages") or []),
    }, ensure_ascii=False)
    questions = {
        "route": {
            "type": "choice",
            "instructions": "Choose the cheapest routing mode that is still sufficient for a high-quality answer.",
            "criteria": {
                "fast": "Simple low-risk request; one fast model is enough.",
                "balanced": "Normal request; one balanced model is enough.",
                "smart": "Difficult reasoning, coding, research, or analysis; use the strongest single free model.",
                "verify": "Independent second opinion materially improves reliability; use two models without a judge.",
                "fusion": "Only for unusually difficult work where synthesis of two independent answers is worth an extra judge call."
            }
        },
        "needs_verification": {
            "type": "noul",
            "instructions": "Would an independent second model materially reduce the risk of a wrong answer?"
        }
    }
    payload = json.dumps({
        "state": state,
        "model": "jev-latest",
        "questions": questions,
    }).encode("utf-8")

    req = urllib.request.Request(
        JEV_URL,
        data=payload,
        headers={
            "Authorization": "Bearer " + key,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=4) as resp:
            data = json.load(resp)
    except Exception:
        return None
    answers = data.get("answers") or {}
    route_answer = answers.get("route") or {}
    choice = route_answer.get("choice")
    confidence = float(route_answer.get("confidence") or 0)
    verify = float((answers.get("needs_verification") or {}).get("noul") or 0)

    if choice == "fusion" and confidence >= 0.75 and not body.get("tools"):
        return "fusion:synthesize", f"jev-fusion-{confidence:.2f}"
    if (choice == "verify" or verify >= 0.82) and not body.get("tools"):
        return "fusion:best_of", f"jev-verify-{max(confidence, verify):.2f}"
    if choice == "smart":
        return "auto:smart", f"jev-smart-{confidence:.2f}"
    if choice == "fast":
        return "auto:fast", f"jev-fast-{confidence:.2f}"
    return "auto:balanced", f"jev-balanced-{confidence:.2f}"

def _prepare(body: dict) -> tuple[dict, str]:
    out = dict(body)
    requested = str(out.get("model") or "smart")
    if requested != "smart":
        return out, "passthrough"
    route, reason = _jev_route(out) or _heuristic_route(out)
    if route == "fusion:best_of":
        out["model"] = "fusion"
        out["fusion"] = {"k": 2, "strategy": "best_of", "expose_panel": False}
    elif route == "fusion:synthesize":
        out["model"] = "fusion"
        out["fusion"] = {"k": 2, "strategy": "synthesize", "expose_panel": False}
    else:
        out["model"] = route
        out.pop("fusion", None)
    current = out.get("max_tokens")
    if current is None or int(current) > MAX_OUTPUT_TOKENS:
        out["max_tokens"] = MAX_OUTPUT_TOKENS
    return out, reason + ":" + route

class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        return

    def _headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": self.headers.get(
                "Content-Type", "application/json"
            )
        }
        auth = self.headers.get("Authorization")
        if auth:
            headers["Authorization"] = auth
        return headers

    def do_GET(self):
        target = UPSTREAM + self.path
        req = urllib.request.Request(target, headers=self._headers())
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw = resp.read()
                if self.path.startswith("/v1/models"):
                    data = json.loads(raw)
                    models = data.setdefault("data", [])
                    if not any(
                        isinstance(x, dict) and x.get("id") == "smart"
                        for x in models
                    ):
                        models.insert(0, {
                            "id": "smart",
                            "object": "model",
                            "owned_by": "free-ai-radar",
                        })
                    raw = json.dumps(data).encode("utf-8")

                self.send_response(resp.status)
                self.send_header(
                    "Content-Type",
                    resp.headers.get("Content-Type", "application/json"),
                )
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            self.send_response(exc.code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)
        try:
            body = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            self.send_error(400)
            return

        prepared, decision = _prepare(body)
        payload = json.dumps(
            prepared, separators=(",", ":")
        ).encode("utf-8")
        req = urllib.request.Request(
            UPSTREAM + self.path,
            data=payload,
            headers=self._headers(),
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                ctype = resp.headers.get(
                    "Content-Type", "application/json"
                )
                self.send_response(resp.status)
                self.send_header("Content-Type", ctype)
                self.send_header("X-Smart-Route", decision)
                for name in (
                    "X-Routed-Via",
                    "X-FreeLLM-Cache",
                    "X-FreeLLM-Compress",
                    "X-Fallback-Attempts",
                ):
                    value = resp.headers.get(name)
                    if value:
                        self.send_header(name, value)

                if "text/event-stream" in ctype:
                    self.send_header("Connection", "close")
                    self.end_headers()
                    while True:
                        chunk = resp.read(4096)
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        self.wfile.flush()
                    self.close_connection = True
                else:
                    data = resp.read()
                    self.send_header(
                        "Content-Length", str(len(data))
                    )
                    self.end_headers()
                    self.wfile.write(data)

        except urllib.error.HTTPError as exc:
            data = exc.read()
            self.send_response(exc.code)
            self.send_header(
                "Content-Type",
                exc.headers.get("Content-Type", "application/json"),
            )
            self.send_header("X-Smart-Route", decision)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except Exception as exc:
            data = json.dumps({
                "error": {
                    "message": f"smart gateway upstream error: {type(exc).__name__}",
                    "type": "gateway_error",
                }
            }).encode("utf-8")
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self.send_header("X-Smart-Route", decision)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

def run() -> None:
    print(
        f"SMART_GATEWAY_READY http://{HOST}:{PORT}/v1",
        flush=True,
    )
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()

if __name__ == "__main__":
    run()
