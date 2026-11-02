"""Spec-0070/T3: freeze transport and verify the actual delivery reader before models run."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import uuid
from collections.abc import Callable
from pathlib import Path

from ahe_beta.observations.publication import bounded_command, preflight_root
from ahe_beta.observations.transport import (
    freeze_transport_profile,
    load_transport_profile,
)

CAPABILITY_SCHEMA = "openagents-observation-reader-capabilities-v1"
READER_RECORD = ".reader-capabilities.json"


def needs_reader_capabilities(*, profile: dict) -> bool:
    """Legacy gzip/direct deployments do not require a new OpenAgents command."""
    return profile["encoding"] != "gzip" or profile["download_policy"] != "same-origin-v1"


def validate_reader_capabilities(*, capabilities: dict, profile: dict) -> None:
    """Check a versioned contract, not a package version string or stdout substring."""
    expected = {
        "schema": CAPABILITY_SCHEMA,
        "marker": "auto-designer:observation-evidence-v1",
        "max_transfer_bytes": profile["max_transfer_bytes"],
        "max_expanded_bytes": profile["max_expanded_bytes"],
    }
    if not isinstance(capabilities, dict) or any(
        capabilities.get(key) != value for key, value in expected.items()
    ):
        raise ValueError(
            "OpenAgents observation capability contract/limits mismatch; upgrade reader"
        )
    for key, required in (
        ("encodings", profile["encoding"]),
        ("download_policies", profile["download_policy"]),
    ):
        values = capabilities.get(key)
        if not isinstance(values, list) or required not in values:
            raise ValueError(f"OpenAgents lacks observation {key}: {required}; upgrade reader")
    if (
        profile["encoding"] == "zip"
        and capabilities.get("zip_profile") != "single-evidence-json-v1"
    ):
        raise ValueError("OpenAgents ZIP profile mismatch; upgrade reader")


def _command_json(*, argv: list[str]) -> dict:
    try:
        raw = bounded_command(argv, timeout=10, limit=16 * 1024)
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError("expected object")
        return value
    except (OSError, ValueError, subprocess.TimeoutExpired):
        raise ValueError(
            "OpenAgents observation capability check failed; use a compatible actual reader runtime"
        ) from None


def probe_reader(
    *, mode: str, image: str, container: str | None = None, executable: str | None = None
) -> dict:
    """Run a bounded, credential-free capability command in the selected installation."""
    command = ["observation-capabilities", "--json"]
    if mode == "subprocess":
        selected = executable or shutil.which("openagents")
        if not selected:
            raise ValueError("OpenAgents executable missing; install the compatible reader")
        selected = str(Path(selected).absolute())
        capabilities = _command_json(
            argv=["env", "OPENAGENTS_NO_SELF_UPDATE=1", selected, *command]
        )
        runtime = {"mode": mode, "executable": selected}
    elif mode == "container":
        if container:
            # An exec-only override cannot freeze the already-running vigil process.
            frozen = bounded_command(
                [
                    "docker",
                    "inspect",
                    "--format",
                    '{{range .Config.Env}}{{if eq . "OPENAGENTS_NO_SELF_UPDATE=1"}}frozen{{end}}{{end}}',
                    container,
                ],
                timeout=10,
                limit=256,
            ).strip()
            if frozen != b"frozen":
                raise ValueError("Recreate the delivery container with OPENAGENTS_NO_SELF_UPDATE=1")
            capabilities = _command_json(
                argv=[
                    "docker",
                    "exec",
                    "-e",
                    "OPENAGENTS_NO_SELF_UPDATE=1",
                    container,
                    "openagents",
                    *command,
                ]
            )
            identity = (
                bounded_command(
                    ["docker", "inspect", "--format", "{{.Image}}", container],
                    timeout=10,
                    limit=256,
                )
                .decode()
                .strip()
            )
            runtime = {"mode": mode, "container": container, "image_id": identity}
        else:
            identity = (
                bounded_command(
                    ["docker", "image", "inspect", "--format", "{{.Id}}", image],
                    timeout=10,
                    limit=256,
                )
                .decode()
                .strip()
            )
            if not re.fullmatch(r"sha256:[a-f0-9]{64}", identity):
                raise ValueError("OpenAgents image did not resolve to an immutable image ID")
            name = "observation-reader-check-" + uuid.uuid4().hex
            try:
                capabilities = _command_json(
                    argv=[
                        "docker",
                        "run",
                        "--rm",
                        "--name",
                        name,
                        "--network",
                        "none",
                        "--entrypoint",
                        "openagents",
                        "-e",
                        "OPENAGENTS_NO_SELF_UPDATE=1",
                        identity,
                        *command,
                    ]
                )
            finally:
                # Killing a timed-out docker CLI alone leaves the daemon's container alive.
                # The unique name limits cleanup to this probe, never a reused vigil.
                try:
                    bounded_command(["docker", "rm", "--force", name], timeout=10, limit=256)
                except (OSError, ValueError, subprocess.TimeoutExpired):
                    pass  # --rm normally removed a completed probe already.
            runtime = {"mode": mode, "image_id": identity}
        if not re.fullmatch(r"sha256:[a-f0-9]{64}", runtime["image_id"]):
            raise ValueError("OpenAgents container image identity is invalid")
    else:
        raise ValueError("Unsupported OpenAgents reader runtime mode")
    return {"capabilities": capabilities, "runtime": runtime}


def reusable_container(*, name: str) -> str | None:
    """Select only the same run's container; its installed reader takes precedence over tags."""
    try:
        state = (
            bounded_command(
                [
                    "docker",
                    "inspect",
                    "--format",
                    '{{.State.Running}}|{{index .Config.Labels "io.ahe-beta.run_id"}}|'
                    '{{index .Config.Labels "io.openagents.experiment_id"}}',
                    name,
                ],
                timeout=10,
                limit=4096,
            )
            .decode()
            .strip()
            .split("|")
        )
    except OSError:
        return None
    if len(state) != 3:
        raise ValueError("Invalid delivery container identity response")
    running, run_id, experiment = state
    if running != "true":
        return None
    experiment = "" if experiment == "<no value>" else experiment
    run_id = "" if run_id == "<no value>" else run_id
    if experiment and experiment != os.environ.get("AHE_BETA_EXPERIMENT_ID", "").strip():
        raise ValueError("refusing to probe another experiment's delivery container")
    expected_run = os.environ.get("AHE_BETA_RUN_ID", "").strip()
    return name if not expected_run or run_id == expected_run else None


