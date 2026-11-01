"""Spec-0069/T4: identity-owned E2B execution and user-owned Gitea.com evidence."""

from __future__ import annotations

import hashlib
import io
import json
import shlex
import tarfile
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import requests

from auto_designer.experiment.backends.base import BackendError, require_execution_reader
from auto_designer.experiment.backends.e2b_bootstrap import (
    EXECUTION_USER,
    bootstrap_command,
    json_command,
    task_workspace_record,
    upload_frozen_inputs,
)
from auto_designer.experiment.backends.e2b_template import resolve_template, sandbox_facts


def timestamp() -> str:
    return datetime.now(UTC).isoformat()


def _write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.replace(path)


def _read(path: Path) -> dict:
    return json.loads(path.read_text()) if path.is_file() else {}


class E2BBackend:
    def __init__(self, run_dir: Path, manifest: dict[str, Any], credentials: Mapping[str, str]):
        self.run_dir = Path(run_dir)
        self.manifest = manifest
        self.credentials = dict(credentials)
        self.resource_file = self.run_dir / "resources.json"
        self.root = "/opt/auto-designer/runs/" + manifest["run_id"]

    @property
    def metadata(self) -> dict[str, str]:
        return {
            "run_id": self.manifest["run_id"],
            "config_hash": self.manifest["config_hash"],
            "application": "auto-designer",
        }

    def _owned_sandboxes(self) -> list[Any]:
        from e2b import Sandbox, SandboxQuery

        if not self.credentials.get("E2B_API_KEY"):
            raise BackendError("Missing environment variable: E2B_API_KEY")
        pages = Sandbox.list(
            query=SandboxQuery(metadata=self.metadata), api_key=self.credentials["E2B_API_KEY"]
        )
        items = []
        while pages.has_next:
            items.extend(pages.next_items())
        return items

    def _sandbox(self, *, validate_resources: bool = True):
        from e2b import Sandbox

        resource = _read(self.resource_file)
        sid = resource.get("sandbox_id")
        if not sid:
            raise BackendError("No recorded E2B sandbox; provision must establish ownership first")
        found = next((s for s in self._owned_sandboxes() if s.sandbox_id == sid), None)
        if found is None:
            raise BackendError(
                "LOST: recorded E2B sandbox has expired or been destroyed; it cannot be silently replaced"
            )
        if str(found.state).lower().split(".")[-1] != "running":
            raise BackendError("E2B sandbox is paused; explicit provider recovery is required")
        # List first: connect must never implicitly resume an unknown/paused instance.
        sandbox = Sandbox.connect(sid, api_key=self.credentials["E2B_API_KEY"])
        observed = sandbox.get_info()
        if any(dict(observed.metadata or {}).get(k) != v for k, v in self.metadata.items()):
            raise BackendError("Actual sandbox ownership differs")
        if validate_resources:
            self._observed_sandbox = {
                **sandbox_facts(observed, manifest=self.manifest, template=resource["template"]),
                "observed_at": timestamp(),
            }
        return sandbox

    def _command(
        self, sandbox, command: str, *, timeout: int = 120, envs=None, user: str = "root"
    ) -> str:
        result = sandbox.commands.run(command, timeout=timeout, user=user, envs=envs)
        if result.exit_code != 0:
            raise BackendError(
                f"E2B command failed (exit {result.exit_code}); inspect sandbox/bootstrap logs"
            )
        return result.stdout.strip()

    def _api(self, method: str, endpoint: str, **kwargs):
        token = self.credentials.get("GITEA_TOKEN")
        if not token:
            raise BackendError("Missing environment variable: GITEA_TOKEN")
        response = requests.request(
            method,
            "https://gitea.com/api/v1" + endpoint,
            headers={"Authorization": "token " + token},
            timeout=30,
            **kwargs,
        )
        if response.status_code not in {200, 201, 204, 404}:
            raise BackendError(f"Gitea.com returned HTTP {response.status_code} for {endpoint}")
        return response

    def _gitea(self) -> dict:
        identity = self._api("GET", "/user")
        if identity.status_code != 200:
            raise BackendError("Gitea.com token did not resolve a user")
        owner = identity.json()["login"]
        expected = self.credentials.get("GITEA_USER")
        if expected and expected != owner:
            raise BackendError("GITEA_USER differs from authenticated Gitea.com identity")
        recorded = _read(self.resource_file).get("gitea") or {}
        if recorded.get("owner") and recorded["owner"] != owner:
            raise BackendError(
                "Authenticated Gitea identity changed; resume must retain the original repository"
            )
        prefix = self.manifest["config"]["runtime"]["gitea"]["repository_prefix"]
        repo = prefix + "-" + self.manifest["run_id"].lower()
        marker = (
            "auto-designer run "
            + self.manifest["run_id"]
            + " config "
            + self.manifest["config_hash"]
        )
        response = self._api("GET", f"/repos/{owner}/{repo}")
        if response.status_code == 404:
            # Persist the creation intent before request; a lost response is reconciled by GET.
            resources = _read(self.resource_file)
            resources["gitea_creation_intent"] = {
                "owner": owner,
                "repo": repo,
                "description": marker,
            }
            _write(self.resource_file, resources)
            try:
                response = self._api(
                    "POST",
                    "/user/repos",
                    json={"name": repo, "description": marker, "private": True, "auto_init": False},
                )
            except requests.RequestException:
                response = self._api("GET", f"/repos/{owner}/{repo}")
        value = response.json()
        if (
            value.get("description") != marker
            or value.get("owner", {}).get("login") != owner
            or value.get("private") is not True
        ):
            raise BackendError(
                "Existing Gitea repository does not belong to this frozen experiment"
            )
        if recorded.get("repository_id") and value["id"] != recorded["repository_id"]:
            raise BackendError(
                "Original Gitea repository was replaced; resume cannot reset delivery history"
            )
        return {
            "url": "https://gitea.com",
            "internal_url": "https://gitea.com",
            "owner": owner,
            "repo": repo,
            "repository_id": value["id"],
            "description": marker,
        }

    def provision(self) -> dict:
        from e2b import Sandbox

        resources = _read(self.resource_file)
        if resources.get("sandbox_id"):
            sandbox = self._sandbox()
        else:
            template = resources.get("template") or resolve_template(
                run_dir=self.run_dir, manifest=self.manifest, credentials=self.credentials
            )
            resources.update(
                template=template,
                creation_intent={"metadata": self.metadata, "created_at": timestamp()},
                root=self.root,
            )
            _write(self.resource_file, resources)
            found = self._owned_sandboxes()
            if len(found) > 1:
                raise BackendError(
                    "Multiple sandboxes match the creation intent; reconcile provider resources before continuing"
                )
            if found:
                resources["sandbox_id"] = found[0].sandbox_id
                _write(self.resource_file, resources)
                sandbox = self._sandbox()
            else:
                sandbox = Sandbox.create(
                    template["selection"],
                    timeout=self.manifest["config"]["runtime"]["e2b"]["timeout_seconds"],
                    metadata=self.metadata,
                    secure=True,
                    allow_internet_access=True,
                    api_key=self.credentials["E2B_API_KEY"],
                )
                resources["sandbox_id"] = sandbox.sandbox_id
                _write(self.resource_file, resources)
        resources.update(
            sandbox_facts(
                sandbox.get_info(), manifest=self.manifest, template=resources["template"]
            )
        )
        resources["sandbox"] = {
            key: resources[key]
            for key in (
                "sandbox_id",
                "template_id",
                "selected_build_id",
                "cpu_count",
                "memory_mb",
                "allow_internet_access",
                "metadata",
                "started_at",
                "expires_at",
                "state",
            )
        }
        resources["sandbox"]["observed_at"] = timestamp()
        _write(self.resource_file, resources)
        resources["gitea"] = self._gitea()
        resources["source_root"] = self.root + "/source/controller"
        if self.manifest.get("workload_contract_version") is None:
            resources["workspace"] = {
                "kind": "prebuilt",
                "params": {
                    "source": self.root + "/workspace/task",
                    "instance_id": self.manifest["task_package"]["id"],
                    "activate_venv": True,
                    "harness_python": self.root + "/source/controller/.venv/bin/python",
                },
            }
        resources["vigil"] = {"mode": "subprocess"}
        _write(self.resource_file, resources)
        if not resources.get("bootstrap_complete"):
            upload_frozen_inputs(
                sandbox, run_dir=self.run_dir, manifest=self.manifest, root=self.root
            )
            try:
                self._command(
                    sandbox,
                    bootstrap_command(self.root)
                    + " > "
                    + shlex.quote(self.root + "/runtime/bootstrap.log")
                    + " 2>&1",
                    timeout=3600,
                )
            except Exception:
                resources["bootstrap_failed_at"] = timestamp()
                _write(self.resource_file, resources)
                raise
            resources["bootstrap"] = json.loads(
                sandbox.files.read(self.root + "/runtime/bootstrap.json", user="root")
            )
            resources["bootstrap_complete"] = True
            _write(self.resource_file, resources)
        if self.manifest.get("workload_contract_version") is not None:
            resources["task_workspaces"] = self._task_workspaces(resources["bootstrap"])
            resources.pop("workspace", None)
            _write(self.resource_file, resources)
        return resources

    def _task_workspaces(self, bootstrap: dict) -> dict:
        from auto_designer.experiment.workload import (
            catalog_tasks,
            read_task_catalog,
            verify_task_workspaces,
        )

        catalog = read_task_catalog(self.run_dir, self.manifest)
        actual = bootstrap.get("task_workspaces")
        verify_task_workspaces(catalog, actual)
        expected = {
            task["id"]: task_workspace_record(
                task, self.manifest, self.root, bootstrap, material_root=self.run_dir
            )
            for task in catalog_tasks(catalog)
        }
        if actual != expected:
            raise BackendError(
                "E2B task preparation recipe or owned paths differ from frozen inputs"
            )
        return actual

    def _python(self, resources: dict, program: str, *args: str) -> str:
        return (
            shlex.quote(resources["bootstrap"]["controller_python"])
            + " -c "
            + shlex.quote(program)
            + " "
            + " ".join(map(shlex.quote, args))
        )

    def preflight(self) -> dict:
        sandbox = self._sandbox()
        resources = _read(self.resource_file)
        bootstrap = resources["bootstrap"]
        if self.manifest.get("workload_contract_version") is not None:
            prepared = self._task_workspaces(bootstrap)
            if resources.get("task_workspaces") != prepared:
                raise BackendError("E2B task workspace resources differ from bootstrap receipt")
        caps = self._command(
            sandbox,
            shlex.quote(bootstrap["openagents_bin"] + "/openagents")
            + " observation-capabilities --json",
            envs={"OPENAGENTS_NO_SELF_UPDATE": "1", "DISABLE_UPDATES": "1"},
        )
        capability = json.loads(caps)
        if "zip" not in capability.get("encodings", []) or "gitea-com-r2-v1" not in capability.get(
            "download_policies", []
        ):
            raise BackendError("Frozen OpenAgents reader lacks Gitea.com ZIP/redirect support")
        require_execution_reader(capability)
        probe = self._probe(sandbox, resources)
        facts = sandbox_facts(
            sandbox.get_info(), manifest=self.manifest, template=resources["template"]
        )
        receipt = {
            "status": "ready",
            "sandbox": facts,
            "reader_capabilities": capability,
            "evidence_probe": probe,
            "observed_at": timestamp(),
        }
        if self.manifest.get("workload_contract_version") is not None:
            receipt["task_workspaces"] = {
                task_id: {
                    name: record[name]
                    for name in (
                        "task_digest",
                        "recipe_hash",
                        "status",
                        "source_revision",
                        "source_hash",
                    )
                }
                for task_id, record in prepared.items()
            }
        container_records = {
            task_id: record
            for task_id, record in (resources.get("task_workspaces") or {}).items()
            if record["kind"] == "container"
        }
        if container_records:
            program = "import json,sys;sys.path.insert(0,sys.argv[1]+'/source/controller/backend');from auto_designer.experiment.backends.e2b_bootstrap import probe_container_workspace;print(json.dumps({key:probe_container_workspace(value) for key,value in json.loads(sys.argv[2]).items()}))"
            receipt["container_preflight"] = json.loads(
                self._command(
                    sandbox,
                    self._python(resources, program, self.root, json.dumps(container_records)),
                    user=bootstrap["execution_user"],
                    timeout=1800,
                )
            )
        _write(self.run_dir / "runtime/preflight.json", receipt)
        return receipt

    def _probe(self, sandbox, resources: dict) -> dict:
        # Exercise the real installed forge downloader and reader. No user/demand issue is generated.
        g = resources["gitea"]
        endpoint = f"/repos/{g['owner']}/{g['repo']}/issues"
        issue = self._api(
            "POST",
            endpoint,
            json={
                "title": "[preflight] evidence transport probe",
                "body": "Auto-designer technical preflight; excluded from user feedback.",
            },
        )
        number = issue.json()["number"]
        resources["evidence_probe_issue"] = number
        _write(self.resource_file, resources)
        try:
            from auto_designer.demand.delivery_evidence import MARKER, _compress

            data = _compress(
                json.dumps({"format": MARKER, "issue": number, "sessions": []}).encode(), "zip"
            )
            digest = hashlib.sha256(data).hexdigest()
            result = self._api(
                "POST",
                endpoint + f"/{number}/assets",
                files={
                    "attachment": (
                        "observation-evidence-" + digest + ".zip",
                        data,
                        "application/zip",
                    )
                },
            )
            asset = result.json()
            program = """import json,os,sys; from openagents.utils import forge; from openagents.observations.evidence import decode_package
value=json.loads(sys.argv[1]); forge.configure(name='gitea',settings={'base_url':'https://gitea.com','owner':value['owner'],'repo':value['repo']})
data=forge.download_observation_asset(number=value['issue'],asset_id=value['asset'],limit=4000000)
package=decode_package(data=data,digest=value['sha256'],issue=value['issue'],encoding='zip')
print(json.dumps({'sha256':value['sha256'],'issue':package['issue'],'status':'verified'}))"""
            value = {
                "owner": g["owner"],
                "repo": g["repo"],
                "issue": number,
                "asset": asset["id"],
                "sha256": digest,
            }
            command = (
                shlex.quote(resources["bootstrap"]["openagents_bin"] + "/python")
                + " -c "
                + shlex.quote(program)
                + " "
                + shlex.quote(json.dumps(value))
            )
            return json.loads(
                self._command(
                    sandbox,
                    command,
                    envs={
                        "GITEA_TOKEN": self.credentials["GITEA_TOKEN"],
                        "OPENAGENTS_NO_SELF_UPDATE": "1",
                    },
                )
            )
        finally:
            self._api("PATCH", endpoint + f"/{number}", json={"state": "closed"})

    def launch(self, *, mode: str = "fresh") -> dict:
        sandbox = self._sandbox()
        resources = _read(self.resource_file)
        bootstrap = resources["bootstrap"]
        # Spec-0072/T3: preserve genuinely frozen pre-policy runs; never let a new
        # run without a verified worker receipt fall back to privileged delivery.
        legacy = "policies" not in self.manifest["config"] and not bootstrap.get("execution_user")
        if not legacy and (
            bootstrap.get("execution_user") != EXECUTION_USER
            or type(bootstrap.get("execution_uid")) is not int
            or bootstrap["execution_uid"] <= 0
            or type(bootstrap.get("execution_gid")) is not int
            or bootstrap["execution_gid"] <= 0
            or bootstrap.get("execution_home") != self.root + "/runtime/home"
        ):
            raise BackendError(
                "Non-root bootstrap identity is missing or unsafe; prepare a new run"
            )
        # Credentials are sent through the API, never interpolated into shell commands or receipts.
        private = self.root + "/secrets/launch.json"
        sandbox.files.write(
            private,
            json.dumps({"credentials": self.credentials, "resources": resources, "mode": mode}),
            user="root",
        )
        self._command(
            sandbox,
            "chmod 700 "
            + shlex.quote(self.root + "/secrets")
            + " && chmod 600 "
            + shlex.quote(private),
        )
        if not legacy:
            # Root may write fresh private files during resume. Hand only these
            # owned paths to the recorded worker, checking the live Unix account.
            ownership = """import json,os,pathlib,pwd,sys
root=pathlib.Path(sys.argv[1]); expected=json.loads(sys.argv[2]); account=pwd.getpwnam(expected['execution_user'])
if account.pw_uid==0 or account.pw_gid==0 or (account.pw_uid,account.pw_gid)!=(expected['execution_uid'],expected['execution_gid']): raise RuntimeError('Execution account identity changed')
for relative,mode in [('',0o700),('secrets',0o700),('secrets/launch.json',0o600),('runtime/home',0o700)]:
    path=root/relative
    if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()): raise RuntimeError('Unsafe execution path')
    os.chown(path,account.pw_uid,account.pw_gid);path.chmod(mode)
"""
            self._command(sandbox, json_command(ownership, self.root, json.dumps(bootstrap)))
        program = """import json,os,pathlib,sys
root=pathlib.Path(sys.argv[1]);sys.path.insert(0,str(root/'source/controller/backend'))
from auto_designer.experiment.context import build_controller_environment
from auto_designer.experiment.engine import launch_controller,controller_command
manifest=json.loads((root/'manifest.json').read_text()); value=json.loads((root/'secrets/launch.json').read_text());(root/'secrets/launch.json').chmod(0o600)
b=value['resources']['bootstrap']
if b.get('execution_user'):
    if os.geteuid()==0 or os.geteuid()!=b['execution_uid']: raise RuntimeError('Controller must run as the recorded non-root worker')
    os.environ.update(HOME=b['execution_home'],USER=b['execution_user'],LOGNAME=b['execution_user'])
env=build_controller_environment(run_dir=root,manifest=manifest,credentials=value['credentials'],resources=value['resources'],execution_root=root,mode=value['mode']);env['PATH']=b['openagents_bin']+':'+b['bin']+':'+env.get('PATH','/usr/bin:/bin')
if b.get('execution_user'):
    env.update(HOME=b['execution_home'],USER=b['execution_user'],LOGNAME=b['execution_user'],UV_PYTHON_INSTALL_DIR=str(root/'runtime/python'),UV_CACHE_DIR=str(root/'runtime/uv-cache'))
manifest['run_dir']=str(root)
print(json.dumps(launch_controller(run_dir=root,command=controller_command(manifest,root/'source/controller',b['controller_python']),env=env)))
"""
        command = self._python(resources, program, self.root)
        receipt = json.loads(
            self._command(sandbox, command)
            if legacy
            else self._command(
                sandbox,
                command,
                user=EXECUTION_USER,
                envs={
                    "HOME": bootstrap["execution_home"],
                    "USER": EXECUTION_USER,
                    "LOGNAME": EXECUTION_USER,
                },
            )
        )
        if receipt.get("state") != "RUNNING" or not receipt.get("runner_pid"):
            raise BackendError("E2B controller failed to acknowledge a live owned runner")
        return receipt

    def _engine(self, action: str, *, grace_seconds: float = 30) -> dict:
        sandbox = self._sandbox()
        resources = _read(self.resource_file)
        call = (
            action
            + "(root"
            + (",grace_seconds=" + str(float(grace_seconds)) if action == "stop_controller" else "")
            + ")"
        )
        program = (
            "import json,pathlib,sys;sys.path.insert(0,sys.argv[1]+'/source/controller/backend');"
            "from auto_designer.experiment.engine import inspect_controller,stop_controller;"
            "from auto_designer.experiment.runtime import progress_v2;"
            "root=pathlib.Path(sys.argv[1]);result="
            + call
            + ";result['progress']=progress_v2(root);"
            + "registry=root/'runtime/task-environments';"
            + "manifest=json.loads((root/'manifest.json').read_text());"
            + "probe_module=__import__('auto_designer.experiment.backends.e2b_bootstrap',fromlist=['']) if registry.exists() and sys.argv[2]=='stop_controller' and not result.get('running') else None;"
            + "probe_module.cleanup_container_probes(registry_root=registry,run_id=manifest['run_id'],config_hash=manifest['config_hash']) if probe_module else None;"
            + "module=__import__('auto_designer.experiment.task_environments.docker',fromlist=['']) if registry.exists() else None;"
            + "operation=getattr(module,'stop_registered' if sys.argv[2]=='stop_controller' and not result.get('running') else 'inspect_registered') if module else None;"
            + "result.update(task_environments=operation(registry_root=registry,run_id=manifest['run_id'],config_hash=manifest['config_hash'])) if operation else None;"
            + "print(json.dumps(result))"
        )
        return json.loads(
            self._command(sandbox, self._python(resources, program, self.root, action))
        )

    def _inspect(self) -> dict:
        resources = _read(self.resource_file)
        if resources.get("resource_state") == "DESTROYED":
            collection = _read(self.run_dir / "runtime/e2b-collection.json")
            controller = collection.get("controller", {}).get(
                "controller", collection.get("controller", {})
            )
            return {
                **controller,
                "state": controller.get("state", "ABSENT"),
                "running": False,
                "controller": controller,
                "resource_state": "DESTROYED",
                "sandbox_id": resources["sandbox_id"],
                "sandbox": collection.get("controller", {}).get(
                    "sandbox", resources.get("sandbox", {})
                ),
                "observed_at": timestamp(),
            }
        if not _read(self.resource_file).get("sandbox_id"):
            return {
                "state": "ABSENT",
                "running": False,
                "resource_state": "ABSENT",
                "observed_at": timestamp(),
            }
        try:
            if not resources.get("bootstrap_complete"):
                sandbox = self._sandbox()
                facts = sandbox_facts(
                    sandbox.get_info(), manifest=self.manifest, template=resources["template"]
                )
                return {
                    "state": "ABSENT",
                    "running": False,
                    "resource_state": "RUNNING",
                    "bootstrap_complete": False,
                    "sandbox": facts,
                    "observed_at": timestamp(),
                }
            receipt = self._engine("inspect_controller")
            return {
                **receipt,
                "controller": receipt,
                "resource_state": "RUNNING",
                "sandbox_id": _read(self.resource_file)["sandbox_id"],
                "sandbox": getattr(self, "_observed_sandbox", resources.get("sandbox", {})),
            }
        except BackendError as exc:
            lost = str(exc).startswith("LOST:")
            return {
                "state": "LOST" if lost else "UNKNOWN",
                "running": False,
                "resource_state": "LOST" if lost else "UNKNOWN",
                "error": str(exc),
                "observed_at": timestamp(),
            }
        except Exception as exc:
            return {
                "state": "UNKNOWN",
                "running": False,
                "resource_state": "UNKNOWN",
                "error": type(exc).__name__,
                "observed_at": timestamp(),
            }

    def inspect(self) -> dict:
        receipt = self._inspect()
        # On an unreachable provider, keep the recorded expiry with its original
        # observation timestamp; an observation failure does not refresh this fact.
        receipt.setdefault("sandbox", _read(self.resource_file).get("sandbox", {}))
        return {**receipt, "controller": receipt.get("controller", dict(receipt))}

    def stop(self, *, grace_seconds: float = 30) -> dict:
        receipt = self._engine("stop_controller", grace_seconds=grace_seconds)
        return {**receipt, "controller": receipt, "resource_state": "RUNNING"}

    def logs(self, *, tail: int = 100, follow: bool = False) -> str:
        if follow:
            raise BackendError("Log following is handled by the unified CLI")
        sandbox = self._sandbox()
        limit = str(max(0, int(tail)))
        controller = shlex.quote(self.root + "/logs/controller.log")
        bootstrap = shlex.quote(self.root + "/runtime/bootstrap.log")
        return self._command(
            sandbox,
            f"if test -f {controller}; then tail -n {limit} {controller}; elif test -f {bootstrap}; then tail -n {limit} {bootstrap}; fi",
        )

    def collect(self) -> dict:
        if _read(self.resource_file).get("resource_state") == "DESTROYED":
            receipt = _read(self.run_dir / "runtime/e2b-collection.json")
            if not receipt:
                raise BackendError("Compute was destroyed before an E2B snapshot was collected")
            snapshot = Path(receipt["snapshot_dir"])
            for relative, digest in receipt["files"].items():
                if hashlib.sha256((snapshot / relative).read_bytes()).hexdigest() != digest:
                    raise BackendError("Preserved E2B snapshot checksum changed")
            return receipt
        sandbox = self._sandbox()
        before = self.inspect()
        program = COLLECTION_PROGRAM
        result = json.loads(self._command(sandbox, json_command(program, self.root)))
        data = sandbox.files.read(
            self.root + "/runtime/collection.tar.gz", format="bytes", user="root"
        )
        if hashlib.sha256(data).hexdigest() != result["archive_sha256"]:
            raise BackendError("E2B collection download checksum differs")
        destination = self.run_dir / "runtime/cloud-snapshot"
        staged = self.run_dir / "runtime" / ("cloud-snapshot-" + uuid.uuid4().hex)
        staged.mkdir(parents=True)
        try:
            with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
                for entry in archive.getmembers():
                    path = Path(entry.name)
                    if (
                        path.is_absolute()
                        or ".." in path.parts
                        or not (entry.isfile() or entry.isdir())
                        or entry.issym()
                        or entry.islnk()
                    ):
                        raise BackendError("Unsafe E2B collection archive")
                archived_files = [entry.name for entry in archive.getmembers() if entry.isfile()]
                if len(set(archived_files)) != len(archived_files) or set(archived_files) != set(
                    result["files"]
                ):
                    raise BackendError("E2B collection inventory differs from the receipt")
                archive.extractall(staged, filter="data")
            for relative, digest in result["files"].items():
                if hashlib.sha256((staged / relative).read_bytes()).hexdigest() != digest:
                    raise BackendError("E2B collected file checksum differs")
            import shutil

            shutil.rmtree(destination, ignore_errors=True)
            staged.rename(destination)
        finally:
            import shutil

            shutil.rmtree(staged, ignore_errors=True)
        after = self.inspect()
        terminal = after["state"] in {"STOPPED", "EXITED"}
        receipt = {
            "snapshot_dir": str(destination),
            "controller": after,
            "consistent": result["consistent"]
            and before.get("nonce") == after.get("nonce")
            and before["state"] == after["state"],
            "terminal": terminal,
            "files": result["files"],
            "collected_at": timestamp(),
        }
        _write(self.run_dir / "runtime/e2b-collection.json", receipt)
        return receipt

    def assessment_exchange(self, action: str, payload: dict) -> dict:
        # Spec-0084/T5: reuse verified sandbox ownership and the frozen controller.
        sandbox = self._sandbox()
        resources = _read(self.resource_file)
        program = "import json,pathlib,sys;sys.path.insert(0,sys.argv[1]+'/source/controller/backend');from auto_designer.loop.round_assessment import exchange;print(json.dumps(exchange(pathlib.Path(sys.argv[1]),sys.argv[2],json.loads(sys.argv[3]))))"
        return json.loads(
            self._command(
                sandbox,
                self._python(resources, program, self.root, action, json.dumps(payload)),
                user=resources["bootstrap"].get("execution_user", "root"),
            )
        )

    def assessment_download(self, request_digest: str) -> bytes:
        from auto_designer.loop.round_assessment import MAX_BUNDLE_BYTES, _digest

        sandbox = self._sandbox()
        resources = _read(self.resource_file)
        program = "import pathlib,sys;sys.path.insert(0,sys.argv[1]+'/source/controller/backend');from auto_designer.loop.round_assessment import bundle_path;print(bundle_path(pathlib.Path(sys.argv[1]),sys.argv[2]).stat().st_size)"
        length = int(
            self._command(
                sandbox, self._python(resources, program, self.root, _digest(request_digest))
            )
        )
        if length > MAX_BUNDLE_BYTES:
            raise BackendError("Assessment bundle too large")
        data = bytes(
            sandbox.files.read(
                self.root + "/assessment/requests/" + request_digest + "/bundle.json",
                format="bytes",
                user="root",
            )
        )
        if len(data) != length:
            raise BackendError("Assessment bundle changed during download")
        return data

    def destroy(self) -> dict:
        resources = _read(self.resource_file)
        if resources.get("resource_state") == "DESTROYED":
            return {
                "resource_state": "DESTROYED",
                "sandbox_id": resources["sandbox_id"],
                "gitea_preserved": True,
                "observed_at": timestamp(),
            }
        if not resources.get("sandbox_id"):
            return {"resource_state": "ABSENT", "observed_at": timestamp()}
        found = next(
            (
                item
                for item in self._owned_sandboxes()
                if item.sandbox_id == resources["sandbox_id"]
            ),
            None,
        )
        if found is not None and str(found.state).lower().split(".")[-1] != "running":
            from e2b import Sandbox

            Sandbox.kill(resources["sandbox_id"], api_key=self.credentials["E2B_API_KEY"])
            resources.update(resource_state="DESTROYED", destroyed_at=timestamp())
            _write(self.resource_file, resources)
            return {
                "resource_state": "DESTROYED",
                "sandbox_id": resources["sandbox_id"],
                "gitea_preserved": True,
                "observed_at": timestamp(),
            }
        try:
            sandbox = self._sandbox(validate_resources=False)
        except BackendError as exc:
            if str(exc).startswith("LOST:"):
                return {"resource_state": "LOST", "observed_at": timestamp()}
            raise
        if resources.get("bootstrap_complete"):
            self.stop()
        if resources.get("bootstrap_complete") and self.inspect().get("running"):
            raise BackendError(
                "Owned controller remains alive; refusing premature compute destruction"
            )
        if any(
            record["kind"] == "container"
            for record in (resources.get("task_workspaces") or {}).values()
        ):
            program = "import json,pathlib,sys;sys.path.insert(0,sys.argv[1]+'/source/controller/backend');from auto_designer.experiment.task_environments.docker import destroy_registered;root=pathlib.Path(sys.argv[1]);manifest=json.loads((root/'manifest.json').read_text());print(json.dumps(destroy_registered(registry_root=root/'runtime/task-environments',run_id=manifest['run_id'],config_hash=manifest['config_hash'])))"
            self._command(sandbox, self._python(resources, program, self.root))
        sandbox.kill()
        resources["destroyed_at"] = timestamp()
        resources["resource_state"] = "DESTROYED"
        _write(self.resource_file, resources)
        return {
            "resource_state": "DESTROYED",
            "sandbox_id": resources["sandbox_id"],
            "gitea_preserved": True,
            "observed_at": timestamp(),
        }


