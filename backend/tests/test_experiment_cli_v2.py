"""Spec-0069/T5: the public CLI reports observed outcomes and routes v2 commands."""

import json
from pathlib import Path

import pytest

from ahe_beta.experiment import cli, runtime
from ahe_beta.experiment.config import ConfigError


@pytest.mark.parametrize("interaction", ["direct", "simulated_user"])
def test_task_text_emits_existing_package_without_credentials(
    tmp_path, monkeypatch, capsys, interaction
):
    # Spec-0076/T2: material preparation must never enter the provider lifecycle.
    from ahe_beta.experiment.config import load_task_package

    monkeypatch.setattr(
        runtime, "credentials_v2", lambda **kwargs: pytest.fail("no credentials for task import")
    )
    monkeypatch.setattr(
        runtime, "backend_v2", lambda **kwargs: pytest.fail("no provider for task import")
    )
    instruction = tmp_path / "instruction.md"
    original = "Implement a small utility。\r\nPreserve the user's text.\r\n".encode()
    instruction.write_bytes(original)
    output = tmp_path / "converted"
    assert (
        cli.dispatch(
            [
                "--json",
                "--secrets-file",
                "/missing-unneeded.env",
                "task",
                "from-text",
                "--instruction",
                str(instruction),
                "--id",
                "text-task",
                "--output",
                str(output),
                "--not-in-benchmark",
                "--interaction",
                interaction,
            ]
        )
        == 0
    )
    receipt = json.loads(capsys.readouterr().out)
    assert receipt["ok"] is True and len(receipt["task_packages"]) == 1
    package = load_task_package(receipt["task_packages"][0])
    assert package["kind"] == "ordinary" and package["interaction"] == interaction
    assert Path(package["instruction_file"]).read_bytes() == original
    assert instruction.read_bytes() == original


def test_task_from_text_requires_explicit_nonbenchmark_declaration(tmp_path):
    with pytest.raises(SystemExit) as exc:
        cli.dispatch(
            [
                "task",
                "from-text",
                "--instruction",
                "task.md",
                "--id",
                "text-task",
                "--output",
                str(tmp_path / "converted"),
            ]
        )
    assert exc.value.code == 2 and not (tmp_path / "converted").exists()


def test_task_seeds_respects_selection_order_and_reports_existing_output(tmp_path, capsys):
    # Spec-0076/T2: selection belongs to this conversion, not a hidden runtime flag.
    cards = [
        {"id": name, "source": {"not_in_benchmark": True}, "task": {"prompt": name}}
        for name in ("first", "second")
    ]
    library = tmp_path / "library.json"
    library.write_text(json.dumps({"seeds": cards}))
    output = tmp_path / "converted"
    args = [
        "--json",
        "task",
        "import-seeds",
        str(library),
        "--output",
        str(output),
        "--seed",
        "second",
        "--seed",
        "first",
    ]
    assert cli.dispatch(args) == 0
    result = json.loads(capsys.readouterr().out)
    # Original library order defines the workload rotation, even when selecting IDs.
    assert [Path(path).parent.name for path in result["task_packages"]] == ["first", "second"]
    saved = Path(result["index_file"]).read_bytes()
    assert cli.dispatch(args) == 2
    assert "error" in json.loads(capsys.readouterr().out)
    assert Path(result["index_file"]).read_bytes() == saved


@pytest.mark.parametrize("offline", [False, True])
def test_grade_routes_pinned_dataset_without_credentials(monkeypatch, capsys, tmp_path, offline):
    # Spec-0075/T3: global credentials are deliberately absent from the grading API.
    from ahe_beta.experiment import grading

    seen = {}

    def grade(**kwargs):
        seen.update(kwargs)
        return {"ok": True, "run_id": kwargs["run_id"], "offline": kwargs["offline"]}

    monkeypatch.setattr(grading, "grade_run", grade)
    arguments = [
        "--json",
        "--runs-dir",
        str(tmp_path),
        "--secrets-file",
        "/does-not-exist.env",
        "grade",
        "same-run",
        "--plan",
        "grading-plan.json",
        "--round",
        "2",
    ]
    if offline:
        arguments.append("--offline")
    assert cli.dispatch(arguments) == 0
    assert seen == {
        "run_id": "same-run",
        "root": tmp_path,
        "plan": Path("grading-plan.json"),
        "round_no": 2,
        "offline": offline,
    }
    assert json.loads(capsys.readouterr().out)["ok"] is True


def test_grade_incomplete_evidence_returns_business_failure(monkeypatch, capsys):
    from ahe_beta.experiment import grading

    monkeypatch.setattr(
        grading, "grade_run", lambda **kwargs: {"ok": False, "entries": [{"status": "ungradable"}]}
    )
    assert cli.dispatch(["--json", "grade", "same-run", "--plan", "plan.json"]) == 1
    assert json.loads(capsys.readouterr().out)["entries"][0]["status"] == "ungradable"


