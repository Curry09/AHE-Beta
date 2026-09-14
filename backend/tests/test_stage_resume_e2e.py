"""Hermetic end-to-end fault matrix for the resumable round state machine."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

from auto_designer.loop.orchestrator import Orchestrator
from auto_designer.loop.recovery import RecoveryIdentity, RecoveryStore
from auto_designer.loop.round_gate import RoundDeliveryBlocked
from auto_designer.models import Persona, SeedScenario
from auto_designer.usage import current_usage_context


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), "-c", "user.email=t@x", "-c", "user.name=t", *args],
        check=True,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "GIT_AUTHOR_DATE": "2000-01-01T00:00:00Z",
            "GIT_COMMITTER_DATE": "2000-01-01T00:00:00Z",
        },
    )
    return result.stdout.strip()


def _repo(root: Path) -> Path:
    repo = root / "harness"
    repo.mkdir(parents=True)
    subprocess.run(["git", "init", "-b", "main", str(repo)], check=True, capture_output=True)
    (repo / "README.md").write_text("v0\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "seed")
    return repo


@dataclass
class _Outcome:
    admitted: list[int]


class _Launcher:
    def launch(self, ref: str, *, workspace_dir=None):
        return {"ref": ref}


def _run_case(root: Path, failure_stage: str | None) -> dict[str, object]:
    repo = _repo(root)
    identity = RecoveryIdentity("exp", "run", "config", "controller", "plan")
    recovery = RecoveryStore.initialize(root=root / "checkpoints", identity=identity)
    calls = {
        stage: 0 for stage in ("users", "triage", "divergent", "designer", "owner", "delivery")
    }
    effects: set[str] = set()
    sessions: dict[str, dict[str, str]] = {}
    issue = {"state": "open", "labels": ["ready"]}
    armed = {"value": failure_stage is not None}

    def fail(stage: str) -> None:
        if armed["value"] and failure_stage == stage:
            armed["value"] = False
            raise RuntimeError(f"crash-after-{stage}-side-effect")

    def run_user(persona, scenario, harness, *, workspace_dir=None):
        calls["users"] += 1
        session_id = str(current_usage_context().session_id)
        sessions[session_id] = {"session_id": session_id, "scenario": scenario.description}
        effects.add(f"session:{scenario.description}")
        fail("users")
        return sessions[session_id]

    run_user.load_completed_session = sessions.get

    class Role:
        def __init__(self, stage: str) -> None:
            self.stage = stage

        def snapshot_pending(self):
            return []

        def triage_once(self, *, pending=None, shard=None):
            return self._call()

        def propose_once(self):
            return self._call()

        def _call(self):
            calls[self.stage] += 1
            effects.add(self.stage)
            fail(self.stage)
            return {"stage": self.stage, "completed": True}

    class Owner:
        def admit_once(self):
            calls["owner"] += 1
            effects.add("owner:41")
            fail("owner")
            return _Outcome([41])

    def fetch_issue(number: int):
        assert number == 41
        return dict(issue)

    def wait_delivery(*, numbers: list[int]) -> None:
        assert numbers == [41]
        calls["delivery"] += 1
        effects.add("delivery:41")
        issue["state"] = "closed"
        if armed["value"] and failure_stage == "delivery":
            armed["value"] = False
            raise RoundDeliveryBlocked(numbers=[41], reason="timeout")

    plan = [
        (
            Persona(identity="p", level="l", domain="d", goal="g", speaking_style="s"),
            SeedScenario(description="task"),
        )
    ]

    def orchestrator(store: RecoveryStore) -> Orchestrator:
        return Orchestrator(
            launcher=_Launcher(),
            harness_repo=str(repo),
            fixed_set=plan,
            run_session_fn=run_user,
            initial_ref="main",
            triagers=[Role("triage")],
            divergents=[Role("divergent")],
            designers=[Role("designer")],
            owner=Owner(),
            fetch_issue=fetch_issue,
            wait_delivery=wait_delivery,
            recovery=store,
        )

    first = orchestrator(recovery)
    if failure_stage is None:
        sealed = first.run_round("main", round_no=1)
    else:
        with pytest.raises(RoundDeliveryBlocked):
            first.run_round("main", round_no=1)
        reopened = RecoveryStore.open(root=root / "checkpoints", identity=identity)
        sealed = orchestrator(reopened).run_round("main", round_no=1)
        recovery = reopened

    state = recovery.round_state(round_no=1)
    assert state is not None
    return {
        "effects": sorted(effects),
        "sessions": sorted(value["scenario"] for value in sessions.values()),
        "admitted": state["admitted_issue_ids"],
        "sealed": sealed,
        "stage_statuses": {name: value["status"] for name, value in state["stages"].items()},
        "issue": issue,
        "calls": calls,
    }


@pytest.mark.parametrize(
    "failure_stage", ["users", "triage", "divergent", "designer", "owner", "delivery"]
)
def test_every_stage_resumes_to_the_same_authoritative_result(
    tmp_path: Path, failure_stage: str
) -> None:
    baseline = _run_case(tmp_path / "baseline", None)
    resumed = _run_case(tmp_path / f"resume-{failure_stage}", failure_stage)

    for field in ("effects", "sessions", "admitted", "sealed", "stage_statuses", "issue"):
        assert resumed[field] == baseline[field]
    assert all(status == "completed" for status in resumed["stage_statuses"].values())
    assert resumed["calls"]["users"] == 1


def test_business_delivery_failure_remains_blocked(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    recovery = RecoveryStore.initialize(
        root=tmp_path / "checkpoints",
        identity=RecoveryIdentity("exp", "run", "config", "controller", "plan"),
    )

    class Owner:
        def admit_once(self):
            return _Outcome([41])

    orchestrator = Orchestrator(
        launcher=_Launcher(),
        harness_repo=str(repo),
        fixed_set=[],
        run_session_fn=lambda *args, **kwargs: None,
        initial_ref="main",
        owner=Owner(),
        fetch_issue=lambda number: {"state": "closed", "labels": ["automation-failed"]},
        recovery=recovery,
    )

    with pytest.raises(RoundDeliveryBlocked, match="delivery-failed"):
        orchestrator.run_round("main", round_no=1)
    assert recovery.stage_status(round_no=1, stage="delivery_wait") == "blocked"
