"""Spec-0069/T2: supervise the existing controller, with owned PIDs and receipts.

The supervisor survives CLI disconnects. It holds an exclusive run lock, forwards
stop to Python as SIGINT (so the runner's finally stops Vigil), and reaps the
controller process group. Exit code alone is never evidence of completed rounds.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import tarfile
import tempfile
import time
import uuid
from collections import deque
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ahe_beta.experiment.config import ConfigError
from ahe_beta.experiment.context import material_path
from ahe_beta.experiment.materials import sha256_file


def _timestamp() -> str:
    return datetime.now(UTC).isoformat()


def _json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _write(path: Path, values: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(values, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def _process_identity(pid: int) -> str | None:
    """Linux /proc start ticks prevent a stale run from signalling a reused PID."""
    try:
        data = Path(f"/proc/{pid}/stat").read_text()
        fields = data[data.rindex(")") + 2 :].split()
        if fields[0] == "Z":
            return None
        return fields[19]
    except (OSError, ValueError, IndexError):
        return None


def _alive(pid: Any, identity: Any) -> bool:
    return bool(pid and identity and _process_identity(int(pid)) == str(identity))


def materialize_controller_source(run_dir: Path, manifest: dict[str, Any]) -> Path:
    """Extract the frozen snapshot, verify it, then give repo_guard an independent Git repo."""
    root = Path(run_dir).resolve()
    destination = root / "source/controller"
    expected = manifest["source_snapshot"]["files"]
    if destination.exists():
        for relative, digest in expected.items():
            path = destination / relative
            if path.is_symlink() or not path.is_file() or sha256_file(path) != digest:
                raise ConfigError(f"Frozen controller source was modified: {relative}")
        _exclude_generated_runtime(destination)
        return destination
    archive = material_path(root, manifest, "controller_source_archive")
    if sha256_file(archive) != manifest["materials"]["controller_source_archive"]["sha256"]:
        raise ConfigError("Controller source archive SHA-256 mismatch")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".controller-", dir=destination.parent))
    try:
        with tarfile.open(archive, "r:gz") as bundle:
            for member in bundle.getmembers():
                relative = Path(member.name)
                if (
                    relative.is_absolute()
                    or ".." in relative.parts
                    or not (member.isfile() or member.isdir())
                ):
                    raise ConfigError("Controller archive contains an unsafe entry")
                if member.isfile() and member.name not in expected:
                    raise ConfigError(f"Unexpected controller archive file: {member.name}")
            bundle.extractall(temporary, filter="data")
        for relative, digest in expected.items():
            path = temporary / relative
            if not path.is_file() or sha256_file(path) != digest:
                raise ConfigError(f"Controller source snapshot hash mismatch: {relative}")
        subprocess.run(
            ["git", "init", "-b", "main", str(temporary)], check=True, capture_output=True
        )
        _exclude_generated_runtime(temporary)
        git = [
            "git",
            "-C",
            str(temporary),
            "-c",
            "user.name=Experiment snapshot",
            "-c",
            "user.email=experiment@localhost",
            "-c",
            "commit.gpgsign=false",
            "-c",
            "core.hooksPath=/dev/null",
        ]
        subprocess.run([*git, "add", "."], check=True, capture_output=True)
        subprocess.run(
            [*git, "commit", "-m", "snapshot: frozen controller inputs"],
            check=True,
            capture_output=True,
        )
        temporary.rename(destination)
    finally:
        shutil.rmtree(temporary, ignore_errors=True)
    return destination


def _exclude_generated_runtime(source: Path) -> None:
    """Keep installed environments out of Git without hiding tracked source changes."""
    if not (source / ".git").is_dir():
        return
    path = source / ".git/info/exclude"
    path.parent.mkdir(parents=True, exist_ok=True)
    current = path.read_text() if path.is_file() else ""
    patterns = [".venv/", "__pycache__/", "*.py[cod]"]
    missing = [pattern for pattern in patterns if pattern not in current.splitlines()]
    if missing:
        with path.open("a") as stream:
            if current and not current.endswith("\n"):
                stream.write("\n")
            stream.write("\n".join(missing) + "\n")


def controller_command(
    manifest: dict[str, Any], source_root: Path, python: str = sys.executable
) -> list[str]:
    """Spec-0073/T5: launch this run's original frozen contract and source."""
    backend = Path(source_root) / "backend"
    files = manifest["source_snapshot"]["files"]
    recipe = manifest["source_snapshot"].get("entrypoint")
    if "workload_contract_version" in manifest:
        version = manifest["workload_contract_version"]
        if type(version) is not int or version != 1:
            raise ConfigError("Unknown frozen workload contract version")
        expected_module = "ahe_beta.experiment.controllers.unified"
        relative = "backend/" + expected_module.replace(".", "/") + ".py"
        if recipe != {"kind": "module", "module": expected_module} or relative not in files:
            raise ConfigError("Frozen controller entrypoint does not match its workload contract")
        return [python, "-m", expected_module]
    kind = manifest.get("config", {}).get("workload", {}).get("kind")
    if kind not in {"ordinary", "swebench"}:
        raise ConfigError("Unknown legacy frozen workload kind")
    if recipe is not None:
        expected_module = f"ahe_beta.experiment.controllers.{kind}"
        relative = "backend/" + expected_module.replace(".", "/") + ".py"
        if recipe != {"kind": "module", "module": expected_module} or relative not in files:
            raise ConfigError("Frozen controller entrypoint does not match its source snapshot")
        return [python, "-m", expected_module]
    script = (
        "backend/scripts/run_swebench_closed_loop.py" if kind == "swebench" else "backend/run.py"
    )
    if script not in files:
        raise ConfigError("Frozen v2 source does not contain its original controller script")
    if kind == "swebench":
        return [python, str(Path(source_root) / script)]
    run_dir = Path(manifest["run_dir"])
    return [
        python,
        str(backend / "run.py"),
        "--persona-library",
        str(material_path(run_dir, manifest, "persona_library")),
    ]