def probe_reader_from_environment() -> dict:
    """Probe the planned image or executable; reused containers are rechecked before attach."""
    mode = os.environ.get("VIGIL_MODE", "").strip().lower() or "container"
    container = (
        reusable_container(name=os.environ.get("AHE_BETA_VIGIL_CONTAINER", "ahe-beta-vigil"))
        if mode == "container"
        else None
    )
    return probe_reader(
        mode=mode,
        image=os.environ.get("AHE_BETA_VIGIL_IMAGE", "").strip() or "ahe-beta-vigil:latest",
        container=container,
    )


def write_reader_record(*, root: Path, profile: dict, result: dict) -> None:
    """Record only validated capabilities and local runtime identity, never credentials."""
    validate_reader_capabilities(capabilities=result["capabilities"], profile=profile)
    _write_json(
        path=root / READER_RECORD,
        value={"schema": "observation-reader-check-v1", "profile": profile, **result},
    )


def _write_json(*, path: Path, value: dict) -> None:
    if path.is_symlink():
        raise ValueError("linked observation contract")
    fd, name = tempfile.mkstemp(prefix=".preflight-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def prepare_observations(
    *, tracker, root: Path, reader_probe: Callable[[], dict] | None = None
) -> dict | None:
    """Bind an explicitly checked profile before existing framework-contract validation."""
    preflight_root(root)
    preflight = getattr(tracker, "preflight_observations", None)
    if preflight is None:
        return None
    profile, result = None, None
    select = getattr(tracker, "select_observation_transport", None)
    if select is not None:
        candidate = select()
        profile = load_transport_profile(root=root, repository=candidate["repository"]) or candidate
        if needs_reader_capabilities(profile=profile):
            result = (reader_probe or probe_reader_from_environment)()
            validate_reader_capabilities(capabilities=result["capabilities"], profile=profile)
        tracker.bind_observation_transport(profile=profile, reader_verified=result is not None)
    contract = preflight()
    binding = root / ".framework-contract.json"
    if binding.is_symlink():
        raise ValueError("linked observation contract")
    if binding.exists() and json.loads(binding.read_text()) != contract:
        raise ValueError("observation root already belongs to a different repository/contract")
    if profile is not None:
        freeze_transport_profile(root=root, profile=profile)
    if result is not None:
        write_reader_record(root=root, profile=profile, result=result)
    if not binding.exists():
        _write_json(path=binding, value=contract)
    return profile
