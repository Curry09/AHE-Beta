"""Regression tests for interrupted runs and stable observation snapshots."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest


def load(name):
    path = Path(__file__).parents[1] / "harness-suite-20260920" / (name + ".py")
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def sandbox(exit_code="", running=True, malformed=False):
    ledger = {
        "round": 1,
        "revision": 71,
        "padding": "x" * 300_000,
        "rounds": {
            "1": {"stages": {"users": {"status": "completed"}, "triage": {"status": "running"}}}
        },
    }

    def read(path, **kwargs):
        if path.endswith("/recovery.json"):
            return "invalid" if malformed else json.dumps(ledger)
        if path.endswith("/run.json"):
            return json.dumps({"running": running, "round": 1, "total_rounds": 5})
        if path.endswith("/exit_code"):
            return exit_code
        return "{}"

    return SimpleNamespace(
        files=SimpleNamespace(read=read),
        commands=SimpleNamespace(
            run=lambda cmd, **kw: SimpleNamespace(
                stdout="22 openagents vigil --parallel 4" if cmd.startswith("ps") else ""
            )
        ),
    )


def test_large_json_not_truncated():
    relay = load("sync_status_vps")
    value, _, _ = relay.snapshot(sandbox(), "test", "sb")
    assert value["recovery_revision"] == 71
    assert value["phase"] == "triage"
    assert value["components"][0]["state"] == "finished"
    assert value["components"][1]["state"] == "running"


@pytest.mark.parametrize("exit_code", ["", "1"])
def test_stopped_controller_never_means_success(exit_code):
    relay = load("sync_status_vps")
    value, _, _ = relay.snapshot(sandbox(exit_code=exit_code, running=False), "test", "sb")
    assert value["state"] == "controller_exited"
    if exit_code:
        assert value["components"][1]["state"] == "interrupted"
        assert value["components"][-1]["state"] == "retained"
        assert value["components"][-1]["process_running"] is True


def test_failed_read_does_not_publish_empty_progress():
    relay = load("sync_status_vps")
    with pytest.raises(ValueError, match="retaining"):
        relay.snapshot(sandbox(malformed=True), "test", "sb")


def test_recovery_download_timeout_uses_small_command_projection():
    relay = load("sync_status_vps")
    compile(relay._RECOVERY_PROJECTION, "<recovery-projection>", "exec")
    fake = sandbox()
    original_read = fake.files.read

    def read(path, **kwargs):
        if path.endswith("/recovery.json"):
            raise TimeoutError("file transfer stalled")
        return original_read(path, **kwargs)

    fake.files.read = read
    fake.commands.run = lambda command, **kwargs: SimpleNamespace(
        stdout=json.dumps(
            {
                "round": 1,
                "revision": 71,
                "rounds": {
                    "1": {
                        "stages": {
                            "users": {"status": "completed"},
                            "triage": {"status": "running"},
                        }
                    }
                },
            }
        )
        if command.startswith("python3 -c ")
        else ""
    )
    value, _, _ = relay.snapshot(fake, "test", "sb")
    assert value["recovery_revision"] == 71
    assert value["phase"] == "triage"


def test_single_command_snapshot_uses_compact_bundle():
    relay = load("sync_status_vps")
    compile(relay._REMOTE_COLLECT, "<remote-collect>", "exec")
    fake = sandbox()
    fake.files.read = lambda *args, **kwargs: pytest.fail("bundle should avoid file transfers")
    bundle = {
        "run": {"running": True, "round": 1, "total_rounds": 5},
        "agents": {},
        "recovery": {
            "round": 1,
            "revision": 72,
            "rounds": {
                "1": {"stages": {"users": {"status": "completed"}, "triage": {"status": "running"}}}
            },
        },
        "runtime": {"runs": {}},
        "env": "USER_LLM_BASE_URL=https://api.boyuerichdata.opensphereai.com/v1",
        "exit_code": "",
        "log_tail": "recent log",
        "events": "recent event",
        "timing": "",
        "openagents_running": True,
    }
    fake.commands.run = lambda command, **kwargs: SimpleNamespace(stdout=json.dumps(bundle))
    value, events, log_tail = relay.snapshot(fake, "test", "sb")
    assert value["recovery_revision"] == 72
    assert value["phase"] == "triage"
    assert value["api_sources"]["user"] == "Boyue"
    assert value["components"][-1]["process_running"] is True
    assert (events, log_tail) == ("recent event", "recent log")


def test_command_timeout_reconnects_without_slow_file_fallback():
    relay = load("sync_status_vps")
    fake = sandbox()
    fake.files.read = lambda *args, **kwargs: pytest.fail(
        "timed out command should reopen connection"
    )
    fake.commands.run = lambda *args, **kwargs: (_ for _ in ()).throw(
        TimeoutError("E2B stream stalled")
    )
    with pytest.raises(TimeoutError, match="E2B stream stalled"):
        relay.snapshot(fake, "test", "sb")


def test_dashboard_order_stable_and_keeps_unreadable_snapshot(tmp_path):
    dashboard = load("vps_status_dashboard")
    dashboard.ROOT = tmp_path
    for run_id, stamp in [("20260101-a", "z"), ("20260102-b", "a")]:
        directory = tmp_path / run_id
        directory.mkdir()
        (directory / "status.json").write_text(json.dumps({"run_id": run_id, "updated_at": stamp}))
    assert [r["run_id"] for r in dashboard._runs()] == ["20260102-b", "20260101-a"]
    (tmp_path / "20260101-a/status.json").write_text("{")
    assert [r["run_id"] for r in dashboard._runs()] == ["20260102-b", "20260101-a"]


def test_atomic_status_publish(tmp_path):
    relay = load("sync_status_vps")
    ask = tmp_path / "askpass"
    ask.touch()
    local = tmp_path / "local"
    local.mkdir()
    (local / "status.json").write_text(json.dumps({"run_id": "run", "round": 2}))
    (local / "events.jsonl").write_text("event\n")
    (local / "log.tail").write_text("log\n")
    calls = []
    real_run = subprocess.run

    def run(cmd, **kwargs):
        calls.append(cmd)
        assert cmd[0] == "ssh"
        return real_run(
            [sys.executable, "-c", relay._REMOTE_PUBLISH],
            input=kwargs["input"],
            text=True,
            capture_output=True,
            timeout=5,
        )

    with (
        patch.object(relay, "_ssh_env", return_value=({}, ask)),
        patch.object(relay.subprocess, "run", side_effect=run),
    ):
        assert relay.push(local, "host", "redacted", str(tmp_path / "remote"), "run", "22")
    assert len(calls) == 1
    remote = tmp_path / "remote" / "run"
    assert json.loads((remote / "status.json").read_text())["round"] == 2
    assert (remote / "events.jsonl").read_text() == "event\n"
    assert (remote / "log.tail").read_text() == "log\n"


def test_ssh_uses_configured_socks_proxy(monkeypatch):
    relay = load("sync_status_vps")
    monkeypatch.delenv("HSE_VPS_SSH_PROXY", raising=False)
    monkeypatch.setenv("ALL_PROXY", "socks5://127.0.0.1:7890")
    assert relay._ssh_proxy_options() == ["-o", "ProxyCommand=nc -X 5 -x 127.0.0.1:7890 %h %p"]


def test_public_mode_filters_raw_logs():
    dashboard = load("vps_status_dashboard")
    result = dashboard.public_status(
        {"run_id": "test", "log_tail": "secret", "events": ["secret"], "sandbox_id": "private"}
    )
    assert "secret" not in json.dumps(result)
    assert "sandbox_id" not in result


def test_api_sources_use_effective_endpoints_without_exposing_keys():
    relay = load("sync_status_vps")
    sources = relay.api_sources("""HARNESS_LLM_BASE_URL=https://openrouter.ai/api/v1
USER_LLM_BASE_URL=https://api.boyuerichdata.opensphereai.com/v1
DESIGNER_LLM_BASE_URL=https://aigateway.paperbypass.com/v1
DESIGNER_LLM_API_KEY=secret-value
""")
    assert sources == {"harness": "OpenRouter", "user": "Boyue", "designer": "WIS"}
    assert "secret-value" not in json.dumps(sources)
    dashboard = load("vps_status_dashboard")
    public = dashboard.public_status({"api_sources": {**sources, "token": "secret-value"}})
    assert public["api_sources"] == sources