def test_grade_defaults_to_last_round(monkeypatch):
    from ahe_beta.experiment import grading

    seen = {}
    monkeypatch.setattr(grading, "grade_run", lambda **kwargs: seen.update(kwargs) or {"ok": True})
    assert cli.dispatch(["grade", "run", "--plan", "plan.json"]) == 0
    assert seen["round_no"] is None


@pytest.mark.parametrize("command", ["create", "plan", "preflight", "start", "archive"])
def test_retired_commands_reject_before_runtime(command, monkeypatch):
    # Spec-0071/T3: old commands cannot provision anything through an alias.
    monkeypatch.setattr(
        runtime, "backend_v2", lambda **kwargs: pytest.fail("provider must not be constructed")
    )
    with pytest.raises(SystemExit) as exc:
        cli.dispatch([command])
    assert exc.value.code == 2


@pytest.mark.parametrize("command", ["status", "stop", "resume", "collect", "logs"])
def test_old_manifest_requires_frozen_checkout(command, monkeypatch, tmp_path, capsys):
    directory = tmp_path / "historical"
    directory.mkdir()
    (directory / "manifest.json").write_text(
        json.dumps({"schema_version": 1, "run_id": "historical"})
    )
    monkeypatch.setattr(
        runtime, "backend_v2", lambda **kwargs: pytest.fail("provider must not be constructed")
    )
    assert cli.dispatch(["--json", "--runs-dir", str(tmp_path), command, "historical"]) == 2
    assert "frozen checkout" in json.loads(capsys.readouterr().out)["error"]


def test_check_offline_doesnt_require_credentials_or_provider(monkeypatch, capsys):
    seen = {}

    def check(**kwargs):
        seen.update(kwargs)
        return {"offline": True, "ok": True}

    monkeypatch.setattr(runtime, "check_v2", check)
    assert cli.dispatch(["--json", "check", "--config", "new.json", "--offline"]) == 0
    assert seen["offline"] is True
    assert seen["secrets_file"] is None
    assert json.loads(capsys.readouterr().out)["ok"] is True


