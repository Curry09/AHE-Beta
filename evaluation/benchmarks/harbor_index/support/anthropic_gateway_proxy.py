"""Non-streaming ARE judge bridge for gateways returning null usage metadata.

This file runs unchanged inside the official ARE image and uses only stdlib.
Requests, judge content, token counts and HTTP error responses stay intact.
"""

from __future__ import annotations

import json
import math
import os
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
    "content-length",
}
HEALTH_BODY = b"are-judge-gateway-ready"


def normalize_response(body: bytes) -> bytes:
    try:
        payload = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return body
    usage = payload.get("usage") if isinstance(payload, dict) else None
    if isinstance(usage, dict) and usage.get("server_tool_use", {}) is None:
        usage["server_tool_use"] = {}
        return json.dumps(payload, ensure_ascii=False).encode()
    return body


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # URLs, authorization headers and judge content never enter logs.

    def respond(self, status, body, headers=()):
        connection = ",".join(value for name, value in headers if name.lower() == "connection")
        blocked = HOP_HEADERS | {name.strip().lower() for name in connection.split(",")}
        self.send_response(status)
        for name, value in headers:
            if name.lower() not in blocked:
                self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            self.respond(200, HEALTH_BODY)
        else:
            self.send_error(404)

    def do_POST(self):
        if urlsplit(self.path).path != "/v1/messages":
            self.send_error(404)
            return
        try:
            body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            request_json = json.loads(body)
            if not isinstance(request_json, dict):
                raise ValueError("Expected an object")
        except (ValueError, UnicodeDecodeError):
            self.respond(400, b'{"error":{"type":"invalid_request_error"}}')
            return
        if request_json.get("stream"):
            self.respond(400, b'{"error":{"type":"streaming_not_supported_by_are_bridge"}}')
            return
        blocked = (
            HOP_HEADERS
            | {"host", "accept-encoding"}
            | {name.strip().lower() for name in self.headers.get("Connection", "").split(",")}
        )
        headers = {k: v for k, v in self.headers.items() if k.lower() not in blocked}
        headers["Accept-Encoding"] = "identity"
        request = urllib.request.Request(
            self.server.upstream + self.path,
            data=body,
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.server.upstream_timeout) as response:
                status, payload, response_headers = (
                    response.status,
                    response.read(),
                    list(response.headers.items()),
                )
            if 200 <= status < 300:
                payload = normalize_response(payload)
        except urllib.error.HTTPError as error:
            with error:
                status, payload, response_headers = (
                    error.code,
                    error.read(),
                    list(error.headers.items()),
                )
        except Exception as error:
            status = 504 if isinstance(error, TimeoutError) else 502
            payload = json.dumps({"error": {"type": type(error).__name__}}).encode()
            response_headers = [("Content-Type", "application/json")]
        self.respond(status, payload, response_headers)
        print(json.dumps({"status": status, "response_bytes": len(payload)}), flush=True)


def create_server(upstream, timeout, port=0):
    parsed = urlsplit(upstream)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("An HTTP(S) upstream is required")
    if (
        isinstance(timeout, bool)
        or not isinstance(timeout, (int, float))
        or not math.isfinite(timeout)
        or timeout <= 0
    ):
        raise ValueError("A finite positive upstream timeout is required")
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    server.upstream = upstream.rstrip("/")
    server.upstream_timeout = timeout
    return server


if __name__ == "__main__":
    with create_server(
        os.environ["ARE_JUDGE_UPSTREAM"], float(os.environ["ARE_JUDGE_TIMEOUT_SECONDS"])
    ) as server:
        ready = Path("/logs/judge-proxy.json")
        temporary = ready.with_suffix(".tmp")
        temporary.write_text(json.dumps({"port": server.server_port, "pid": os.getpid()}))
        temporary.replace(ready)
        server.serve_forever()
