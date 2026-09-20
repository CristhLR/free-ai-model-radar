from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .config import ROOT

HOST = "127.0.0.1"
PORT = 3004
UPSTREAM = "http://127.0.0.1:3002"
MAX_OUTPUT_TOKENS = 4096


def _load_local_env() -> None:
    path = ROOT / ".env.local"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" not in line or line.lstrip().startswith("#"):
            continue
        name, value = line.split("=", 1)
        name, value = name.strip(), value.strip()
        if name and value:
            os.environ.setdefault(name, value)


def _post_jev(body: dict) -> dict:
    import importlib.util
    adapter = (
        Path.home() / ".dsh" / "integrations" / "jev-ultrafast"
        / "jev_ultrafast" / "gateway_adapter.py"
    )
    spec = importlib.util.spec_from_file_location(
        "_jev_gateway_adapter", adapter
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Jev gateway adapter could not be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _load_local_env()
    return module.post_jev(body)


def _last_user_text(body: dict) -> str:
    for msg in reversed(body.get("messages") or []):
        if msg.get("role") != "user":
            continue
        content = msg.get("content", "")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return " ".join(
                str(x.get("text", ""))
                for x in content
                if isinstance(x, dict) and x.get("type") == "text"
            )
    return ""


def _jev_decision(body: dict) -> tuple[str, str] | None:
    text = _last_user_text(body)[:2500]
    state = {
        "request": text,
        "request_chars": len(text),
        "has_tools": bool(body.get("tools")),
        "message_count": len(body.get("messages") or []),
    }
    questions = {
        "route": {
            "type": "choice",
            "instructions": (
                "Choose the cheapest route that should still produce a high-quality answer. "
                "Avoid multi-model routes unless they materially improve correctness."
            ),
            "criteria": {
                "fast": "Simple low-risk request; one fast model is enough.",
                "balanced": "Normal task; one balanced model is enough.",
                "smart": "Hard reasoning, coding, research, or analysis; use one strong model.",
                "verify": "A second independent answer materially improves reliability; no judge needed.",
                "fusion": "An unusually difficult task where two answers should be synthesized by a judge.",
            },
        }
    }
    try:
        data = _post_jev({"state": state, "questions": questions})
    except Exception:
        return None

    answer = (data.get("answers") or {}).get("route") or {}
    choice = str(answer.get("choice") or "")
    probs = answer.get("probabilities") or {}
    confidence = answer.get("confidence")
    if confidence is None and probs:
        try:
            confidence = max(float(v) for v in probs.values())
        except Exception:
            confidence = 0.0
    confidence = float(confidence or 0.0)

    if body.get("tools") and choice in {"verify", "fusion"}:
        return "auto:smart", f"jev-tools-{confidence:.2f}"
    if choice == "fusion" and confidence >= 0.78:
        return "fusion:synthesize", f"jev-fusion-{confidence:.2f}"
    if choice == "verify" and confidence >= 0.72:
        return "fusion:best_of", f"jev-verify-{confidence:.2f}"
    if choice == "smart":
        return "auto:smart", f"jev-smart-{confidence:.2f}"
    if choice == "fast" and confidence >= 0.65:
        return "auto:fast", f"jev-fast-{confidence:.2f}"
    return "auto:balanced", f"jev-balanced-{confidence:.2f}"


def _prepare(body: dict) -> tuple[dict, str]:
    out = dict(body)
    if str(out.get("model") or "smart") != "smart":
        return out, "passthrough"
    decision = _jev_decision(out)
    if decision is None:
        return out, "jev-unavailable:fallback-smart"
    route, reason = decision
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
        headers = {"Content-Type": self.headers.get("Content-Type", "application/json")}
        auth = self.headers.get("Authorization")
        if auth:
            headers["Authorization"] = auth
        return headers

    def do_GET(self):
        req = urllib.request.Request(UPSTREAM + self.path, headers=self._headers())
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw = resp.read()
                self.send_response(resp.status)
                self.send_header("Content-Type", resp.headers.get("Content-Type", "application/json"))
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
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self.send_error(400)
            return
        prepared, decision = _prepare(body)
        payload = json.dumps(prepared, separators=(",", ":")).encode("utf-8")
        req = urllib.request.Request(
            UPSTREAM + self.path,
            data=payload,
            headers=self._headers(),
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                ctype = resp.headers.get("Content-Type", "application/json")
                self.send_response(resp.status)
                self.send_header("Content-Type", ctype)
                self.send_header("X-Jev-Route", decision)
                for name in (
                    "X-Smart-Route",
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
                    raw = resp.read()
                    self.send_header("Content-Length", str(len(raw)))
                    self.end_headers()
                    self.wfile.write(raw)
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            self.send_response(exc.code)
            self.send_header("Content-Type", exc.headers.get("Content-Type", "application/json"))
            self.send_header("X-Jev-Route", decision)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)


def run() -> None:
    print(f"JEV_ROUTER_READY http://{HOST}:{PORT}/v1", flush=True)
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()


if __name__ == "__main__":
    run()
