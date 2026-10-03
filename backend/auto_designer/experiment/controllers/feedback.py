"""Spec-0079/T4: concrete phase role assembly and inherited feedback initialization."""

from __future__ import annotations

import json
import subprocess

from auto_designer.experiment.config import ConfigError
from auto_designer.experiment.context import material_path
from auto_designer.experiment.materials import sha256_file


def assemble_feedback_roles(
    *,
    tracker,
    store,
    repo,
    definitions_root,
    roster,
    round_provider,
    artifact_root,
    status_factory,
    event_factory,
):
    """Assemble separate instances for the ordinary and bootstrap phases."""
    from auto_designer.demand.divergent import Divergent
    from auto_designer.demand.grouped_synthesizer import group_synthesizer_stage
    from auto_designer.demand.owner import Owner
    from auto_designer.demand.synthesizer import Synthesizer
    from auto_designer.demand.triage import Triager

    def workers(role, constructor, definition, has_round):
        result = []
        for index in range(roster[role]):
            agent_id = f"{role}-{index}"
            label = role if roster[role] == 1 else f"{role}#{index + 1}"
            options = {
                "on_status": status_factory(role, agent_id, label),
                "on_event": event_factory(agent_id),
            }
            if has_round:
                options["round_provider"] = round_provider
            result.append(
                constructor(
                    tracker,
                    store,
                    str(repo),
                    str(definitions_root / definition),
                    **options,
                )
            )
        return result

    triagers = workers("triager", Triager, "triage_agent", False)
    synthesizers = workers("synthesizer", Synthesizer, "synthesizer", True)
    divergents = workers("divergent", Divergent, "divergent_pm", True)
    owner = Owner(
        tracker,
        store,
        str(repo),
        str(definitions_root / "owner"),
        on_status=status_factory("owner", "owner-0", "owner"),
        on_event=event_factory("owner-0"),
        review=roster["owner"] >= 1,
    )
    return {
        "triagers": triagers,
        "synthesizers": group_synthesizer_stage(synthesizers, artifact_root=artifact_root),
        "divergents": divergents,
        "owner": owner,
    }


