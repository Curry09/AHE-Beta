"""Spec-0069/T2: frozen runtime wiring and real owned controller supervision."""

from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
import sys
import tarfile
import time
from pathlib import Path

import pytest

from auto_designer.experiment.config import ConfigError
from auto_designer.experiment.context import (
    build_controller_environment,
    frozen_scenario,
    load_controller_context,
)
from auto_designer.experiment.engine import (
    _completion,
    _process_identity,
    controller_command,
    controller_logs,
    inspect_controller,
    launch_controller,
    materialize_controller_source,
    stop_controller,
)


@pytest.fixture
def prepared(tmp_path):
    root = tmp_path / "run"
    (root / "materials").mkdir(parents=True)
    documents = {
        "harness_archive": b"harness",
        "persona_library": b"[]",
        "persona_roster": b'{"personas":[]}',
        "interaction_plan": b"[]",
        "dataset": b"parquet",
        "pool": b'{"instances":[]}',
        "task_package": json.dumps(
            {"id": "task-1", "kind": "ordinary", "instruction_file": "materials/instruction.md"}
        ).encode(),
    }
    materials = {}
    for key, data in documents.items():
        path = root / "materials" / key
        path.write_bytes(data)
        materials[key] = {
            "path": str(path.relative_to(root)),
            "sha256": hashlib.sha256(data).hexdigest(),
        }
    (root / "materials/instruction.md").write_text("Repair the task")
    config = {
        "runtime": {"backend": "local"},
        "workload": {"kind": "ordinary"},
        "rounds": {"count": 2, "sessions_per_round": 1, "max_parallel_users": 1},
        "roles": {"triager": 1, "synthesizer": 2, "divergent": 0, "developer": 1},
        "models": {
            role: {
                "model": f"{role}-model",
                "base_url_env": f"{role.upper()}_URL",
                "api_key_env": f"{role.upper()}_KEY",
            }
            for role in ("user", "harness", "demand", "delivery")
        },
    }
    manifest = {
        "experiment_id": "run-1",
        "run_id": "run-1",
        "run_dir": str(root),
        "config_hash": "c" * 64,
        "controller_sha": "a" * 40,
        "plan_hash": "p" * 64,
        "materials": materials,
        "config": config,
    }
    credentials = {"GITEA_TOKEN": "provider-secret"}
    for role in config["models"]:
        credentials[role.upper() + "_URL"] = "https://model.example/v1"
        credentials[role.upper() + "_KEY"] = role + "-secret"
    resources = {
        "gitea": {
            "url": "http://127.0.0.1:12345",
            "owner": "trial",
            "repo": "run-1",
            "internal_url": "http://gitea:3000",
        },
        "vigil": {"container": "run-1-vigil", "network": "run-1-net", "image": "vigil:pin"},
        "workspace": {
            "kind": "docker-seed",
            "params": {"image": "seed:pin", "instance_id": "task-1"},
        },
    }
    return root, manifest, credentials, resources


