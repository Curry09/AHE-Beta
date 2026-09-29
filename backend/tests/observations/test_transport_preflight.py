"""Spec-0070/T3: fail before model construction, preserve old runs and pin real readers."""

import json
import subprocess
from types import SimpleNamespace

import pytest

from auto_designer.observations import preflight as module
from auto_designer.observations.transport import make_transport_profile


def profile(*, encoding="zip", policy="gitea-com-r2-v1"):
    return make_transport_profile(
        repository="https://gitea.com/api/v1/repos/owner/repo",
        encoding=encoding,
        download_policy=policy,
    )


def capabilities():
    return {
        "schema": "openagents-observation-reader-capabilities-v1",
        "marker": "auto-designer:observation-evidence-v1",
        "encodings": ["gzip", "zip"],
        "zip_profile": "single-evidence-json-v1",
        "download_policies": ["same-origin-v1", "gitea-com-r2-v1"],
        "max_transfer_bytes": 4_000_000,
        "max_expanded_bytes": 24_000_000,
    }


def result():
    return {
        "capabilities": capabilities(),
        "runtime": {"mode": "subprocess", "executable": "/reader"},
    }


class Tracker:
    def __init__(self, selected=None):
        self.selected = selected or profile()
        self.bound = None
        self.verified = False

    def select_observation_transport(self):
        return self.selected

    def bind_observation_transport(self, *, profile, reader_verified):
        self.bound, self.verified = profile, reader_verified

    def preflight_observations(self):
        assert self.bound is not None
        return {
            "repository": self.selected["repository"],
            "format": "auto-designer:observation-evidence-v1",
            "max_transfer_bytes": 4_000_000,
        }


def test_new_run_checks_reader_and_freezes_before_return(tmp_path):
    tracker = Tracker()
    actual = module.prepare_observations(tracker=tracker, root=tmp_path, reader_probe=result)
    assert actual == tracker.bound == profile()
    assert tracker.verified
    assert json.loads((tmp_path / ".transport-profile.json").read_text()) == actual
    record = json.loads((tmp_path / module.READER_RECORD).read_text())
    assert record["runtime"]["executable"] == "/reader"
    assert (
        json.loads((tmp_path / ".framework-contract.json").read_text())
        == tracker.preflight_observations()
    )


def test_old_framework_is_not_rewritten_or_required_to_have_new_cli(tmp_path):
    tracker = Tracker()
    tracker.bound = profile(encoding="gzip", policy="same-origin-v1")
    old = json.dumps(tracker.preflight_observations(), indent=4) + "\n"
    (tmp_path / ".framework-contract.json").write_text(old)
    actual = module.prepare_observations(
        tracker=tracker,
        root=tmp_path,
        reader_probe=lambda: pytest.fail("legacy run must not query new CLI"),
    )
    assert actual["encoding"] == "gzip"
    assert actual["download_policy"] == "same-origin-v1"
    assert not tracker.verified
    assert (tmp_path / ".framework-contract.json").read_text() == old


def test_resume_preserves_frozen_zip_when_site_starts_allowing_gzip(tmp_path):
    module.prepare_observations(tracker=Tracker(), root=tmp_path, reader_probe=result)
    tracker = Tracker(profile(encoding="gzip"))
    actual = module.prepare_observations(tracker=tracker, root=tmp_path, reader_probe=result)
    assert actual["encoding"] == "zip"


def test_failed_reader_does_not_bind_or_freeze(tmp_path):
    tracker = Tracker()
    with pytest.raises(ValueError, match="capability"):
        module.prepare_observations(
            tracker=tracker, root=tmp_path, reader_probe=lambda: {"capabilities": {}}
        )
    assert tracker.bound is None
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize(
    "change",
    [
        {"schema": "future"},
        {"marker": "future"},
        {"encodings": ["gzip"]},
        {"encodings": "gzip,zip"},
        {"download_policies": ["same-origin-v1"]},
        {"zip_profile": "general-zip"},
        {"max_transfer_bytes": 8_000_000},
        {"max_expanded_bytes": 48_000_000},
    ],
)
def test_incompatible_capabilities_rejected(change):
    with pytest.raises(ValueError):
        module.validate_reader_capabilities(
            capabilities={**capabilities(), **change}, profile=profile()
        )


