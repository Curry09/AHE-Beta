"""Imported user feedback uses the native round ledger without duplicate publication."""

import subprocess
import threading

from test_hermit_session import Conversation, HostWorkspace, Reviewer, params

from ahe_beta.integrations.hermit import feedback
from ahe_beta.integrations.hermit.session import run_session
from ahe_beta.models import Session
from ahe_beta.tracker.fake import FakeTracker


def test_feedback_recovery_does_not_republish_or_rebind_tested_source(tmp_path, monkeypatch):
    import json

    repo = tmp_path / "adapter"
    repo.mkdir()

    def git(*args):
        return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()

    git("init", "-b", "main")
    git("config", "user.name", "Test")
    git("config", "user.email", "test@example.invalid")
    (repo / "ADAPTER.md").write_text("Implement and verify the task.")
    git("add", "ADAPTER.md")
    git("commit", "-m", "fixture")
    git("remote", "add", "origin", str(repo))
    cfg = params(tmp_path, "direct")
    cfg["harness_sha"] = git("rev-parse", "HEAD")
    result = run_session(
        {"instruction": "Inspect a.txt"},
        Conversation(),
        HostWorkspace(cfg["environment"]["workdir"]),
        cfg,
        client_factory=Reviewer,
    )
    session = Session.from_dict(json.loads(result["files"]["session.json"]))
    monkeypatch.setattr(feedback, "assemble_feedback_roles", lambda **kwargs: {})
    tracker = FakeTracker()
    kwargs = dict(
        root=tmp_path / "delivery",
        repo=repo,
        tracker=tracker,
        sessions=[session.to_dict()],
        identity={
            "experiment_id": "demo",
            "run_id": "hermit-smoke",
            "config_hash": "config",
            "controller_sha": "source",
            "plan_hash": "plan",
        },
        round_no=1,
        user_sha=cfg["harness_sha"],
        roster={},
        definitions_root=tmp_path,
        cancel=threading.Event(),
        delivery_timeout=30,
    )
    first = feedback.feedback_round(**kwargs)
    second = feedback.feedback_round(**kwargs)
    assert first == second
    assert len(tracker.list_open_issues()) == 1
    assert first["tested_adapter"] == first["delivered_adapter"] == cfg["harness_sha"]