def test_prepare_outputs_auto_run_id(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(
        runtime, "prepare_v2", lambda **kwargs: {"run_id": "automatic", "resource_state": "ABSENT"}
    )
    assert (
        cli.dispatch(["--json", "--runs-dir", str(tmp_path), "prepare", "--config", "new.json"])
        == 0
    )
    assert json.loads(capsys.readouterr().out)["run_id"] == "automatic"


def test_resume_uses_same_frozen_run_and_explicit_secrets(monkeypatch, capsys):
    seen = {}

    def run(**kwargs):
        seen.update(kwargs)
        return {"run_id": kwargs["run_id"]}

    monkeypatch.setattr(runtime, "run_v2", run)
    assert cli.dispatch(["--json", "resume", "same-run", "--secrets-file", "private.env"]) == 0
    assert seen["resume_run"] is True
    assert seen["secrets_file"] == Path("private.env")
    assert seen["run_id"] == "same-run"


def test_controlled_error_is_machine_readable(monkeypatch, capsys):
    def fail(**kwargs):
        raise ConfigError("Missing model credential variables: USER_API_KEY")

    monkeypatch.setattr(runtime, "run_v2", fail)
    assert cli.dispatch(["--json", "run", "same-run"]) == 2
    assert "USER_API_KEY" in json.loads(capsys.readouterr().out)["error"]


def test_log_viewer_interrupt_doesnt_stop_controller(monkeypatch):
    monkeypatch.setattr(
        runtime, "logs_v2", lambda **kwargs: (_ for _ in ()).throw(KeyboardInterrupt())
    )
    monkeypatch.setattr(
        runtime, "stop_v2", lambda **kwargs: (_ for _ in ()).throw(AssertionError("must not stop"))
    )
    assert cli.dispatch(["logs", "same-run", "--follow"]) == 130


def test_destroy_discard_is_explicit(monkeypatch):
    seen = {}

    def destroy(**kwargs):
        seen.update(kwargs)
        return {}

    monkeypatch.setattr(runtime, "destroy_v2", destroy)
    assert (
        cli.dispatch(
            [
                "--runs-dir",
                "/tmp/runs",
                "destroy",
                "same-run",
                "--confirm",
                "same-run",
                "--discard-uncollected",
            ]
        )
        == 0
    )
    assert seen["discard_uncollected"] is True


def test_dashboard_routes_explicit_run_and_server_options(monkeypatch):
    from ahe_beta.experiment import dashboard

    seen = {}
    monkeypatch.setattr(dashboard, "serve_dashboard", lambda **kwargs: seen.update(kwargs))
    assert (
        cli.dispatch(
            [
                "--runs-dir",
                "/tmp/runs",
                "dashboard",
                "selected-run",
                "--host",
                "localhost",
                "--port",
                "8123",
                "--secrets-file",
                "/tmp/private.env",
            ]
        )
        == 0
    )
    assert seen == {
        "run_id": "selected-run",
        "root": Path("/tmp/runs"),
        "secrets_file": Path("/tmp/private.env"),
        "host": "localhost",
        "port": 8123,
    }


def test_dashboard_uncollected_error_is_actionable(monkeypatch, capsys):
    from ahe_beta.experiment import dashboard

    def fail(**kwargs):
        raise ConfigError(
            "E2B dashboard requires local artifacts; run experiment collect RUN_ID first"
        )

    monkeypatch.setattr(dashboard, "serve_dashboard", fail)
    assert cli.dispatch(["--json", "dashboard", "selected-run"]) == 2
    assert "collect RUN_ID" in json.loads(capsys.readouterr().out)["error"]


@pytest.mark.parametrize(
    "command", ["check", "prepare", "run", "resume", "status", "stop", "collect"]
)
def test_batch_verbs_preserve_explicit_root_and_credentials(command, monkeypatch, capsys):
    # Spec-0074/T3: all management verbs accept credentials after the verb.
    from ahe_beta.experiment import batch

    seen = {}

    def handle(**kwargs):
        seen.update(kwargs)
        progress = kwargs.get("progress")
        if progress:
            progress({"batch_id": "selected-batch", "phase": "PREPARING", "entry_id": "u1"})
        return {"batch_id": "selected-batch", "ok": True, "batch_state": "READY"}

    target = "run" if command == "resume" else command
    monkeypatch.setattr(batch, target + "_batch", handle)
    argv = ["--json", "--runs-dir", "/tmp/runs", "--secrets-file", "global.env", "batch", command]
    argv += ["--config", "list.json"] if command in {"check", "prepare"} else ["selected-batch"]
    argv += ["--secrets-file", "override.env"]
    assert cli.dispatch(argv) == 0
    output = capsys.readouterr()
    assert json.loads(output.out)["batch_id"] == "selected-batch"
    assert seen["secrets_file"] == Path("override.env")
    if command == "check":
        assert seen["offline"] is False and seen["config_path"] == Path("list.json")
    else:
        assert seen["root"] == Path("/tmp/runs")
    if command in {"run", "resume"}:
        assert seen["resume_batch"] is (command == "resume")
    if "progress" in seen:
        assert "[batch] selected-batch" in output.err
        assert "[batch]" not in output.out


@pytest.mark.parametrize(
    "state,ok,exit_code",
    [
        ("COMPLETED", True, 0),
        ("PAUSED", True, 0),
        ("BLOCKED_LOST", False, 1),
        ("INTERRUPTED", True, 130),
    ],
)
def test_batch_exit_codes_distinguish_completion_blocking_and_detach(
    state, ok, exit_code, monkeypatch, capsys
):
    from ahe_beta.experiment import batch

    monkeypatch.setattr(batch, "run_batch", lambda **kwargs: {"batch_state": state, "ok": ok})
    monkeypatch.setattr(runtime, "stop_v2", lambda **kwargs: pytest.fail("detach must not stop"))
    assert cli.dispatch(["--json", "batch", "run", "chosen"]) == exit_code
    assert json.loads(capsys.readouterr().out)["batch_state"] == state


def test_batch_check_offline_routes_without_loading_credentials(monkeypatch, capsys):
    from ahe_beta.experiment import batch

    seen = {}

    def check(**kwargs):
        seen.update(kwargs)
        return {"ok": True, "offline": kwargs["offline"]}

    monkeypatch.setattr(batch, "check_batch", check)
    assert cli.dispatch(["--json", "batch", "check", "--config", "list.json", "--offline"]) == 0
    assert seen["offline"] is True and seen["secrets_file"] is None
    assert json.loads(capsys.readouterr().out)["offline"] is True


def test_batch_provider_exception_cannot_leak_credential_text(monkeypatch, capsys):
    from ahe_beta.experiment import batch

    def fail(**kwargs):
        raise OSError("sensitive-provider-value")

    monkeypatch.setattr(batch, "status_batch", fail)
    assert cli.dispatch(["--json", "batch", "status", "chosen"]) == 2
    output = capsys.readouterr()
    assert "sensitive-provider-value" not in output.out + output.err
    assert "error" in json.loads(output.out)


def test_batch_progress_shows_user_completion_without_polluting_json(capsys):
    cli._batch_progress(
        {
            "batch_id": "chosen",
            "batch_state": "RUNNING",
            "counts": {"active": 1, "pending": 1, "completed": 0},
            "entries": {
                "u4": {
                    "last_status": {
                        "progress": {
                            "current_round": 2,
                            "rounds": {
                                "2": {"users": {"expected": 4, "completed": 3, "running": 1}}
                            },
                        }
                    }
                }
            },
        }
    )
    output = capsys.readouterr()
    assert output.out == ""
    assert "u4 R2: 3/4 sessions completed, 1 running" in output.err


@pytest.mark.parametrize(
    "args",
    [
        ["batch"],
        ["batch", "run"],
        ["batch", "destroy", "x"],
        ["batch", "run", "--config", "list.json"],
    ],
)
def test_batch_rejects_missing_identity_and_second_launcher_options(args):
    with pytest.raises(SystemExit) as exc:
        cli.dispatch(args)
    assert exc.value.code == 2
