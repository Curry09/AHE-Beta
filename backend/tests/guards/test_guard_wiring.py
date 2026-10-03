"""Spec-0068/T6: the real seed entrypoint installs the relocated guard after seeding."""

import importlib
import subprocess
from pathlib import Path

import pytest

from auto_designer.guards import harness_boundary
from auto_designer.guards.workspace_jail import WorkspaceJailMiddleware


def test_seed_entrypoint_installs_guard_after_initial_commit(monkeypatch, tmp_path):
    run = importlib.import_module("auto_designer.experiment.controllers.runtime")
    backend = tmp_path / "backend"
    template = backend / "harness_template"
    template.mkdir(parents=True)
    (template / "entry.py").write_text("print('seed')\n")
    repo = tmp_path / "new-harness"
    monkeypatch.setattr(run, "ROOT", backend)
    monkeypatch.setattr(run, "HARNESS_REPO", repo)
    monkeypatch.delenv("AUTO_DESIGNER_HARNESS_ARCHIVE", raising=False)
    for name in ("GIT_AUTHOR_NAME", "GIT_COMMITTER_NAME"):
        monkeypatch.setenv(name, "Offline Test")
    for name in ("GIT_AUTHOR_EMAIL", "GIT_COMMITTER_EMAIL"):
        monkeypatch.setenv(name, "offline@example.invalid")
    installed = []
    original = harness_boundary.install_pre_commit

    def install_after_seed(path):
        count = subprocess.check_output(["git", "-C", str(path), "rev-list", "--count", "HEAD"])
        assert count.strip() == b"1"
        installed.append(path)
        original(path)

    monkeypatch.setattr(harness_boundary, "install_pre_commit", install_after_seed)
    assert run._seed_harness_repo() == repo
    assert installed == [repo]
    (repo / ".env").write_text("API_KEY=offline-sentinel\n")
    subprocess.run(["git", "-C", str(repo), "add", ".env"], check=True)
    result = subprocess.run(
        ["git", "-C", str(repo), "commit", "-m", "test: reject private file"],
        text=True,
        capture_output=True,
    )
    assert result.returncode != 0
    assert "harness-boundary" in result.stderr


@pytest.mark.parametrize("role", ["triage_agent", "synthesizer", "divergent_pm", "owner"])
def test_real_agent_yaml_resolves_middleware_and_tool_bindings(role, monkeypatch, tmp_path):
    from nexau import AgentConfig

    monkeypatch.setenv("DEMAND_LLM_MODEL", "offline-test")
    monkeypatch.setenv("DEMAND_LLM_API_KEY", "offline-only")
    monkeypatch.setenv("DEMAND_LLM_BASE_URL", "http://127.0.0.1:9/v1")
    monkeypatch.setenv("SANDBOX_WORK_DIR", str(tmp_path))
    config = AgentConfig.from_yaml(
        config_path=Path(__file__).resolve().parents[3] / "backend/agent_defs" / role / "agent.yaml"
    )
    assert any(isinstance(m, WorkspaceJailMiddleware) for m in config.middlewares)
    assert config.tools
    assert config.llm_config.model == "offline-test"
