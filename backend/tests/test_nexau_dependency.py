"""The new Git upstream must stay immutable across declarations and installations."""

import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from check_nexau_dependency import check, check_installed

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def project(tmp_path):
    for name in ("pyproject.toml", "uv.lock", "backend/compatibility.json"):
        dest = tmp_path / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, dest)
    return tmp_path


def test_git_declaration_lock_compatibility_and_installation_agree(project):
    expected = check(project)
    assert expected["repository"] == "https://github.com/hzhua/nexau.git"
    assert expected["revision"] == "28511d9f0362191a6c378fd441b2be55309a9e32"
    check_installed(expected)


def test_floating_git_branch_is_rejected(project):
    for name in ("pyproject.toml", "uv.lock"):
        path = project / name
        path.write_text(
            path.read_text().replace("28511d9f0362191a6c378fd441b2be55309a9e32", "main")
        )
    with pytest.raises(ValueError, match="full Git commit"):
        check(project)


def test_lock_revision_must_match_declaration(project):
    path = project / "uv.lock"
    path.write_text(path.read_text().replace("28511d9f0362191a6c378fd441b2be55309a9e32", "a" * 40))
    with pytest.raises(ValueError, match="full Git commit"):
        check(project)


def test_compatibility_manifest_cannot_silently_keep_old_sdk(project):
    path = project / "backend/compatibility.json"
    value = json.loads(path.read_text())
    value["nexau"]["commit"] = "a" * 40
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="compatibility manifest"):
        check(project)


def test_local_source_override_is_rejected(project):
    path = project / "pyproject.toml"
    path.write_text(path.read_text() + '\n[tool.uv.sources]\nnexau = { path = "local-sdk" }\n')
    with pytest.raises(ValueError, match="source override"):
        check(project)


def test_embedded_source_copy_cannot_return(project):
    (project / "third_party/nexau").mkdir(parents=True)
    with pytest.raises(ValueError, match="embedded NexAU"):
        check(project)


@pytest.mark.parametrize("mismatch", ["commit", "repository", "wheel"])
def test_installed_sdk_provenance_is_required(project, monkeypatch, mismatch):
    expected = check(project)
    source = {
        "url": expected["repository"],
        "vcs_info": {"vcs": "git", "commit_id": expected["revision"]},
    }
    if mismatch == "commit":
        source["vcs_info"]["commit_id"] = "a" * 40
    elif mismatch == "repository":
        source["url"] = "https://example.com/unreviewed.git"
    else:
        source = {"url": "file:///tmp/nexau-0.4.1.whl"}
    fake = SimpleNamespace(version=expected["version"], read_text=lambda name: json.dumps(source))
    monkeypatch.setattr("check_nexau_dependency.importlib.metadata.distribution", lambda name: fake)
    with pytest.raises(ValueError, match="Installed NexAU"):
        check_installed(expected)
