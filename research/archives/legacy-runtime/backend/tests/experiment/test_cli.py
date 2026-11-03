# Spec-0047/T4: CLI idempotency and keyless plan.
from __future__ import annotations

import json
from pathlib import Path

from auto_designer.experiment import cli
from auto_designer.experiment.manifest import last_state


def _yaml(tmp_path: Path, *, experiment_id: str) -> Path:
    path = tmp_path / f"{experiment_id}.yaml"
    path.write_text(
        "\n".join(
            [
                "schema_version: 1",
                f"experiment_id: {experiment_id}",
                "mode: full-evolution",
                "source:",
                "  auto_designer_sha: abcdef",
                "images:",
                "  vigil: sha256:vigilpin",
                "models:",
                "  profile: glm-local",
                "capacity:",
                "  endpoint: glm-local",
                "infrastructure:",
                "  isolation: dedicated",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def test_cli_create_plan_status_json(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("EXPERIMENTS_ROOT", str(tmp_path))
    cfg = _yaml(tmp_path, experiment_id="exp-cli")
    assert cli.dispatch(["--json", "create", "--config", str(cfg)]) == 0
    capsys.readouterr()
    assert last_state(path=tmp_path / "exp-cli" / "journal.jsonl") == "CREATED"
    assert cli.dispatch(["--json", "plan", "exp-cli"]) == 0
    plan_out = capsys.readouterr().out
    assert "TOKEN" not in plan_out
    plan = json.loads(plan_out)
    assert plan["experiment_id"] == "exp-cli"
    assert plan["secrets_excluded"] is True
    assert cli.dispatch(["--json", "status", "exp-cli"]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["state"] == "CREATED"
    assert status["manifest"]["experiment_id"] == "exp-cli"
