"""Spec-0077/T4: real nonce-owned cleanup without optional Python pidfd APIs."""

import os
import signal
import subprocess
import sys
import time
import uuid

import pytest

from auto_designer.user.sim import runtime


def test_missing_python_pidfd_apis_still_stop_owned_child_and_leave_foreign(monkeypatch):
    nonce = uuid.uuid4().hex
    owned = subprocess.Popen(
        [sys.executable, "-c", "import time;time.sleep(60)"],
        env={**os.environ, "AUTO_DESIGNER_ATTEMPT_NONCE": nonce},
    )
    foreign = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(60)"])
    monkeypatch.delattr(os, "pidfd_open", raising=False)
    monkeypatch.delattr(signal, "pidfd_send_signal", raising=False)
    try:
        deadline = time.monotonic() + 3
        while owned.pid not in runtime._owned_processes(nonce) and time.monotonic() < deadline:
            time.sleep(0.01)
        assert owned.pid in runtime._owned_processes(nonce)
        assert runtime.stop_owned_processes(nonce)
        assert owned.wait(timeout=3) == -signal.SIGTERM
        assert foreign.poll() is None
    finally:
        for process in (owned, foreign):
            if process.poll() is None:
                process.kill()
            process.wait(timeout=3)


def test_unsupported_kernel_is_not_reported_as_success(monkeypatch):
    monkeypatch.setattr(runtime, "_owned_processes", lambda nonce: [123])

    def unavailable(**kwargs):
        raise OSError(38, "Function not implemented")

    monkeypatch.setattr(runtime, "_open_pidfd", unavailable)
    with pytest.raises(OSError, match="not implemented"):
        runtime.stop_owned_processes("owned")
