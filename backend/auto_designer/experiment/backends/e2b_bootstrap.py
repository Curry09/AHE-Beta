"""Spec-0069/T4: portable frozen-input bootstrap, without developer home files."""

from __future__ import annotations

import shlex
from pathlib import Path
from typing import Any

UV_VERSION = "0.11.28"
PYTHON_VERSION = "3.12.13"
UV_SHA256 = "e490a6464492183c5d4534a5527fb4440f7f2bb2f228162ad7e4afe076dc0224"
CLAUDE_VERSION = "2.1.284"
CLAUDE_SHA256 = "5cd90aabd83f8a15136c35aa37bb1d92b348993573316643dc3fe4e04afbf88f"
EXECUTION_USER = "user"


def task_workspace_record(task: dict, manifest: dict, root: str, tools: dict) -> dict:
    """Spec-0073/T3: provider coordinates do not enter the task's logical digest."""
    from auto_designer.experiment.config import config_hash

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


_MULTITASK_BOOTSTRAP = r"""
tools={'python':python,'uv':str(uv),'controller_python':str(controller/'.venv/bin/python'),'execution_uid':account.pw_uid,'execution_gid':account.pw_gid}
catalog=json.loads((root/manifest['materials']['task_catalog']['path']).read_text())
if catalog.get('contract_version')!=1: raise RuntimeError('Unknown task catalog contract')
task_workspaces={}
for task_record in catalog['tasks']:
    task_id=task_record['id'];package=task_record['package'];source=package['source']
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
program='import json,sys;from auto_designer.experiment.backends.e2b_bootstrap import task_workspace_record;from auto_designer.user.sim.sources.prebuilt import validate_task_baseline;task,manifest,root,tools=json.loads(sys.argv[1]);record=task_workspace_record(task,manifest,root,tools);validate_task_baseline(record["params"]);print(json.dumps(record))'
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
env.update(TASK_ROOT=str(task),TASK_PYTHON=python,REQUIREMENTS_LOCK=lock,AUTO_DESIGNER_TASK_REQUIREMENTS=lock,VIRTUAL_ENV=str(task/'.venv'),UV_BIN=str(uv))
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
claude=binroot/'claude';download('https://downloads.claude.ai/claude-code-releases/2.1.284/linux-x64/claude','CLAUDE_SHA',claude);claude.chmod(0o755)
TASK_SETUP
# Keep task venv selection across explicit bash login shells without activating it for controller/vigil.
pathlib.Path('/etc/profile.d/auto-designer-task.sh').write_text('if [ -n "${VIRTUAL_ENV:-}" ] && [ -x "$VIRTUAL_ENV/bin/python" ]; then export PATH="$VIRTUAL_ENV/bin:$PATH"; fi\n')
receipt={'python':python,'uv':str(uv),'controller_python':str(controller/'.venv/bin/python'),'openagents_bin':str(oa/'.venv/bin'),'bin':str(binroot),'task_root':str(task),'python_version':'3.12.13','uv_version':'0.11.28','claude_version':'2.1.284','execution_user':'user','execution_uid':account.pw_uid,'execution_gid':account.pw_gid,'execution_home':str(home)}
if manifest.get('workload_contract_version')==1: receipt['task_workspaces']=task_workspaces
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


def upload_frozen_inputs(sandbox: Any, *, run_dir: Path, manifest: dict, root: str) -> None:
    """Upload immutable manifest bytes and only checksum-verified frozen materials."""
    from auto_designer.experiment.materials import verify_materials

    verify_materials(manifest)
    paths = ["manifest.json", *(entry["path"] for entry in manifest["materials"].values())]
    for relative in paths:
        sandbox.files.write(root + "/" + relative, (run_dir / relative).read_bytes(), user="root")
    sandbox.files.write(root + "/runtime/bootstrap.py", BOOTSTRAP_PROGRAM, user="root")


def json_command(program: str, *args: str) -> str:
    return "python3 -c " + shlex.quote(program) + " " + " ".join(map(shlex.quote, args))
