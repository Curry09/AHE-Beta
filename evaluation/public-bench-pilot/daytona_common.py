"""Small local-only Daytona controller helpers (no benchmark imports)."""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import time
from collections.abc import Iterable
from datetime import UTC, datetime
from getpass import getpass
from pathlib import Path

from daytona import SessionExecuteRequest

ROOT = Path(__file__).resolve().parents[2]


def harness_archive_path(here: Path) -> Path:
    """Resolve the harness under test without implying a specific version."""
    configured = os.environ.get("HARNESS_ARCHIVE") or os.environ.get(
        "HARNESS_V0_ARCHIVE"
    )
    return Path(configured) if configured else here / "artifacts/harness-v0-cade14d.tar.gz"


def harness_eval_label(archive: Path) -> str:
    return os.environ.get("HARNESS_EVAL_LABEL", archive.name.removesuffix(".tar.gz"))


def safe_run_label(label: str) -> str:
    cleaned = "".join(c if c.isalnum() or c in "-_" else "-" for c in label)
    return cleaned.strip("-")[:80] or "unlabeled-harness"


def evaluation_model() -> str:
    return os.environ.get("HARNESS_MODEL", "z-ai/glm-5.2")


def user_simulator_model() -> str:
    return os.environ.get("USER_SIMULATOR_MODEL", evaluation_model())


def openrouter_litellm_model(model: str) -> str:
    return model if model.startswith("openrouter/") else f"openrouter/{model}"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def prepared_root(here: Path) -> Path:
    """Resolve the intentionally external, controller-private prepared data."""
    configured = os.environ.get("PUBLIC_BENCH_PREPARED_DIR")
    candidates = [
        Path(configured).expanduser() if configured else None,
        here / "prepared",
        here.parents[2]
        / "auto-designer-experiment-configs/public-bench-pilot-20260917/prepared",
    ]
    for candidate in candidates:
        if candidate is not None and candidate.is_dir():
            return candidate.resolve()
    raise FileNotFoundError(
        "prepared benchmark data not found; set PUBLIC_BENCH_PREPARED_DIR"
    )


def load_env(path: Path | None = None) -> dict[str, str]:
    configured = os.environ.get("PUBLIC_BENCH_ENV_FILE")
    candidates = (
        [path]
        if path is not None
        else [Path(configured)]
        if configured
        else [ROOT / ".env", ROOT.parent / ".env"]
    )
    path = next((candidate for candidate in candidates if candidate.is_file()), candidates[0])
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("\"'")
    return values


def credentials() -> tuple[str, str]:
    values = load_env()
    daytona_key = os.environ.get("DAYTONA_API_KEY") or getpass("Daytona API key: ")
    model_key = os.environ.get("OPENROUTER_API_KEY") or values.get(
        "openrouter_api_key", ""
    )
    if not model_key:
        raise SystemExit("OPENROUTER_API_KEY is unavailable")
    return daytona_key, model_key


def new_run_dir(base: Path, suffix: str) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    target = base / "runs" / f"{stamp}-{suffix}"
    target.mkdir(parents=True, exist_ok=False)
    return target


def exec_logged(sandbox, run_dir: Path, name: str, command: str, timeout: int):
    print(f"REMOTE_START {name}", flush=True)
    response = sandbox.process.exec(command, timeout=timeout)
    (run_dir / f"remote-{name}.log").write_text(
        response.result or "", encoding="utf-8"
    )
    print(f"REMOTE_END {name} exit={response.exit_code}", flush=True)
    if response.exit_code != 0:
        tail = (response.result or "")[-3000:]
        raise RuntimeError(f"remote step {name} failed ({response.exit_code}): {tail}")
    return response


def exec_async_logged(
    sandbox, run_dir: Path, name: str, command: str, timeout: int
) -> tuple[int, str, str]:
    """Run a long remote command without holding one HTTP request open."""
    session_id = f"pilot-{name}"
    sandbox.process.create_session(session_id)
    try:
        started = sandbox.process.execute_session_command(
            session_id,
            SessionExecuteRequest(command=command, run_async=True),
            timeout=60,
        )
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            current = sandbox.process.get_session_command(session_id, started.cmd_id)
            if current.exit_code is not None:
                logs = sandbox.process.get_session_command_logs(session_id, started.cmd_id)
                stdout = logs.stdout or ""
                stderr = logs.stderr or ""
                (run_dir / f"remote-{name}.log").write_text(
                    stdout, encoding="utf-8"
                )
                (run_dir / f"remote-{name}-stderr.log").write_text(
                    stderr, encoding="utf-8"
                )
                return int(current.exit_code), stdout, stderr
            time.sleep(5)
        logs = sandbox.process.get_session_command_logs(session_id, started.cmd_id)
        stdout = logs.stdout or ""
        stderr = logs.stderr or ""
        (run_dir / f"remote-{name}.log").write_text(stdout, encoding="utf-8")
        (run_dir / f"remote-{name}-stderr.log").write_text(
            stderr, encoding="utf-8"
        )
        raise TimeoutError(f"remote async step {name} exceeded {timeout}s")
    finally:
        try:
            sandbox.process.delete_session(session_id)
        except Exception:
            pass


def download_if_present(sandbox, remote: str, local: Path) -> bool:
    probe = sandbox.process.exec(f"test -f {remote}", timeout=30)
    if probe.exit_code != 0:
        return False
    sandbox.fs.download_file(remote, str(local))
    return True


def download_artifacts(
    sandbox, run_dir: Path, names: Iterable[str], remote_dir: str = "/tmp/eval-output"
) -> None:
    for name in names:
        download_if_present(sandbox, f"{remote_dir}/{name}", run_dir / name)


def upload_tree(sandbox, local_root: Path, remote_root: str) -> None:
    """Upload a small benchmark fixture tree without local archive tooling."""
    for path in sorted(local_root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(local_root).as_posix()
        remote = f"{remote_root.rstrip('/')}/{relative}"
        parent = remote.rsplit("/", 1)[0]
        response = sandbox.process.exec(
            f"mkdir -p {shlex.quote(parent)}", timeout=30
        )
        if response.exit_code != 0:
            raise RuntimeError(f"could not create remote directory {parent}")
        sandbox.fs.upload_file(str(path), remote)


def write_controller_manifest(run_dir: Path, payload: dict) -> None:
    (run_dir / "controller-manifest.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
