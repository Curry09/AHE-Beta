"""Spec-0073/T3: real offline editable installs and managed attempt reclamation."""

from __future__ import annotations

import contextvars
import hashlib
import io
import json
import os
import shutil
import sys
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

from ahe_beta.models import WorkspaceSpec
from ahe_beta.user.sim.sources.prebuilt import PrebuiltSource

_USAGE = contextvars.ContextVar("test_task_workspace_usage")


@pytest.fixture
def cloud_task(tmp_path, monkeypatch):
    monkeypatch.setattr("ahe_beta.usage.current_usage_context", lambda: _USAGE.get())
    uv = shutil.which("uv")
    assert uv, "Pinned project uv must be available for offline environment validation"
    root = tmp_path / "run"
    root.mkdir()
    (root / "manifest.json").write_text(
        json.dumps({"run_id": "run-1", "config_hash": "f" * 64, "workload_contract_version": 1})
    )

    def task(task_id, version):
        source = root / "workspace/tasks" / task_id / "source"
        source.mkdir(parents=True)
        (source / "task_module.py").write_text(
            "from pathlib import Path\nimport tinydep\n"
            "def main(): print(str(Path(__file__).parent)+':'+tinydep.VALUE)\n"
        )
        (source / "pyproject.toml").write_text(
            '[build-system]\nrequires=[]\nbuild-backend="build_backend"\nbackend-path=["."]\n'
        )
        (source / "build_backend.py").write_text(
            """import os,zipfile
def build_editable(wheel_directory, config_settings=None, metadata_directory=None):
    name="fixture_task-1.0-py3-none-any.whl"
    with zipfile.ZipFile(os.path.join(wheel_directory,name),'w') as out:
        out.writestr('fixture_task.pth',os.getcwd()+'\\n')
        out.writestr('fixture_task-1.0.dist-info/METADATA','Metadata-Version: 2.1\\nName: fixture-task\\nVersion: 1.0\\n')
        out.writestr('fixture_task-1.0.dist-info/WHEEL','Wheel-Version: 1.0\\nRoot-Is-Purelib: true\\nTag: py3-none-any\\n')
        out.writestr('fixture_task-1.0.dist-info/entry_points.txt','[console_scripts]\\ntask-tool = task_module:main\\n')
        out.writestr('fixture_task-1.0.dist-info/RECORD','')
    return name
"""
        )
        wheel = io.BytesIO()
        with zipfile.ZipFile(wheel, "w") as bundle:
            bundle.writestr("tinydep.py", f"VALUE={version!r}\n")
            bundle.writestr("tinydep-1.0.dist-info/METADATA", "Name: tinydep\nVersion: 1.0\n")
            bundle.writestr(
                "tinydep-1.0.dist-info/WHEEL", "Wheel-Version: 1.0\nTag: py3-none-any\n"
            )
            bundle.writestr("tinydep-1.0.dist-info/RECORD", "")
        (source / "tinydep-1.0-py3-none-any.whl").write_bytes(wheel.getvalue())
        material = root / "materials/tasks" / task_id
        material.mkdir(parents=True)
        lock = material / "requirements.lock"
        lock.write_text("# dependency wheel is part of frozen source inventory\n")
        script = material / "setup.sh"
        script.write_text("""set -euo pipefail
test "$UV_LINK_MODE" = copy
"$UV_BIN" venv --python "$TASK_PYTHON" "$VIRTUAL_ENV"
"$UV_BIN" pip install --python "$VIRTUAL_ENV/bin/python" --no-index --no-deps ./tinydep-1.0-py3-none-any.whl
"$UV_BIN" pip install --python "$VIRTUAL_ENV/bin/python" --no-index --no-deps --no-build-isolation -e .
""")
        files = {
            str(p.relative_to(source)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in source.rglob("*")
            if p.is_file()
        }
        params = {
            "workload_contract_version": 1,
            "run_root": str(root),
            "run_id": "run-1",
            "config_hash": "f" * 64,
            "task_id": task_id,
            "task_digest": "a" * 64,
            "recipe_hash": hashlib.sha256(task_id.encode()).hexdigest(),
            "source": str(source),
            "source_files": files,
            "session_root": str(root / "workspace/sessions"),
            "cache_root": str(root / "runtime/task-cache"),
            "managed_python": sys.executable,
            "uv": uv,
            "harness_python": sys.executable,
            "setup_script": str(script),
            "setup_script_sha256": hashlib.sha256(script.read_bytes()).hexdigest(),
            "requirements_lock": str(lock),
            "requirements_lock_sha256": hashlib.sha256(lock.read_bytes()).hexdigest(),
            "execution_uid": os.getuid(),
            "execution_gid": os.getgid(),
        }
        return WorkspaceSpec(kind="prebuilt", params=params)

    return root, task


def _provision(spec, session, attempt):
    _USAGE.set(
        SimpleNamespace(
            run_id="run-1",
            session_id=session,
            task_id=spec.params["task_id"],
            task_digest=spec.params["task_digest"],
            attempt=attempt,
        )
    )
    return PrebuiltSource().provision(spec)


def _tree_hash(root):
    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in root.rglob("*")
        if p.is_file() and not p.is_symlink()
    }


