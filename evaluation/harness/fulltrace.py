"""Additive HTTP and tool capture. Never change prompts, payloads or results."""

import functools
import hashlib
import json
import os
import re
import sys
import time
import uuid
from pathlib import Path

ROOT = None
ROLE = None
SECRETS = []


def scrub(data):
    for value in SECRETS:
        data = data.replace(value, b"[REDACTED]")
    return data


def bytes_of(value):
    return scrub(
        json.dumps(
            value,
            ensure_ascii=False,
            default=lambda x: x.model_dump() if hasattr(x, "model_dump") else str(x),
        ).encode()
    )


def store(path, data):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(scrub(data))
            f.flush()
            os.fsync(f.fileno())
    except BaseException:
        raise


def event(kind, **data):
    try:
        ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
        data = (
            bytes_of(
                dict(
                    at=time.time(),
                    role=ROLE,
                    pid=os.getpid(),
                    ppid=os.getppid(),
                    event=kind,
                    **data,
                )
            )
            + b"\n"
        )
        fd = os.open(ROOT / "events.jsonl", os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "ab") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
    except Exception as e:
        sys.stderr.write("FULL_TRACE_CAPTURE_ERROR:" + type(e).__name__ + "\n")


def headers(value):
    hidden = {
        "authorization",
        "proxy-authorization",
        "x-api-key",
        "api-key",
        "cookie",
        "set-cookie",
    }
    return [(k, "[REDACTED]" if k.lower() in hidden else v) for k, v in value.multi_items()]


def request_start(request):
    if not re.search(r"/(?:chat/completions|messages)/?$", request.url.path):
        return None
    ident = uuid.uuid4().hex
    try:
        body = request.content
        store(ROOT / (ident + ".request.body"), body)
        event(
            "request_started",
            call_id=ident,
            url=str(request.url),
            method=request.method,
            headers=headers(request.headers),
            body_file=ident + ".request.body",
            body_bytes=len(body),
            body_sha256=hashlib.sha256(body).hexdigest(),
        )
    except Exception as e:
        event("capture_error", call_id=ident, stage="request", error=type(e).__name__)
    return ident


