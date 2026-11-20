"""Host conversation sessions preserve AHE feedback and defer forge publication."""

import json
import subprocess
from pathlib import Path

import pytest

from ahe_beta.integrations.hermit.session import run_session
from ahe_beta.loop.sim_user import publish_session_reports
from ahe_beta.models import Session
from ahe_beta.tracker.fake import FakeTracker
from ahe_beta.user.session_store import SessionStore


class HostWorkspace:
    def __init__(self, root):
        self.root = root
        self.frozen = False
        self.closed = False

    def run(self, command, timeout=60, cwd=None):
        p = subprocess.run(
            command,
            shell=True,
            cwd=cwd or self.root,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return {"code": p.returncode, "stdout": p.stdout, "stderr": p.stderr}

    def read(self, path):
        return Path(path).read_text()

    def write(self, path, text):
        Path(path).write_text(text)

    def quiesce(self):
        self.frozen = True

    def close(self):
        self.closed = True


class Conversation:
    def __init__(self):
        self.sent = []
        self.closed = False
        self.replied = False

    def write(self, text):
        self.sent.append(text)
        self.replied = False

    def poll(self, timeout=0):
        if not self.replied:
            self.replied = True
            return {"text": "Implemented and verified.", "kind": "reply"}
        return None

    def events(self):
        return []

    def close(self):
        self.closed = True


class Reviewer:
    def respond(self, system, user):
        return {
            "score": 3,
            "reason": "Solved with some friction",
            "task_assessment": "fulfilled",
            "opportunities": [
                {
                    "kind": "feature",
                    "title": "Show progress",
                    "body": "Show progress during long operations",
                }
            ],
        }


def params(tmp_path, mode):
    root = Path(__file__).resolve().parents[3]
    card = json.loads((root / "examples/personas/library.json").read_text())[0]
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "a.txt").write_text("initial")
    return {
        "interaction": mode,
        "scenario": {
            "description": "Inspect a.txt",
            "workspace": {
                "kind": "external",
                "params": {
                    "task_id": "demo",
                    "task_digest": "a" * 64,
                    "task_kind": "ordinary",
                    "interaction": mode,
                    "evaluation_artifacts": [],
                },
            },
        },
        "environment": {"workdir": str(workspace), "patch": "not_applicable"},
        "session_id": "trial-1",
        "task_id": "demo",
        "round": 1,
        "slot": 0,
        "run_id": "hermit-smoke",
        "task_digest": "a" * 64,
        "task_kind": "ordinary",
        "harness_sha": "b" * 40,
        "persona": card,
        "artifact_root": str(tmp_path / "artifacts"),
    }


def test_direct_uses_native_review_and_retains_deferred_reports(tmp_path):
    cfg = params(tmp_path, "direct")
    host, actor = HostWorkspace(cfg["environment"]["workdir"]), Conversation()
    verdict = run_session(
        {"instruction": "Inspect a.txt"}, actor, host, cfg, client_factory=Reviewer
    )
    session = Session.from_dict(json.loads(verdict["files"]["session.json"]))
    assert actor.sent == ["Inspect a.txt"]
    assert actor.closed and host.frozen and host.closed
    assert verdict["score"] == 2 / 3 and verdict["rating"] == 3
    assert session.feedback["task_assessment"]["status"] == "fulfilled"
    assert session.report_plan and session.issue_refs == []
    assert session.request_outcomes[0]["status"] == "completed"
    store = SessionStore(Path(cfg["artifact_root"]) / "sessions")
    tracker = FakeTracker()
    publish_session_reports(session, tracker=tracker, store=store)
    publish_session_reports(session, tracker=tracker, store=store)
    assert len(tracker.list_open_issues()) == 1


def test_wrong_instruction_fails_before_actor_starts(tmp_path):
    cfg = params(tmp_path, "direct")
    actor = Conversation()
    with pytest.raises(ValueError, match="frozen"):
        run_session(
            {"instruction": "different task"},
            actor,
            HostWorkspace(tmp_path),
            cfg,
            client_factory=Reviewer,
        )
    assert not actor.sent


def test_missing_rating_does_not_become_zero_reward(tmp_path):
    cfg = params(tmp_path, "direct")

    class NoRating:
        def respond(self, system, user):
            return {"task_assessment": "unknown"}

    with pytest.raises(RuntimeError, match="experience score"):
        run_session(
            {"instruction": "Inspect a.txt"},
            Conversation(),
            HostWorkspace(tmp_path),
            cfg,
            client_factory=NoRating,
        )
    assert (Path(cfg["artifact_root"]) / "sessions/trial-1.json").is_file()


def test_simulated_mode_uses_native_heartbeat_protocol(tmp_path):
    from ahe_beta.user.sim.persona_client import ScriptedPersonaClient

    cfg = params(tmp_path, "simulated_user")
    actor = Conversation()
    verdict = run_session(
        {"instruction": "Inspect a.txt"},
        actor,
        HostWorkspace(cfg["environment"]["workdir"]),
        cfg,
        client_factory=ScriptedPersonaClient,
    )
    session = Session.from_dict(json.loads(verdict["files"]["session.json"]))
    assert actor.sent and actor.closed
    assert session.sim_trace and session.sim_trace.turns
    assert session.sim_trace.evaluation_status == "valid"
    assert session.session_provenance["harness_sha"] == cfg["harness_sha"]
    assert not session.user_outcome.get("error")


@pytest.mark.parametrize("missing", [False, True])
def test_management_exports_are_retained_outside_public_snapshot(tmp_path, missing):
    cfg = params(tmp_path, "direct")
    cfg["environment"]["services"] = [
        {
            "id": "capture",
            "placement": "companion",
            "exports": [
                {"handle": "raw-measurement", "path": "/private/result", "visibility": "management"}
            ],
        }
    ]

    class ServiceWorkspace(HostWorkspace):
        def service_read(self, path, *, service, max_bytes):
            assert self.frozen and service == "capture" and path == "/private/result"
            if missing:
                raise FileNotFoundError(path)
            return b"private original measurement"

    def execute():
        return run_session(
            {"instruction": "Inspect a.txt"},
            Conversation(),
            ServiceWorkspace(cfg["environment"]["workdir"]),
            cfg,
            client_factory=Reviewer,
        )

    if missing:
        with pytest.raises(RuntimeError):
            execute()
    else:
        verdict = execute()
        assert "private original measurement" not in verdict["files"]["session.json"]
        assert (
            Path(cfg["artifact_root"]) / "management/trial-1/raw-measurement.data"
        ).read_bytes() == b"private original measurement"
    receipt = json.loads(
        (Path(cfg["artifact_root"]) / "management/trial-1/receipts.json").read_text()
    )
    assert receipt["raw-measurement"]["status"] == ("unavailable" if missing else "collected")
