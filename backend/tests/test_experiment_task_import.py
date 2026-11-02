"""Spec-0076/T1: real input preservation and fail-closed material conversion."""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import subprocess
from pathlib import Path

import pytest

from ahe_beta.experiment import task_import
from ahe_beta.experiment.config import ConfigError, load_task_package
from ahe_beta.experiment.task_import import import_seed_tasks, import_text_task

ROOT = Path(__file__).resolve().parents[2]
SHA = "a" * 40


def card(*, task_id: str, repo: str | None) -> dict:
    result = {
        "id": task_id,
        "source": {"not_in_benchmark": True},
        "task": {"prompt": "保留 'quote' 和换行。\r\n\n  "},
    }
    if repo is not None:
        result["source"]["repo"] = repo
        result["env"] = {"repo_at": SHA}
    return result


def library_file(*, root: Path, document: object) -> Path:
    path = root / "library.json"
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    return path


def test_actual_archived_seven_cards_generate_current_packages(tmp_path):
    library = ROOT / "research/archives/legacy-materials/seeds.json"
    originals = json.loads(library.read_bytes())["seeds"]
    result = import_seed_tasks(library=library, output=tmp_path / "result")
    assert result["ok"] is True
    assert result["source_sha256"] == hashlib.sha256(library.read_bytes()).hexdigest()
    assert len(result["task_packages"]) == len(originals) == 7
    for original, path in zip(originals, result["task_packages"], strict=True):
        package = load_task_package(path)
        assert package["id"] == original["id"]
        assert package["kind"] == "ordinary" and package["not_in_benchmark"] is True
        assert package["interaction"] == "simulated_user"
        assert Path(package["instruction_file"]).read_bytes() == original["task"]["prompt"].encode()
        assert Path(package["source"]["path"], "README.md").is_file()
    index = json.loads(Path(result["index_file"]).read_bytes())
    assert index["task_packages"] == [f"tasks/{record['id']}/task.json" for record in originals]
    assert all(Path(value).is_absolute() for value in result["task_packages"])
    assert not list(tmp_path.glob(".task-import-*"))


@pytest.mark.parametrize("envelope", [False, True])
def test_git_and_text_selection_preserves_order_and_discards_hidden_fields(tmp_path, envelope):
    records = [card(task_id="git-task", repo="owner/repo"), card(task_id="text", repo=None)]
    for record in records:
        record["task"]["context"] = "CONTEXT_MUST_NOT_BE_ADDED"
        record["oracle"] = {"reference_solution": "ORACLE_MUST_NOT_ESCAPE"}
        record["gates"] = {"oracle_gate": "GATE_MUST_NOT_ESCAPE"}
        record["provenance"] = {"resolution_quote": "PROVENANCE_MUST_NOT_ESCAPE"}
        record.setdefault("env", {})["test_cmd"] = "TEST_COMMAND_MUST_NOT_ESCAPE"
    document = {"version": 1, "seeds": records} if envelope else records
    library = library_file(root=tmp_path, document=document)
    result = import_seed_tasks(
        library=library,
        output=tmp_path / "out",
        seed_ids=["text", "git-task"],
        interaction="direct",
    )
    packages = [load_task_package(path) for path in result["task_packages"]]
    assert [package["id"] for package in packages] == ["git-task", "text"]
    assert packages[0]["source"] == {
        "kind": "git",
        "url": "https://github.com/owner/repo.git",
        "revision": SHA,
        "repo": "owner/repo",
    }
    assert all(package["interaction"] == "direct" for package in packages)
    contents = b"".join(
        file.read_bytes() for file in (tmp_path / "out").rglob("*") if file.is_file()
    )
    for sentinel in (b"CONTEXT_", b"ORACLE_", b"GATE_", b"PROVENANCE_", b"TEST_COMMAND_"):
        assert sentinel not in contents


