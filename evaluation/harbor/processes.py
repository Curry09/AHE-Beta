"""Pinned stdlib-only runtime and cancellation boundary for installed agents."""

from __future__ import annotations

import asyncio
import fcntl
import hashlib
import json
import platform
import shlex
import sys
import tarfile
import tempfile
from pathlib import Path
from uuid import uuid4

from platformdirs import user_cache_path

from evaluation.harness.python_runtime import portable_python_base


class CommandCleanupError(RuntimeError):
    """Command cancellation could not confirm that owned work stopped."""


def prepare_process_runtime() -> dict:
    base = portable_python_base()
    executable = base / "bin/python3.12"
    identity = hashlib.sha256(
        (sys.version + platform.machine() + str(base)).encode() + executable.read_bytes()
    ).hexdigest()
    directory = user_cache_path("auto-designer-evaluation") / "native-runtime" / identity
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "runtime.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        descriptor = directory / "runtime.json"
        if not descriptor.exists():
            with tempfile.TemporaryDirectory(dir=directory) as staging:
                archive = Path(staging) / "python312.tar.gz"
                with tarfile.open(archive, "w:gz") as pack:
                    pack.add(
                        base,
                        arcname="python312",
                        filter=lambda item: (
                            None if "__pycache__" in Path(item.name).parts else item
                        ),
                    )
                sha = hashlib.sha256(archive.read_bytes()).hexdigest()
                target = directory / archive.name
                archive.rename(target)
                descriptor.write_text(
                    json.dumps({"python_archive": str(target), "python_sha256": sha}) + "\n"
                )
        return json.loads(descriptor.read_text())


class CommandProcessOwner:
    """One remote command tree, stopped before collection when its wait fails."""

    preserve_children_on_success = False
    receipt_name = "harness-command-cleanup.jsonl"
    prefix = "ad-harness-owner"

    def __init__(self, root: str, python: str, logs_dir: Path):
        self.root = root
        self.python = python
        self.logs_dir = Path(logs_dir)

    def command(self, original: str) -> tuple[str, str, str]:
        identity = uuid4().hex
        pid_file = f"/tmp/{self.prefix}-{identity}.pid"
        cancel_file = f"/tmp/{self.prefix}-{identity}.cancel"
        # Keep the SDK command's shell alive as the owner's parent. If that
        # shell is killed, PDEATHSIG still lets the owner reap detached work.
        preserve = "--preserve-children-on-success " if self.preserve_children_on_success else ""
        wrapper = (
            f"{self.python} -E -s {self.root}/process_runner.py $$ "
            f"{preserve}--pid-file {pid_file} "
            f"--cancel-file {cancel_file} /bin/bash -c {shlex.quote(original)} & "
            'ad_command_owner_pid=$!; wait "$ad_command_owner_pid"; '
            'ad_command_owner_status=$?; exit "$ad_command_owner_status"'
        )
        return wrapper, pid_file, cancel_file

    async def cancel(self, environment, pid_file: str, cancel_file: str) -> None:
        script = (
            "import os,signal,time,json;from pathlib import Path;"
            f"marker=Path({cancel_file!r});marker.touch();pidfile=Path({pid_file!r});"
            "pid=int(pidfile.read_text()) if pidfile.exists() else None;"
            "cmd=Path('/proc/'+str(pid)+'/cmdline')\n"
            "def owned():\n"
            " try:return str(marker).encode() in cmd.read_bytes()\n"
            " except FileNotFoundError:return False\n"
            "try:\n"
            " if owned():os.kill(pid,signal.SIGTERM)\n"
            "except ProcessLookupError:pass\n"
            "deadline=time.monotonic()+7\n"
            "while owned() and time.monotonic()<deadline:time.sleep(0.01)\n"
            "print(json.dumps({'stop_requested':True,'owner_exited':not owned()}))\n"
        )
        result = await environment.exec(
            self.python + " -E -s -c " + shlex.quote(script), timeout_sec=30, user="root"
        )
        proof = json.loads(result.stdout) if result.return_code == 0 else {}
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        with (self.logs_dir / self.receipt_name).open("a") as log:
            log.write(json.dumps({"pid_file": pid_file, **proof}) + "\n")
        if not proof.get("owner_exited"):
            raise CommandCleanupError("Remote command tree shutdown was not confirmed")

    async def cancel_shielded(self, environment, pid_file: str, cancel_file: str) -> None:
        try:
            await asyncio.shield(self.cancel(environment, pid_file, cancel_file))
        except Exception as error:
            raise CommandCleanupError("Remote command tree shutdown failed") from error


class NativeProcessOwner(CommandProcessOwner):
    preserve_children_on_success = True
    receipt_name = "native-command-cleanup.jsonl"
    prefix = "ad-native-owner"

    def __init__(self, runtime: dict, logs_dir: Path):
        self.archive = Path(runtime["python_archive"])
        self.sha = runtime["python_sha256"]
        if hashlib.sha256(self.archive.read_bytes()).hexdigest() != self.sha:
            raise ValueError("Native process runtime checksum mismatch")
        root = "/opt/auto-designer-native-owner"
        super().__init__(root, root + "/python312/bin/python3.12", logs_dir)

    async def setup(self, environment) -> None:
        result = await environment.exec("mkdir -p " + self.root, user="root", timeout_sec=30)
        if result.return_code:
            raise RuntimeError("Cannot prepare native process runtime directory")
        parts = []
        with tempfile.TemporaryDirectory(prefix="native-owner-upload-") as staging:
            with self.archive.open("rb") as stream:
                while chunk := stream.read(2 * 1024**2):
                    part = Path(staging) / f"part-{len(parts):04d}"
                    part.write_bytes(chunk)
                    target = self.root + "/" + part.name
                    await environment.upload_file(part, target)
                    parts.append(target)
        owner = Path(__file__).parents[1] / "harness/process_runner.py"
        await environment.upload_file(owner, self.root + "/process_runner.py")
        owner_sha = hashlib.sha256(owner.read_bytes()).hexdigest()
        command = (
            "cat " + " ".join(parts) + " > " + self.root + "/python.tar.gz && "
            "printf '%s  %s\\n' " + self.sha + " " + self.root + "/python.tar.gz | "
            "sha256sum -c - && tar -xzf "
            + self.root
            + "/python.tar.gz -C "
            + self.root
            + " && printf '%s  %s\\n' "
            + owner_sha
            + " "
            + self.root
            + "/process_runner.py | sha256sum -c - && chmod -R a+rX "
            + self.root
            + " && rm -f "
            + " ".join(parts)
        )
        result = await environment.exec(command, user="root", timeout_sec=120)
        if result.return_code:
            raise RuntimeError("Cannot install verified native process runtime")
