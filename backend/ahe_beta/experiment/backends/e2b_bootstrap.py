"""Spec-0069/T4: portable frozen-input bootstrap, without developer home files."""

from __future__ import annotations

import logging
import shlex
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

UV_VERSION = "0.11.28"
PYTHON_VERSION = "3.12.13"
UV_SHA256 = "e490a6464492183c5d4534a5527fb4440f7f2bb2f228162ad7e4afe076dc0224"
CLAUDE_VERSION = "2.1.284"
CLAUDE_SHA256 = "5cd90aabd83f8a15136c35aa37bb1d92b348993573316643dc3fe4e04afbf88f"
EXECUTION_USER = "user"


def task_workspace_record(
    task: dict, manifest: dict, root: str, tools: dict, *, material_root: Path | None = None
) -> dict:
    """Spec-0073/T3: provider coordinates do not enter the task's logical digest."""
    from ahe_beta.experiment.config import config_hash
    from ahe_beta.experiment.task_environments.contract import (
        environment_identity,
        is_container_task,
    )

    if is_container_task(task["package"]):
        # Spec-0081/T4: verify local immutable bytes, then map their execution coordinates.
        from ahe_beta.experiment.task_environments.materials import execution_environment

        environment = execution_environment(
            package=task["package"],
            run_root=material_root or Path(root),
            destination_root=Path(root),
        )
        recipe = environment_identity(task["package"])
        controller_venv = str(Path(tools["controller_python"]).parent.parent)
        python_root = tools["python_root"]
        params = {
            "workload_contract_version": 1,
            "run_root": root,
            "run_id": manifest["run_id"],
            "config_hash": manifest["config_hash"],
            "task_id": task["id"],
            "task_digest": task["digest"],
            "recipe_hash": recipe,
            "environment": environment,
            "registry_root": root + "/runtime/task-environments",
            "harness_python": tools["controller_python"],
            "harness_mounts": [
                {"source": path, "target": path}
                for path in dict.fromkeys(
                    (controller_venv, python_root, tools.get("python_alias_root", python_root))
                )
            ],
        }
        source = task["package"].get("source")
        if source:
            params.update(source=source, expected_git_revision=source["revision"])
        return {
            "kind": "container",
            "params": params,
            "setup": [],
            "task_digest": task["digest"],
            "recipe_hash": recipe,
            "status": "prepared",
            "source_revision": source["revision"] if source else None,
            "source_hash": None,
        }

    recipe = config_hash(
        data={
            "version": 1,
            "task_digest": task["digest"],
            "python": PYTHON_VERSION,
            "uv": UV_VERSION,
            "platform": "linux-x86_64",
            "link_mode": "copy",
        }
    )
    params = {
        "workload_contract_version": 1,
        "run_root": root,
        "run_id": manifest["run_id"],
        "config_hash": manifest["config_hash"],
        "task_id": task["id"],
        "task_digest": task["digest"],
        "recipe_hash": recipe,
        "source": root + "/workspace/tasks/" + task["id"] + "/source",
        "source_files": task["source_snapshot"]["files"],
        "session_root": root + "/workspace/sessions",
        "cache_root": root + "/runtime/task-cache",
        "managed_python": tools["python"],
        "uv": tools["uv"],
        "harness_python": tools["controller_python"],
        "execution_uid": tools["execution_uid"],
        "execution_gid": tools["execution_gid"],
    }
    for name, material in (("setup_script", "script"), ("requirements_lock", "requirements_lock")):
        entry = manifest["materials"][task["materials"][material]]
        params[name] = root + "/" + entry["path"]
        params[name + "_sha256"] = entry["sha256"]
    return {
        "kind": "prebuilt",
        "params": params,
        "setup": [],
        "task_digest": task["digest"],
        "recipe_hash": recipe,
        "status": "prepared",
        "source_revision": task["source_snapshot"]["revision"],
        "source_hash": config_hash(data=task["source_snapshot"]["files"]),
    }


