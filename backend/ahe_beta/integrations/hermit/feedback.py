"""One complete AHE demand/delivery cycle for a frozen external adapter cohort."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import threading
from pathlib import Path

from ahe_beta.demand.artifact import bind_artifact_handoff
from ahe_beta.integrations.hermit.contract import read_adapter_contract
from ahe_beta.experiment.controllers.feedback import assemble_feedback_roles
from ahe_beta.loop.feedback_pipeline import FeedbackPipeline
from ahe_beta.loop.recovery import RecoveryIdentity, RecoveryStore
from ahe_beta.loop.round_gate import wait_round_delivery
from ahe_beta.loop.sim_user import publish_session_reports
from ahe_beta.models import Session
from ahe_beta.user.session_store import SessionStore

def _git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


def feedback_round(
    *,
    root,
    repo,
    tracker,
    sessions,
    identity,
    round_no,
    user_sha,
    roster,
    definitions_root,
    cancel,
    delivery_timeout,
):
    """Import a valid cohort, then reuse native triage/admission/delivery recovery.

    The caller owns Gitea/OpenAgents startup and adapter import/export. Keeping these
    callbacks outside the session simulator prevents an individual user from editing
    the shared adapter or starting a delivery round.
    """
    root, repo = Path(root), Path(repo)
    contract = read_adapter_contract(repo, tested_sha=user_sha)
    cohort = [Session.from_dict(row) for row in sessions]
    if not cohort or len({s.session_id for s in cohort}) != len(cohort):
        raise ValueError("feedback requires a nonempty, unique session cohort")
    for session in cohort:
        p = session.session_provenance
        if p.get("harness_sha") != user_sha or p.get("round_no") != round_no:
            raise ValueError("session is not bound to the frozen adapter round")
        if session.feeling is None or (
            session.sim_trace and session.sim_trace.evaluation_status != "valid"
        ):
            raise ValueError("unscored user session cannot enter demand analysis")
        if session.user_outcome.get("error") or session.user_outcome.get("review_error"):
            raise ValueError("infrastructure failure cannot enter demand analysis")
    recovery_id = RecoveryIdentity(**identity)
    recovery = (
        RecoveryStore.open(root=root, identity=recovery_id)
        if (root / "recovery.json").exists()
        else RecoveryStore.initialize(root=root, identity=recovery_id)
    )
    plan = {"sessions": sorted(s.session_id for s in cohort)}
    recovery.freeze_round(round_no=round_no, user_sha=user_sha, plan=plan)
    store = SessionStore(root / "sessions")
    for session in cohort:
        previous = store.reconcile(
            session.session_id, expected_provenance=session.session_provenance
        )
        if previous is not None:
            if previous.report_plan != session.report_plan or previous.feedback != session.feedback:
                raise ValueError("completed session changed on feedback recovery")
            session = previous
        else:
            store.save(session)
        publish_session_reports(session, tracker=tracker, store=store)
    roles = assemble_feedback_roles(
        tracker=tracker,
        store=store,
        repo=repo,
        definitions_root=Path(definitions_root),
        roster=roster,
        round_provider=lambda: round_no,
        artifact_root=root,
        status_factory=lambda *args: None,
        event_factory=lambda *args: None,
    )

    def resolve_head():
        if cancel.is_set():
            raise InterruptedError("delivery cancelled; receipts retained")
        _git(repo, "fetch", "origin", "main")
        return _git(repo, "rev-parse", "origin/main")

    def assert_descendant(*, ancestor, descendant):
        _git(repo, "merge-base", "--is-ancestor", ancestor, descendant)

    def sleep(seconds):
        if cancel.wait(seconds):
            raise InterruptedError("delivery cancelled; receipts retained")

    def wait_delivery(*, numbers):
        wait_round_delivery(
            numbers=numbers,
            fetch_issue=lambda n: tracker.get_issue(number=n),
            timeout_sec=delivery_timeout,
            poll_sec=5,
            sleep=sleep,
        )

    pipeline = FeedbackPipeline(
        recovery=recovery,
        resolve_head=resolve_head,
        assert_descendant=assert_descendant,
        **roles,
        fetch_issue=lambda n: tracker.get_issue(number=n),
        wait_delivery=wait_delivery,
        prerequisite="feedback_imported",
        operation_namespace=identity["run_id"],
        grounding_repo=str(repo),
    )
    pipeline.mark_stage(round_no=round_no, stage="feedback_imported", input_value=plan)
    with bind_artifact_handoff(contract.handoff()):
        sealed_sha = pipeline.run(round_no=round_no, user_sha=user_sha)
    receipt = {
        "schema_version": 1,
        "round": round_no,
        "tested_adapter": user_sha,
        "delivered_adapter": sealed_sha,
        "session_ids": plan["sessions"],
    }
    (root / f"round-{round_no}-adapter.json").write_text(json.dumps(receipt, indent=2) + "\n")
    return receipt


def import_artifacts(source, destination):
    """Copy immutable native evidence, refusing linked or conflicting files."""
    source, destination = Path(source).resolve(), Path(destination)
    for item in sorted(source.rglob("*")):
        if item.is_symlink():
            raise ValueError("linked native artifact is not importable")
        if not item.is_file():
            continue
        rel = item.relative_to(source)
        # Session publication owns its derived index and receipts at the destination.
        if rel.parts[0] == "sessions" and len(rel.parts) == 2:
            continue
        if item.name.endswith(".lock"):
            continue
        if rel == Path("usage.jsonl"):
            # Each Harbor process has its own complete usage file.
            rel = Path("user-usage") / (hashlib.sha256(item.read_bytes()).hexdigest() + ".jsonl")
        target = destination / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if (
                hashlib.sha256(target.read_bytes()).digest()
                != hashlib.sha256(item.read_bytes()).digest()
            ):
                raise ValueError(f"native evidence collision: {rel}")
        else:
            shutil.copy2(item, target)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument("--result", required=True, type=Path)
    args = parser.parse_args()
    request = json.loads(args.request.read_text())
    from ahe_beta.tracker.gitea import GiteaTracker
    from ahe_beta.usage import bind_usage_context, default_usage_store

    root = Path(request["root"]).resolve()
    root.mkdir(parents=True, exist_ok=True)
    os.environ["ROLE_RUNS_DIR"] = str(root)
    os.environ["AHE_BETA_USAGE_PATH"] = str(root / "demand-usage.jsonl")
    tracker_config = request["tracker"]
    tracker = GiteaTracker(
        tracker_config["base_url"],
        tracker_config["owner"],
        tracker_config["repo"],
        os.environ[tracker_config["token_env"]],
    )
    sessions = []
    for folder in request["session_roots"]:
        store = SessionStore(Path(folder) / "sessions")
        candidates = [store.load(row["session_id"]) for row in store.index()]
        if len(candidates) != 1:
            raise ValueError("each rollout must supply exactly one native session")
        sessions.append(candidates[0].to_dict())
        import_artifacts(folder, root)
    if len(sessions) != request["sessions_per_round"]:
        raise ValueError("incomplete feedback cohort")
    with bind_usage_context(run_id=request["identity"]["run_id"], round_no=request["round"]):
        receipt = feedback_round(
            root=root,
            repo=request["repo"],
            tracker=tracker,
            sessions=sessions,
            identity=request["identity"],
            round_no=request["round"],
            user_sha=request["user_sha"],
            roster=request["roster"],
            definitions_root=request["definitions_root"],
            cancel=threading.Event(),
            delivery_timeout=request["delivery_timeout"],
        )
    receipt["usage"] = default_usage_store().summary(round_no=request["round"])
    args.result.write_text(json.dumps(receipt, indent=2) + "\n")


if __name__ == "__main__":
    main()