def install(role="actor", directory=None):
    global ROOT, ROLE, SECRETS
    ROOT = Path(directory or os.environ.get("FULL_TRACE_DIR", "/logs/agent/full-call-traces/actor"))
    ROLE = role
    SECRETS = sorted(
        {
            v.encode()
            for k, v in os.environ.items()
            if len(v) >= 12 and (k.endswith("API_KEY") or k.endswith("API_TOKEN"))
        },
        key=len,
        reverse=True,
    )
    import httpx

    if getattr(httpx.Client, "_full_trace_installed", False):
        return
    httpx.Client._full_trace_installed = True
    sync_original = httpx.Client._send_single_request
    async_original = httpx.AsyncClient._send_single_request

    class SyncCapture(httpx.SyncByteStream):
        def __init__(self, stream, ident, status, began):
            self.stream, self.ident, self.status, self.began = stream, ident, status, began

        def __iter__(self):
            size = 0
            tail = b""
            terminal_seen = False
            path = ROOT / (self.ident + ".response.body")
            try:
                with path.open("wb") as f:
                    os.chmod(path, 0o600)
                    for chunk in self.stream:
                        data = scrub(chunk)
                        tail = (tail + data)[-256:]
                        terminal_seen = terminal_seen or bool(
                            re.search(rb"(?:^|\n)data: *\[DONE\](?:\r?\n|$)", tail)
                        )
                        f.write(data)
                        f.flush()
                        size += len(chunk)
                        yield chunk
                    os.fsync(f.fileno())
                event(
                    "response_completed",
                    call_id=self.ident,
                    http_status=self.status,
                    elapsed_seconds=time.monotonic() - self.began,
                    body_file=path.name,
                    body_bytes=size,
                )
            except BaseException as e:
                completed = terminal_seen and isinstance(e, GeneratorExit)
                event(
                    "response_completed" if completed else "response_interrupted",
                    call_id=self.ident,
                    http_status=self.status,
                    elapsed_seconds=time.monotonic() - self.began,
                    body_file=path.name,
                    body_bytes=size,
                    error=None if completed else type(e).__name__,
                    stream_close_reason=type(e).__name__,
                    terminal_marker_seen=terminal_seen,
                )
                raise

        def close(self):
            self.stream.close()

    class AsyncCapture(httpx.AsyncByteStream):
        def __init__(self, stream, ident, status, began):
            self.stream, self.ident, self.status, self.began = stream, ident, status, began

        async def __aiter__(self):
            size = 0
            tail = b""
            terminal_seen = False
            path = ROOT / (self.ident + ".response.body")
            try:
                with path.open("wb") as f:
                    os.chmod(path, 0o600)
                    async for chunk in self.stream:
                        data = scrub(chunk)
                        tail = (tail + data)[-256:]
                        terminal_seen = terminal_seen or bool(
                            re.search(rb"(?:^|\n)data: *\[DONE\](?:\r?\n|$)", tail)
                        )
                        f.write(data)
                        f.flush()
                        size += len(chunk)
                        yield chunk
                    os.fsync(f.fileno())
                event(
                    "response_completed",
                    call_id=self.ident,
                    http_status=self.status,
                    elapsed_seconds=time.monotonic() - self.began,
                    body_file=path.name,
                    body_bytes=size,
                )
            except BaseException as e:
                completed = terminal_seen and isinstance(e, GeneratorExit)
                event(
                    "response_completed" if completed else "response_interrupted",
                    call_id=self.ident,
                    http_status=self.status,
                    elapsed_seconds=time.monotonic() - self.began,
                    body_file=path.name,
                    body_bytes=size,
                    error=None if completed else type(e).__name__,
                    stream_close_reason=type(e).__name__,
                    terminal_marker_seen=terminal_seen,
                )
                raise

        async def aclose(self):
            await self.stream.aclose()

    @functools.wraps(sync_original)
    def sync(self, request):
        ident = request_start(request)
        began = time.monotonic()
        try:
            response = sync_original(self, request)
        except BaseException as e:
            if ident:
                event(
                    "request_failed",
                    call_id=ident,
                    error=type(e).__name__,
                    elapsed_seconds=time.monotonic() - began,
                )
            raise
        if ident:
            event(
                "response_headers",
                call_id=ident,
                http_status=response.status_code,
                headers=headers(response.headers),
            )
            response.stream = SyncCapture(response.stream, ident, response.status_code, began)
        return response

    @functools.wraps(async_original)
    async def asynchronous(self, request):
        ident = request_start(request)
        began = time.monotonic()
        try:
            response = await async_original(self, request)
        except BaseException as e:
            if ident:
                event(
                    "request_failed",
                    call_id=ident,
                    error=type(e).__name__,
                    elapsed_seconds=time.monotonic() - began,
                )
            raise
        if ident:
            event(
                "response_headers",
                call_id=ident,
                http_status=response.status_code,
                headers=headers(response.headers),
            )
            response.stream = AsyncCapture(response.stream, ident, response.status_code, began)
        return response

    httpx.Client._send_single_request = sync
    httpx.AsyncClient._send_single_request = asynchronous
    event("capture_installed", httpx_version=httpx.__version__)


def wrap_collector_factory(namespace):
    original = namespace["_make_step_collector"]

    @functools.wraps(original)
    def factory(*args, **kwargs):
        collector = original(*args, **kwargs)
        start, end = collector.start_span, collector.end_span

        @functools.wraps(start)
        def begin(*args, **kwargs):
            span = start(*args, **kwargs)
            if str(span.type) == "SpanType.TOOL":
                inputs = kwargs.get("inputs", args[2] if len(args) > 2 else None)
                event("tool_started", span_id=span.id, name=span.name, inputs=inputs)
            return span

        @functools.wraps(end)
        def finish(span, *args, **kwargs):
            if str(span.type) == "SpanType.TOOL":
                outputs = kwargs.get("outputs", args[0] if args else None)
                error = kwargs.get("error", args[1] if len(args) > 1 else None)
                event(
                    "tool_finished",
                    span_id=span.id,
                    name=span.name,
                    outputs=outputs,
                    error=None if error is None else str(error),
                )
            return end(span, *args, **kwargs)

        collector.start_span, collector.end_span = begin, finish
        return collector

    namespace["_make_step_collector"] = factory