def test_actual_subprocess_executable_is_queried_with_updates_disabled(monkeypatch):
    calls = []
    monkeypatch.setattr(module.shutil, "which", lambda _: "/opt/reader/bin/openagents")
    monkeypatch.setattr(
        module,
        "bounded_command",
        lambda argv, **kw: calls.append((argv, kw)) or json.dumps(capabilities()).encode(),
    )
    value = module.probe_reader(mode="subprocess", image="unused")
    assert calls[0][0] == [
        "env",
        "OPENAGENTS_NO_SELF_UPDATE=1",
        "/opt/reader/bin/openagents",
        "observation-capabilities",
        "--json",
    ]
    assert calls[0][1] == {"timeout": 10, "limit": 16 * 1024}
    assert value["runtime"]["executable"] == "/opt/reader/bin/openagents"


def test_image_tag_resolved_then_only_immutable_id_queried(monkeypatch):
    identity = "sha256:" + "a" * 64
    calls = []

    def command(argv, **kw):
        calls.append(argv)
        return identity.encode() if argv[1] == "image" else json.dumps(capabilities()).encode()

    monkeypatch.setattr(module, "bounded_command", command)
    value = module.probe_reader(mode="container", image="reader:candidate")
    assert calls[0][-1] == "reader:candidate"
    assert identity in calls[1] and "reader:candidate" not in calls[1]
    assert calls[1][calls[1].index("--network") + 1] == "none"
    assert value["runtime"]["image_id"] == identity


def test_reused_container_requires_formal_process_updates_disabled(monkeypatch):
    monkeypatch.setattr(module, "bounded_command", lambda *a, **kw: b"")
    with pytest.raises(ValueError, match="Recreate"):
        module.probe_reader(mode="container", image="ignored", container="actual-vigil")


def test_reused_container_queries_installed_reader_not_host_image(monkeypatch):
    calls = []

    def command(argv, **kw):
        calls.append(argv)
        if argv[1] == "exec":
            return json.dumps(capabilities()).encode()
        return ("sha256:" + "b" * 64).encode() if "{{.Image}}" in argv else b"frozen"

    monkeypatch.setattr(module, "bounded_command", command)
    value = module.probe_reader(mode="container", image="unused-host", container="actual-vigil")
    assert value["runtime"]["container"] == "actual-vigil"
    assert any(c[1] == "exec" and "actual-vigil" in c for c in calls)
    assert not any("run" in c or "unused-host" in c for c in calls)


@pytest.mark.parametrize("output", [b"not JSON", b"[]", b"{}\nextra output", b"x" * 16_385])
def test_bad_capability_output_is_safe_and_rejected(monkeypatch, output):
    monkeypatch.setattr(module, "bounded_command", lambda *a, **kw: output)
    with pytest.raises(ValueError, match="capability check failed"):
        module.probe_reader(mode="subprocess", image="unused", executable="/reader")


def test_timed_out_capability_command_reports_stage_not_stdout(monkeypatch):
    def command(*a, **kw):
        raise subprocess.TimeoutExpired("reader", 10, output="private-output")

    monkeypatch.setattr(module, "bounded_command", command)
    with pytest.raises(ValueError) as error:
        module.probe_reader(mode="subprocess", image="unused", executable="/reader")
    assert "private-output" not in str(error.value)