def run_continuation_bootstrap(
    *,
    run_root,
    manifest,
    tracker,
    child_store,
    repo,
    definitions_root,
    roster,
    resolve_head,
    assert_descendant,
    integrity_guard,
    status_factory,
    event_factory,
):
    """Reconcile parent reports and deliver them before any new user unit starts."""
    from auto_designer.experiment.continuation.evidence import (
        ContinuationEvidenceView,
        install_parent_observations,
    )
    from auto_designer.experiment.continuation.forge import project_reports
    from auto_designer.loop.feedback_pipeline import FeedbackPipeline
    from auto_designer.loop.recovery import RecoveryIdentity, RecoveryStore
    from auto_designer.observations.grants import observation_root

    input_path = material_path(run_root, manifest, "continuation_input")
    input_digest = sha256_file(input_path)
    if input_digest != manifest["materials"]["continuation_input"]["sha256"]:
        raise ConfigError("Frozen continuation input digest changed")
    inherited = json.loads(input_path.read_text())
    parent_root = run_root / inherited["parent_root"]
    seed = subprocess.check_output(
        ["git", "-C", str(repo), "rev-list", "--max-parents=0", "main"],
        text=True,
    ).strip()
    tree = subprocess.check_output(
        ["git", "-C", str(repo), "rev-parse", seed + "^{tree}"],
        text=True,
    ).strip()
    if tree != inherited["export"]["harness"]["tree_id"]:
        raise ConfigError("Continuation seed tree differs from frozen parent")
    identity = RecoveryIdentity(
        experiment_id=manifest["experiment_id"],
        run_id=manifest["run_id"],
        config_hash=manifest["config_hash"],
        controller_sha=manifest["controller_sha"],
        plan_hash=input_digest,
    )
    ledger_root = run_root / "checkpoints/continuation-bootstrap"
    ledger = (
        RecoveryStore.open(root=ledger_root, identity=identity)
        if (ledger_root / "recovery.json").exists()
        else RecoveryStore.initialize(root=ledger_root, identity=identity)
    )
    ledger.freeze_round(round_no=1, user_sha=seed, plan={"input_sha256": input_digest})
    receipt_path = run_root / "runtime/continuation-bootstrap.json"
    if ledger.round_state(round_no=1).get("status") == "completed":
        _verify_frozen_import(
            ledger=ledger,
            input_digest=input_digest,
            mapping_path=run_root / "runtime/continuation-issue-map.json",
            observations_path=run_root / "runtime/continuation-observations.json",
        )
        if not receipt_path.is_file():
            # A crash between ledger seal and receipt rename is recoverable without models.
            _persist_bootstrap_receipt(
                receipt_path=receipt_path,
                identity=identity.to_dict(),
                input_digest=input_digest,
                inherited=inherited,
                seed=seed,
                tree=tree,
                ledger=ledger,
                mapping_path=run_root / "runtime/continuation-issue-map.json",
            )
        receipt = json.loads(receipt_path.read_text())
        if (
            receipt.get("identity") != identity.to_dict()
            or receipt.get("input_sha256") != input_digest
            or receipt.get("sealed_sha") != ledger.round_state(round_no=1).get("sealed_sha")
        ):
            raise ConfigError("Completed bootstrap has no matching receipt")
        mapping_path = run_root / "runtime/continuation-issue-map.json"
        if receipt.get("issue_map_sha256") != sha256_file(mapping_path):
            raise ConfigError("Completed bootstrap issue mapping changed")
        assert_descendant(ancestor=seed, descendant=receipt["sealed_sha"])
        return receipt

    mapping_path = run_root / "runtime/continuation-issue-map.json"
    observations_path = run_root / "runtime/continuation-observations.json"
    imported = ledger.round_state(round_no=1).get("stages", {}).get("feedback_imported", {})
    if imported.get("status") == "completed":
        from auto_designer.experiment.continuation.evidence import (
            verify_installed_parent_observations,
        )
        from auto_designer.experiment.continuation.forge import verify_report_projection

        projection, observations = _verify_frozen_import(
            ledger=ledger,
            input_digest=input_digest,
            mapping_path=mapping_path,
            observations_path=observations_path,
        )
        verify_report_projection(
            tracker=tracker,
            parent_root=parent_root,
            export=inherited["export"],
            projection=projection,
            child_identity=identity.to_dict(),
            child_seed=seed,
            parent_archive_sha256=inherited["lineage"]["parent_archive_sha256"],
        )
        verify_installed_parent_observations(
            export=inherited["export"],
            observation_root=observation_root(child_store),
            receipt=observations,
        )
    else:
        projection = project_reports(
            tracker=tracker,
            parent_root=parent_root,
            export=inherited["export"],
            child_identity=identity.to_dict(),
            child_seed=seed,
            receipt_path=mapping_path,
            parent_archive_sha256=inherited["lineage"]["parent_archive_sha256"],
        )
        evidence = ContinuationEvidenceView(
            child_store=child_store,
            parent_root=parent_root,
            export=inherited["export"],
            issue_map=projection["issue_map"],
        )
        observations = install_parent_observations(
            parent_root=parent_root,
            export=inherited["export"],
            observation_root=observation_root(child_store),
            issue_map=projection["issue_map"],
            store=evidence,
        )
        if observations_path.is_file():
            if json.loads(observations_path.read_text()) != observations:
                raise ConfigError("Bootstrap observation projection changed")
        else:
            temporary = observations_path.with_suffix(".tmp")
            temporary.write_text(json.dumps(observations, indent=2) + "\n")
            temporary.replace(observations_path)
    evidence = ContinuationEvidenceView(
        child_store=child_store,
        parent_root=parent_root,
        export=inherited["export"],
        issue_map=projection["issue_map"],
    )
    roles = assemble_feedback_roles(
        tracker=tracker,
        store=evidence,
        repo=repo,
        definitions_root=definitions_root,
        roster=roster,
        round_provider=lambda: None,
        artifact_root=child_store.root.parent / "continuation-bootstrap/synthesizer_grouping",
        status_factory=status_factory,
        event_factory=event_factory,
    )
    pipeline = FeedbackPipeline(
        recovery=ledger,
        resolve_head=resolve_head,
        assert_descendant=assert_descendant,
        integrity_guard=integrity_guard,
        fetch_issue=lambda number: tracker.get_issue(number=number),
        prerequisite="feedback_imported",
        operation_namespace="continuation-bootstrap",
        **roles,
    )
    pipeline.mark_stage(
        round_no=1,
        stage="feedback_imported",
        input_value={
            "input_sha256": input_digest,
            "projection": projection,
            "observations": observations,
        },
    )
    pipeline.run(round_no=1, user_sha=seed)
    return _persist_bootstrap_receipt(
        receipt_path=receipt_path,
        identity=identity.to_dict(),
        input_digest=input_digest,
        inherited=inherited,
        seed=seed,
        tree=tree,
        ledger=ledger,
        mapping_path=run_root / "runtime/continuation-issue-map.json",
    )


def _persist_bootstrap_receipt(
    *,
    receipt_path,
    identity,
    input_digest,
    inherited,
    seed,
    tree,
    ledger,
    mapping_path,
):
    projection = json.loads(mapping_path.read_text())
    if projection.get("complete") is not True:
        raise ConfigError("Bootstrap mapping was not completed")
    state = ledger.round_state(round_no=1)
    if state.get("status") != "completed":
        raise ConfigError("Bootstrap ledger is not sealed")
    receipt = {
        "phase": "continuation-bootstrap",
        "status": "completed",
        "identity": identity,
        "input_sha256": input_digest,
        "source_digest": projection["source_digest"],
        "issue_map_sha256": sha256_file(mapping_path),
        "child_seed": seed,
        "parent_commit": inherited["export"]["harness"]["commit"],
        "tree_id": tree,
        "sealed_sha": state["sealed_sha"],
        "admitted_issue_ids": state.get("admitted_issue_ids", []),
        "no_admissions": not state.get("admitted_issue_ids"),
        "issue_map": projection["issue_map"],
    }
    temporary = receipt_path.with_suffix(".tmp")
    temporary.write_text(json.dumps(receipt, indent=2) + "\n")
    temporary.replace(receipt_path)
    return receipt


def _verify_frozen_import(*, ledger, input_digest, mapping_path, observations_path):
    from auto_designer.loop.recovery import digest_value

    projection = json.loads(mapping_path.read_text())
    observations = json.loads(observations_path.read_text())
    expected = {
        "input_sha256": input_digest,
        "projection": projection,
        "observations": observations,
    }
    imported = ledger.round_state(round_no=1).get("stages", {}).get("feedback_imported", {})
    units = imported.get("units", {})
    if (
        imported.get("status") != "completed"
        or len(units) != 1
        or any(
            unit.get("input_digest") != digest_value(expected)
            or unit.get("input") != expected
            or unit.get("status") != "completed"
            for unit in units.values()
        )
    ):
        raise ConfigError("Frozen bootstrap import receipt changed")
    return projection, observations
