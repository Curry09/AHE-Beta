"""Spec-0079/T2: parent facts are read-only; native evidence remains byte exact."""

import gzip
import hashlib
import json

import pytest

from auto_designer.demand.delivery_evidence import build_package
from auto_designer.demand.observation_provider import ObservationProvider
from auto_designer.execution_contract import canonical_sha256, make_execution_contract
from auto_designer.experiment.config import ConfigError
from auto_designer.experiment.continuation.evidence import (
    ContinuationEvidenceView,
    install_parent_observations,
    verify_installed_parent_observations,
)
from auto_designer.models import (
    FeelingScore,
    IssueRef,
    Persona,
    SeedScenario,
    Session,
    SimTrace,
    Transcript,
)
from auto_designer.observations.grants import authorized_sessions
from auto_designer.user.session_store import SessionConflictError, SessionStore


@pytest.fixture
def evidence(tmp_path):
    parent = tmp_path / "parent"
    parent.mkdir()
    session = Session(
        session_id="parent-sid",
        persona=Persona("p", "l", "d", "g", "s"),
        scenario=SeedScenario("task"),
        transcript=Transcript([]),
        feeling=FeelingScore(2, "gap"),
        issue_refs=[IssueRef(7, "https://parent/issues/7", "open")],
        sim_trace=SimTrace(
            persona_id="p", end_reason="evaluator_invalid", evaluation_status="invalid"
        ),
        accept_validity="unverified_accept",
    )
    path = parent / "sessions/parent-sid.json"
    path.parent.mkdir()
    path.write_text(json.dumps(session.to_dict()))
    exported = {
        "boundary": {
            "sessions": [
                {
                    "session_id": session.session_id,
                    "path": "sessions/parent-sid.json",
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }
            ]
        }
    }
    child = SessionStore(tmp_path / "child/sessions")
    issue_map = {"source": {"source_number": 7, "current_number": 1, "session_ids": ["parent-sid"]}}
    return parent, exported, child, issue_map


def test_view_keeps_invalid_and_original_refs_without_writing_child_index(evidence):
    parent, exported, child, issue_map = evidence
    before = {p.relative_to(parent): p.read_bytes() for p in parent.rglob("*") if p.is_file()}
    view = ContinuationEvidenceView(
        child_store=child, parent_root=parent, export=exported, issue_map=issue_map
    )
    assert view.index() == []
    row = view.index(include_invalid=True)[0]
    assert row["issue_numbers"] == [1] and row["source_issue_numbers"] == [7]
    assert view.find_session_id_by_issue(1) == "parent-sid"
    assert view.find_session_id_by_issue(7) is None
    assert view.load("parent-sid").issue_refs[0].number == 7
    assert view.load("parent-sid").accept_validity == "unverified_accept"
    assert child.index(include_invalid=True) == []
    assert not child.root.exists()
    assert before == {
        p.relative_to(parent): p.read_bytes() for p in parent.rglob("*") if p.is_file()
    }


def test_parent_child_sid_collision_is_not_overwritten(evidence):
    parent, exported, child, issue_map = evidence
    child.root.mkdir(parents=True)
    (child.root / "parent-sid.json").write_text("different")
    with pytest.raises(SessionConflictError, match="collide"):
        ContinuationEvidenceView(
            child_store=child, parent_root=parent, export=exported, issue_map=issue_map
        )


def test_parent_tampering_is_detected_on_load(evidence):
    parent, exported, child, issue_map = evidence
    view = ContinuationEvidenceView(
        child_store=child, parent_root=parent, export=exported, issue_map=issue_map
    )
    path = parent / "sessions/parent-sid.json"
    path.write_text(path.read_text() + " ")
    with pytest.raises(ConfigError, match="content changed"):
        view.load("parent-sid")


@pytest.fixture
def assessed_parent(evidence):
    parent, exported, child, issue_map = evidence
    path = parent / "sessions/parent-sid.json"
    session = json.loads(path.read_text())
    contract = make_execution_contract(
        session_id="parent-sid",
        task_id="task",
        task_digest="a" * 64,
        followup_input="unavailable",
        task_budget_seconds=600,
        budget_source="task_metadata",
    )
    session.update(
        execution_contract=contract,
        session_provenance={"round_no": 1, "harness_sha": "b" * 40},
    )
    path.write_text(json.dumps(session))
    exported["boundary"]["sessions"][0]["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    summary = dict(
        receipt_id="parent-assessment",
        session_id="parent-sid",
        contract_id=contract["contract_id"],
        status="completed",
        passed=False,
        score=None,
        metric_definition=None,
        assessment_kind="custom",
        source_sha256="c" * 64,
    )
    relative = "assessment/feedback/round-1.json"
    projection = parent / relative
    projection.parent.mkdir(parents=True)
    projection.write_text(
        json.dumps(
            dict(
                round_no=1,
                user_sha="b" * 40,
                summaries=[summary],
                sha256=canonical_sha256([summary]),
            )
        )
    )
    (parent / "collection.json").write_text(
        json.dumps({"files": {relative: hashlib.sha256(projection.read_bytes()).hexdigest()}})
    )
    return evidence, summary, projection


