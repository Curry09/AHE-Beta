"""Real Git collection retains task edits while omitting runtime logs."""

import subprocess

from evaluation.harness.workspace import reserve_bookkeeping


def git(root, *arguments):
    return subprocess.run(
        ["git", "-C", str(root), *arguments], check=True, capture_output=True, text=True
    ).stdout


def repository(root):
    git(root, "init", "-q")
    git(root, "config", "user.email", "fixture@example.invalid")
    git(root, "config", "user.name", "Fixture")
    (root / "task.txt").write_text("original\n")
    git(root, "add", "task.txt")
    git(root, "commit", "-qm", "baseline")


def write(root, name, contents):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents)


def test_official_add_all_keeps_task_changes_and_omits_bookkeeping(tmp_path):
    repository(tmp_path)
    metadata = tmp_path / ".git/info/exclude"
    metadata.write_text("existing-rule")
    assert reserve_bookkeeping(tmp_path)["excluded"] == ["/.harness/"]
    original_exclusion = metadata.read_text()
    reserve_bookkeeping(tmp_path)
    assert metadata.read_text() == original_exclusion
    assert original_exclusion.startswith("existing-rule\n")
    write(tmp_path, ".harness/wire.jsonl", "runtime event\n")
    write(tmp_path, "task.txt", "changed\n")
    write(tmp_path, "tests/new_test.py", "assert True\n")
    git(tmp_path, "add", "-A")
    patch = git(tmp_path, "diff", "--binary", "HEAD")
    assert "diff --git a/.harness" not in patch
    assert "diff --git a/task.txt" in patch
    assert "diff --git a/tests/new_test.py" in patch
    assert (tmp_path / ".harness/wire.jsonl").read_text() == "runtime event\n"
    assert not (tmp_path / ".gitignore").exists()


def test_nested_workspace_does_not_hide_unrelated_root_paths(tmp_path):
    repository(tmp_path)
    workspace = tmp_path / "nested"
    workspace.mkdir()
    assert reserve_bookkeeping(workspace)["excluded"] == ["/nested/.harness/"]
    write(tmp_path, "nested/.harness/wire.jsonl", "runtime\n")
    write(tmp_path, ".harness/task_input.txt", "task data\n")
    git(tmp_path, "add", "-A")
    names = git(tmp_path, "diff", "--name-only", "HEAD").splitlines()
    assert names == [".harness/task_input.txt"]


def test_task_owned_tracked_harness_path_is_never_hidden(tmp_path):
    repository(tmp_path)
    write(tmp_path, ".harness/task_input.txt", "original\n")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-qm", "task-owned input")
    assert reserve_bookkeeping(tmp_path)["reason"] == "task_tracks_bookkeeping_path"
    write(tmp_path, ".harness/task_input.txt", "changed\n")
    write(tmp_path, ".harness/new_task_file.txt", "new\n")
    git(tmp_path, "add", "-A")
    assert len(git(tmp_path, "diff", "--name-only", "HEAD").splitlines()) == 2


def test_non_git_task_does_not_gain_a_repository(tmp_path):
    assert reserve_bookkeeping(tmp_path) == {"excluded": [], "reason": "not_git_workspace"}
    assert list(tmp_path.iterdir()) == []