def cleanup_container_probes(
    *, registry_root: Path, run_id: str, config_hash: str, nonce: str | None = None
) -> list[str]:
    """Spec-0081/T4: recover only persisted, label-verified technical probe intents."""
    import json
    import subprocess

    root = registry_root / "probes"
    if not root.exists():
        return []
    if registry_root.is_symlink() or root.is_symlink():
        raise RuntimeError("Linked task probe registry")
    removed = []
    for path in sorted(root.glob("*.json")):
        if path.is_symlink():
            raise RuntimeError("Linked task probe intent")
        value = json.loads(path.read_text())
        if nonce is not None and value.get("nonce") != nonce:
            continue
        if value.get("run_id") != run_id or value.get("config_hash") != config_hash:
            continue
        if value.get("phase") == "removed":
            continue
        labels = value["labels"]
        if labels != {
            "io.ahe-beta.preflight.run_id": run_id,
            "io.ahe-beta.preflight.config_hash": config_hash,
            "io.ahe-beta.preflight.nonce": value["nonce"],
        }:
            raise RuntimeError("Task probe intent labels differ")
        result = subprocess.run(
            ["docker", "container", "inspect", value["name"]],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if not result.returncode:
            info = json.loads(result.stdout)[0]
            actual = info.get("Config", {}).get("Labels", {})
            if any(actual.get(key) != expected for key, expected in labels.items()):
                raise RuntimeError("Refusing a task probe with different ownership")
            subprocess.run(
                ["docker", "rm", "-f", info["Id"]],
                capture_output=True,
                text=True,
                check=True,
                timeout=30,
            )
            removed.append(info["Id"])
        elif "No such" not in result.stderr:
            raise RuntimeError("Task probe ownership could not be inspected")
        value["phase"] = "removed"
        path.write_text(json.dumps(value, indent=2) + "\n")
    return removed


def probe_container_workspace(record: dict) -> dict:
    """Spec-0081/T4: prove actual image and mounted toolchain without starting task Actors.

    Initializers, services and task readiness run once per fresh bound attempt,
    before its first model call. This probe does not warm or reuse task state.
    """
    import json
    import os
    import subprocess
    import uuid

    from ahe_beta.experiment.task_environments.docker import probe_docker

    params = record["params"]
    environment = params["environment"]
    daemon = probe_docker()
    images = [(environment["image"], environment)]
    images.extend(
        (service["image"], service)
        for service in environment["services"]
        if service["placement"] == "companion"
    )
    observed = {}
    probed = set()
    for image, settings in images:
        resources = settings.get("resources", {})
        if (
            resources.get("cpus", 0) > daemon["cpus"]
            or resources.get("memory_mb", 0) * 1024**2 > daemon["memory_bytes"]
        ):
            raise RuntimeError("Declared task resources exceed the actual Docker daemon")
        result = subprocess.run(
            ["docker", "image", "inspect", image], capture_output=True, text=True, timeout=30
        )
        if result.returncode:
            subprocess.run(
                ["docker", "pull", image], capture_output=True, text=True, check=True, timeout=1800
            )
            result = subprocess.run(
                ["docker", "image", "inspect", image],
                capture_output=True,
                text=True,
                check=True,
                timeout=30,
            )
        info = json.loads(result.stdout)[0]
        digest = image.rsplit("@", 1)[1]
        if not any(ref.endswith("@" + digest) for ref in info.get("RepoDigests", [])):
            raise RuntimeError("Task image digest differs from its frozen recipe")
        actor = settings is environment
        ptrace = actor and "ptrace" in environment["capabilities"]
        probe_key = (image, settings.get("user"), ptrace, actor)
        if probe_key in probed:
            continue
        nonce = uuid.uuid4().hex
        name = "adx-preflight-" + nonce
        labels = {
            "io.ahe-beta.preflight.run_id": params["run_id"],
            "io.ahe-beta.preflight.config_hash": params["config_hash"],
            "io.ahe-beta.preflight.nonce": nonce,
        }
        registry = Path(params["registry_root"])
        probes = registry / "probes"
        if registry.is_symlink() or probes.is_symlink():
            raise RuntimeError("Linked task probe registry")
        probes.mkdir(mode=0o700, parents=True, exist_ok=True)
        intent = {
            "version": 1,
            "run_id": params["run_id"],
            "config_hash": params["config_hash"],
            "nonce": nonce,
            "name": name,
            "labels": labels,
            "phase": "launching",
        }
        descriptor = os.open(
            probes / (nonce + ".json"), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600
        )
        with os.fdopen(descriptor, "w") as stream:
            stream.write(json.dumps(intent, indent=2) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        argv = ["docker", "run", "--rm", "--name", name, "--network", "none"]
        for key, value in labels.items():
            argv.extend(["--label", key + "=" + value])
        # Companion services keep their native runtime; only the Actor needs NexAU.
        for mount in params["harness_mounts"] if actor else []:
            argv.extend(
                [
                    "--mount",
                    "type=bind,source="
                    + mount["source"]
                    + ",target="
                    + mount["target"]
                    + ",readonly",
                ]
            )
        if settings.get("user"):
            argv.extend(["--user", settings["user"]])
        if ptrace:
            argv.extend(["--cap-add", "SYS_PTRACE", "--security-opt", "seccomp=unconfined"])
        argv.extend(
            [
                "--entrypoint",
                params["harness_python"] if actor else "/bin/sh",
                image,
                "-c",
                "import json,nexau;print(json.dumps({'ready':True}))"
                if actor
                else "command -v cat >/dev/null && command -v mkdir >/dev/null && "
                "sleep 0 && printf '%s\\n' '{\"ready\":true}'",
            ]
        )
        try:
            execution = subprocess.run(argv, capture_output=True, text=True, check=True, timeout=60)
            if json.loads(execution.stdout).get("ready") is not True:
                raise RuntimeError("Mounted task Harness toolchain did not pass its import probe")
        finally:
            cleanup_container_probes(
                registry_root=registry,
                run_id=params["run_id"],
                config_hash=params["config_hash"],
                nonce=nonce,
            )
        probed.add(probe_key)
        observed.setdefault(image, {"image_id": info["Id"]})[
            "harness_ready" if actor else "native_service_ready"
        ] = True
    return {"daemon": daemon, "images": observed, "readiness": "before-each-actor"}


_MULTITASK_BOOTSTRAP = r"""
tools={'python':python,'uv':str(uv),'controller_python':str(controller/'.venv/bin/python'),'execution_uid':account.pw_uid,'execution_gid':account.pw_gid}
if container_tasks:
    tools.update(python_root=str(pathlib.Path(python).resolve().parent.parent),python_alias_root=str(pathlib.Path(os.path.abspath(os.path.join(str(controller/'.venv/bin'),os.readlink(controller/'.venv/bin/python')))).parent.parent))
catalog=json.loads((root/manifest['materials']['task_catalog']['path']).read_text())
if catalog.get('contract_version')!=1: raise RuntimeError('Unknown task catalog contract')
task_workspaces={}
for task_record in catalog['tasks']:
    task_id=task_record['id'];package=task_record['package']
    if package.get('schema_version')==3: continue
    source=package['source']
    task=root/'workspace/tasks'/task_id/'source'
    if task.is_symlink(): raise RuntimeError('Linked task baseline destination')
    shutil.rmtree(task,ignore_errors=True);task.mkdir(parents=True)
    if source['kind']=='git':
        run(['git','init',str(task)]);run(['git','-C',str(task),'remote','add','origin',source['url']])
        run(['git','-C',str(task),'fetch','--depth','1','origin',source['revision']])
        run(['git','-C',str(task),'checkout','--detach',source['revision']])
    extract(root/manifest['materials'][task_record['materials']['source_archive']]['path'],task)
    for name,digest in task_record['source_snapshot']['files'].items():
        if hashlib.sha256((task/name).read_bytes()).hexdigest()!=digest: raise RuntimeError('Task baseline snapshot mismatch')
    if source['kind']=='git':
        if subprocess.check_output(['git','-C',str(task),'rev-parse','HEAD'],text=True).strip()!=source['revision']: raise RuntimeError('Task revision differs')
        if subprocess.check_output(['git','-C',str(task),'status','--porcelain'],text=True).strip(): raise RuntimeError('Task archive differs from fixed Git revision')
    else:
        run(['git','init',str(task)]);run(['git','-C',str(task),'add','.'])
        run(['git','-C',str(task),'-c','user.name=Experiment','-c','user.email=experiment@localhost','commit','-m','Frozen task source'])
# Hand writable run directories to the worker before executing its frozen setup.
# Baselines and shared interpreters remain management-owned, readable but not writable.
protected=(root/'runtime/python',root/'workspace/tasks')
for directory,dirs,files in os.walk(root,followlinks=False):
    here=pathlib.Path(directory)
    dirs[:]=[name for name in dirs if not any((here/name)==p for p in protected)]
    for item in [here,*(here/name for name in dirs+files)]: os.chown(item,account.pw_uid,account.pw_gid,follow_symlinks=False)
program='import json,sys;from ahe_beta.experiment.backends.e2b_bootstrap import task_workspace_record;from ahe_beta.user.sim.sources.prebuilt import validate_task_baseline;task,manifest,root,tools=json.loads(sys.argv[1]);record=task_workspace_record(task,manifest,root,tools);validate_task_baseline(record["params"]) if record["kind"]=="prebuilt" else None;print(json.dumps(record))'
worker_env={**install_env,'PYTHONPATH':str(controller/'backend')}
for task_record in catalog['tasks']:
    output=subprocess.check_output([str(controller/'.venv/bin/python'),'-c',program,json.dumps([task_record,manifest,str(root),tools])],cwd=controller,env=worker_env,text=True,user=account.pw_uid,group=account.pw_gid,extra_groups=[],timeout=660)
    task_workspaces[task_record['id']]=json.loads(output.strip().splitlines()[-1])
"""

_SINGLE_TASK_BOOTSTRAP = r"""
package=manifest['task_package']; source=package['source'];task.mkdir(parents=True,exist_ok=True)
if source['kind']=='git':
    run(['git','init',str(task)])
    run(['git','-C',str(task),'remote','add','origin',source['url']])
    run(['git','-C',str(task),'fetch','--depth','1','origin',source['revision']])
    run(['git','-C',str(task),'checkout','--detach',source['revision']])
extract(root/manifest['materials']['task_source_archive']['path'],task)
if source['kind']=='git':
    if subprocess.check_output(['git','-C',str(task),'rev-parse','HEAD'],text=True).strip()!=source['revision']: raise RuntimeError('Task revision differs')
    if subprocess.check_output(['git','-C',str(task),'status','--porcelain'],text=True).strip(): raise RuntimeError('Task archive differs from fixed Git revision')
else:
    run(['git','init',str(task)]);run(['git','-C',str(task),'add','.']);run(['git','-C',str(task),'-c','user.name=Experiment','-c','user.email=experiment@localhost','commit','-m','Frozen task source'])
lock=str(root/manifest['materials']['requirements_lock']['path'])
env.update(TASK_ROOT=str(task),TASK_PYTHON=python,REQUIREMENTS_LOCK=lock,AHE_BETA_TASK_REQUIREMENTS=lock,VIRTUAL_ENV=str(task/'.venv'),UV_BIN=str(uv))
run(['bash',str(root/manifest['materials']['script']['path'])],cwd=task,env=env)
if not(task/'.venv/bin/python').is_file(): raise RuntimeError('Task setup did not produce its isolated Python environment')
"""

# This program runs with the template's system Python before any project imports.
BOOTSTRAP_PROGRAM = r"""
import hashlib,json,os,pathlib,pwd,shutil,subprocess,sys,tarfile,urllib.request
root=pathlib.Path(sys.argv[1]); manifest=json.loads((root/'manifest.json').read_text())
def run(args,**kw): subprocess.run(args,check=True,**kw)
# Spec-0072/T3: management remains root; only this run is handed to the worker.
try: account=pwd.getpwnam('user')
except KeyError:
    run(['useradd','--create-home','--shell','/bin/bash','user']);account=pwd.getpwnam('user')
if account.pw_uid==0 or account.pw_gid==0: raise RuntimeError('Execution account must be non-root')
home=root/'runtime/home';home.mkdir(parents=True,exist_ok=True,mode=0o700)
install_env=dict(os.environ);install_env.pop('VIRTUAL_ENV',None)
install_env.update(HOME=str(home),USER='user',LOGNAME='user',UV_PYTHON_INSTALL_DIR=str(root/'runtime/python'),UV_CACHE_DIR=str(root/'runtime/uv-cache'))
def download(url,digest,dest):
    urllib.request.urlretrieve(url,dest)
    if hashlib.sha256(dest.read_bytes()).hexdigest()!=digest: raise RuntimeError('Runtime download checksum mismatch')
def extract(archive,dest):
    dest.mkdir(parents=True,exist_ok=True)
    with tarfile.open(archive) as tar:
        for member in tar.getmembers():
            p=pathlib.PurePosixPath(member.name)
            if p.is_absolute() or '..' in p.parts or member.issym() or member.islnk() or not(member.isfile() or member.isdir()):
                raise RuntimeError('Unsafe frozen source archive')
        tar.extractall(dest,filter='data')
for key,record in manifest['materials'].items():
    p=root/record['path']
    if not p.resolve().is_relative_to(root.resolve()) or p.is_symlink() or hashlib.sha256(p.read_bytes()).hexdigest()!=record['sha256']:
        raise RuntimeError('Frozen material mismatch: '+key)
cache=root/'runtime/downloads'; cache.mkdir(parents=True,exist_ok=True)
binroot=root/'runtime/bin';binroot.mkdir(parents=True,exist_ok=True)
uvtar=cache/'uv.tar.gz';download('https://github.com/astral-sh/uv/releases/download/0.11.28/uv-x86_64-unknown-linux-gnu.tar.gz','UV_SHA',uvtar)
extract(uvtar,cache/'uv');uv=cache/'uv/uv-x86_64-unknown-linux-gnu/uv'
run([str(uv),'python','install','3.12.13'],env=install_env)
python=subprocess.check_output([str(uv),'python','find','3.12.13'],text=True,env=install_env).strip()
if subprocess.check_output([python,'--version'],text=True).strip()!='Python 3.12.13': raise RuntimeError('Python runtime mismatch')
controller=root/'source/controller';oa=root/'source/openagents'; task=root/'workspace/task'
container_tasks=manifest.get('workload_contract_version')==1 and any(t['package'].get('schema_version')==3 for t in json.loads((root/manifest['materials']['task_catalog']['path']).read_text())['tasks'])
if container_tasks:
    install_env['UV_LINK_MODE']='copy'
    run(['usermod','-aG','docker','user'])
    run(['docker','info'])
for path in (controller,oa,task):
    if path.is_symlink(): raise RuntimeError('Linked bootstrap destination')
    shutil.rmtree(path,ignore_errors=True)
extract(root/manifest['materials']['controller_source_archive']['path'],controller)
extract(root/manifest['materials']['openagents_source_archive']['path'],oa)
for name,digest in manifest['source_snapshot']['files'].items():
    if hashlib.sha256((controller/name).read_bytes()).hexdigest()!=digest: raise RuntimeError('Controller snapshot mismatch')
run(['git','init','-b','main',str(controller)])
run(['git','-C',str(controller),'add','.'])
run(['git','-C',str(controller),'-c','user.name=Experiment','-c','user.email=experiment@localhost','-c','commit.gpgsign=false','-c','core.hooksPath=/dev/null','commit','-m','Frozen controller snapshot'])
env=dict(install_env);env['UV_PYTHON']=python
run([str(uv),'sync','--locked','--extra','experiments','--extra','dev','--python',python],cwd=controller,env=env)
run([str(uv),'sync','--locked','--extra','nexau','--extra','dev','--python',python],cwd=oa,env=env)
sdk_probe="import importlib.metadata,json,sys;source=json.loads(importlib.metadata.distribution('nexau').read_text('direct_url.json'));pin=source.get('vcs_info',{}).get('commit_id');assert pin==sys.argv[1], 'NexAU installed Git commit differs';print(pin)"
for project in (controller,oa):
    run([str(project/'.venv/bin/python'),'-c',sdk_probe,manifest['source_pins']['nexau']['revision']],env=env)
claude=binroot/'claude';download('https://downloads.claude.ai/claude-code-releases/2.1.284/linux-x64/claude','CLAUDE_SHA',claude);claude.chmod(0o755)
TASK_SETUP
# Keep task venv selection across explicit bash login shells without activating it for controller/vigil.
pathlib.Path('/etc/profile.d/ahe-beta-task.sh').write_text('if [ -n "${VIRTUAL_ENV:-}" ] && [ -x "$VIRTUAL_ENV/bin/python" ]; then export PATH="$VIRTUAL_ENV/bin:$PATH"; fi\n')
receipt={'python':python,'uv':str(uv),'controller_python':str(controller/'.venv/bin/python'),'openagents_bin':str(oa/'.venv/bin'),'bin':str(binroot),'task_root':str(task),'python_version':'3.12.13','uv_version':'0.11.28','claude_version':'2.1.284','execution_user':'user','execution_uid':account.pw_uid,'execution_gid':account.pw_gid,'execution_home':str(home)}
if manifest.get('workload_contract_version')==1: receipt['task_workspaces']=task_workspaces
if container_tasks:
    receipt['python_root']=tools['python_root'];receipt['python_alias_root']=tools['python_alias_root']
    docker_probe='import json;from ahe_beta.experiment.task_environments.docker import probe_docker;print(json.dumps(probe_docker()))'
    receipt['docker']=json.loads(subprocess.check_output([str(controller/'.venv/bin/python'),'-c',docker_probe],cwd=controller,env={**install_env,'PYTHONPATH':str(controller/'backend')},text=True,user=account.pw_uid,group=account.pw_gid,extra_groups=os.getgrouplist('user',account.pw_gid),timeout=35))
(root/'runtime/bootstrap.json').write_text(json.dumps(receipt,indent=2)+'\n')
# Do not open /root or chown outside the owned run (including symlink targets).
for directory,dirs,files in os.walk(root,followlinks=False):
    if manifest.get('workload_contract_version')==1:
        dirs[:]=[name for name in dirs if pathlib.Path(directory)/name not in protected]
    for item in [pathlib.Path(directory),*(pathlib.Path(directory)/name for name in dirs+files)]:
        os.chown(item,account.pw_uid,account.pw_gid,follow_symlinks=False)
root.chmod(0o700);home.chmod(0o700)
""".replace("UV_SHA", UV_SHA256).replace("CLAUDE_SHA", CLAUDE_SHA256)

# Old frozen single-task resources retain their original preparation protocol.
BOOTSTRAP_PROGRAM = BOOTSTRAP_PROGRAM.replace(
    "TASK_SETUP",
    "if manifest.get('workload_contract_version') is not None:\n"
    "    if type(manifest['workload_contract_version']) is not int or manifest['workload_contract_version']!=1: raise RuntimeError('Unknown workload contract')\n"
    + "\n".join("    " + line for line in _MULTITASK_BOOTSTRAP.strip().splitlines())
    + "\nelse:\n"
    + "\n".join("    " + line for line in _SINGLE_TASK_BOOTSTRAP.strip().splitlines()),
)


def bootstrap_command(root: str) -> str:
    return f"python3 {shlex.quote(root + '/runtime/bootstrap.py')} {shlex.quote(root)}"


def _upload_timeout_seconds(*, size_bytes: int) -> int:
    # Finite I/O waits for preparation, separate from Actor budgets or a wall deadline.
    return 60 + (size_bytes + 65535) // 65536


@contextmanager
def _private_upload_logs():
    # upload_url is an official API, but its query contains a file-scoped signature.
    # Suppress only these transport loggers while that URL is in use, then restore them.
    roots = ("httpx", "httpcore")
    for name in roots:
        logging.getLogger(name)
    loggers = [
        logger
        for name, logger in list(logging.Logger.manager.loggerDict.items())
        if isinstance(logger, logging.Logger)
        and any(name == root or name.startswith(root + ".") for root in roots)
    ]
    states = [(logger, logger.level, logger.disabled) for logger in loggers]
    try:
        for logger in loggers:
            logger.setLevel(logging.CRITICAL + 1)
            logger.disabled = True
        yield
    finally:
        for logger, level, disabled in states:
            logger.setLevel(level)
            logger.disabled = disabled


def _upload_file(sandbox: Any, *, path: Path, remote: str, timeout_seconds: int) -> None:
    import httpx

    from ahe_beta.experiment.backends.base import BackendError

    # e2b 2.55 ignores request_timeout for files.write(binary IO), in both its
    # octet-stream and multipart branches. The public upload URL lets HTTPX stream
    # the binary file with finite connect/read/write waits, without private SDK hooks.
    for attempt in range(1, 4):
        try:
            with (
                _private_upload_logs(),
                path.open("rb") as stream,
                httpx.Client(
                    http2=False,
                    trust_env=False,
                    proxy=sandbox.connection_config.proxy,
                    timeout=timeout_seconds,
                    follow_redirects=False,
                ) as client,
            ):
                url = sandbox.upload_url(remote, user="root")
                response = client.post(
                    url,
                    files={"file": (path.name, stream, "application/octet-stream")},
                    timeout=timeout_seconds,
                )
                response.raise_for_status()
                try:
                    result = response.json()
                except ValueError:
                    raise BackendError("E2B input upload returned an invalid receipt") from None
                if not isinstance(result, list) or not result:
                    raise BackendError("E2B input upload returned an invalid receipt")
            return
        except httpx.RemoteProtocolError:
            if attempt == 3:
                raise BackendError("E2B input upload failed (RemoteProtocolError)") from None
            print(
                f"[setup] upload connection interrupted; retrying file ({attempt + 1}/3)",
                file=sys.stderr,
                flush=True,
            )
            time.sleep(attempt)
        except httpx.HTTPError as error:
            status = (
                f", HTTP {error.response.status_code}"
                if isinstance(error, httpx.HTTPStatusError)
                else ""
            )
            raise BackendError(
                f"E2B input upload failed ({type(error).__name__}{status})"
            ) from None


def upload_frozen_inputs(sandbox: Any, *, run_dir: Path, manifest: dict, root: str) -> None:
    """Upload immutable manifest bytes and only checksum-verified frozen materials."""
    from ahe_beta.experiment.materials import verify_materials

    verify_materials(manifest)
    paths = ["manifest.json", *(entry["path"] for entry in manifest["materials"].values())]
    total = len(paths) + 1
    for index, relative in enumerate(paths, start=1):
        path = run_dir / relative
        size = path.stat().st_size
        timeout = _upload_timeout_seconds(size_bytes=size)
        print(
            f"[setup] uploading {index}/{total}: {relative} ({size} bytes, I/O timeout {timeout}s)",
            file=sys.stderr,
            flush=True,
        )
        _upload_file(sandbox, path=path, remote=root + "/" + relative, timeout_seconds=timeout)
        print(f"[setup] uploaded {index}/{total}: {relative}", file=sys.stderr, flush=True)
    print(f"[setup] uploading {total}/{total}: runtime/bootstrap.py", file=sys.stderr, flush=True)
    sandbox.files.write(
        root + "/runtime/bootstrap.py",
        BOOTSTRAP_PROGRAM,
        user="root",
        request_timeout=_upload_timeout_seconds(size_bytes=len(BOOTSTRAP_PROGRAM.encode())),
    )
    print(f"[setup] uploaded {total}/{total}: runtime/bootstrap.py", file=sys.stderr, flush=True)


def json_command(program: str, *args: str) -> str:
    return "python3 -c " + shlex.quote(program) + " " + " ".join(map(shlex.quote, args))