def test_selected_card_does_not_validate_unselected_recipe(tmp_path):
    bad = card(task_id="unselected", repo="owner/repo")
    bad["env"]["repo_at"] = "unresolved"
    library = library_file(root=tmp_path, document=[bad, card(task_id="selected", repo=None)])
    result = import_seed_tasks(library=library, output=tmp_path / "out", seed_ids=["selected"])
    assert len(result["task_packages"]) == 1


def test_index_filename_is_also_a_valid_task_id(tmp_path):
    library = library_file(root=tmp_path, document=[card(task_id="tasks.json", repo=None)])
    result = import_seed_tasks(library=library, output=tmp_path / "out")
    assert load_task_package(result["task_packages"][0])["id"] == "tasks.json"
    assert Path(result["index_file"]).is_file()


@pytest.mark.parametrize("raw", [b"\xe4\xb8\xad\r\n\r\n  ", b"plain text\n"])
def test_text_preserves_input_bytes_and_has_no_pip_seed(tmp_path, raw):
    instruction = tmp_path / "instruction.md"
    instruction.write_bytes(raw)
    result = import_text_task(
        instruction=instruction, task_id="text", output=tmp_path / "out", not_in_benchmark=True
    )
    package = load_task_package(result["task_packages"][0])
    assert Path(package["instruction_file"]).read_bytes() == raw
    assert result["source_sha256"] == hashlib.sha256(raw).hexdigest()
    assert "--seed" not in Path(package["setup"]["script"]).read_text()


def test_import_never_executes_setup_or_contacts_network(tmp_path, monkeypatch):
    record = card(task_id="git", repo="https://example.com/owner/repo.git")
    record["env"]["setup"] = [f"touch {shlex.quote(str(tmp_path / 'must-not-exist'))}"]
    library = library_file(root=tmp_path, document=[record])

    def forbidden(*args, **kwargs):
        pytest.fail("Pure conversion attempted subprocess or network access")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    import socket

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    result = import_seed_tasks(library=library, output=tmp_path / "out")
    assert load_task_package(result["task_packages"][0])["source"]["repo"] == "owner/repo"
    assert not (tmp_path / "must-not-exist").exists()


def test_generated_setup_runs_original_strings_in_independent_shells_with_venv_pip(tmp_path):
    original = card(task_id="text", repo=None)
    commands = [
        "printf '%s\\n' \"a 'quote' and \\\"double\\\"\" > quoted.txt\n"
        "cat <<'END' >> quoted.txt\nline one\n中文 line two\nEND\n"
        "export FROM_FIRST=yes; cd /",
        'test -z "${FROM_FIRST:-}"; test "$PWD" = "$TASK_ROOT"; pip --version > pip.txt',
    ]
    original["env"] = {"setup": commands}
    library = library_file(root=tmp_path, document=[original])
    result = import_seed_tasks(library=library, output=tmp_path / "out")
    package = load_task_package(result["task_packages"][0])
    script = Path(package["setup"]["script"])
    assert "--seed" in script.read_text()
    assert "NOT automatically locked" in Path(package["setup"]["requirements_lock"]).read_text()
    root = Path(package["source"]["path"])
    fake_uv = tmp_path / "fake-uv"
    fake_uv.write_text(
        "#!/usr/bin/env bash\nset -e\n"
        'printf "%s\\n" "$@" > "$TASK_ROOT/uv-args.txt"\n'
        'mkdir -p "$VIRTUAL_ENV/bin"\n'
        "cat > \"$VIRTUAL_ENV/bin/pip\" <<'END'\n"
        "#!/usr/bin/env bash\nprintf 'task venv pip\\n'\nEND\n"
        'chmod +x "$VIRTUAL_ENV/bin/pip"\n'
    )
    fake_uv.chmod(0o700)
    env = {
        **os.environ,
        "TASK_ROOT": str(root),
        "TASK_PYTHON": "/unused/managed-python",
        "VIRTUAL_ENV": str(root / ".venv"),
        "UV_BIN": str(fake_uv),
    }
    subprocess.run(["bash", str(script)], env=env, check=True, capture_output=True)
    assert (
        root / "quoted.txt"
    ).read_text() == "a 'quote' and \"double\"\nline one\n中文 line two\n"
    assert (root / "pip.txt").read_text() == "task venv pip\n"
    assert "--seed" in (root / "uv-args.txt").read_text().splitlines()


