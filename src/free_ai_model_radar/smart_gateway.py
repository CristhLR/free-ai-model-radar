from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .smart_model_selector import SelectionPlan, get_model_selector
from .smart_router_engine import Decision, get_router_engine

HOST = "127.0.0.1"
PORT = 3002
UPSTREAM = "http://127.0.0.1:31415"
MAX_OUTPUT_TOKENS = 4096
ENGINE = get_router_engine()
SELECTOR = get_model_selector()


def _prepare(body: dict[str, Any]) -> tuple[dict[str, Any], Decision | None, SelectionPlan | None]:
    out = dict(body)
    requested = str(out.get("model") or "smart")
    if requested != "smart":
        return out, None, None

    decision = ENGINE.decide(out)
    try:
        plan = SELECTOR.select(out, decision)
    except Exception:
        plan = None

    route = decision.route
    if route == "fusion:best_of":
        out["model"] = "fusion"
        out["fusion"] = {"k": 2, "strategy": "best_of", "expose_panel": False}
    elif route == "fusion:synthesize":
        out["model"] = "fusion"
        out["fusion"] = {"k": 2, "strategy": "synthesize", "expose_panel": False}
    elif plan and plan.apply and plan.selected_model:
        out["model"] = plan.selected_model
        out.pop("fusion", None)
    else:
        out["model"] = route
        out.pop("fusion", None)

    current = out.get("max_tokens")
    try:
        current_tokens = int(current) if current is not None else None
    except (TypeError, ValueError):
        current_tokens = None
    if current_tokens is None or current_tokens > MAX_OUTPUT_TOKENS:
        out["max_tokens"] = MAX_OUTPUT_TOKENS
    return out, decision, plan


def _selector_retryable(status: int) -> bool:
    return status >= 500 or status in (400, 404, 408, 409, 422, 429)