def test_concurrent_tasks_and_same_task_editable_imports_are_session_local(cloud_task):
    root, task = cloud_task
    first, second = task("first", "ONE"), task("second", "TWO")
    baseline = _tree_hash(root / "workspace/tasks")
    env_before = dict(os.environ)
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [
            pool.submit(_provision, spec, session, 1)
            for spec, session in ((first, "user-a"), (second, "user-b"), (first, "user-c"))
        ]
        runtimes = [f.result() for f in futures]
    try:
        a, b, c = runtimes
        for runtime, value in ((a, "ONE"), (b, "TWO"), (c, "ONE")):
            result = runtime.run("task-tool")
            assert result["returncode"] == 0, result
            assert result["stdout"].strip() == runtime.cwd + ":" + value
            site = next(Path(runtime.cwd, ".venv/lib").glob("python*/site-packages"))
            assert (site / "fixture_task.pth").read_text().strip() == runtime.cwd
            # Long Unix shebangs use a shell trampoline; both forms must name
            # this final session interpreter, never a baseline/previous venv.
            assert (
                runtime.cwd + "/.venv/bin/python"
                in Path(runtime.cwd, ".venv/bin/task-tool").read_text()
            )
            imported = runtime.run("python -c 'import task_module;print(task_module.__file__)'")
            assert imported["stdout"].strip() == runtime.cwd + "/task_module.py"
            assert runtime.evidence["task_python_prefix"] == runtime.cwd + "/.venv"
        cache_before = _tree_hash(root / "runtime/task-cache")
        a.write_text("task_module.py", "def main(): print('changed')\n")
        site = next(Path(a.cwd, ".venv/lib").glob("python*/site-packages"))
        (site / "tinydep.py").write_text("VALUE='CHANGED'\n")
        assert c.run("task-tool")["stdout"].strip() == c.cwd + ":ONE"
        assert b.run("task-tool")["stdout"].strip() == b.cwd + ":TWO"
        assert _tree_hash(root / "runtime/task-cache") == cache_before
        assert _tree_hash(root / "workspace/tasks") == baseline
        assert dict(os.environ) == env_before
    finally:
        for runtime in runtimes:
            attempt = Path(runtime.attempt_root)
            runtime.close()
            assert not attempt.exists()
            receipt = json.loads(Path(runtime.evidence["receipt_path"]).read_text())
            assert receipt["descendants_stopped"] is True
            assert receipt["attempt_identity"]["task_id"] in {"first", "second"}


def test_setup_timeout_stops_background_descendants_before_reclaim(cloud_task):
    root, task = cloud_task
    spec = task("timeout", "unused")
    script = Path(spec.params["setup_script"])
    marker = root / "runtime/writes"
    script.write_text(
        f"{sys.executable} -c \"import pathlib,time; p=pathlib.Path('{marker}'); "
        "exec('while True:\\n p.write_text(str(time.time()))\\n time.sleep(0.03)')\" &\n"
        "sleep 30\n"
    )
    spec.params["setup_script_sha256"] = hashlib.sha256(script.read_bytes()).hexdigest()
    spec.params["setup_timeout"] = 0.4
    with pytest.raises(RuntimeError, match="超时"):
        _provision(spec, "user-timeout", 1)
    saved = marker.read_text()
    time.sleep(0.15)
    assert marker.read_text() == saved
    assert not list((root / "workspace/sessions").glob("*/attempt-*"))
    receipt = json.loads(next((root / "runtime/workspace-receipts").glob("*/*.json")).read_text())
    assert receipt["timeout_contained"] and receipt["descendants_stopped"]
    assert receipt["attempt_identity"]["session_id"] == "user-timeout"
    assert receipt["invalid_reason"]