@pytest.mark.parametrize(
    "document",
    [None, {}, [], {"seeds": []}, [None], [{"description": "old SeedScenario"}]],
)
def test_bad_library_shapes_leave_no_output(tmp_path, document):
    library = library_file(root=tmp_path, document=document)
    with pytest.raises(ConfigError):
        import_seed_tasks(library=library, output=tmp_path / "out")
    assert not (tmp_path / "out").exists()
    assert not list(tmp_path.glob(".task-import-*"))


@pytest.mark.parametrize(
    "field,value",
    [
        ("source", None),
        ("source", {"not_in_benchmark": False}),
        ("source", {"not_in_benchmark": 1}),
        ("task", {}),
        ("task", {"prompt": 10}),
        ("task", {"prompt": " \n"}),
        ("env", []),
        ("env", {"setup": "pip install package"}),
        ("env", {"setup": [False]}),
        ("env", {"setup": ["\x00"]}),
        ("domain", ["dev-tooling"]),
        ("domain", "invalid-domain"),
        ("capability_probed", "env-setup"),
        ("capability_probed", [{}]),
        ("reject_reason", "not admitted"),
        ("benchmark_score", 1),
    ],
)
def test_bad_card_fields_abort_whole_batch(tmp_path, field, value):
    bad = card(task_id="bad", repo=None)
    bad[field] = value
    library = library_file(root=tmp_path, document=[card(task_id="good", repo=None), bad])
    with pytest.raises(ConfigError):
        import_seed_tasks(library=library, output=tmp_path / "out")
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize(
    "repo,revision",
    [
        ("owner/repo", "a" * 39),
        ("owner/repo", "A" * 40),
        ("owner/repo", "main"),
        ("owner/repo", None),
        ("git@example.com:owner/repo", SHA),
        ("http://example.com/owner/repo", SHA),
        ("https://user:password@example.com/owner/repo", SHA),
        ("https://example.com/owner/repo?token=private", SHA),
        ("https://example.com/owner/repo#fragment", SHA),
        ("https://example.com/group/owner/repo", SHA),
        ("https://example.com/../repo", SHA),
    ],
)
def test_invalid_git_metadata_is_rejected_without_output(tmp_path, repo, revision):
    record = card(task_id="git", repo=repo)
    record["env"]["repo_at"] = revision
    library = library_file(root=tmp_path, document=[record])
    with pytest.raises(ConfigError):
        import_seed_tasks(library=library, output=tmp_path / "out")
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("ids", [["absent"], ["good", "good"], [], ["../bad"]])
def test_invalid_selections_are_rejected(tmp_path, ids):
    library = library_file(root=tmp_path, document=[card(task_id="good", repo=None)])
    with pytest.raises(ConfigError):
        import_seed_tasks(library=library, output=tmp_path / "out", seed_ids=ids)


@pytest.mark.parametrize("task_id", ["../escape", "a/b", "", "a" * 129])
def test_bad_id_and_duplicate_ids_are_rejected(tmp_path, task_id):
    library = library_file(root=tmp_path, document=[card(task_id=task_id, repo=None)])
    with pytest.raises(ConfigError):
        import_seed_tasks(library=library, output=tmp_path / "out")
    library = library_file(root=tmp_path, document=[card(task_id="same", repo=None)] * 2)
    with pytest.raises(ConfigError):
        import_seed_tasks(library=library, output=tmp_path / "out")


