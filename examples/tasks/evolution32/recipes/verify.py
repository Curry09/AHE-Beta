"""Check declared task inputs and runtime availability without solving the task."""

from __future__ import annotations

import argparse
import ctypes
import importlib
import json
import os
import platform
import shlex
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path


def verify_module_sources(*, modules: list[str], root: Path, pytest: bool) -> None:
    """Check both the hook interpreter and the user's login-shell tool entrypoints."""
    expected = root.resolve()
    locations = {}
    for name in modules:
        module = importlib.import_module(name)
        location = getattr(module, "__file__", None)
        if location is None or not Path(location).resolve().is_relative_to(expected):
            raise RuntimeError(f"{name} imports outside the current task source: {location}")
        locations[name] = str(Path(location).resolve())
    assertion = (
        "import importlib\nfrom pathlib import Path\n"
        f"root=Path({str(expected)!r})\n"
        f"for name in {modules!r}:\n"
        "    value=getattr(importlib.import_module(name),'__file__',None)\n"
        "    assert value and Path(value).resolve().is_relative_to(root), (name,value)\n"
    )
    subprocess.run(["bash", "-lc", "python -c " + shlex.quote(assertion)], check=True, timeout=30)
    if pytest:
        with tempfile.TemporaryDirectory(prefix="task-runtime-import-") as temporary:
            directory = Path(temporary)
            probe = directory / "test_current_task_source.py"
            probe.write_text(
                "def test_current_task_source():\n"
                + "\n".join("    " + line for line in assertion.splitlines())
                + "\n"
            )
            command = shlex.join(
                ["pytest", "-q", "-c", "/dev/null", "--confcutdir", temporary, str(probe)]
            )
            subprocess.run(["bash", "-lc", command], check=True, timeout=60)
    print(json.dumps({"task_module_sources": locations, "login_shell": "verified"}))


def verify_ptrace() -> None:
    """Exercise attach/detach against a sibling process, like the live task service."""
    target = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    reader, writer = os.pipe()
    try:
        tracer = os.fork()
        if tracer == 0:
            os.close(reader)
            attached = False
            result = 0
            try:
                libc = ctypes.CDLL(None, use_errno=True)
                libc.ptrace.argtypes = [
                    ctypes.c_uint,
                    ctypes.c_uint,
                    ctypes.c_void_p,
                    ctypes.c_void_p,
                ]
                libc.ptrace.restype = ctypes.c_long
                if libc.ptrace(16, target.pid, None, None) == -1:
                    raise OSError(ctypes.get_errno(), "PTRACE_ATTACH failed")
                attached = True
                _, status = os.waitpid(target.pid, 0)
                if not os.WIFSTOPPED(status):
                    raise RuntimeError("Trace target did not enter the expected stop")
                if libc.ptrace(17, target.pid, None, None) == -1:
                    raise OSError(ctypes.get_errno(), "PTRACE_DETACH failed")
                attached = False
            except Exception as exc:
                os.write(writer, str(exc).encode())
                result = 1
            finally:
                if attached:
                    libc.ptrace(17, target.pid, None, None)
                os.close(writer)
                os._exit(result)
        os.close(writer)
        writer = -1
        _, status = os.waitpid(tracer, 0)
        detail = os.read(reader, 4096).decode(errors="replace")
        if not os.WIFEXITED(status) or os.WEXITSTATUS(status) != 0:
            raise RuntimeError(
                "Required sibling-process ptrace capability is unavailable: " + detail
            )
    finally:
        os.close(reader)
        if writer != -1:
            os.close(writer)
        if target.poll() is None:
            target.kill()
        target.wait(timeout=5)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", type=Path, action="append", default=[])
    parser.add_argument("--absent", type=Path, action="append", default=[])
    parser.add_argument("--module", action="append", default=[])
    parser.add_argument("--source-module", action="append", default=[])
    parser.add_argument("--module-root", type=Path)
    parser.add_argument("--pytest-source", action="store_true")
    parser.add_argument("--git-revision")
    parser.add_argument("--workbook", type=Path)
    parser.add_argument("--http", action="append", default=[])
    parser.add_argument("--ptrace", action="store_true")
    args = parser.parse_args()
    if args.source_module:
        if args.module_root is None:
            parser.error("--source-module requires the current --module-root")
        verify_module_sources(
            modules=args.source_module, root=args.module_root, pytest=args.pytest_source
        )
    elif args.module_root is not None or args.pytest_source:
        parser.error("Source provenance checks require at least one --source-module")
    if args.ptrace:
        verify_ptrace()
        print(json.dumps({"ptrace": "verified", "architecture": platform.machine()}))
    for path in args.path:
        if not path.exists():
            raise SystemExit(f"Original task input is missing: {path}")
    for path in args.absent:
        if path.exists() or path.is_symlink():
            raise SystemExit(f"Management-only material is exposed to the task: {path}")
    for name in args.module:
        importlib.import_module(name)
    if args.git_revision:
        head = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True, timeout=10).strip()
        if head != args.git_revision:
            raise SystemExit("Task Git revision differs from the declared original baseline")
    if args.workbook:
        with zipfile.ZipFile(args.workbook) as workbook:
            if "xl/workbook.xml" not in workbook.namelist() or workbook.testzip() is not None:
                raise SystemExit("Original workbook is missing or damaged")
    for url in args.http:
        with urllib.request.urlopen(url, timeout=5) as response:
            if response.status != 200:
                raise SystemExit("A declared task service is not ready")


if __name__ == "__main__":
    main()
