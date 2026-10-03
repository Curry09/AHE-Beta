"""Spec-0072/T3: run-local dependencies and an unprivileged delivery boundary."""

from __future__ import annotations

import hashlib
import io
import json
import os
import pwd
import site
import subprocess
import sys
import tarfile
import urllib.request
from pathlib import Path
from types import SimpleNamespace

import pytest

from auto_designer.experiment.backends.e2b_bootstrap import (
    BOOTSTRAP_PROGRAM,
    CLAUDE_SHA256,
    UV_SHA256,
)


@pytest.mark.parametrize("multitask", [False, True])
def test_bootstrap_installs_run_local_python_and_transfers_only_owned_tree(
    tmp_path, monkeypatch, multitask
):
    root = tmp_path / "run"
    materials = root / "materials"
    materials.mkdir(parents=True)
    records = {}

    def material(name, data):
        path = materials / name
        path.write_bytes(data)
        records[name] = {"path": "materials/" + name, "sha256": hashlib.sha256(data).hexdigest()}

    def archive(entries):
        output = io.BytesIO()
        with tarfile.open(fileobj=output, mode="w:gz") as bundle:
            for name, data, mode in entries:
                info = tarfile.TarInfo(name)
                info.size, info.mode = len(data), mode
                bundle.addfile(info, io.BytesIO(data))
        return output.getvalue()

    controller_entries = [("README", b"controller", 0o644)]
    if multitask:
        package_root = Path(__file__).parents[1] / "auto_designer"
        controller_entries.extend(
            (
                "backend/auto_designer/" + str(path.relative_to(package_root)),
                path.read_bytes(),
                0o644,
            )
            for path in sorted(package_root.rglob("*.py"))
        )
        # A poisonous ambient source proves bootstrap selects only its frozen
        # controller tree, even when uv sync has not installed auto_designer.
        ambient = tmp_path / "ambient/auto_designer"
        ambient.mkdir(parents=True)
        (ambient / "__init__.py").write_text(
            "raise AssertionError('ambient controller imported')\n"
        )
        monkeypatch.setenv("PYTHONPATH", str(ambient.parent))
    material("controller_source_archive", archive(controller_entries))
    material("openagents_source_archive", archive([("README", b"openagents", 0o644)]))
    material("task_source_archive", archive([("task.py", b"print('task')\n", 0o644)]))
    material("requirements_lock", b"# frozen\n")
    material("script", b'"$TASK_PYTHON" -m venv --without-pip "$VIRTUAL_ENV"\n')
    manifest = {
        "materials": records,
        "source_snapshot": {"files": {}},
        "task_package": {"source": {"kind": "local"}},
    }
    if multitask:
        tasks = []
        for task_id in ("ordinary", "swe"):
            tasks.append(
                {
                    "id": task_id,
                    "digest": hashlib.sha256(task_id.encode()).hexdigest(),
                    "package": {"source": {"kind": "local", "path": "source/tasks/" + task_id}},
                    "source_snapshot": {
                        "revision": None,
                        "files": {"task.py": hashlib.sha256(b"print('task')\n").hexdigest()},
                    },
                    "materials": {
                        "source_archive": "task_source_archive",
                        "script": "script",
                        "requirements_lock": "requirements_lock",
                    },
                }
            )
        material("task_catalog", json.dumps({"contract_version": 1, "tasks": tasks}).encode())
        manifest.update(workload_contract_version=1, run_id="run-1", config_hash="f" * 64)
    (root / "manifest.json").write_text(json.dumps(manifest))
    uv = (
        f"#!{sys.executable}\n"
        + """import json,os,pathlib,sys
install=pathlib.Path(os.environ['UV_PYTHON_INSTALL_DIR']);python=install/'bin/python'
with (install.parent/'uv-calls.jsonl').open('a') as out:
    out.write(json.dumps({'home':os.environ['HOME'],'install':str(install),'args':sys.argv[1:]})+'\\n')
if sys.argv[1:3]==['python','install']:
    python.parent.mkdir(parents=True);python.symlink_to(sys.executable)
elif sys.argv[1:3]==['python','find']: print(python)
elif sys.argv[1]=='sync':
    dest=pathlib.Path.cwd()/'.venv/bin';dest.mkdir(parents=True);(dest/'python').symlink_to(python)
    venv=dest.parent
    (venv/'pyvenv.cfg').write_text('home = '+str(pathlib.Path(sys.base_prefix)/'bin')+'\\ninclude-system-site-packages = false\\n')
    packages=venv/'lib'/('python'+str(sys.version_info.major)+'.'+str(sys.version_info.minor))/'site-packages'
    packages.mkdir(parents=True)
    (packages/'fixture-dependencies.pth').write_text('\\n'.join(DEPENDENCY_SITES)+'\\n')
"""
    ).replace("DEPENDENCY_SITES", repr(site.getsitepackages()))
    uv_archive = archive([("uv-x86_64-unknown-linux-gnu/uv", uv.encode(), 0o755)])
    claude = b"#!/bin/sh\necho '2.1.284'\n"

    def download(url, destination):
        Path(destination).write_bytes(uv_archive if "uv/releases" in url else claude)

    monkeypatch.setattr(urllib.request, "urlretrieve", download)
    monkeypatch.setattr(
        pwd, "getpwnam", lambda name: SimpleNamespace(pw_uid=os.geteuid(), pw_gid=os.getegid())
    )
    # This offline bootstrap emulator cannot create a real alternate account.
    # All chown calls must still stay within the run and avoid following symlinks.
    transfers = []

    def chown(path, uid, gid, *, follow_symlinks):
        transfers.append((Path(path), follow_symlinks))

    monkeypatch.setattr(os, "chown", chown)
    worker_calls = []
    original_check_output = subprocess.check_output

    def check_output(args, **kwargs):
        if "user" in kwargs:
            # The cloud manager is root. This fixture is already non-root and
            # cannot call setgroups; retain and assert the real worker identity
            # while emulating only that root-management transition.
            worker_calls.append((kwargs["user"], kwargs["group"], kwargs["extra_groups"]))
            kwargs = {
                key: value
                for key, value in kwargs.items()
                if key not in {"user", "group", "extra_groups"}
            }
            assert kwargs["env"]["PYTHONPATH"] == str(root / "source/controller/backend")
        return original_check_output(args, **kwargs)

    monkeypatch.setattr(subprocess, "check_output", check_output)
    profile = tmp_path / "task-profile.sh"
    program = (
        BOOTSTRAP_PROGRAM.replace(UV_SHA256, hashlib.sha256(uv_archive).hexdigest())
        .replace(CLAUDE_SHA256, hashlib.sha256(claude).hexdigest())
        .replace("'/etc/profile.d/auto-designer-task.sh'", repr(str(profile)))
    )
    # Test runtimes may differ from the production pinned Python; the fake uv
    # supplies this test interpreter while checking the same installation layout.
    version = sys.version.split()[0]
    program = program.replace("!='Python 3.12.13'", f"!='Python {version}'")
    if os.geteuid() == 0:
        monkeypatch.setattr(pwd, "getpwnam", lambda name: SimpleNamespace(pw_uid=1000, pw_gid=1000))
    monkeypatch.setattr(sys, "argv", ["bootstrap", str(root)])
    exec(compile(program, "bootstrap", "exec"), {"__name__": "__main__"})
    receipt = json.loads((root / "runtime/bootstrap.json").read_text())
    assert receipt["execution_user"] == "user"
    assert receipt["execution_uid"] > 0
    assert receipt["execution_home"] == str(root / "runtime/home")
    python = Path(receipt["python"])
    assert python.is_relative_to(root / "runtime/python")
    assert (root / "source/controller/.venv/bin/python").resolve() == Path(sys.executable).resolve()
    assert (
        subprocess.check_output([str(python), "--version"], text=True).strip().startswith("Python")
    )
    assert (
        subprocess.check_output([root / "runtime/bin/claude", "--version"], text=True).strip()
        == "2.1.284"
    )
    calls = [
        json.loads(line) for line in (root / "runtime/uv-calls.jsonl").read_text().splitlines()
    ]
    assert all(item["home"] == receipt["execution_home"] for item in calls)
    assert all(item["install"] == str(root / "runtime/python") for item in calls)
    assert transfers and all(
        path.is_relative_to(root) and follow is False for path, follow in transfers
    )
    if multitask:
        assert worker_calls == [(os.getuid(), os.getgid(), [])] * 2
        assert list((root / "source/controller/backend/auto_designer").rglob("prebuilt.*.pyc"))
        assert set(receipt["task_workspaces"]) == {"ordinary", "swe"}
        for task_id, record in receipt["task_workspaces"].items():
            baseline = root / "workspace/tasks" / task_id / "source"
            assert (baseline / "task.py").read_text() == "print('task')\n"
            assert not (baseline / ".venv").exists()
            assert record["params"]["source"] == str(baseline)
            assert record["params"]["workload_contract_version"] == 1
            assert record["setup"] == []
        assert not list((root / "workspace/sessions").glob("*/attempt-*"))
        saved = [
            json.loads(p.read_text())
            for p in (root / "runtime/workspace-receipts").glob("*/*.json")
        ]
        assert len(saved) == 2
        assert all(item["descendants_stopped"] and item["setup_completed_at"] for item in saved)
        # Root management never hands shared interpreter/baseline files to the worker.
        assert all(not p.is_relative_to(root / "runtime/python") for p, _ in transfers)
        assert all(not p.is_relative_to(root / "workspace/tasks") for p, _ in transfers)
    else:
        assert "task_workspaces" not in receipt
        assert (root / "workspace/task/.venv/bin/python").is_file()


