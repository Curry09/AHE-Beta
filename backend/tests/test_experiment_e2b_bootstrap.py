"""Spec-0072/T3: run-local dependencies and an unprivileged delivery boundary."""

from __future__ import annotations

import hashlib
import io
import json
import os
import pwd
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


def test_bootstrap_installs_run_local_python_and_transfers_only_owned_tree(tmp_path, monkeypatch):
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

    material("controller_source_archive", archive([("README", b"controller", 0o644)]))
    material("openagents_source_archive", archive([("README", b"openagents", 0o644)]))
    material("task_source_archive", archive([("task.py", b"print('task')\n", 0o644)]))
    material("requirements_lock", b"# frozen\n")
    material("script", b'mkdir -p .venv/bin\nln -s "$TASK_PYTHON" .venv/bin/python\n')
    manifest = {
        "materials": records,
        "source_snapshot": {"files": {}},
        "task_package": {"source": {"kind": "local"}},
    }
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
"""
    )
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
