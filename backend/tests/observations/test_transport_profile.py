import json

import pytest

from auto_designer.observations.transport import (
    freeze_transport_profile,
    load_transport_profile,
    make_transport_profile,
    validate_transport_profile,
)

REPO = "http://gitea:3000/api/v1/repos/o/r"


def test_new_freeze_and_recovery_are_identical(tmp_path):
    assert load_transport_profile(root=tmp_path, repository=REPO) is None
    profile = make_transport_profile(repository=REPO)
    assert freeze_transport_profile(root=tmp_path, profile=profile) == profile
    assert load_transport_profile(root=tmp_path, repository=REPO) == profile
    assert freeze_transport_profile(root=tmp_path, profile=profile) == profile
    with pytest.raises(ValueError, match="changed"):
        freeze_transport_profile(
            root=tmp_path, profile=make_transport_profile(repository=REPO, encoding="zip")
        )


def test_legacy_contract_implies_gzip_and_is_never_rewritten(tmp_path):
    raw = json.dumps(
        {"repository": REPO, "format": "artifact-observations-v1", "max_transfer_bytes": 4000000}
    )
    (tmp_path / ".framework-contract.json").write_text(raw)
    old = load_transport_profile(root=tmp_path, repository=REPO)
    assert old["encoding"] == "gzip"
    assert old["download_policy"] == "same-origin-v1"
    with pytest.raises(ValueError, match="changed"):
        freeze_transport_profile(
            root=tmp_path, profile=make_transport_profile(repository=REPO, encoding="zip")
        )
    freeze_transport_profile(root=tmp_path, profile=old)
    assert (tmp_path / ".framework-contract.json").read_text() == raw


@pytest.mark.parametrize(
    "change",
    [
        {"encoding": "tar"},
        {"schema": "future"},
        {"max_transfer_bytes": 4000001},
        {"download_policy": "anything"},
        {"token": "secret"},
    ],
)
def test_profile_rejects_unknowns_and_changed_limits(change):
    with pytest.raises(ValueError):
        validate_transport_profile({**make_transport_profile(repository=REPO), **change})


def test_other_repository_is_not_resumed(tmp_path):
    freeze_transport_profile(root=tmp_path, profile=make_transport_profile(repository=REPO))
    with pytest.raises(ValueError):
        load_transport_profile(root=tmp_path, repository=REPO + "-other")


@pytest.mark.parametrize("name", [".framework-contract.json", ".transport-profile.json"])
def test_symlink_binding_rejected(tmp_path, name):
    target = tmp_path / "other"
    target.write_text("{}")
    (tmp_path / name).symlink_to(target)
    with pytest.raises(ValueError, match="symlink"):
        load_transport_profile(root=tmp_path, repository=REPO)
