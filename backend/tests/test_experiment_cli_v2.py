"""Spec-0069/T5: the public CLI reports observed outcomes and routes v2 commands."""

import json
from pathlib import Path

import pytest

from auto_designer.experiment import cli, runtime
from auto_designer.experiment.config import ConfigError


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
    from auto_designer.experiment import dashboard

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
    from auto_designer.experiment import dashboard

    def fail(**kwargs):
        raise ConfigError(
            "E2B dashboard requires local artifacts; run experiment collect RUN_ID first"
        )

    monkeypatch.setattr(dashboard, "serve_dashboard", fail)
    assert cli.dispatch(["--json", "dashboard", "selected-run"]) == 2
    assert "collect RUN_ID" in json.loads(capsys.readouterr().out)["error"]