def test_managed_binding_digest_owner_and_stale_attempt_fail_closed(cloud_task):
    _, task = cloud_task
    spec = task("first", "ONE")
    _USAGE.set(
        SimpleNamespace(
            run_id="run-1", session_id=None, task_id="first", task_digest="a" * 64, attempt=1
        )
    )
    with pytest.raises(ValueError, match="bound session"):
        PrebuiltSource().provision(spec)
    runtime = _provision(spec, "user-a", 1)
    try:
        with pytest.raises(FileExistsError):
            _provision(spec, "user-a", 1)
        owner = Path(runtime.attempt_root, "owner.json")
        original = owner.read_text()
        owner.write_text("{}")
        with pytest.raises(RuntimeError, match="ownership changed"):
            runtime.close()
        assert Path(runtime.cwd).is_dir()
        owner.write_text(original)
    finally:
        runtime.close()
    Path(spec.params["source"], "task_module.py").write_text("changed")
    with pytest.raises(ValueError, match="inventory changed"):
        _provision(spec, "user-b", 1)


def test_cache_key_and_run_manifest_mismatch_rejected_before_allocating_attempt(cloud_task):
    root, task = cloud_task
    spec = task("first", "ONE")
    original = spec.params["recipe_hash"]
    spec.params["recipe_hash"] = "../../another-run"
    with pytest.raises(ValueError, match="content key"):
        _provision(spec, "user-a", 1)
    assert not (root / "workspace/sessions").exists()
    spec.params["recipe_hash"] = original
    spec.params["config_hash"] = "b" * 64
    with pytest.raises(ValueError, match="frozen manifest"):
        _provision(spec, "user-a", 1)
    assert not (root / "workspace/sessions").exists()


@pytest.mark.parametrize("location", ["params", "manifest"])
def test_managed_contract_boolean_is_rejected_before_allocating_attempt(cloud_task, location):
    root, task = cloud_task
    spec = task("first", "ONE")
    if location == "params":
        spec.params["workload_contract_version"] = True
        message = "Unknown prebuilt workload contract"
    else:
        manifest = root / "manifest.json"
        document = json.loads(manifest.read_text())
        document["workload_contract_version"] = True
        manifest.write_text(json.dumps(document))
        message = "frozen manifest"
    with pytest.raises(ValueError, match=message):
        _provision(spec, "user-a", 1)
    assert not (root / "workspace/sessions").exists()


@pytest.mark.parametrize("linked_venv", [False, True])
def test_setup_rejects_python_outside_final_session_virtualenv(cloud_task, linked_venv):
    root, task = cloud_task
    spec = task("first", "ONE")
    script = Path(spec.params["setup_script"])
    if linked_venv:
        script.write_text(
            '"$UV_BIN" venv --python "$TASK_PYTHON" "$TASK_ROOT/../other-venv"\n'
            'ln -s ../other-venv "$VIRTUAL_ENV"\n'
        )
    else:
        # A runnable Python symlink is not proof that setup created a venv.
        script.write_text(
            'mkdir -p "$VIRTUAL_ENV/bin"\nln -s "$TASK_PYTHON" "$VIRTUAL_ENV/bin/python"\n'
        )
    spec.params["setup_script_sha256"] = hashlib.sha256(script.read_bytes()).hexdigest()
    with pytest.raises(RuntimeError, match="final session"):
        _provision(spec, "user-a", 1)
    assert not list((root / "workspace/sessions").glob("*/attempt-*"))
    receipt = json.loads(next((root / "runtime/workspace-receipts").glob("*/*.json")).read_text())
    assert receipt["descendants_stopped"]
    assert "setup_completed_at" not in receipt