@pytest.mark.parametrize("uid,gid", [(1000, 1000), (12345, 12346)])
def test_vigil_entrypoint_reexecutes_as_worker_before_openagents(tmp_path, uid, gid):
    # Exercise the actual shell script with harmless command shims. The Docker
    # runtime remains responsible for the real setpriv syscall and mount ownership.
    source = Path(__file__).parents[1] / "deploy/vigil/entrypoint.sh"
    script = tmp_path / "entrypoint.sh"
    config = tmp_path / "config"
    config.mkdir()
    (config / "openagents.yml").write_text("version: 1\n")
    script.write_text(
        source.read_text()
        .replace("/config/openagents.yml", str(config / "openagents.yml"))
        .replace("HOME=/home/vigil", "HOME=" + str(tmp_path / "home"))
        .replace("/work", str(tmp_path / "work"))
    )
    commands = tmp_path / "bin"
    commands.mkdir()
    audit = tmp_path / "audit"
    shims = {
        "id": '#!/bin/sh\necho "${FAKE_UID:-0}"\n',
        "chown": '#!/bin/sh\nprintf "%s\\n" "$*" >> "$AUDIT/chown"\n',
        "setpriv": '#!/bin/sh\nprintf "%s\\n" "$*" > "$AUDIT/setpriv"\nexport FAKE_UID="${1#--reuid=}"\nwhile [ "$1" != bash ]; do shift; done\nexec "$@"\n',
        "git": '#!/bin/sh\nif [ "$1" = clone ]; then mkdir -p "$3"; fi\n',
        "openagents": f"#!{sys.executable}\n"
        + """import json,os,pathlib
out=pathlib.Path(os.environ['AUDIT']);out.mkdir(exist_ok=True)
out.joinpath('worker.json').write_text(json.dumps({'uid':os.environ.get('FAKE_UID'),'home':os.environ['HOME'],'user':os.environ['USER'],'model':os.environ['CLAUDE_CODE_SUBAGENT_MODEL']}))
pathlib.Path(os.environ['ROLE_RUNS_DIR'],'written-by-worker').write_text('ok')
""",
    }
    for name, content in shims.items():
        path = commands / name
        path.write_text(content)
        path.chmod(0o755)
    audit.mkdir()
    roles = tmp_path / "role_runs"
    env = {
        **os.environ,
        "PATH": str(commands) + ":" + os.environ["PATH"],
        "AUDIT": str(audit),
        "ROLE_RUNS_DIR": str(roles),
        "VIGIL_REPO_URL": "http://user:dummy@gitea:3000/user/repo.git",
        "ANTHROPIC_MODEL": "configured-model",
        "VIGIL_EXEC_UID": str(uid),
        "VIGIL_EXEC_GID": str(gid),
    }
    subprocess.run(["bash", str(script)], env=env, check=True, capture_output=True, text=True)
    receipt = json.loads((audit / "worker.json").read_text())
    assert receipt == {
        "uid": str(uid),
        "home": str(tmp_path / "home"),
        "user": "vigil",
        "model": "configured-model",
    }
    assert (roles / "written-by-worker").read_text() == "ok"
    assert f"-R --no-dereference {uid}:{gid}" in (audit / "chown").read_text()
    privilege = (audit / "setpriv").read_text()
    assert f"--reuid={uid} --regid={gid} --clear-groups" in privilege


def test_vigil_entrypoint_refuses_root_worker_before_any_bootstrap(tmp_path):
    source = Path(__file__).parents[1] / "deploy/vigil/entrypoint.sh"
    result = subprocess.run(
        ["bash", str(source)],
        env={**os.environ, "VIGIL_REPO_URL": "dummy", "VIGIL_EXEC_UID": "0"},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "VIGIL_EXEC_UID/GID" in result.stderr