def test_complete_model_mapping_and_context_excludes_tokens(prepared, monkeypatch):
    root, manifest, credentials, resources = prepared
    monkeypatch.setenv("HARNESS_LLM_API_KEY", "wrong-host-key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "unrelated-host-key")
    env = build_controller_environment(
        run_dir=root, manifest=manifest, credentials=credentials, resources=resources
    )
    assert env["HARNESS_LLM_API_KEY"] == "harness-secret"
    assert env["USER_LLM_MODEL"] == "user-model"
    assert env["DEMAND_LLM_MODEL"] == "demand-model"
    assert env["ANTHROPIC_AUTH_TOKEN"] == "delivery-secret"
    assert env["ANTHROPIC_SMALL_FAST_MODEL"] == env["ANTHROPIC_MODEL"]
    assert "ANTHROPIC_API_KEY" not in env
    assert env["N_SYNTHESIZERS"] == "2"
    assert env["N_OWNERS"] == "0"
    assert env["TOTAL_ROUNDS"] == "2"
    assert env["AUTO_DESIGNER_OBJECTIVE_EVALUATION"] == "0"
    assert env["VIGIL_KEEP_ALIVE"] == "0"
    document = Path(env["AUTO_DESIGNER_EXPERIMENT_CONTEXT"]).read_text()
    assert "secret" not in document
    context = load_controller_context(env["AUTO_DESIGNER_EXPERIMENT_CONTEXT"])
    assert context.gitea_host == "http://127.0.0.1:12345"
    private = root / "secrets/demand-gitea.env"
    assert private.stat().st_mode & 0o777 == 0o600
    assert "TOKEN=provider-secret" in private.read_text()


def test_standard_anthropic_key_keeps_api_key_auth(prepared):
    root, manifest, credentials, resources = prepared
    manifest["config"]["models"]["delivery"]["api_key_env"] = "ANTHROPIC_API_KEY"
    credentials["ANTHROPIC_API_KEY"] = "standard-secret"
    env = build_controller_environment(
        run_dir=root, manifest=manifest, credentials=credentials, resources=resources
    )
    assert env["ANTHROPIC_API_KEY"] == "standard-secret"
    assert "ANTHROPIC_AUTH_TOKEN" not in env


def test_e2b_swe_context_and_explicit_workspace(prepared, monkeypatch):
    root, manifest, credentials, resources = prepared
    manifest["config"]["runtime"]["backend"] = "e2b"
    manifest["config"]["workload"]["kind"] = "swebench"
    resources["sandbox_id"] = "sandbox-actual"
    resources["workspace"] = {"kind": "prebuilt", "params": {"source": "/workspace/prepared"}}
    env = build_controller_environment(
        run_dir=root, manifest=manifest, credentials=credentials, resources=resources
    )
    assert env["VIGIL_MODE"] == "subprocess"
    assert env["AUTO_DESIGNER_SANDBOX_ID"] == "sandbox-actual"
    assert env["SWEBENCH_PARQUET"].endswith("/materials/dataset")
    assert env["SWEBENCH_INTERACTION_PLAN"] == env["AUTO_DESIGNER_INTERACTION_PLAN"]
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    scenario = frozen_scenario()
    assert scenario.description == "Repair the task"
    assert scenario.workspace.kind == "prebuilt"
    assert scenario.workspace.params["instance_id"] == "task-1"


def test_context_rejects_wrong_backend_workspace_or_missing_keys(prepared):
    root, manifest, credentials, resources = prepared
    resources["workspace"]["kind"] = "prebuilt"
    with pytest.raises(ConfigError, match="docker-seed"):
        build_controller_environment(
            run_dir=root, manifest=manifest, credentials=credentials, resources=resources
        )
    resources["workspace"]["kind"] = "docker-seed"
    del credentials["DEMAND_KEY"]
    with pytest.raises(ConfigError, match="demand"):
        build_controller_environment(
            run_dir=root, manifest=manifest, credentials=credentials, resources=resources
        )


# Spec-0073/T5: the shared runtime accepts original context paths, without host defaults.
def test_shared_runtime_reads_explicit_context_without_repository_env(prepared, monkeypatch):
    from auto_designer.experiment.context import load_controller_context
    from auto_designer.experiment.controllers import runtime as run_mod

    root, manifest, credentials, resources = prepared
    env = build_controller_environment(
        run_dir=root, manifest=manifest, credentials=credentials, resources=resources
    )
    for name in (
        "DATA",
        "HARNESS_REPO",
        "_SANDBOX_ROOT",
        "_VIGIL_CONTAINER",
        "_VIGIL_NETWORK",
        "_VIGIL_CONFIG_STAGING",
        "GITEA_ENV_FILE",
    ):
        monkeypatch.setattr(run_mod, name, getattr(run_mod, name))
    for name in ("AUTO_DESIGNER_EXPERIMENT_ID", "AUTO_DESIGNER_VIGIL_CONTAINER"):
        monkeypatch.setenv(name, os.environ.get(name, ""))
    run_mod.apply_experiment_context(
        ctx=load_controller_context(Path(env["AUTO_DESIGNER_EXPERIMENT_CONTEXT"]))
    )
    assert run_mod.DATA == root / "data"
    assert run_mod.GITEA_ENV_FILE == root / "secrets/demand-gitea.env"


def _wait_exit(root: Path, timeout: float = 8):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = inspect_controller(root)
        if result["state"] in {"EXITED", "STOPPED"}:
            return result
        time.sleep(0.05)
    raise AssertionError(f"Controller did not exit: {inspect_controller(root)}")


def test_real_controller_exit_logs_and_no_false_completion(tmp_path):
    root = tmp_path / "run"
    launch_controller(
        run_dir=root,
        command=[sys.executable, "-c", "print('finished');raise SystemExit(7)"],
        env={"PATH": os.environ["PATH"]},
    )
    result = _wait_exit(root)
    assert result["exit_code"] == 7
    assert result["experiment_complete"] is False
    assert result["runner_start"]
    assert result["command_identity"]
    assert "finished" in controller_logs(root)


def test_duplicate_launch_attaches_and_stop_runs_finally(tmp_path):
    root = tmp_path / "run"
    marker = tmp_path / "cleanup"
    code = (
        "import pathlib,time\n"
        "try:\n while True: time.sleep(.05)\n"
        f"finally: pathlib.Path({str(marker)!r}).write_text('stopped')"
    )
    command = [sys.executable, "-c", code]
    env = {"PATH": os.environ["PATH"]}
    first = launch_controller(run_dir=root, command=command, env=env)
    try:
        # Ensure the runner has installed its try/finally before stopping it.
        time.sleep(0.15)
        second = launch_controller(run_dir=root, command=command, env=env)
        assert second["nonce"] == first["nonce"]
        assert second["runner_pid"] == first["runner_pid"]
        stopped = stop_controller(root, grace_seconds=3)
        assert stopped["state"] == "STOPPED"
        assert stopped["stopped_by_user"] is True
        assert marker.read_text() == "stopped"
        assert _process_identity(first["runner_pid"]) is None
    finally:
        stop_controller(root, grace_seconds=1)


def test_stop_does_not_signal_reused_pid(tmp_path):
    root = tmp_path
    (root / "runtime").mkdir()
    sleeper = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(30)"])
    try:
        (root / "runtime/controller.json").write_text(
            json.dumps(
                {
                    "nonce": "stale",
                    "supervisor_pid": sleeper.pid,
                    "supervisor_start": "wrong",
                    "runner_pid": sleeper.pid,
                    "runner_start": "wrong",
                }
            )
        )
        result = stop_controller(root, grace_seconds=0.1)
        assert result["state"] == "UNKNOWN"
        assert sleeper.poll() is None
    finally:
        sleeper.terminate()
        sleeper.wait(timeout=3)


def test_exit_zero_requires_all_sealed_rounds_and_recovery(tmp_path):
    root = tmp_path
    (root / "manifest.json").write_text(
        json.dumps({"run_id": "run-1", "config": {"rounds": {"count": 2}}})
    )
    directory = root / "data/role_runs/run-1"
    directory.mkdir(parents=True)
    (directory / "manifest.json").write_text(
        json.dumps({"rounds": [{"round": 1, "sealed_sha": "a"}]})
    )
    assert _completion(root)["experiment_complete"] is False
    (directory / "manifest.json").write_text(
        json.dumps({"rounds": [{"round": 1, "sealed_sha": "a"}, {"round": 2, "sealed_sha": "b"}]})
    )
    assert _completion(root)["experiment_complete"] is False
    (root / "checkpoints").mkdir()
    (root / "checkpoints/recovery.json").write_text(
        json.dumps(
            {
                "rounds": {
                    "1": {"status": "completed", "sealed_sha": "a"},
                    "2": {"status": "completed", "sealed_sha": "b"},
                }
            }
        )
    )
    assert _completion(root)["experiment_complete"] is True


def test_materialize_controller_hashes_and_git_guard(prepared):
    root, manifest, _credentials, _resources = prepared
    archive = root / "materials/controller.tar.gz"
    source = root / "origin"
    (source / "backend").mkdir(parents=True)
    code = source / "backend/run.py"
    code.write_text("print('frozen')\n")
    with tarfile.open(archive, "w:gz") as bundle:
        bundle.add(code, arcname="backend/run.py")
    manifest["materials"]["controller_source_archive"] = {
        "path": "materials/controller.tar.gz",
        "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
    }
    manifest["source_snapshot"] = {
        "files": {"backend/run.py": hashlib.sha256(code.read_bytes()).hexdigest()}
    }
    frozen = materialize_controller_source(root, manifest)
    assert (frozen / ".git").is_dir()
    assert (
        subprocess.run(
            ["git", "-C", str(frozen), "rev-parse", "HEAD"], capture_output=True
        ).returncode
        == 0
    )
    assert controller_command(manifest, frozen)[1] == str(frozen / "backend/run.py")
    # Frozen source archives need no .gitignore supplied by a particular checkout.
    # uv-created venvs and interpreter caches remain untracked runtime by-products.
    for generated in (".venv/lib/generated.py", "backend/__pycache__/run.cpython-312.pyc"):
        path = frozen / generated
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("generated")
    clean = subprocess.run(
        ["git", "-C", str(frozen), "status", "--porcelain"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert clean.stdout == ""
    (frozen / "backend/run.py").write_text("print('changed')\n")
    with pytest.raises(ConfigError, match="modified"):
        materialize_controller_source(root, manifest)


def test_supervisor_kills_residual_owned_child(tmp_path):
    root = tmp_path / "run"
    marker = tmp_path / "child.pid"
    child = "import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(30)"
    code = (
        "import subprocess,sys,pathlib,time\n"
        f"p=subprocess.Popen([sys.executable,'-c',{child!r}])\n"
        f"pathlib.Path({str(marker)!r}).write_text(str(p.pid))\n"
        "time.sleep(.2)"
    )
    launch_controller(
        run_dir=root, command=[sys.executable, "-c", code], env={"PATH": os.environ["PATH"]}
    )
    _wait_exit(root)
    pid = int(marker.read_text())
    deadline = time.monotonic() + 3
    while _process_identity(pid) is not None and time.monotonic() < deadline:
        time.sleep(0.05)
    try:
        assert _process_identity(pid) is None
    finally:
        if _process_identity(pid):
            os.kill(pid, signal.SIGKILL)


def test_hard_stop_kills_detached_attempt_children_and_preserves_other_nonce(tmp_path):
    root = tmp_path / "run"
    marker = tmp_path / "detached-pids.json"
    sleeper = "import signal,time;signal.signal(signal.SIGINT,signal.SIG_IGN);signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(30)"
    foreign = subprocess.Popen(
        [sys.executable, "-c", sleeper],
        env={**os.environ, "AUTO_DESIGNER_CONTROLLER_NONCE": "another-attempt"},
        start_new_session=True,
    )
    detached = (
        "import json,os,pathlib,signal,subprocess,sys,time\n"
        "signal.signal(signal.SIGINT,signal.SIG_IGN);signal.signal(signal.SIGTERM,signal.SIG_IGN)\n"
        f'p=subprocess.Popen([sys.executable,"-c",{sleeper!r}],start_new_session=True)\n'
        f"pathlib.Path({str(marker)!r}).write_text(json.dumps([os.getpid(),p.pid]))\n"
        "time.sleep(30)"
    )
    runner = (
        "import signal,subprocess,sys,time\n"
        "signal.signal(signal.SIGINT,signal.SIG_IGN);signal.signal(signal.SIGTERM,signal.SIG_IGN)\n"
        f'subprocess.Popen([sys.executable,"-c",{detached!r}],start_new_session=True)\n'
        "time.sleep(30)"
    )
    owned = []
    try:
        launched = launch_controller(
            run_dir=root, command=[sys.executable, "-c", runner], env={"PATH": os.environ["PATH"]}
        )
        deadline = time.monotonic() + 5
        while not marker.is_file() and time.monotonic() < deadline:
            time.sleep(0.05)
        owned = json.loads(marker.read_text())
        assert all(os.getpgid(pid) != launched["runner_pid"] for pid in owned)
        stopped = stop_controller(root, grace_seconds=0.1)
        assert stopped["state"] == "STOPPED"
        assert stopped["cleanup_complete"] and stopped["residual_processes"] == 0
        assert all(_process_identity(pid) is None for pid in owned)
        assert foreign.poll() is None
    finally:
        stop_controller(root, grace_seconds=0.1)
        for pid in owned:
            if _process_identity(pid):
                os.kill(pid, signal.SIGKILL)
        foreign.kill()
        foreign.wait(timeout=3)


def test_attempt_signalling_does_not_signal_reused_process_identity(monkeypatch):
    from unittest.mock import Mock

    from auto_designer.experiment import engine

    monkeypatch.setattr(engine, "_owned_attempt_processes", lambda nonce: [(123456, "old-start")])
    monkeypatch.setattr(engine, "_process_identity", lambda pid: "replacement-start")
    descriptor = os.open("/dev/null", os.O_RDONLY)
    monkeypatch.setattr(engine.os, "pidfd_open", Mock(return_value=descriptor), raising=False)
    send = Mock()
    monkeypatch.setattr(engine.signal, "pidfd_send_signal", send, raising=False)
    kill = Mock()
    monkeypatch.setattr(engine.os, "kill", kill)
    assert engine._signal_owned_attempt("attempt", signal.SIGKILL) == 0
    send.assert_not_called()
    kill.assert_not_called()


@pytest.mark.parametrize("kind,controller", [("ordinary", "ordinary"), ("swebench", "swebench")])
def test_frozen_module_launch_uses_source_recipe_and_keeps_manifest_identity(
    tmp_path, kind, controller
):
    source = tmp_path / "frozen"
    module = f"auto_designer.experiment.controllers.{controller}"
    relative = "backend/" + module.replace(".", "/") + ".py"
    path = source / relative
    path.parent.mkdir(parents=True)
    path.write_text("print('frozen module executed')\n")
    manifest = {
        "run_id": "saved-run",
        "experiment_id": "saved-run",
        "controller_sha": "fixed-revision",
        "config_hash": "fixed-config",
        "plan_hash": "fixed-plan",
        "config": {"workload": {"kind": kind}},
        "source_snapshot": {
            "files": {relative: hashlib.sha256(path.read_bytes()).hexdigest()},
            "entrypoint": {"kind": "module", "module": module},
        },
    }
    before = json.dumps(manifest, sort_keys=True)
    command = controller_command(manifest, source)
    assert command == [sys.executable, "-m", module]
    result = subprocess.run(
        command,
        env={**os.environ, "PYTHONPATH": str(source / "backend")},
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == "frozen module executed"
    assert json.dumps(manifest, sort_keys=True) == before


@pytest.mark.parametrize(
    "kind,script",
    [
        ("ordinary", "backend/run.py"),
        ("swebench", "backend/scripts/run_swebench_closed_loop.py"),
    ],
)
def test_old_v2_launch_requires_frozen_script_and_preserves_manifest(tmp_path, kind, script):
    manifest = {
        "run_dir": str(tmp_path),
        "config": {"workload": {"kind": kind}},
        "source_snapshot": {"files": {script: "unchanged-frozen-hash"}},
        "materials": {"persona_library": {"path": "personas.json"}},
    }
    (tmp_path / "personas.json").write_text("[]")
    before = json.dumps(manifest, sort_keys=True)
    assert controller_command(manifest, tmp_path)[1] == str(tmp_path / script)
    assert json.dumps(manifest, sort_keys=True) == before
    manifest["source_snapshot"]["files"].clear()
    with pytest.raises(ConfigError, match="original controller script"):
        controller_command(manifest, tmp_path)


def test_module_recipe_cannot_launch_unfrozen_or_unrelated_module(tmp_path):
    manifest = {
        "config": {"workload": {"kind": "ordinary"}},
        "source_snapshot": {
            "files": {},
            "entrypoint": {
                "kind": "module",
                "module": "auto_designer.experiment.controllers.ordinary",
            },
        },
    }
    with pytest.raises(ConfigError, match="entrypoint"):
        controller_command(manifest, tmp_path)
    manifest["source_snapshot"]["entrypoint"]["module"] = "arbitrary.module"
    with pytest.raises(ConfigError, match="entrypoint"):
        controller_command(manifest, tmp_path)


def test_internal_controller_refuses_implicit_repository_configuration(monkeypatch):
    monkeypatch.delenv("AUTO_DESIGNER_EXPERIMENT_CONTEXT", raising=False)
    from auto_designer.experiment.controllers import unified

    with pytest.raises(ConfigError, match="frozen inputs"):
        unified.main()


# Spec-0072/T1: both backends use frozen settings rather than silently ignoring old knobs.
@pytest.mark.parametrize("backend", ["local", "e2b"])
def test_frozen_policy_environment_overrides_host_settings(prepared, monkeypatch, backend):
    root, manifest, credentials, resources = prepared
    manifest["config"]["runtime"]["backend"] = backend
    if backend == "e2b":
        resources["sandbox_id"] = "owned-sandbox"
        resources["workspace"] = {"kind": "prebuilt", "params": {"source": "/workspace"}}
    manifest["config"]["policies"] = {
        "synthesizer_grouping": True,
        "timing": {"latency_isolated": True, "wall_guard_seconds": 4000},
        "delivery": {
            "timeout_seconds": 1800,
            "poll_seconds": 0.5,
            "coordination": "dependencies",
            "permission_mode": "acceptEdits",
            "idle_timeout_seconds": 0,
        },
        "alarms": {"proposal_depth": 7, "ready_depth": 8},
    }
    manifest["config"]["roles"]["owner_mode"] = "llm"
    manifest["config"]["models"]["user"]["reasoning_effort"] = "high"
    manifest["config"]["models"]["demand"]["reasoning_effort"] = "medium"
    expected = {
        "SYNTHESIZER_GROUPING": "1",
        "AUTO_DESIGNER_LATENCY_ISOLATED_TIMEOUT": "1",
        "AUTO_DESIGNER_LATENCY_WALL_GUARD_SECONDS": "4000",
        "ROUND_DELIVERY_TIMEOUT_SEC": "1800",
        "ROUND_DELIVERY_POLL_SEC": "0.5",
        "VIGIL_COORDINATION": "dependencies",
        "OPENAGENTS_PERMISSION_MODE": "acceptEdits",
        "OPENAGENTS_CLAUDE_IDLE_TIMEOUT": "0",
        "PROPOSAL_DEPTH_ALARM": "7",
        "READY_DEPTH_ALARM": "8",
        "N_OWNERS": "1",
        "USER_LLM_REASONING_EFFORT": "high",
        "DEMAND_LLM_REASONING_EFFORT": "medium",
    }
    for key in expected:
        monkeypatch.setenv(key, "unrelated-host-value")
        credentials[key] = "unrelated-env-profile-value"
    env = build_controller_environment(
        run_dir=root, manifest=manifest, credentials=credentials, resources=resources
    )
    assert {key: env[key] for key in expected} == expected
    assert not any("unrelated" in value for value in env.values())


@pytest.mark.parametrize(
    "auth_type, target",
    [
        ("api-key", "ANTHROPIC_API_KEY"),
        ("bearer", "ANTHROPIC_AUTH_TOKEN"),
        ("oauth", "CLAUDE_CODE_OAUTH_TOKEN"),
    ],
)
def test_explicit_delivery_auth_is_independent_of_source_name(
    prepared, monkeypatch, auth_type, target
):
    root, manifest, credentials, resources = prepared
    manifest["config"]["models"]["delivery"].update(
        api_key_env="CUSTOM_DELIVERY_SECRET", auth_type=auth_type
    )
    credentials["CUSTOM_DELIVERY_SECRET"] = "selected-secret"
    auth_vars = {"ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN"}
    for key in auth_vars:
        monkeypatch.setenv(key, "wrong-host-secret")
    env = build_controller_environment(
        run_dir=root, manifest=manifest, credentials=credentials, resources=resources
    )
    assert auth_vars.intersection(env) == {target}
    assert env[target] == "selected-secret"


def test_old_frozen_config_does_not_silently_enable_bypass_permissions(prepared):
    root, manifest, credentials, resources = prepared
    assert "policies" not in manifest["config"]
    before = json.dumps(manifest, sort_keys=True)
    env = build_controller_environment(
        run_dir=root, manifest=manifest, credentials=credentials, resources=resources
    )
    assert "OPENAGENTS_PERMISSION_MODE" not in env
    assert json.dumps(manifest, sort_keys=True) == before


# Spec-0073/T5: new launch contracts coexist with immutable legacy recipes.
def test_new_controller_launch_uses_frozen_unified_module_without_global_kind(tmp_path):
    module = "auto_designer.experiment.controllers.unified"
    relative = "backend/" + module.replace(".", "/") + ".py"
    source = tmp_path / "frozen"
    path = source / relative
    path.parent.mkdir(parents=True)
    path.write_text("print('unified frozen source')\n")
    manifest = {
        "workload_contract_version": 1,
        "config": {"workload": {"task_packages": ["frozen-a", "frozen-b"]}},
        "source_snapshot": {
            "files": {relative: hashlib.sha256(path.read_bytes()).hexdigest()},
            "entrypoint": {"kind": "module", "module": module},
        },
    }
    before = json.dumps(manifest, sort_keys=True)
    command = controller_command(manifest, source)
    result = subprocess.run(
        command,
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(source / "backend")},
        text=True,
        capture_output=True,
        check=True,
    )
    assert result.stdout.strip() == "unified frozen source"
    assert json.dumps(manifest, sort_keys=True) == before


@pytest.mark.parametrize("version", [True, False, "1", None, 0, 2])
def test_unknown_workload_contract_never_falls_back_to_legacy(tmp_path, version):
    manifest = {
        "workload_contract_version": version,
        "config": {"workload": {"kind": "ordinary"}},
        "source_snapshot": {"files": {"backend/run.py": "legacy"}},
    }
    with pytest.raises(ConfigError, match="contract version"):
        controller_command(manifest, tmp_path)


def test_new_contract_refuses_legacy_recipe_even_if_source_contains_it(tmp_path):
    manifest = {
        "workload_contract_version": 1,
        "config": {"workload": {"task_packages": ["task-a"]}},
        "source_snapshot": {
            "files": {"backend/auto_designer/experiment/controllers/ordinary.py": "frozen"},
            "entrypoint": {
                "kind": "module",
                "module": "auto_designer.experiment.controllers.ordinary",
            },
        },
    }
    with pytest.raises(ConfigError, match="entrypoint"):
        controller_command(manifest, tmp_path)


def test_legacy_unknown_kind_is_not_guessed_as_ordinary(tmp_path):
    manifest = {"config": {"workload": {"kind": "mixed"}}, "source_snapshot": {"files": {}}}
    with pytest.raises(ConfigError, match="legacy frozen workload kind"):
        controller_command(manifest, tmp_path)