def inspect_controller(run_dir: Path) -> dict[str, Any]:
    root = Path(run_dir)
    owner = _json(root / "runtime/controller.json")
    if not owner:
        return {"state": "ABSENT", "running": False, "observed_at": _timestamp()}
    receipt = _json(root / "runtime/controller-exit.json")
    if receipt.get("nonce") == owner.get("nonce"):
        return {
            **receipt,
            "running": bool(receipt.get("residual_processes")),
            "observed_at": _timestamp(),
        }
    if _alive(owner.get("supervisor_pid"), owner.get("supervisor_start")):
        if owner.get("runner_pid") and not _alive(owner["runner_pid"], owner.get("runner_start")):
            # The supervisor may be collecting the terminal receipt. Its existence
            # alone must not be called a healthy controller.
            return {**owner, "state": "STOPPING", "running": False, "observed_at": _timestamp()}
        return {**owner, "state": "RUNNING", "running": True, "observed_at": _timestamp()}
    if _alive(owner.get("runner_pid"), owner.get("runner_start")):
        return {
            **owner,
            "state": "UNKNOWN",
            "running": True,
            "error": "Controller survived its supervisor",
            "observed_at": _timestamp(),
        }
    return {
        **owner,
        "state": "UNKNOWN",
        "running": False,
        "error": "Controller owner disappeared without an exit receipt",
        "observed_at": _timestamp(),
    }