def _candidate_models(plan: SelectionPlan | None) -> list[str]:
    if not plan:
        return []
    return [str(item.get("model")) for item in plan.candidates if item.get("model")][:8]


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        return

    def _headers(self, task_type: str | None = None) -> dict[str, str]:
        headers = {"Content-Type": self.headers.get("Content-Type", "application/json")}
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

    def _smart_headers(
        self,
        decision: Decision | None,
        plan: SelectionPlan | None = None,
        selector_fallback: bool = False,
    ) -> None:
        if decision is None:
            return
        self.send_header("X-Smart-Route", decision.header_value)
        self.send_header("X-Smart-Domain", decision.domain)
        self.send_header("X-Smart-Complexity", decision.complexity)
        self.send_header("X-Smart-Confidence", f"{decision.confidence:.4f}")
        self.send_header("X-Smart-Task-Type", decision.task_type)
        if plan:
            self.send_header("X-Smart-Selector", plan.mode)
            self.send_header("X-Smart-Selector-Confidence", f"{plan.confidence:.4f}")
            self.send_header("X-Smart-Candidates", str(len(plan.candidates)))
            if plan.selected_model:
                self.send_header("X-Smart-Model", plan.selected_model)
        if selector_fallback:
            self.send_header("X-Smart-Selector-Fallback", "1")

    def _record(
        self,
        decision: Decision | None,
        plan: SelectionPlan | None,
        *,
        status: int,
        started: float,
        routed_via: str | None = None,
        fallback_attempts: str | None = None,
        cache: str | None = None,
        compression: str | None = None,
        selector_fallback: bool = False,
    ) -> None:
        if decision is None:
            return
        ENGINE.record_result(
            decision,
            status=status,
            latency_ms=(time.perf_counter() - started) * 1000,
            routed_via=routed_via,
            fallback_attempts=fallback_attempts,
            cache=cache,
            compression=compression,
            selected_model=plan.selected_model if plan else None,
            selector_mode=plan.mode if plan else None,
            selector_confidence=plan.confidence if plan else None,
            selector_fallback=selector_fallback,
            candidate_models=_candidate_models(plan),
        )

    def do_GET(self):
        if self.path.rstrip("/") == "/smart/status":
            self._send_json(200, {
                "engine": "hybrid-semantic-v2",
                "classifier": ENGINE.status(),
                "selector": SELECTOR.status(),
            })
            return

        target = UPSTREAM + self.path
        req = urllib.request.Request(target, headers=self._headers())
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw = resp.read()
                if self.path.startswith("/v1/models"):
                    data = json.loads(raw)
                    models = data.setdefault("data", [])
                    if not any(isinstance(item, dict) and item.get("id") == "smart" for item in models):
                        models.insert(0, {
                            "id": "smart",
                            "object": "model",
                            "owned_by": "free-ai-radar",
                        })
                    raw = json.dumps(data).encode("utf-8")
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
        raw = self.rfile.read(length)
        try:
            body = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            self._send_json(400, {"error": {"message": "Invalid JSON", "type": "invalid_request_error"}})
            return

        path = self.path.rstrip("/")
        if path == "/smart/classify":
            self._send_json(200, ENGINE.decide(body).public_dict())
            return
        if path == "/smart/select":
            decision = ENGINE.decide(body)
            plan = SELECTOR.select(body, decision)
            self._send_json(200, {
                "decision": decision.public_dict(),
                "selection": plan.public_dict(),
            })
            return

        prepared, decision, plan = _prepare(body)
        task_type = decision.task_type if decision else None
        attempts = [prepared]
        if plan and plan.apply and plan.selected_model and plan.fallback_route:
            fallback = dict(prepared)
            fallback["model"] = plan.fallback_route
            fallback.pop("fusion", None)
            attempts.append(fallback)

        started = time.perf_counter()
        resp = None
        http_error: urllib.error.HTTPError | None = None
        generic_error: Exception | None = None
        selector_fallback = False

        for index, attempt in enumerate(attempts):
            payload = json.dumps(attempt, separators=(",", ":")).encode("utf-8")
            req = urllib.request.Request(
                UPSTREAM + self.path,
                data=payload,
                headers=self._headers(task_type),
                method="POST",
            )
            try:
                resp = urllib.request.urlopen(req, timeout=180)
                selector_fallback = index > 0
                break
            except urllib.error.HTTPError as exc:
                if index == 0 and len(attempts) > 1 and _selector_retryable(exc.code):
                    exc.read()
                    SELECTOR.record_fallback()
                    selector_fallback = True
                    continue
                http_error = exc
                break
            except Exception as exc:
                if index == 0 and len(attempts) > 1:
                    SELECTOR.record_fallback()
                    selector_fallback = True
                    continue
                generic_error = exc
                break

        if resp is not None:
            with resp:
                ctype = resp.headers.get("Content-Type", "application/json")
                routed_via = resp.headers.get("X-Routed-Via")
                fallback_attempts = resp.headers.get("X-Fallback-Attempts")
                cache = resp.headers.get("X-FreeLLM-Cache")
                compression = resp.headers.get("X-FreeLLM-Compress")
                self.send_response(resp.status)
                self.send_header("Content-Type", ctype)
                self._smart_headers(decision, plan, selector_fallback)
                for name in ("X-Routed-Via", "X-FreeLLM-Cache", "X-FreeLLM-Compress", "X-Fallback-Attempts"):
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
                        try:
                            self.wfile.write(chunk)
                            self.wfile.flush()
                        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
                            break
                    self.close_connection = True
                else:
                    data = resp.read()
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    try:
                        self.wfile.write(data)
                    except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
                        pass

                self._record(
                    decision, plan,
                    status=resp.status,
                    started=started,
                    routed_via=routed_via,
                    fallback_attempts=fallback_attempts,
                    cache=cache,
                    compression=compression,
                    selector_fallback=selector_fallback,
                )
            return

        if http_error is not None:
            data = http_error.read()
            self.send_response(http_error.code)
            self.send_header("Content-Type", http_error.headers.get("Content-Type", "application/json"))
            self._smart_headers(decision, plan, selector_fallback)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            self._record(
                decision, plan,
                status=http_error.code,
                started=started,
                routed_via=http_error.headers.get("X-Routed-Via"),
                fallback_attempts=http_error.headers.get("X-Fallback-Attempts"),
                cache=http_error.headers.get("X-FreeLLM-Cache"),
                compression=http_error.headers.get("X-FreeLLM-Compress"),
                selector_fallback=selector_fallback,
            )
            return

        err = generic_error or RuntimeError("upstream request failed")
        data = {"error": {
            "message": f"smart gateway upstream error: {type(err).__name__}",
            "type": "gateway_error",
        }}
        self._record(
            decision, plan,
            status=502,
            started=started,
            selector_fallback=selector_fallback,
        )
        self._send_json(502, data)


def run() -> None:
    print(f"SMART_GATEWAY_READY http://{HOST}:{PORT}/v1", flush=True)
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()


if __name__ == "__main__":
    run()
