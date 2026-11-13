"""Two-round recovery with real Docker resources and deterministic Actor/reviewer calls."""

import hashlib
import os
import subprocess
import sys
import uuid
from collections import Counter
from pathlib import Path

import pytest

from ahe_beta.experiment.task_environments.contract import environment_identity
from ahe_beta.experiment.task_environments.docker import (
    _QUIESCE,
    DockerTaskEnvironmentManager,
    TaskEnvironmentError,
    stop_registered,
)
from ahe_beta.loop.orchestrator import Orchestrator
from ahe_beta.loop.recovery import RecoveryIdentity, RecoveryStore, operation_key
from ahe_beta.loop.round_gate import RoundDeliveryBlocked
from ahe_beta.loop.sim_user import make_direct_run_session_fn
from ahe_beta.models import Persona, SeedScenario, WorkspaceSpec
from ahe_beta.tracker.fake import FakeTracker
from ahe_beta.usage import current_usage_context
from ahe_beta.user.session_store import SessionStore
from ahe_beta.user.sim.run_live import expert


def docker(*argv, check=True):
    return subprocess.run(
        ["docker", *argv], capture_output=True, text=True, timeout=30, check=check
    )


@pytest.mark.parametrize("failure", ["release", "capture", "lost"])
def test_two_rounds_workspace_recovery(tmp_path, monkeypatch, failure):
    if os.environ.get("RUN_SPEC_0084_DOCKER") != "1":
        pytest.skip("set RUN_SPEC_0084_DOCKER=1 for real Docker lifecycle verification")
    image = os.environ.get(
        "AHE_BETA_TEST_TASK_IMAGE",
        "nikolaik/python-nodejs@sha256:d8ed2762eba48008c58d6284eed6a8a17fc0974f073c1fd5f5c93821b7265fd2",
    )
    docker("image", "inspect", image)  # Never pull as part of this test.
    harness_python = Path(sys.executable).absolute()
    mounts = [str(harness_python.parent.parent), str(Path(sys.base_prefix).resolve())]
    # The venv's Python may point to an alias within the uv toolchain directory.
    link_target = Path(os.readlink(harness_python)) if harness_python.is_symlink() else None
    if link_target is not None and link_target.is_absolute():
        mounts.append(str(link_target.parent.parent))
    registry = tmp_path / "runtime/task-environments"
    run_id = "workspace-recovery-" + uuid.uuid4().hex[:12]
    identity = RecoveryIdentity("docker-faults", run_id, "c" * 64, "d" * 40, "e" * 64)
    recovery_root = tmp_path / "checkpoints"
    recovery = RecoveryStore.initialize(root=recovery_root, identity=identity)
    store = SessionStore(tmp_path / "sessions")
    repo = tmp_path / "harness"
    subprocess.run(["git", "init", "-qb", "main", str(repo)], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "--allow-empty",
            "-qm",
            "seed",
        ],
        check=True,
    )

    def plan(round_no):
        return [
            {
                "round_no": round_no,
                "slot": slot,
                "persona_id": "reviewer",
                "task_id": task,
                "task_digest": hashlib.sha256(task.encode()).hexdigest(),
                "interaction": "direct",
            }
            for slot, task in enumerate(("target", "other"))
        ]

    def scenario(binding):
        environment = {
            "kind": "container",
            "image": image,
            "workdir": "/tmp/ahe-task",
            "user": "root",
            "inputs": [],
            "readiness": {"argv": ["true"], "timeout_seconds": 5},
            "finalize": {
                "argv": ["sh", "-c", "echo finalized >> result.txt"],
                "timeout_seconds": 5,
            },
        }
        return Persona("reviewer", "expert", "test", "verify", "plain"), SeedScenario(
            binding["task_id"],
            WorkspaceSpec(
                kind="container",
                params={
                    "run_id": run_id,
                    "config_hash": identity.config_hash,
                    "registry_root": str(registry),
                    "task_id": binding["task_id"],
                    "task_digest": binding["task_digest"],
                    "task_kind": "ordinary",
                    "interaction": "direct",
                    "environment": environment,
                    "recipe_hash": environment_identity(
                        {"schema_version": 3, "environment": environment}
                    ),
                    "harness_python": str(harness_python),
                    "harness_mounts": [{"source": p, "target": p} for p in dict.fromkeys(mounts)],
                    "evaluation_artifacts": [
                        {
                            "id": "result",
                            "source": "workspace",
                            "path": "result.txt",
                            "content_type": "text/plain",
                            "required": True,
                            "max_bytes": 1024,
                        }
                    ],
                },
            ),
        )

    actor_calls = Counter()
    created = {}
    starts = []

    class Launcher:
        def launch(self, sha, *, workspace_dir):
            context = current_usage_context()
            created[(context.round_no, context.task_id, context.attempt)] = (
                workspace_dir.container_id
            )

            class Harness:
                observation_source = None
                request_outcomes = []

                def reset(self):
                    pass

                def close(self):
                    pass

                def send(self, message):
                    assert message == context.task_id
                    actor_calls[(context.round_no, context.task_id)] += 1
                    result = workspace_dir.run("printf 'actor output\\n' > result.txt")
                    assert result["returncode"] == 0
                    return "Wrote result.txt."

            return Harness()

    class Review:
        def bind_session(self, *, persona, workspace_dir):
            self.snapshot = workspace_dir

        def respond(self, system, user):
            assert self.snapshot.read_text("artifacts/result") == "actor output\nfinalized\n"
            return {
                "task_assessment": "fulfilled",
                "score": 4,
                "reason": "verified",
                "opportunities": [],
            }

    runner = make_direct_run_session_fn(
        client_factory=Review,
        tracker=FakeTracker(),
        store=store,
        sim_personas={"reviewer": expert()},
    )

    def orchestrator(ledger):
        return Orchestrator(
            launcher=Launcher(),
            harness_repo=str(repo),
            fixed_set=[],
            frozen_session_plan=plan,
            resolve_session=scenario,
            task_kinds={"target": "ordinary", "other": "ordinary"},
            run_session_fn=runner,
            initial_ref="main",
            recovery=ledger,
            on_round_start=starts.append,
            max_parallel_users=1,
        )

    original_docker = DockerTaskEnvironmentManager._docker
    original_exec = DockerTaskEnvironmentManager._exec_in
    faults = []

    def target(manager):
        return (
            manager.identity["round_no"],
            manager.identity["task_id"],
            manager.identity["attempt"],
        ) == (1, "target", 1)

    def inject_release(self, *, argv, timeout, check):
        if failure == "release" and target(self) and argv[:2] == ["rm", "-f"]:
            assert store.load(self.identity["session_id"]).user_outcome["status"] == "completed"
            faults.append("release after session save")
            raise TaskEnvironmentError("injected Docker removal failure")
        return original_docker(self, argv=argv, timeout=timeout, check=check)

    def inject_capture(self, **kwargs):
        if failure != "release" and target(self) and _QUIESCE in kwargs["argv"] and not faults:
            sid = self.identity["session_id"]
            assert store.load_actor_checkpoint(sid) and store.load_actor_capture(sid) is None
            faults.append("capture before freeze")
            raise TaskEnvironmentError("injected Docker freeze failure")
        return original_exec(self, **kwargs)

    def key(task, round_no=1):
        return operation_key(
            run_id, "users", next(row for row in plan(round_no) if row["task_id"] == task)
        )

    try:
        monkeypatch.setattr(DockerTaskEnvironmentManager, "_docker", inject_release)
        monkeypatch.setattr(DockerTaskEnvironmentManager, "_exec_in", inject_capture)
        if failure == "release":
            assert len(orchestrator(recovery).run(2)) == 2
            old_id = created[(1, "target", 1)]
            assert docker("inspect", old_id).returncode == 0
            journals = [
                row
                for row in registry.glob("*.json")
                if '"release_pending": true' in row.read_text()
            ]
            assert len(journals) == 1 and '"release_error"' in journals[0].read_text()
            assert len(faults) == 1
            before = (store.root / f"{key('target')}.json").read_bytes()
            monkeypatch.setattr(DockerTaskEnvironmentManager, "_docker", original_docker)
            stop_registered(registry_root=registry, run_id=run_id, config_hash=identity.config_hash)
            assert docker("inspect", old_id, check=False).returncode != 0
            assert (store.root / f"{key('target')}.json").read_bytes() == before
        else:
            with pytest.raises(RoundDeliveryBlocked, match="user-sessions-incomplete"):
                orchestrator(recovery).run(2)
            assert starts == [1]
            assert store.load_actor_capture(key("target")) is None
            assert not (store.root / f"{key('target')}.json").exists()
            other = store.root / f"{key('other')}.json"
            before = other.read_bytes()
            target_actor = store.root / "actor-checkpoints" / f"{key('target')}.actor.json"
            actor_before = target_actor.read_bytes()
            if failure == "lost":
                docker("rm", "-f", created[(1, "target", 1)])
            recovery = RecoveryStore.open(root=recovery_root, identity=identity)
            assert len(orchestrator(recovery).run(2)) == 2
            assert starts == [1, 1, 2]
            assert other.read_bytes() == before
            assert recovery.unit(round_no=1, stage="users", key=key("other"))["attempt"] == 1
            assert recovery.unit(round_no=1, stage="users", key=key("target"))["attempt"] == 2
            if failure == "lost":
                assert (
                    target_actor.parent / f"{key('target')}.attempt-1/actor.json"
                ).read_bytes() == actor_before
                assert (1, "target", 2) in created
            else:
                assert target_actor.read_bytes() == actor_before
                assert (1, "target", 2) not in created
        assert actor_calls == {
            (1, "target"): 2 if failure == "lost" else 1,
            (1, "other"): 1,
            (2, "target"): 1,
            (2, "other"): 1,
        }
        assert created[(1, "target", 1)] != created[(2, "target", 1)]
        for round_no in (1, 2):
            assert recovery.round_state(round_no=round_no)["status"] == "completed"
            session = store.load(key("target", round_no))
            assert session.workspace_evidence["evaluation_artifacts"]["complete"]
            assert session.user_outcome["review_status"] == "completed"
    finally:
        for kind, selector in (("container", "ps"), ("network", "network")):
            listing = [selector, "-aq"] if kind == "container" else [selector, "ls", "-q"]
            owned = docker(
                *listing, "--filter", "label=io.ahe-beta.task-environment.run_id=" + run_id
            )
            for resource in owned.stdout.splitlines():
                docker(
                    *(["rm", "-f"] if kind == "container" else ["network", "rm"]),
                    resource,
                    check=False,
                )