def launch_controller(
    *, run_dir: Path, command: list[str], env: Mapping[str, str]
) -> dict[str, Any]:
    """Start once and wait for an identity-bearing supervisor acknowledgement."""
    root = Path(run_dir).resolve()
    _exclude_generated_runtime(root / "source/controller")
    runtime = root / "runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    (root / "logs").mkdir(parents=True, exist_ok=True)
    with (runtime / "controller-launch.lock").open("a+") as gate:
        fcntl.flock(gate, fcntl.LOCK_EX)
        current = inspect_controller(root)
        if current["state"] in {"RUNNING", "STOPPING"} or current.get("running"):
            return current
        nonce = uuid.uuid4().hex
        child_env = dict(env)
        # The module must be available even for standalone supervisor integration tests.
        module_backend = str(Path(__file__).resolve().parents[2])
        child_env["PYTHONPATH"] = os.pathsep.join(
            filter(None, [child_env.get("PYTHONPATH"), module_backend])
        )
        with (root / "logs/supervisor.log").open("ab") as log:
            proc = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "ahe_beta.experiment.engine",
                    "--supervise",
                    "--run-dir",
                    str(root),
                    "--command",
                    json.dumps(command),
                    "--nonce",
                    nonce,
                ],
                env=child_env,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            owner = _json(runtime / "controller.json")
            if owner.get("nonce") == nonce:
                return inspect_controller(root)
            if proc.poll() is not None:
                raise ConfigError(
                    f"Controller supervisor failed ({proc.returncode}); see logs/supervisor.log"
                )
            time.sleep(0.05)
        proc.terminate()
        raise ConfigError("Controller supervisor did not acknowledge startup")


def stop_controller(run_dir: Path, grace_seconds: float = 30) -> dict[str, Any]:
    root = Path(run_dir)
    owner = _json(root / "runtime/controller.json")
    current = inspect_controller(root)
    if current.get("state") in {"ABSENT", "EXITED", "STOPPED"}:
        return current
    if _alive(owner.get("supervisor_pid"), owner.get("supervisor_start")):
        os.kill(int(owner["supervisor_pid"]), signal.SIGTERM)
    elif _alive(owner.get("runner_pid"), owner.get("runner_start")):
        os.killpg(int(owner["runner_pid"]), signal.SIGINT)
    else:
        return current  # Stale PIDs are never signalled.
    deadline = time.monotonic() + grace_seconds
    while time.monotonic() < deadline:
        current = inspect_controller(root)
        if current["state"] in {"STOPPED", "EXITED"}:
            return current
        time.sleep(0.05)
    if _alive(owner.get("runner_pid"), owner.get("runner_start")):
        os.killpg(int(owner["runner_pid"]), signal.SIGKILL)
    # Keep the supervisor alive long enough to reap and write its receipt.
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        current = inspect_controller(root)
        if current["state"] in {"STOPPED", "EXITED"}:
            return current
        time.sleep(0.05)
    return inspect_controller(root)


def controller_logs(run_dir: Path, tail: int = 100, follow: bool = False) -> str:
    """Return a bounded snapshot; the CLI follows it through repeated reads."""
    path = Path(run_dir) / "logs/controller.log"
    if not path.is_file():
        return ""
    with path.open(encoding="utf-8", errors="replace") as handle:
        return "".join(deque(handle, maxlen=max(0, tail)))


def _completion(root: Path) -> dict[str, Any]:
    manifest = _json(root / "manifest.json")
    expected = int((manifest.get("config", {}).get("rounds") or {}).get("count", 0))
    run_id = manifest.get("run_id", "")
    invocation = _json(root / "data/role_runs" / str(run_id) / "manifest.json")
    sealed_rows = {
        int(row.get("round", 0)): row["sealed_sha"]
        for row in invocation.get("rounds", [])
        if isinstance(row, dict) and row.get("sealed_sha")
    }
    sealed = set(sealed_rows)
    recovery = _json(root / "checkpoints/recovery.json")
    saved = recovery.get("rounds") or {}
    complete = (
        expected > 0
        and sealed == set(range(1, expected + 1))
        and all(
            (saved.get(str(number)) or {}).get("status") == "completed"
            and (saved.get(str(number)) or {}).get("sealed_sha") == sealed_rows.get(number)
            for number in range(1, expected + 1)
        )
    )
    bootstrap = {}
    if "continuation" in manifest.get("config", {}):
        bootstrap = _bootstrap_completion(root=root, manifest=manifest, rounds=saved)
        complete = complete and bootstrap.get("complete") is True
    return {
        "expected_rounds": expected,
        "sealed_rounds": sorted(sealed),
        "experiment_complete": bool(complete),
        **({"continuation_bootstrap": bootstrap} if bootstrap else {}),
    }


