"""Servidor HTTP local: interface web em / e API (equivalente ao API Gateway) em /api."""
from __future__ import annotations

import json
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qsl, urlparse

from local_runtime.runtime import PROJECT_ROOT, LocalRuntime

FRONTEND_DIR = PROJECT_ROOT / "frontend"
LOCAL_CONFIG_JS = (
    "window.TECHCOMMERCE_CONFIG = { apiBaseUrl: '/api', localRuntime: true, "
    "environmentLabel: 'LOCAL (simulação: moto + simulador EventBridge/Scheduler)' };\n"
)


def build_handler(runtime: LocalRuntime):
    class Handler(BaseHTTPRequestHandler):
        server_version = "TechCommerceLocal/1.0"

        def log_message(self, fmt, *args):  # silencia o log de acesso padrão
            pass

        def _send(self, status: int, body: bytes, content_type: str, extra: dict | None = None):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            for key, value in (extra or {}).items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, data):
            self._send(status, json.dumps(data, default=str, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

        def do_OPTIONS(self):
            self._send(204, b"", "text/plain", {
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type,Idempotency-Key,X-Correlation-Id",
            })

        def do_GET(self):
            self._dispatch("GET")

        def do_POST(self):
            self._dispatch("POST")

        def _dispatch(self, method: str):
            parsed = urlparse(self.path)
            path = parsed.path
            query = dict(parse_qsl(parsed.query))
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length).decode("utf-8") if length else None
            try:
                if path.startswith("/api/"):
                    result = runtime.handle_api(method, path[4:], query, dict(self.headers), body)
                    headers = {k: v for k, v in (result.get("headers") or {}).items() if k.lower() != "content-type"}
                    content_type = (result.get("headers") or {}).get("Content-Type", "application/json")
                    self._send(result["statusCode"], (result.get("body") or "").encode("utf-8"), content_type, headers)
                elif path == "/local/status" and method == "GET":
                    self._json(200, runtime.status())
                elif path == "/local/events" and method == "GET":
                    self._json(200, {"events": list(runtime.event_trace)})
                elif path == "/local/dead-letters" and method == "GET":
                    self._json(200, {"deadLetters": list(runtime.dead_letters)})
                elif path == "/local/scheduler/run" and method == "POST":
                    self._json(202, {"triggered": runtime.run_schedules_now(),
                                     "message": "Agendamento executado (simulação local do EventBridge Scheduler)."})
                elif path == "/config.js":
                    self._send(200, LOCAL_CONFIG_JS.encode("utf-8"), "application/javascript")
                elif method == "GET":
                    self._static(path)
                else:
                    self._json(404, {"error": "Rota não encontrada"})
            except Exception as exc:  # noqa: BLE001 - equivalente a um 502 do API Gateway
                self._json(502, {"error": "Erro interno na função (simulação local)", "detail": str(exc)})

        def _static(self, path: str):
            relative = "index.html" if path in ("", "/") else path.lstrip("/")
            target = (FRONTEND_DIR / relative).resolve()
            if FRONTEND_DIR.resolve() not in target.parents or not target.is_file():
                self._json(404, {"error": "Arquivo não encontrado"})
                return
            content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            if content_type.startswith("text/") or content_type == "application/javascript":
                content_type += "; charset=utf-8"
            self._send(200, target.read_bytes(), content_type)

    return Handler


def serve(runtime: LocalRuntime, host: str = "127.0.0.1", port: int = 8000) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), build_handler(runtime))


def frontend_path() -> Path:
    return FRONTEND_DIR