@pytest.mark.parametrize("factory_name", ["make_sim_run_session_fn", "make_direct_run_session_fn"])
def test_both_session_factories_block_before_constructing_model(
    tmp_path, monkeypatch, factory_name
):
    from auto_designer.loop import sim_user
    from auto_designer.user.session_store import SessionStore

    monkeypatch.setenv("AUTO_DESIGNER_OBSERVATION_ROOT", str(tmp_path / "observations"))
    monkeypatch.setattr(module, "probe_reader_from_environment", lambda: {"capabilities": {}})
    with pytest.raises(ValueError, match="capability"):
        getattr(sim_user, factory_name)(
            client_factory=lambda: pytest.fail("model must not be constructed"),
            tracker=Tracker(),
            store=SessionStore(tmp_path / "sessions"),
            sim_personas={},
        )


def test_tracker_without_observation_capability_remains_supported(tmp_path):
    assert module.prepare_observations(tracker=SimpleNamespace(), root=tmp_path) is None


def test_timed_out_image_probe_cleans_its_own_container(monkeypatch):
    calls = []

    def command(argv, **kw):
        calls.append(argv)
        if argv[1] == "image":
            return ("sha256:" + "e" * 64).encode()
        if argv[1] == "run":
            raise TimeoutError("stalled probe")
        return b""

    monkeypatch.setattr(module, "bounded_command", command)
    with pytest.raises(ValueError, match="capability check failed"):
        module.probe_reader(mode="container", image="reader:candidate")
    argv = next(a for a in calls if a[1] == "run")
    name = argv[argv.index("--name") + 1]
    assert name.startswith("observation-reader-check-")
    assert calls[-1] == ["docker", "rm", "--force", name]


def test_early_preflight_prefers_reusable_container_over_missing_image_tag(monkeypatch):
    monkeypatch.setenv("VIGIL_MODE", "container")
    monkeypatch.setenv("AUTO_DESIGNER_VIGIL_CONTAINER", "experiment-vigil")
    monkeypatch.setenv("AUTO_DESIGNER_RUN_ID", "run-1")
    monkeypatch.setenv("AUTO_DESIGNER_EXPERIMENT_ID", "exp-1")
    monkeypatch.setenv("AUTO_DESIGNER_VIGIL_IMAGE", "deleted:tag")
    calls = []

    def command(argv, **kw):
        calls.append(argv)
        if argv[1] in ("image", "run"):
            pytest.fail("must use actual reader in the reusable container")
        if argv[1] == "exec":
            return json.dumps(capabilities()).encode()
        if "{{.Image}}" in argv:
            return ("sha256:" + "f" * 64).encode()
        if any(".State.Running" in arg for arg in argv):
            assert "io.openagents.experiment_id" in argv[3]
            return b"true|run-1|exp-1"
        return b"frozen"

    monkeypatch.setattr(module, "bounded_command", command)
    actual = module.probe_reader_from_environment()
    assert actual["runtime"]["container"] == "experiment-vigil"
    assert not any(c[1] == "rm" for c in calls)


@pytest.mark.parametrize(
    "state,expected",
    [
        (b"false|run-1|exp-1", None),
        (b"true|old-run|exp-1", None),
        (b"true|run-1|exp-1", "vigil"),
    ],
)
def test_reuse_respects_running_state_and_frozen_identity(monkeypatch, state, expected):
    monkeypatch.setenv("AUTO_DESIGNER_RUN_ID", "run-1")
    monkeypatch.setenv("AUTO_DESIGNER_EXPERIMENT_ID", "exp-1")
    monkeypatch.setattr(module, "bounded_command", lambda *a, **kw: state)
    assert module.reusable_container(name="vigil") == expected


def test_early_reuse_rejects_foreign_experiment(monkeypatch):
    monkeypatch.setenv("AUTO_DESIGNER_EXPERIMENT_ID", "exp-1")
    monkeypatch.setattr(module, "bounded_command", lambda *a, **kw: b"true|run-1|foreign")
    with pytest.raises(ValueError, match="another experiment"):
        module.reusable_container(name="vigil")
