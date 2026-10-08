"""Spec-0083/T3: original binary outputs survive both real session lifecycle paths.

Scripted personas and Harness responses exercise the production runners, filesystem
export, persistence and recovery without making model or provider requests.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from auto_designer.loop.sim_user import make_direct_run_session_fn, make_sim_run_session_fn
from auto_designer.models import Persona, SeedScenario, WorkspaceSpec
from auto_designer.tracker.fake import FakeTracker
from auto_designer.usage import bind_usage_context
from auto_designer.user.session_store import SessionStore
from auto_designer.user.sim.harness_adapter import ScriptedHarness
from auto_designer.user.sim.persona_client import ScriptedPersonaClient
from auto_designer.user.sim.run_live import expert
from auto_designer.user.sim.runtime import LocalWorkspaceRuntime

BINARY_OUTPUT = b"PK\x03\x04\x00\xff\xfe\x80finalized workbook\x00"
USER_SHA = "a" * 40
DELIVERED_SHA = "b" * 40


class RecordingWorkspace(LocalWorkspaceRuntime):
    def __init__(self, root: Path, events: list[str], *, failure: str | None = None):
        super().__init__(str(root), owns_tmp=True)
        self.events = events
        self.failure = failure

    def quiesce(self):
        self.events.append("quiesce")
        super().quiesce()

    def finalize_task(self):
        self.events.append("finalize")
        if self.failure == "finalize":
            raise RuntimeError("sidecar finalize failed")
        if self.failure != "missing":
            target = Path(self.cwd) / "output/result.xlsx"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(BINARY_OUTPUT)

    def export_file(self, path, max_bytes):
        self.events.append("export")
        return super().export_file(path, max_bytes)

    def close(self):
        if not self._closed:
            self.events.append("workspace_close")
        super().close()


class RecordingHarness(ScriptedHarness):
    def __init__(self, events: list[str]):
        super().__init__()
        self.events = events

    def send(self, message):
        self.events.append("harness_send")
        return super().send(message)

    def close(self):
        self.events.append("harness_close")
        super().close()


class RecordingSimClient(ScriptedPersonaClient):
    def __init__(self, events: list[str]):
        self.events = events

    def respond(self, system, user):
        self.events.append("user_review")
        return super().respond(system, user)


class RecordingDirectClient:
    model = "scripted-offline-review"

    def __init__(self, events: list[str]):
        self.events = events

    def respond(self, system, user):
        self.events.append("user_review")
        return {
            "verdict": "accept",
            "feedback": "Reviewed the delivery",
            "issue": "",
            "score": 3,
            "reason": "Terminal user review completed",
        }


@pytest.fixture
def session_setup(tmp_path, monkeypatch):
    monkeypatch.delenv("AUTO_DESIGNER_OBSERVATION_ROOT", raising=False)
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "main.py").write_text('print("baseline")\n')
    subprocess.run(["git", "init", "--quiet", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "add", "main.py"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "--quiet",
            "-m",
            "baseline",
        ],
        check=True,
    )
    return root, SessionStore(tmp_path / "data/sessions")


def start_session(mode, session_setup, *, failure=None, byte_limit=4096):
    root, store = session_setup
    events = []
    workspace = RecordingWorkspace(root, events, failure=failure)
    sim_persona = expert()
    persona = Persona(sim_persona.persona_id, "expert", "office", "fix workbook", "direct")
    scenario = SeedScenario(
        "Fix the workbook",
        WorkspaceSpec(
            params={
                "task_id": "excel-local-alias",
                "task_key": "excel-local-alias",
                "task_kind": "benchmark",
                "instance_id": "010-pivot-product-revenue",
                "benchmark": "tua-bench",
                "task_digest": "d" * 64,
                "interaction": mode,
                "evaluation_artifacts": [
                    {
                        "id": "workbook",
                        "source": "workspace",
                        "path": "output/result.xlsx",
                        "content_type": "application/octet-stream",
                        "required": True,
                        "max_bytes": byte_limit,
                    }
                ],
            }
        ),
    )
    tracker = FakeTracker()
    factory = make_direct_run_session_fn if mode == "direct" else make_sim_run_session_fn
    client = RecordingDirectClient if mode == "direct" else RecordingSimClient
    runner = factory(
        client_factory=lambda: client(events),
        tracker=tracker,
        store=store,
        sim_personas={persona.identity: sim_persona},
    )
    context = {
        "run_id": "frozen-run",
        "round_no": 6,
        "slot": 3,
        "session_id": f"stable-{mode}-session",
        "persona_id": persona.identity,
        "task_id": "excel-local-alias",
        "task_digest": "d" * 64,
        "task_kind": "benchmark",
        "interaction_mode": mode,
        "harness_sha": USER_SHA,
    }
    with bind_usage_context(**context):
        session = runner(persona, scenario, RecordingHarness(events), workspace_dir=workspace)
    # direct's workspace belongs to the caller/orchestrator; simulated closes it itself.
    workspace.close()
    return session, runner, store, events, context


@pytest.mark.parametrize("mode", ["direct", "simulated_user"])
def test_binary_output_collected_after_review_and_finalize_before_cleanup(session_setup, mode):
    session, _, store, events, _ = start_session(mode, session_setup)
    receipt = session.workspace_evidence["evaluation_artifacts"]
    assert receipt["complete"] is True
    assert receipt["identity"] == {
        "run_id": "frozen-run",
        "round_no": 6,
        "slot": 3,
        "task_id": "excel-local-alias",
        "task_digest": "d" * 64,
        "session_id": session.session_id,
        "harness_sha": USER_SHA,
    }
    assert receipt["identity"]["harness_sha"] != DELIVERED_SHA
    entry = receipt["entries"][0]
    assert entry["status"] == "collected"
    output = store.root.parent / entry["path"]
    assert output.read_bytes() == BINARY_OUTPUT
    assert entry["bytes"] == len(BINARY_OUTPUT)
    assert entry["sha256"] == hashlib.sha256(BINARY_OUTPUT).hexdigest()
    assert events.index("harness_close") < events.index("quiesce")
    assert max(i for i, event in enumerate(events) if event == "user_review") < events.index(
        "quiesce"
    )
    assert events.index("quiesce") < events.index("finalize") < events.index("export")
    assert events.index("export") < events.index("workspace_close")
    assert not session_setup[0].exists()
    assert store.load(session.session_id).workspace_evidence["evaluation_artifacts"] == receipt


@pytest.mark.parametrize("mode", ["direct", "simulated_user"])
@pytest.mark.parametrize(
    ("failure", "byte_limit", "status"),
    [
        ("missing", 4096, "missing"),
        ("finalize", 4096, "collection_failed"),
        (None, 4, "over_limit"),
    ],
)
def test_missing_or_failed_capture_retains_session_and_reclaims_workspace(
    session_setup,
    mode,
    failure,
    byte_limit,
    status,
):
    session, _, store, events, _ = start_session(
        mode,
        session_setup,
        failure=failure,
        byte_limit=byte_limit,
    )
    receipt = session.workspace_evidence["evaluation_artifacts"]
    assert receipt["complete"] is False
    assert receipt["entries"][0]["status"] == status
    assert "path" not in receipt["entries"][0]
    assert store.load(session.session_id).session_id == session.session_id
    assert "workspace_close" in events
    assert not session_setup[0].exists()
    assert session.user_feedback_envelope


@pytest.mark.parametrize("mode", ["direct", "simulated_user"])
def test_recovery_reads_completed_session_without_recapturing_missing_evidence(session_setup, mode):
    session, runner, store, events, context = start_session(mode, session_setup)
    receipt = session.workspace_evidence["evaluation_artifacts"]
    (store.root.parent / receipt["entries"][0]["path"]).unlink()
    before = (store.root / f"{session.session_id}.json").read_bytes()
    events_before = list(events)
    with bind_usage_context(**context):
        recovered = runner.load_completed_session(session.session_id)
    assert recovered is not None
    assert recovered.workspace_evidence["evaluation_artifacts"] == receipt
    assert events == events_before
    assert (store.root / f"{session.session_id}.json").read_bytes() == before
    assert recovered.session_provenance["harness_sha"] == USER_SHA
    assert len(json.loads((store.root / "index.json").read_text())) == 1


def test_public_generic_task_delivers_only_frozen_collection_contract(tmp_path, monkeypatch):
    from auto_designer.experiment import context, materials, workload
    from test_experiment_config_v2 import write
    from test_experiment_grading_task_config import benchmark_package
    from test_experiment_materials import prepared_inputs
    from test_experiment_workload import task_resources

    config_path = prepared_inputs.__wrapped__(tmp_path, monkeypatch)
    task = benchmark_package()
    task["interaction"] = "direct"
    write(tmp_path / "task.json", task)
    config = json.loads(config_path.read_text())
    config["workload"].pop("kind")
    config["workload"].pop("task_package")
    config["workload"]["task_packages"] = ["../task.json"]
    write(config_path, config)
    manifest = materials.prepare_materials(config_path, tmp_path / "runs")
    root = Path(manifest["run_dir"])
    catalog = workload.read_task_catalog(root, manifest)
    env = context.build_controller_environment(
        run_dir=root,
        manifest=manifest,
        credentials={
            "GITEA_TOKEN": "test",
            "MODEL_BASE_URL": "https://model.invalid",
            "MODEL_API_KEY": "test",
        },
        resources={
            "gitea": {"url": "http://localhost:3000", "owner": "test", "repo": "test"},
            "task_workspaces": task_resources(catalog),
        },
    )
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    context.require_controller_context()
    # Changing the operator's original recipe after prepare cannot change capture.
    write(tmp_path / "task.json", {"grading_plan": "/private/operator/answers.json"})
    scenario = context.frozen_scenario(task["id"])
    params = scenario.workspace.params
    assert params["task_kind"] == "benchmark"
    assert params["benchmark"] == "tua-bench"
    assert params["instance_id"] == "010-pivot-product-revenue"
    assert params["task_id"] == task["id"]
    assert params["task_digest"] == catalog["tasks"][0]["digest"]
    assert params["evaluation_artifacts"] == task["artifacts"]["exports"]
    assert "grading_plan" not in params
    assert params["interaction"] == "direct"


@pytest.mark.parametrize("mode", ["direct", "simulated_user"])
def test_session_ignores_retired_inline_grading_configuration(
    session_setup, mode, monkeypatch, tmp_path
):
    from auto_designer.evaluation.adapters.swebench import _SWEbenchRunner

    monkeypatch.setenv("AUTO_DESIGNER_OBJECTIVE_EVALUATION", "1")
    monkeypatch.setenv("SWEBENCH_PARQUET", str(tmp_path / "hidden-dataset.parquet"))
    results = tmp_path / "inline-results"
    monkeypatch.setenv("SWEBENCH_EVAL_RESULTS_ROOT", str(results))
    monkeypatch.setattr(_SWEbenchRunner, "evaluate", lambda *a, **kw: pytest.fail("inline grading"))
    session, _, _, _, _ = start_session(mode, session_setup)
    assert session.objective_evaluation is None
    assert session.accept_validity == "not_applicable"
    assert not results.exists()
    assert not any(row["event"] == "objective_evaluation_terminal" for row in session.audit_events)