def _supervise(root: Path, command: list[str], nonce: str) -> int:
    runtime = root / "runtime"
    stop = {"requested": False, "at": None}
    proc: subprocess.Popen | None = None

    def request_stop(_signum, _frame):
        if not stop["requested"]:
            stop.update(requested=True, at=time.monotonic())
            if proc is not None and proc.poll() is None:
                os.killpg(proc.pid, signal.SIGINT)

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    with (runtime / "controller-owner.lock").open("a+") as owner_lock:
        try:
            fcntl.flock(owner_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 2
        owner = {
            "nonce": nonce,
            "command_identity": hashlib.sha256(json.dumps(command).encode()).hexdigest(),
            "supervisor_pid": os.getpid(),
            "supervisor_start": _process_identity(os.getpid()),
            "started_at": _timestamp(),
        }
        (runtime / "controller-exit.json").unlink(missing_ok=True)
        with (root / "logs/controller.log").open("ab") as log:
            try:
                runner_env = {**os.environ, "AHE_BETA_CONTROLLER_NONCE": nonce}
                proc = subprocess.Popen(
                    command,
                    env=runner_env,
                    stdin=subprocess.DEVNULL,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
                owner.update(runner_pid=proc.pid, runner_start=_process_identity(proc.pid))
                _write(runtime / "controller.json", owner)
                while proc.poll() is None:
                    _write(runtime / "controller.json", {**owner, "heartbeat_at": _timestamp()})
                    if stop["requested"] and time.monotonic() - float(stop["at"]) >= 30:
                        os.killpg(proc.pid, signal.SIGKILL)
                    time.sleep(0.2)
                code = proc.wait()
            except BaseException as exc:
                code = 1
                log.write(
                    f"\n[supervisor] {type(exc).__name__}: controller launch failed\n".encode()
                )
            finally:
                if proc is not None:
                    # Detached Harness/Claude/model processes can have distinct PGIDs.
                    # Signal exact nonce-bearing processes, never a recycled PGID.
                    _signal_owned_attempt(nonce, signal.SIGTERM)
                    if proc.poll() is None:
                        try:
                            proc.wait(timeout=2)
                        except subprocess.TimeoutExpired:
                            if _alive(proc.pid, owner.get("runner_start")):
                                proc.kill()
                            proc.wait()
                    remaining = _kill_owned_attempt(nonce)
                else:
                    remaining = 0
        receipt = {
            **owner,
            **_completion(root),
            "exit_code": code,
            "state": "UNKNOWN" if remaining else ("STOPPED" if stop["requested"] else "EXITED"),
            "cleanup_complete": not remaining,
            "residual_processes": remaining,
            "stopped_by_user": stop["requested"],
            "exited_at": _timestamp(),
        }
        receipt["experiment_complete"] = bool(
            code == 0 and not remaining and receipt["experiment_complete"]
        )
        _write(runtime / "controller-exit.json", receipt)
        return 0


def _owned_attempt_processes(nonce: str) -> list[tuple[int, str]]:
    """Read an exact per-attempt marker and Linux start identity for every process."""
    marker = f"AHE_BETA_CONTROLLER_NONCE={nonce}".encode()
    matches = []
    for candidate in Path("/proc").iterdir():
        if not candidate.name.isdigit():
            continue
        pid = int(candidate.name)
        if pid <= 1 or pid == os.getpid():
            continue
        try:
            identity = _process_identity(pid)
            if identity and marker in (candidate / "environ").read_bytes().split(b"\0"):
                matches.append((pid, identity))
        except OSError:
            continue
    return matches


def _signal_owned_attempt(nonce: str, signum: int) -> int:
    """PID fds bind signals to a process even if it exits and its number is reused."""
    marker = f"AHE_BETA_CONTROLLER_NONCE={nonce}".encode()
    signalled = 0
    for pid, identity in _owned_attempt_processes(nonce):
        descriptor = None
        try:
            if hasattr(os, "pidfd_open") and hasattr(signal, "pidfd_send_signal"):
                descriptor = os.pidfd_open(pid)
            # Recheck after obtaining the fd: opening a reused PID must not signal
            # its replacement, nor a child that exec'd with another attempt marker.
            if _process_identity(pid) != identity:
                continue
            if marker not in Path(f"/proc/{pid}/environ").read_bytes().split(b"\0"):
                continue
            if descriptor is not None:
                signal.pidfd_send_signal(descriptor, signum)
            else:
                os.kill(pid, signum)
            signalled += 1
        except (OSError, ValueError):
            continue
        finally:
            if descriptor is not None:
                os.close(descriptor)
    return signalled


def _kill_owned_attempt(nonce: str) -> int:
    """Sweep orphaned detached groups, including children forked during shutdown."""
    deadline = time.monotonic() + 3
    while _owned_attempt_processes(nonce):
        _signal_owned_attempt(nonce, signal.SIGKILL)
        if time.monotonic() >= deadline:
            break
        time.sleep(0.05)
    return len(_owned_attempt_processes(nonce))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Owned experiment controller supervisor")
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--mode", choices=("fresh", "resume"), default="fresh")
    parser.add_argument("--supervise", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--command", help=argparse.SUPPRESS)
    parser.add_argument("--nonce", help=argparse.SUPPRESS)
    parser.add_argument("--inspect", action="store_true")
    parser.add_argument("--stop", action="store_true")
    args = parser.parse_args(argv)
    if args.supervise:
        return _supervise(args.run_dir, json.loads(args.command), args.nonce)
    if args.inspect:
        result = inspect_controller(args.run_dir)
    elif args.stop:
        result = stop_controller(args.run_dir)
    else:
        manifest = _json(args.run_dir / "manifest.json")
        source = materialize_controller_source(args.run_dir, manifest)
        relocated = {**manifest, "run_dir": str(args.run_dir)}
        command = controller_command(relocated, source)
        env = dict(os.environ)
        env["AHE_BETA_RUN_MODE"] = args.mode
        result = launch_controller(run_dir=args.run_dir, command=command, env=env)
    print(json.dumps(result, ensure_ascii=False))
    return 0


# Spec-0079/T4: completion must prove new users actually tested the bootstrap result.
def _bootstrap_completion(*, root: Path, manifest: dict[str, Any], rounds: dict) -> dict:
    receipt = _json(root / "runtime/continuation-bootstrap.json")
    ledger = _json(root / "checkpoints/continuation-bootstrap/recovery.json")
    try:
        input_path = material_path(root, manifest, "continuation_input")
        expected_input = manifest["materials"]["continuation_input"]["sha256"]
        identity = {
            key: manifest[key]
            for key in ("run_id", "experiment_id", "config_hash", "controller_sha")
        }
        identity["plan_hash"] = expected_input
        bootstrap = (ledger.get("rounds") or {}).get("1") or {}
        seal = bootstrap.get("sealed_sha")
        issue_map_path = root / "runtime/continuation-issue-map.json"
        projection = _json(issue_map_path)
        complete = (
            sha256_file(input_path) == expected_input
            and ledger.get("identity") == identity
            and receipt.get("identity") == identity
            and receipt.get("phase") == "continuation-bootstrap"
            and receipt.get("status") == "completed"
            and receipt.get("input_sha256") == expected_input
            and receipt.get("issue_map_sha256") == sha256_file(issue_map_path)
            and projection.get("complete") is True
            and bootstrap.get("status") == "completed"
            and seal == receipt.get("sealed_sha")
            and isinstance(seal, str)
            and len(seal) == 40
            and (rounds.get("1") or {}).get("user_sha") == seal
            and (bootstrap.get("stages", {}).get("feedback_imported") or {}).get("status")
            == "completed"
            and (bootstrap.get("stages", {}).get("round_sealed") or {}).get("status") == "completed"
        )
        return {"complete": bool(complete), "phase": "continuation-bootstrap", "sealed_sha": seal}
    except (OSError, KeyError, ConfigError):
        return {"complete": False, "phase": "continuation-bootstrap"}


if __name__ == "__main__":
    raise SystemExit(main())