def test_continuation_preserves_parent_assessment_without_child_writes(assessed_parent):
    (parent, exported, child, issue_map), summary, _ = assessed_parent
    before = {p.relative_to(parent): p.read_bytes() for p in parent.rglob("*") if p.is_file()}
    view = ContinuationEvidenceView(
        child_store=child, parent_root=parent, export=exported, issue_map=issue_map
    )
    assert view.load_assessment_summaries("parent-sid") == [summary]
    assert not child.root.exists()
    assert before == {
        p.relative_to(parent): p.read_bytes() for p in parent.rglob("*") if p.is_file()
    }


@pytest.mark.parametrize("mutation", ["changed", "missing", "unlisted"])
def test_parent_assessment_requires_archived_bytes(assessed_parent, mutation):
    (parent, exported, child, issue_map), _, projection = assessed_parent
    if mutation == "changed":
        frozen = json.loads(projection.read_text())
        frozen["summaries"][0]["passed"] = True
        frozen["sha256"] = canonical_sha256(frozen["summaries"])
        projection.write_text(json.dumps(frozen))
    elif mutation == "missing":
        projection.unlink()
    else:
        (parent / "collection.json").write_text('{"files":{}}')
    view = ContinuationEvidenceView(
        child_store=child, parent_root=parent, export=exported, issue_map=issue_map
    )
    with pytest.raises((SessionConflictError, ConfigError), match="assessment"):
        view.load_assessment_summaries("parent-sid")


def test_parent_without_measurement_stays_unmeasured(evidence):
    parent, exported, child, issue_map = evidence
    view = ContinuationEvidenceView(
        child_store=child, parent_root=parent, export=exported, issue_map=issue_map
    )
    assert view.load_assessment_summaries("parent-sid") == []


@pytest.mark.parametrize("redacted", [False, True])
def test_native_bundle_copy_preserves_bytes_or_marks_unavailable(evidence, monkeypatch, redacted):
    parent, exported, child, issue_map = evidence
    native = parent / "observations/parent-sid"
    native.mkdir(parents=True)
    original = b"real raw model bytes"
    (native / "raw.txt").write_bytes(b"[REDACTED]" if redacted else original)
    manifest = {
        "session_id": "parent-sid",
        "files": [
            {
                "path": "raw.txt",
                "sha256": hashlib.sha256(original).hexdigest(),
                "bytes": len(original),
            }
        ],
    }
    (native / "manifest.json").write_text(json.dumps(manifest))
    exported["boundary"]["sessions"][0]["observation_path"] = "observations/parent-sid"
    view = ContinuationEvidenceView(
        child_store=child, parent_root=parent, export=exported, issue_map=issue_map
    )
    destination = child.root.parent / "observations"
    monkeypatch.delenv("AUTO_DESIGNER_OBSERVATION_ROOT", raising=False)
    args = {
        "parent_root": parent,
        "export": exported,
        "observation_root": destination,
        "issue_map": issue_map,
        "store": view,
    }
    result = install_parent_observations(**args)
    assert result["parent-sid"]["status"] == ("unavailable" if redacted else "available")
    assert authorized_sessions(store=view, issue=1) == {"parent-sid"}
    if redacted:
        assert not (destination / "parent-sid").exists()
    else:
        assert (destination / "parent-sid/raw.txt").read_bytes() == original
        assert (destination / "parent-sid/manifest.json").read_bytes() == (
            native / "manifest.json"
        ).read_bytes()
        assert install_parent_observations(**args) == result
    package = json.loads(gzip.decompress(build_package(store=view, issue=1)))
    assert package["sessions"][0]["status"] == ("unavailable" if redacted else "available")
    provider = ObservationProvider(view, allowed_session_ids=frozenset({"parent-sid"}))
    assert ("parent-sid" in provider.files) is not redacted
    before = {
        p.relative_to(destination): p.read_bytes() for p in destination.rglob("*") if p.is_file()
    }
    verify_installed_parent_observations(
        export=exported, observation_root=destination, receipt=result
    )
    assert before == {
        p.relative_to(destination): p.read_bytes() for p in destination.rglob("*") if p.is_file()
    }
    if not redacted:
        (destination / "parent-sid/raw.txt").write_bytes(b"tampered on resume")
        with pytest.raises(ConfigError, match="installed native observation changed"):
            verify_installed_parent_observations(
                export=exported, observation_root=destination, receipt=result
            )
