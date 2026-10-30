"""Linux owner for one Harness tree, including children that detach sessions.

The Harness keeps its original argv, environment and inherited stdio. This
separate subreaper owns its orphaned children without changing the controller's
process-wide reaping behavior or touching other commands in the task sandbox.
"""

from __future__ import annotations

import ctypes
import os
import signal
import subprocess
import sys
import time
from pathlib import Path


def _children(pid: int) -> set[int]:
    children = set()
    for path in Path(f"/proc/{pid}/task").glob("*/children"):
        try:
            children.update(int(value) for value in path.read_text().split())
        except (FileNotFoundError, ProcessLookupError):
            pass
    return children


def _signal(pid: int, value: int) -> None:
    try:
        os.kill(pid, value)
    except ProcessLookupError:
        pass


def _freeze_tree(pid: int, frozen: set[int]) -> None:
    if pid in frozen:
        return
    # Stop the parent before inspecting its children, so it cannot create new
    # work while we walk the tree. Detached process groups retain ancestry.
    _signal(pid, signal.SIGSTOP)
    frozen.add(pid)
    for child in _children(pid):
        _freeze_tree(child, frozen)


def _reap() -> None:
    while True:
        try:
            pid, _ = os.waitpid(-1, os.WNOHANG)
        except ChildProcessError:
            return
        if pid == 0:
            return


def _cleanup() -> None:
    deadline = time.monotonic() + 5
    while True:
        children = _children(os.getpid())
        if not children:
            _reap()
            return
        frozen: set[int] = set()
        for child in children:
            _freeze_tree(child, frozen)
        for child in frozen:
            _signal(child, signal.SIGKILL)
        _reap()
        if time.monotonic() >= deadline:
            raise RuntimeError("Harness child processes did not exit after SIGKILL")
        # Orphans from a disappearing intermediate parent are now adopted by
        # this subreaper; inspect again rather than relying on a single scan.
        time.sleep(0.01)


def main() -> int:
    if not sys.platform.startswith("linux"):
        raise RuntimeError("Contained Harness execution requires a Linux task environment")
    expected_parent = int(sys.argv[1])
    command = sys.argv[2:]
    preserve_success = False
    pid_file = None
    cancel_file = None
    while command and command[0].startswith("--"):
        option = command.pop(0)
        if option == "--preserve-children-on-success":
            preserve_success = True
        elif option in {"--pid-file", "--cancel-file"}:
            path = Path(command.pop(0))
            if option == "--pid-file":
                pid_file = path
            else:
                cancel_file = path
        else:
            raise ValueError("Unknown process ownership option")
    if not command:
        raise ValueError("Harness command is missing")
    stopped = False

    def stop(signum: int, frame: object) -> None:
        nonlocal stopped
        stopped = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    libc = ctypes.CDLL(None, use_errno=True)
    libc.prctl.argtypes = [
        ctypes.c_int,
        ctypes.c_ulong,
        ctypes.c_ulong,
        ctypes.c_ulong,
        ctypes.c_ulong,
    ]
    libc.prctl.restype = ctypes.c_int
    # PR_SET_CHILD_SUBREAPER and PR_SET_PDEATHSIG apply to this owner only.
    for option, value in ((36, 1), (1, signal.SIGTERM)):
        if libc.prctl(option, value, 0, 0, 0) != 0:
            raise OSError(ctypes.get_errno(), "Cannot establish Harness process ownership")
    if stopped or os.getppid() != expected_parent or (cancel_file and cancel_file.exists()):
        return 143
    if pid_file:
        temporary = pid_file.with_suffix(".tmp")
        temporary.write_text(str(os.getpid()))
        temporary.rename(pid_file)
    if cancel_file and cancel_file.exists():
        return 143
    successful = False
    try:
        process = subprocess.Popen(command)
        while not stopped and not (cancel_file and cancel_file.exists()):
            code = process.poll()
            if code is not None:
                successful = code == 0
                return code if code >= 0 else 128 - code
            time.sleep(0.01)
        return 143
    finally:
        if (
            not (preserve_success and successful)
            or stopped
            or (cancel_file and cancel_file.exists())
        ):
            _cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
