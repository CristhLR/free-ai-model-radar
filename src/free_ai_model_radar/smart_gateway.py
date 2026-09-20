from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .smart_router_engine import Decision, get_router_engine

HOST = "127.0.0.1"
PORT = 3002
UPSTREAM = "http://127.0.0.1:31415"
MAX_OUTPUT_TOKENS = 4096
ENGINE = get_router_engine()


def _prepare(body: dict[str, Any]) -> tuple[dict[str, Any], Decision | None]:
    out = dict(body)
    requested = str(out.get("model") or "smart")
    if requested != "smart":
        return out, None

    decision = ENGINE.decide(out)
    route = decision.route
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
    return out, decision


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        return

    def _headers(self, task_type: str | None = None) -> dict[str, str]:
        headers = {
            "Content-Type": self.headers.get("Content-Type", "application/json")
        }
        auth = self.headers.get("Authorization")
        if auth:
            headers["Authorization"] = auth
        if task_type:
            headers["X-FreeLLM-Task-Type"] = task_type
        return headers

    def _send_json(self, status: int, data: dict[str, Any]) -> None:
        raw = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _smart_headers(self, decision: Decision | None) -> None:
        if decision is None:
            return
        self.send_header("X-Smart-Route", decision.header_value)
        self.send_header("X-Smart-Domain", decision.domain)
        self.send_header("X-Smart-Complexity", decision.complexity)
        self.send_header("X-Smart-Confidence", f"{decision.confidence:.4f}")
        self.send_header("X-Smart-Task-Type", decision.task_type)

    def do_GET(self):
        if self.path.rstrip("/") == "/smart/status":
            self._send_json(200, ENGINE.status())
            return

        target = UPSTREAM + self.path
        req = urllib.request.Request(target, headers=self._headers())
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw = resp.read()
                if self.path.startswith("/v1/models"):
                    data = json.loads(raw)
                    models = data.setdefault("data", [])
                    if not any(
                        isinstance(item, dict) and item.get("id") == "smart"
                        for item in models
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
            self._send_json(400, {"error": {"message": "Invalid JSON", "type": "invalid_request_error"}})
            return

        if self.path.rstrip("/") == "/smart/classify":
            decision = ENGINE.decide(body)
            self._send_json(200, decision.public_dict())
            return

        prepared, decision = _prepare(body)
        payload = json.dumps(prepared, separators=(",", ":")).encode("utf-8")
        task_type = decision.task_type if decision else None
        req = urllib.request.Request(
            UPSTREAM + self.path,
            data=payload,
            headers=self._headers(task_type),
            method="POST",
        )
        started = time.perf_counter()

        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                ctype = resp.headers.get("Content-Type", "application/json")
                routed_via = resp.headers.get("X-Routed-Via")
                fallback_attempts = resp.headers.get("X-Fallback-Attempts")
                cache = resp.headers.get("X-FreeLLM-Cache")
                compression = resp.headers.get("X-FreeLLM-Compress")

                self.send_response(resp.status)
                self.send_header("Content-Type", ctype)
                self._smart_headers(decision)
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
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)

                if decision:
                    ENGINE.record_result(
                        decision,
                        status=resp.status,
                        latency_ms=(time.perf_counter() - started) * 1000,
                        routed_via=routed_via,
                        fallback_attempts=fallback_attempts,
                        cache=cache,
                        compression=compression,
                    )

        except urllib.error.HTTPError as exc:
            data = exc.read()
            self.send_response(exc.code)
            self.send_header(
                "Content-Type",
                exc.headers.get("Content-Type", "application/json"),
            )
            self._smart_headers(decision)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            if decision:
                ENGINE.record_result(
                    decision,
                    status=exc.code,
                    latency_ms=(time.perf_counter() - started) * 1000,
                    routed_via=exc.headers.get("X-Routed-Via"),
                    fallback_attempts=exc.headers.get("X-Fallback-Attempts"),
                    cache=exc.headers.get("X-FreeLLM-Cache"),
                    compression=exc.headers.get("X-FreeLLM-Compress"),
                )
        except Exception as exc:
            data = {
                "error": {
                    "message": f"smart gateway upstream error: {type(exc).__name__}",
                    "type": "gateway_error",
                }
            }
            if decision:
                ENGINE.record_result(
                    decision,
                    status=502,
                    latency_ms=(time.perf_counter() - started) * 1000,
                )
            self._send_json(502, data)


def run() -> None:
    print(f"SMART_GATEWAY_READY http://{HOST}:{PORT}/v1", flush=True)
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()


if __name__ == "__main__":
    run()
