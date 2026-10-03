from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from auto_designer.models import WorkspaceSpec


def test_prebuilt_copies_and_relocates_text_metadata(tmp_path: Path) -> None:
    from auto_designer.user.sim import seed_source

    source = tmp_path / "source"
    (source / ".venv" / "bin").mkdir(parents=True)
    site = source / ".venv" / "lib" / "python3.12" / "site-packages"
    site.mkdir(parents=True)
    (source / "payload.txt").write_text("source\n", encoding="utf-8")
    (site / "editable.pth").write_text(str(source) + "\n", encoding="utf-8")
    (source / ".venv" / "bin" / "tool").write_text(
        f"#!{source}/.venv/bin/python\n", encoding="utf-8"
    )

    copied = Path(
        seed_source.provision(WorkspaceSpec(kind="prebuilt", params={"source": str(source)}))
    )

    assert copied != source
    assert (copied / "payload.txt").read_text(encoding="utf-8") == "source\n"
    assert (copied / ".venv/lib/python3.12/site-packages/editable.pth").read_text().strip() == str(
        copied
    )
    assert (copied / ".venv/bin/tool").read_text().startswith(f"#!{copied}/")


def test_prebuilt_copies_are_isolated_and_skip_stale_venvs(tmp_path: Path) -> None:
    from auto_designer.user.sim import seed_source

    source = tmp_path / "source"
    source.mkdir()
    (source / "a.txt").write_text("base\n", encoding="utf-8")
    (source / ".venv.stale-1").mkdir()
    spec = WorkspaceSpec(kind="prebuilt", params={"source": str(source)})

    first = Path(seed_source.provision(spec))
    second = Path(seed_source.provision(spec))
    (first / "a.txt").write_text("changed\n", encoding="utf-8")

    assert (second / "a.txt").read_text(encoding="utf-8") == "base\n"
    assert not (first / ".venv.stale-1").exists()


def test_prebuilt_requires_existing_source(tmp_path: Path) -> None:
    from auto_designer.user.sim import seed_source

    with pytest.raises(ValueError, match="params.source"):
        seed_source.provision(WorkspaceSpec(kind="prebuilt"))
    with pytest.raises(FileNotFoundError, match="不存在"):
        seed_source.provision(
            WorkspaceSpec(kind="prebuilt", params={"source": str(tmp_path / "missing")})
        )


def test_real_venv_python_survives_copy_when_available(tmp_path: Path) -> None:
    from auto_designer.user.sim import seed_source

    source = tmp_path / "source"
    subprocess.run([sys.executable, "-m", "venv", str(source / ".venv")], check=True)
    copied = Path(
        seed_source.provision(WorkspaceSpec(kind="prebuilt", params={"source": str(source)}))
    )
    proc = subprocess.run(
        [str(copied / ".venv/bin/python"), "-c", "import sys; print(sys.prefix)"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert proc.stdout.strip() == str(copied / ".venv")


def test_unified_prebuilt_shell_and_script_use_copied_task_venv(tmp_path: Path) -> None:
    import json

    from auto_designer.user.sim import seed_source
    from auto_designer.user.sim.runtime import LocalWorkspaceRuntime

    source = tmp_path / "source"
    subprocess.run([sys.executable, "-m", "venv", str(source / ".venv")], check=True)
    # Editable import metadata and script shebangs must point at this session's copy.
    site = next((source / ".venv/lib").glob("python*/site-packages"))
    (source / "task_module.py").write_text("from pathlib import Path\nROOT=Path(__file__).parent\n")
    (site / "task.pth").write_text(str(source) + "\n")
    tool = source / ".venv/bin/task-tool"
    tool.write_text(f"#!{source}/.venv/bin/python\nimport task_module; print(task_module.ROOT)\n")
    tool.chmod(0o755)
    runtime = seed_source.provision(
        WorkspaceSpec(
            kind="prebuilt",
            params={"source": str(source), "activate_venv": True, "harness_python": sys.executable},
        ),
        str(tmp_path / "session"),
    )
    assert isinstance(runtime, LocalWorkspaceRuntime)
    result = runtime.run(
        "python -c 'import json,sys,task_module;print(json.dumps([sys.prefix,str(task_module.ROOT)]))'"
    )
    assert result["returncode"] == 0
    assert json.loads(result["stdout"]) == [runtime.cwd + "/.venv", runtime.cwd]
    assert runtime.run("task-tool")["stdout"].strip() == runtime.cwd
    assert runtime.evidence["harness_python"] == sys.executable
    assert runtime.cwd != str(source)


def test_legacy_linked_metadata_is_copied_without_mutating_shared_targets(tmp_path):
    from auto_designer.user.sim import seed_source

    source = tmp_path / "source"
    site = source / ".venv/lib/python3.12/site-packages"
    site.mkdir(parents=True)
    shared = tmp_path / "shared.pth"
    shared.write_text(str(source) + "\n")
    (site / "editable.pth").symlink_to(shared)
    copied = Path(
        seed_source.provision(WorkspaceSpec(kind="prebuilt", params={"source": str(source)}))
    )
    target = copied / ".venv/lib/python3.12/site-packages/editable.pth"
    assert not target.is_symlink()
    assert target.read_text().strip() == str(copied)
    assert shared.read_text().strip() == str(source)
    target.write_text("session edit")
    assert shared.read_text().strip() == str(source)