@pytest.mark.parametrize("raw", [b"", b" \r\n", b"\xff"])
def test_invalid_text_leaves_no_output(tmp_path, raw):
    instruction = tmp_path / "instruction.md"
    instruction.write_bytes(raw)
    with pytest.raises(ConfigError):
        import_text_task(
            instruction=instruction, task_id="text", output=tmp_path / "out", not_in_benchmark=True
        )
    assert not (tmp_path / "out").exists()


def test_missing_input_and_absent_nonbenchmark_declaration_are_rejected(tmp_path):
    with pytest.raises(ConfigError):
        import_seed_tasks(library=tmp_path / "missing", output=tmp_path / "out")
    instruction = tmp_path / "instruction.md"
    instruction.write_text("task")
    with pytest.raises(ConfigError):
        import_text_task(
            instruction=instruction, task_id="text", output=tmp_path / "out", not_in_benchmark=False
        )
    with pytest.raises(ConfigError):
        import_text_task(
            instruction=instruction,
            task_id="text",
            output=tmp_path / "out",
            not_in_benchmark=True,
            interaction="other",
        )


@pytest.mark.parametrize("kind", ["file", "empty-directory", "directory", "symlink", "dangling"])
def test_existing_output_never_changes(tmp_path, kind):
    library = library_file(root=tmp_path, document=[card(task_id="good", repo=None)])
    output = tmp_path / "out"
    if kind == "file":
        output.write_text("existing")
    elif kind in {"empty-directory", "directory"}:
        output.mkdir()
        if kind == "directory":
            (output / "existing").write_text("existing")
    else:
        target = tmp_path / "target"
        if kind == "symlink":
            target.mkdir()
        output.symlink_to(target)
    with pytest.raises(ConfigError):
        import_seed_tasks(library=library, output=output)
    assert output.exists() or output.is_symlink()
    assert not list(tmp_path.glob(".task-import-*"))


def test_package_validation_failure_cleans_stage_and_keeps_input(tmp_path, monkeypatch):
    library = library_file(root=tmp_path, document=[card(task_id="good", repo=None)])
    original = library.read_bytes()

    def fail_validation(path):
        raise ConfigError("validation failed")

    monkeypatch.setattr(task_import, "load_task_package", fail_validation)
    with pytest.raises(ConfigError, match="validation failed"):
        import_seed_tasks(library=library, output=tmp_path / "out")
    assert not (tmp_path / "out").exists()
    assert not list(tmp_path.glob(".task-import-*"))
    assert library.read_bytes() == original


def test_publish_failure_removes_only_own_output(tmp_path, monkeypatch):
    library = library_file(root=tmp_path, document=[card(task_id="good", repo=None)])
    unrelated = tmp_path / "existing"
    unrelated.write_text("keep")
    original_move = task_import.shutil.move

    def fail_index_move(src, dst):
        if Path(src).name == "tasks.json":
            raise OSError("index publication failed")
        return original_move(src, dst)

    monkeypatch.setattr(task_import.shutil, "move", fail_index_move)
    with pytest.raises(OSError, match="publication failed"):
        import_seed_tasks(library=library, output=tmp_path / "out")
    assert not (tmp_path / "out").exists()
    assert not list(tmp_path.glob(".task-import-*"))
    assert unrelated.read_text() == "keep" and library.is_file()


def test_competing_output_between_check_and_publication_is_preserved(tmp_path, monkeypatch):
    library = library_file(root=tmp_path, document=[card(task_id="good", repo=None)])
    output = tmp_path / "out"
    original_loader = task_import.load_task_package

    def competing_import(path):
        package = original_loader(path)
        output.mkdir()
        (output / "existing").write_text("other publisher")
        return package

    monkeypatch.setattr(task_import, "load_task_package", competing_import)
    with pytest.raises(FileExistsError):
        import_seed_tasks(library=library, output=output)
    assert (output / "existing").read_text() == "other publisher"
    assert not list(tmp_path.glob(".task-import-*"))
