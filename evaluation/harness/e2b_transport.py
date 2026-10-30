"""Reconnect E2B transport to the same process without restarting actor work."""

import asyncio
import json
import time

import httpx
from connectrpc.errors import ConnectError
from e2b.exceptions import SandboxUnreachableException, TimeoutException

TRANSIENT = (httpx.TransportError, SandboxUnreachableException, TimeoutException)


def retryable_transport(error):
    # E2B wraps stream expiry in its own TimeoutException and peer resets
    # in ConnectError. Reattach to the original PID while its task deadline
    # remains open. Never treat arbitrary RPC/application errors as transient.
    return isinstance(error, TRANSIENT) or (
        isinstance(error, ConnectError)
        and any(
            marker in str(error).lower()
            for marker in (
                "cannot decrypt peer's message",
                "connection reset by peer",
                "tls handshake eof",
                "tls close_notify",
                "unexpected eof",
            )
        )
    )


def record(path, operation, error, **fields):
    with path.open("a") as stream:
        stream.write(
            json.dumps(
                {
                    "at": time.time(),
                    "operation": operation,
                    "error_type": type(error).__name__,
                    **fields,
                }
            )
            + "\n"
        )


async def retry_transport(operation, deadline, log, label):
    number = 0
    while True:
        try:
            return await operation()
        except (*TRANSIENT, ConnectError) as error:
            if not retryable_transport(error):
                raise
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise
            number += 1
            record(log, label, error, retry=number)
            await asyncio.sleep(min(2 ** min(number, 4), remaining))


async def wait_for_same_process(handle, commands, deadline, on_stdout, on_stderr, log):
    pid = handle.pid
    while True:
        try:
            return await handle.wait()
        except (*TRANSIENT, ConnectError) as error:
            if not retryable_transport(error):
                raise
            if time.monotonic() >= deadline:
                raise
            record(log, "reconnect_command", error, pid=pid, actor_restarted=False)
            handle = await retry_transport(
                lambda: commands.connect(
                    pid,
                    timeout=max(1, deadline - time.monotonic()),
                    request_timeout=20,
                    on_stdout=on_stdout,
                    on_stderr=on_stderr,
                ),
                deadline,
                log,
                "connect_same_pid",
            )
