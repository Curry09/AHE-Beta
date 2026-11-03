"""Spec-0073/T6: actual compilation/session/demand/recovery with scripted boundaries.

No result file is prewritten. SessionStore files and tracker issues are created by
production session runners, proposals by production demand drivers, and seals by
Orchestrator. Git fetch, workspace providers, models and external delivery are
explicit substitutes; this is not a live Docker/E2B experiment.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import threading
import time
from collections import Counter
from functools import partial
from pathlib import Path

import pytest

from ahe_beta.demand.architect import Architect
from ahe_beta.demand.owner import Owner
from ahe_beta.demand.triage import Triager
from ahe_beta.distill.library import PersonaLibrary
from ahe_beta.experiment import context, materials, workload
from ahe_beta.experiment.config import config_hash
from ahe_beta.experiment.controllers import runtime, unified
from ahe_beta.loop.orchestrator import Orchestrator
from ahe_beta.loop.recovery import RecoveryIdentity, RecoveryStore
from ahe_beta.loop.round_gate import RoundDeliveryBlocked
from ahe_beta.tracker.fake import FakeTracker
from ahe_beta.usage import current_usage_context
from ahe_beta.user.session_store import SessionStore
from ahe_beta.user.sim.harness_adapter import ScriptedHarness
from ahe_beta.user.sim.persona_client import ScriptedPersonaClient
from ahe_beta.user.sim.persona_io import card_to_personas
from ahe_beta.user.sim.runtime import LocalWorkspaceRuntime
from test_experiment_config_v2 import write
from test_experiment_workload import multiple_inputs as base_multiple_inputs
from test_experiment_workload import prepared_inputs as base_prepared_inputs


@pytest.fixture
def prepared_inputs(tmp_path, monkeypatch):
    return base_prepared_inputs.__wrapped__(tmp_path, monkeypatch)


@pytest.fixture
def multiple_inputs(prepared_inputs, tmp_path):
    return base_multiple_inputs.__wrapped__(prepared_inputs, tmp_path)


def git(repo, *args):
    return subprocess.check_output(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            *args,
        ],
        text=True,
    ).strip()


class BoundaryPersona(ScriptedPersonaClient):
    """Model replacement emits protocol objects; the real loop does all side effects."""

    def respond(self, system, user):
        if "<direct_review>" in user:
            return {
                "verdict": "file_issue",
                "feedback": "No verification evidence was provided.",
                "issue": "The harness claimed a change but did not show a test receipt.",
                "score": 2,
                "reason": "Unverified delivery.",
            }
        return super().respond(system, user)

    def _decide(self, system, user):
        output = user.split("<harness_output>", 1)[-1].split("</harness_output>", 1)[0].strip()
        space = user.split("<action_space>", 1)[-1].split("</action_space>", 1)[0]
        if output in {"(empty)", ""}:
            return {
                "perceive": "Starting the assigned task.",
                "verdict": "unsure",
                "action": "send_message",
                "message": "Fix the assigned task and run its visible checks.",
                "task_load": "normal",
            }
        action = next(
            (name for name in ("file_issue", "give_up", "send_message") if name in space), "free"
        )
        return {
            "perceive": "The reply has no verification receipt.",
            "verdict": "failed_blame_harness",
            "action": action,
            "message": "Please provide evidence that the change was checked.",
        }

    @staticmethod
    def _compose_issue():
        return {
            "issue": "The harness claimed a task change without showing any verification receipt."
        }


class BoundaryHarness(ScriptedHarness):
    def __init__(self, workspace):
        super().__init__()
        self.workspace = workspace

    def send(self, message):
        self._ensure_open()
        self.workspace.write_text("session-edit.txt", current_usage_context().session_id)
        return (
            "I changed the assigned task. Tests were not run; no verification receipt is available."
        )


@pytest.mark.parametrize("backend", ["local", "e2b"])
def test_two_round_mixed_workload_stops_resumes_and_delivers_nonempty(
    multiple_inputs, tmp_path, monkeypatch, backend
):
    # A real local Git fixture supplies the fixed revision at the fetch boundary.
    config = json.loads(multiple_inputs.read_text())
    first_path = tmp_path / "task.json"
    first = json.loads(first_path.read_text())
    first.update(
        kind="swebench",
        source={
            "kind": "git",
            "url": "https://example.com/task.git",
            "repo": "fixture/task",
            "revision": config["source"]["openagents"]["revision"],
        },
    )
    first.pop("not_in_benchmark")
    write(first_path, first)
    second_path = tmp_path / "second/task.json"
    second = json.loads(second_path.read_text())
    second["interaction"] = "direct"
    write(second_path, second)
    ids = config["workload"]["persona_ids"]
    config["workload"]["interaction_plan"] = [
        [
            [ids[0], "simple-task"],
            [ids[1], "simple-task"],
            [ids[2], "second-task"],
            [ids[3], "second-task"],
        ],
        [
            [ids[0], "second-task"],
            [ids[1], "second-task"],
            [ids[2], "simple-task"],
            [ids[3], "simple-task"],
        ],
    ]
    if backend == "e2b":
        config["runtime"] = {
            "backend": "e2b",
            "gitea": {"provider": "gitea.com", "repository_prefix": "test"},
            "e2b": {"cpu_count": 4, "memory_mb": 8192, "timeout_seconds": 3600},
        }
    write(multiple_inputs, config)
    assert materials.check_materials(multiple_inputs)["preview"] == {"frozen": False}
    manifest = materials.prepare_materials(multiple_inputs, tmp_path / "runs")
    root = Path(manifest["run_dir"])
    materials.verify_materials(manifest)
    catalog = workload.read_task_catalog(root, manifest)
    plan = workload.read_session_plan(root, manifest)
    tasks = workload.tasks_by_id(catalog)
    resources = {
        "gitea": {"url": "http://127.0.0.1:3000", "owner": "fixture", "repo": manifest["run_id"]},
        "task_workspaces": {
            task_id: {
                "kind": "docker-seed" if backend == "local" else "prebuilt",
                "params": {"task_id": task_id, "provider_coordinate": f"initial/{task_id}"},
                "setup": [],
                "task_digest": task["digest"],
                "recipe_hash": f"recipe-{task_id}",
                "status": "prepared",
                "source_revision": task["source_snapshot"]["revision"],
                "source_hash": config_hash(data=task["source_snapshot"]["files"]),
            }
            for task_id, task in tasks.items()
        },
    }
    if backend == "e2b":
        resources["sandbox_id"] = "scripted-sandbox"
    env = context.build_controller_environment(
        run_dir=root,
        manifest=manifest,
        resources=resources,
        credentials={
            "GITEA_TOKEN": "fixture",
            "MODEL_BASE_URL": "https://model.example",
            "MODEL_API_KEY": "fixture",
        },
    )
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    sim_personas = {
        sp.persona_id: sp for sp in card_to_personas(PersonaLibrary(Path(env["PERSONA_LIBRARY"])))
    }
    frozen_catalog, frozen_plan, _ = context.frozen_workload()
    assert frozen_catalog == catalog and frozen_plan == plan
    tracker = FakeTracker()
    store = SessionStore(root / "data/role_runs" / manifest["run_id"] / "sessions")
    runner = runtime._make_user_run_session_fn(
        client_factory=BoundaryPersona, tracker=tracker, store=store, sim_personas=sim_personas
    )
    calls = Counter()
    active = {"count": 0, "maximum": 0}
    guard = threading.Lock()

    def run_user(persona, scenario, harness, *, workspace_dir):
        ctx = current_usage_context()
        with guard:
            calls[ctx.session_id] += 1
            active["count"] += 1
            active["maximum"] = max(active["maximum"], active["count"])
        try:
            time.sleep(0.01)
            return runner(persona, scenario, harness, workspace_dir=workspace_dir)
        finally:
            with guard:
                active["count"] -= 1

    run_user.load_completed_session = runner.load_completed_session
    first_attempt = {"fail": True}
    provisioned = []

    def materialize(spec):
        ctx = current_usage_context()
        assert (
            ctx.session_id and ctx.harness_sha and ctx.task_digest == tasks[ctx.task_id]["digest"]
        )
        assert (
            spec.params["task_id"] == ctx.task_id
            and spec.params["task_kind"] == tasks[ctx.task_id]["kind"]
        )
        if first_attempt["fail"] and ctx.round_no == 1 and ctx.slot == 2:
            raise RuntimeError("scripted provider stop during third session preparation")
        directory = root / "runtime/scripted-attempts" / ctx.session_id / str(ctx.attempt)
        shutil.copytree(root / "source/tasks" / ctx.task_id, directory)
        # Build a genuine Git worktree for the runner's patch/evidence export.
        if not (directory / ".git").exists():
            subprocess.run(["git", "init", "--quiet", str(directory)], check=True)
            git(directory, "add", ".")
            git(directory, "commit", "--quiet", "-m", "task baseline")
        provisioned.append((ctx.session_id, ctx.task_id, spec.params["provider_coordinate"]))
        return LocalWorkspaceRuntime(str(directory))

    monkeypatch.setattr("ahe_beta.loop.orchestrator.materialize_workspace", materialize)
    repo = root / "data/harness-repo"
    repo.mkdir(parents=True)
    subprocess.run(["git", "init", "--quiet", "-b", "main", str(repo)], check=True)
    (repo / "entry.py").write_text("# initial harness\n")
    git(repo, "add", ".")
    git(repo, "commit", "--quiet", "-m", "seed")
    initial_sha = git(repo, "rev-parse", "HEAD")
    triager = Triager(tracker, store, str(repo), str(tmp_path / "unused-agent"))

    def triage_model(*, pending):
        return json.dumps(
            {
                "dispositions": [
                    {
                        "issue": issue.number,
                        "disposition": "accept",
                        "kind": "bug",
                        "priority": "P1",
                        "proposal_title": "Harness reports changes without verification receipts",
                        "fields": {
                            "root_cause": "reply verification",
                            "boundary": "generic Harness output",
                            "acceptance": "report checks performed",
                        },
                        "artifact": {
                            "reported_problem": "Claims of changes lack verification receipts.",
                            "user_impact": "Users cannot decide whether the work was checked.",
                            "scope_boundary": "Generic Harness output, independent of task details.",
                            "evidence": [f"report:#{issue.number}"],
                            "uncertainties": [],
                            "implementation_target": "harness",
                        },
                    }
                    for issue in pending
                ]
            }
        )

    monkeypatch.setattr(triager, "_run_agent", triage_model)
    architect = Architect(tracker, store, str(repo), str(tmp_path / "unused-agent"))
    architect_sources = []

    def synthesis_model(*, ready, proposals, trend, runtime):
        source_ids = [proposal.number for proposal in proposals]
        assert len(source_ids) >= 2
        architect_sources.extend(source_ids)
        return json.dumps(
            {
                "proposals": [
                    {
                        "title": "Make Harness verification receipts consistent across tasks",
                        "source_proposals": source_ids,
                        "relationship": "Independent users report the same missing verification boundary.",
                        "common_tension": "Changes are claimed without evidence of checks.",
                        "structural_direction": "Expose a shared verification-receipt behavior.",
                        "expected_leverage": "Let users assess verified work across task types.",
                        "solution_level": "structural_mechanism",
                        "abstraction_rationale": "A generic behavior covers multiple reports.",
                        "covers": source_ids,
                    }
                ]
            }
        )

    monkeypatch.setattr(architect, "_run_agent", synthesis_model)
    owner = Owner(tracker, store, str(repo), str(tmp_path / "unused-agent"), review=False)
    delivery_numbers = []

    def deliver(*, numbers):
        assert numbers
        delivery_numbers.extend(numbers)
        (repo / "verification_receipts.py").write_text(
            "# delivered generic verification mechanism\n"
        )
        git(repo, "add", ".")
        git(repo, "commit", "--quiet", "-m", "feat: add verification receipts")
        for number in numbers:
            tracker.set_state(number, "closed", "resolved")

    identity = RecoveryIdentity(
        **{
            key: manifest[key]
            for key in ("experiment_id", "run_id", "config_hash", "controller_sha", "plan_hash")
        }
    )
    recovery = RecoveryStore.initialize(root=root / "checkpoints", identity=identity)

    class Launcher:
        def launch(self, ref, workspace_dir=None):
            assert ref in {initial_sha, git(repo, "rev-parse", "HEAD")}
            return BoundaryHarness(workspace_dir)

    def build_orchestrator():
        return Orchestrator(
            launcher=Launcher(),
            harness_repo=str(repo),
            fixed_set=[],
            run_session_fn=run_user,
            initial_ref="main",
            triagers=[triager],
            architects=[architect],
            owner=owner,
            max_parallel_users=2,
            fetch_issue=lambda number: tracker.get_issue(number=number),
            wait_delivery=deliver,
            recovery=recovery,
            frozen_session_plan=lambda round_no: plan["rounds"][round_no - 1],
            resolve_session=partial(unified._resolve_frozen_session, sim_personas=sim_personas),
            task_kinds={task_id: task["kind"] for task_id, task in tasks.items()},
        )

    orch = build_orchestrator()
    with pytest.raises(RoundDeliveryBlocked, match="user-sessions-incomplete"):
        orch.run(2)
    saved_before = {
        path.stem: path.read_bytes()
        for path in store.root.glob("*.json")
        if path.name != "index.json"
    }
    assert len(saved_before) >= 2 and not delivery_numbers
    # Re-open authoritative state and change provider coordinates. Frozen logical keys stay intact.
    first_attempt["fail"] = False
    for workspace in resources["task_workspaces"].values():
        workspace["params"]["provider_coordinate"] = "different-provider-coordinate"
    context.write_controller_context(
        run_dir=root, manifest=manifest, credentials={"GITEA_TOKEN": "fixture"}, resources=resources
    )
    recovery = RecoveryStore.open(root=root / "checkpoints", identity=identity)
    orch = build_orchestrator()
    refs = orch.run(2)
    sealed = refs[0]
    assert refs[1] == sealed
    assert sealed != initial_sha and architect_sources and delivery_numbers
    assert all(tracker.get_issue(number=number)["state"] == "closed" for number in delivery_numbers)
    assert all(
        (store.root / f"{sid}.json").read_bytes() == body for sid, body in saved_before.items()
    )
    assert all(calls[sid] == 1 for sid in saved_before)
    before_deliveries = list(delivery_numbers)
    assert orch.run(2) == refs
    sessions = [
        store.load(path.stem) for path in store.root.glob("*.json") if path.name != "index.json"
    ]
    assert len(sessions) == 8 and len(calls) == 8 and set(calls.values()) == {1}
    assert delivery_numbers == before_deliveries
    assert 1 <= active["maximum"] <= 2
    assert {session.session_provenance["interaction"] for session in sessions} == {
        "direct",
        "simulated_user",
    }
    assert {session.session_provenance["task_kind"] for session in sessions} == {
        "ordinary",
        "swebench",
    }
    for session in sessions:
        provenance = session.session_provenance
        binding = plan["rounds"][provenance["round_no"] - 1][provenance["slot"]]
        assert all(provenance[key] == binding[key] for key in binding)
        assert (
            session.scenario.description
            == (root / tasks[provenance["task_id"]]["package"]["instruction_file"]).read_text()
        )
        assert session.issue_refs
    assert recovery.round_state(round_no=1)["sealed_sha"] == sealed
    assert recovery.round_state(round_no=2)["sealed_sha"] == sealed
    assert len(provisioned) == 8
    assert any(row[2] == "different-provider-coordinate" for row in provisioned)
    assert not any((root / "source/tasks").rglob("session-edit.txt"))