COLLECTION_PROGRAM = r"""
import hashlib,json,os,pathlib,tarfile,sys
root=pathlib.Path(sys.argv[1]); output=root/'runtime/collection.tar.gz'
excluded={'secrets','.venv','.git','.openagents','__pycache__','source','cloud-snapshot','downloads','bin'}
private_runtime={('runtime','home'),('runtime','python'),('runtime','uv-cache'),('runtime','task-cache')}
def paths():
    result=[]
    for area in ['data','logs','checkpoints','telemetry','runtime','assessment']:
        base=root/area
        if not base.is_dir() or base.is_symlink(): continue
        area_paths=[]
        for directory,dirs,files in os.walk(base,topdown=True,followlinks=False):
            parent=pathlib.Path(directory);relative=parent.relative_to(root)
            # Spec-0072/T3: prune private caches before scandir ever enters them.
            dirs[:]=sorted(name for name in dirs if name not in excluded and relative.parts+(name,) not in private_runtime and not (parent/name).is_symlink())
            for name in sorted(files):
                path=parent/name;rel=path.relative_to(root)
                if path.is_file() and not path.is_symlink() and not any(p in excluded for p in rel.parts) and path!=output and path.name != 'bootstrap.py' and not path.name.endswith('.lock'):
                    area_paths.append(path)
        result.extend(sorted(area_paths))
    return result
files={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths()}
descriptor=os.open(output,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600);os.fchmod(descriptor,0o600)
with os.fdopen(descriptor,'wb') as stream,tarfile.open(fileobj=stream,mode='w:gz',dereference=True) as tar:
    for name in files: tar.add(root/name,arcname=name,recursive=False)
consistent=all((root/name).is_file() and hashlib.sha256((root/name).read_bytes()).hexdigest()==digest for name,digest in files.items())
print(json.dumps({'files':files,'consistent':consistent,'archive_sha256':hashlib.sha256(output.read_bytes()).hexdigest()}))
"""
