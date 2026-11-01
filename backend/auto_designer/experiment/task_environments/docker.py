"""Spec-0081/T3: owned Docker task containers and finite companion services."""

from __future__ import annotations

import contextlib
import copy
import fcntl
import hashlib
import inspect
import io
import json
import os
import re
import selectors
import subprocess
import tarfile
import tempfile
import time
from pathlib import Path, PurePosixPath

from auto_designer.user.sim.runtime import (
    _MAX_OUTPUT,
    DockerWorkspaceRuntime,
    list_review_files,
    read_bounded_file,
    utc_now,
)

LABEL = "io.auto-designer.task-environment"
PRIVATE_LIMIT = 64 * 1024 * 1024


class TaskEnvironmentError(RuntimeError):
    """A task environment cannot prove a required resource or lifecycle fact."""


def _digest(*, value: dict) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _write(*, path: Path, value: dict) -> None:
    temporary = path.with_name(path.name + ".tmp")
    descriptor = os.open(temporary, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        stream.write(json.dumps(value, indent=2, ensure_ascii=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


_PROCESS_STATE = r"""
import json,os,sys
from pathlib import Path
def proc(pid):
    try:
        fields=Path('/proc',str(pid),'stat').read_text().rsplit(')',1)[1].split()
        return {'pid':int(pid),'state':fields[0],'ppid':int(fields[1]),'pgrp':int(fields[2]),'sid':int(fields[3]),'start_ticks':fields[19]}
    except (FileNotFoundError,ProcessLookupError):return None
config=json.loads(sys.argv[1])
if config['action']=='keepers':
    values=[]
    for item in Path('/proc').iterdir():
        if item.name.isdigit():
            row=proc(item.name)
            if row and (row['pid']==1 or (row['ppid']==1 and Path(item,'cmdline').read_bytes().split(b'\x00')[:2]==[b'sleep',b'infinity'])):values.append(row)
    print(json.dumps(values))
elif config['action']=='inspect':print(json.dumps(proc(config['pid'])))
"""

_QUIESCE = r"""
import json,os,signal,sys,time
from pathlib import Path
def proc(pid):
    try:
        f=Path('/proc',str(pid),'stat').read_text().rsplit(')',1)[1].split()
        return {'pid':int(pid),'state':f[0],'ppid':int(f[1]),'pgrp':int(f[2]),'sid':int(f[3]),'start_ticks':f[19]}
    except (FileNotFoundError,ProcessLookupError):return None
config=json.loads(sys.argv[1]);protected={1,os.getpid()};sessions=set();observed={}
for expected in config['protected']:
    actual=proc(expected['pid'])
    if actual and actual['start_ticks']==expected['start_ticks']:
        protected.add(actual['pid'])
        if expected.get('protect_session'):sessions.add(actual['sid'])
def listener_owners(rows):
    ports=set(config.get('handoff_ports',[]));inodes=set();owners=set()
    if not ports:return owners
    for name in ('tcp','tcp6'):
        table=Path('/proc/net',name)
        if not table.exists() and name=='tcp6':continue
        for line in table.read_text().splitlines()[1:]:
            fields=line.split()
            if int(fields[1].rsplit(':',1)[1],16) in ports:inodes.add(fields[9])
    for row in rows:
        try:
            for fd in Path('/proc',str(row['pid']),'fd').iterdir():
                try:target=os.readlink(fd)
                except FileNotFoundError:continue
                if target.startswith('socket:[') and target[8:-1] in inodes:
                    owners.add(row['pid']);observed[row['pid']]=row;break
        except FileNotFoundError:continue
    return owners
def candidates():
    rows=[]
    for entry in Path('/proc').iterdir():
        if entry.name.isdigit():
            row=proc(entry.name)
            if row and row['state']!='Z':rows.append(row)
    owners=listener_owners(rows)
    return [row for row in rows if row['pid'] not in protected and row['sid'] not in sessions and row['pid'] not in owners]
for sig in (signal.SIGTERM,signal.SIGKILL):
    for row in candidates():
        try:os.kill(row['pid'],sig)
        except ProcessLookupError:pass
    time.sleep(.15)
if candidates():raise RuntimeError('task writers remain active')
print(json.dumps({'actor_stopped':True,'protected_services':len(sessions),'handoff_processes':list(observed.values())}))
"""

_START_SERVICE = r"""
import json,os,subprocess,sys
from pathlib import Path
x=json.loads(sys.argv[1]);folder=Path(x['logs']);folder.mkdir(parents=True,exist_ok=True)
with (folder/'stdout.log').open('ab') as out,(folder/'stderr.log').open('ab') as err:
    child=subprocess.Popen(x['argv'],cwd=x['cwd'],env={**os.environ,**x['environment']},stdin=subprocess.DEVNULL,stdout=out,stderr=err,start_new_session=True)
    fields=Path('/proc',str(child.pid),'stat').read_text().rsplit(')',1)[1].split()
    value={'pid':child.pid,'start_ticks':fields[19],'sid':int(fields[3]),'protect_session':True}
    print(json.dumps(value))
"""

_START_NATIVE_SERVICE = r"""
set -eu
logs=$1; shift
mkdir -p "$logs"
"$@" </dev/null >>"$logs/stdout.log" 2>>"$logs/stderr.log" &
pid=$!
line=$(cat "/proc/$pid/stat")
fields=${line##*) }
set -- $fields
shift 19
start=$1
printf '{"pid":%s,"start_ticks":"%s","protect_session":false}\n' "$pid" "$start"
"""


class DockerTaskEnvironmentManager:
    """One manager owns a single bound attempt and its persistent resource journal."""

    def __init__(
        self,
        *,
        environment: dict,
        identity: dict,
        registry_root: Path,
        harness_python: str,
        harness_mounts: list[dict],
        expected_git_revision: str | None = None,
    ):
        self._reconcile_only = getattr(self, "_reconcile_only", False)
        required = {
            "run_id",
            "config_hash",
            "task_id",
            "task_digest",
            "recipe_hash",
            "session_id",
            "attempt",
            "round_no",
            "slot",
        }
        if set(identity) != required:
            raise TaskEnvironmentError("Task environment requires a complete bound attempt")
        if any(
            not isinstance(identity[k], str) or not identity[k]
            for k in required - {"attempt", "round_no", "slot"}
        ):
            raise TaskEnvironmentError("Task environment identity is incomplete")
        for key in ("attempt", "round_no", "slot"):
            if type(identity[key]) is not int or identity[key] < (0 if key == "slot" else 1):
                raise TaskEnvironmentError("Invalid bound attempt number")
        for key in ("config_hash", "task_digest", "recipe_hash"):
            if not re.fullmatch(r"[a-f0-9]{64}", identity[key]):
                raise TaskEnvironmentError("Task environment identity requires full content hashes")
        self.environment = copy.deepcopy(environment)
        from auto_designer.experiment.task_environments.contract import (
            container_environment,
            environment_identity,
        )

        package = {"schema_version": 3, "environment": self.environment}
        self.environment = container_environment(package)
        if environment_identity(package) != identity["recipe_hash"]:
            raise TaskEnvironmentError("Task environment recipe differs from its frozen identity")
        self.identity = dict(identity)
        self.key = _digest(value=identity)
        self.root = Path(registry_root)
        if self.root.is_symlink():
            raise TaskEnvironmentError("Linked task environment registry")
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.record_path = self.root / (self.key + ".json")
        self.private_root = self.root / self.key
        self.private_root.mkdir(mode=0o700, exist_ok=True)
        self.harness_python = harness_python
        self.expected_git_revision = expected_git_revision
        if expected_git_revision is not None and not re.fullmatch(
            r"[a-f0-9]{40}", expected_git_revision
        ):
            raise TaskEnvironmentError("Expected Git revision must be a fixed commit")
        self.harness_mounts = copy.deepcopy(harness_mounts)
        if not harness_python.startswith("/") or not self.harness_mounts:
            raise TaskEnvironmentError(
                "Task environment requires an explicit readonly Harness toolchain"
            )
        real_sources = {
            Path(mount.get("source", "")).resolve()
            for mount in self.harness_mounts
            if not self._reconcile_only
            and isinstance(mount, dict)
            and not Path(mount.get("source", "")).is_symlink()
        }
        for mount in self.harness_mounts:
            if set(mount) != {"source", "target"} or mount["source"] != mount["target"]:
                raise TaskEnvironmentError(
                    "Harness toolchain mounts must use trusted identical paths"
                )
            source = Path(mount["source"])
            if (
                not source.is_absolute()
                or not self._reconcile_only
                and (
                    not source.is_dir()
                    or source.is_symlink()
                    and source.resolve() not in real_sources
                )
                or str(source) in {"/", "/home", "/root", "/opt"}
            ):
                raise TaskEnvironmentError("Invalid readonly Harness toolchain mount")
        if not any(
            Path(harness_python).is_relative_to(Path(mount["target"]))
            for mount in self.harness_mounts
        ):
            raise TaskEnvironmentError("Harness interpreter is outside its readonly mounts")
        self.labels = {LABEL: "1", LABEL + ".key": self.key}
        self.labels.update({LABEL + "." + k: str(v) for k, v in identity.items()})

    @classmethod
    def _from_record(cls, *, value: dict, registry_root: Path):
        """Restore only ownership reconciliation; removed toolchains never block cleanup."""
        instance = cls.__new__(cls)
        instance._reconcile_only = True
        instance.__init__(
            environment=value["environment"],
            identity=value["identity"],
            registry_root=registry_root,
            harness_python=value["harness_python"],
            harness_mounts=value["harness_mounts"],
            expected_git_revision=value.get("expected_git_revision"),
        )
        return instance

    @contextlib.contextmanager
    def _lock(self):
        with (self.root / (self.key + ".lock")).open("a+") as stream:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            yield

    def _record(self) -> dict:
        if not self.record_path.exists():
            return {}
        value = json.loads(self.record_path.read_text())
        if value.get("identity") != self.identity or value.get("key") != self.key:
            raise TaskEnvironmentError("Task resource journal identity differs")
        if value.get("expected_git_revision") != self.expected_git_revision:
            raise TaskEnvironmentError("Task resource journal Git source differs")
        return value

    def _save(self, *, value: dict) -> None:
        value["updated_at"] = utc_now()
        _write(path=self.record_path, value=value)

    def _docker(
        self, *, argv: list[str], timeout: float, check: bool
    ) -> subprocess.CompletedProcess:
        value = subprocess.run(["docker", *argv], capture_output=True, text=True, timeout=timeout)
        if check and value.returncode:
            raise TaskEnvironmentError("Docker task operation failed: " + value.stderr[-1600:])
        return value

    def _inspect(self, *, kind: str, name: str) -> dict | None:
        value = self._docker(argv=[kind, "inspect", name], timeout=30, check=False)
        if value.returncode:
            if "no such" in value.stderr.lower() or "not found" in value.stderr.lower():
                return None
            raise TaskEnvironmentError("Cannot inspect Docker task resources")
        return json.loads(value.stdout)[0]

    def _owned(self, *, kind: str, name: str, running: bool) -> dict:
        info = self._inspect(kind=kind, name=name)
        if info is None:
            raise TaskEnvironmentError("LOST: recorded task resource is absent")
        labels = (
            info.get("Labels", {})
            if kind == "network"
            else (info.get("Config") or {}).get("Labels", {})
        )
        if any(labels.get(k) != v for k, v in self.labels.items()):
            raise TaskEnvironmentError("Docker task resource ownership differs")
        if running and not info.get("State", {}).get("Running"):
            raise TaskEnvironmentError("Task container is stopped; explicit recovery is required")
        return info

    def _exec_in(
        self,
        *,
        container: str,
        argv: list[str],
        cwd: str,
        user: str | None,
        environment: dict,
        timeout: float,
    ) -> subprocess.CompletedProcess:
        if self._reconcile_only:
            raise TaskEnvironmentError("Reconciliation cannot execute task processes")
        self._owned(kind="container", name=container, running=True)
        command = ["exec", "-i", "-w", cwd]
        if user:
            command.extend(["--user", user])
        for key, value in environment.items():
            command.extend(["--env", key + "=" + value])
        return self._docker(argv=[*command, container, *argv], timeout=timeout, check=True)

    def _image(self, *, image: str) -> dict:
        info = self._inspect(kind="image", name=image)
        if info is None:
            self._docker(argv=["pull", image], timeout=1200, check=True)
            info = self._inspect(kind="image", name=image)
        digest = image.rsplit("@", 1)[1]
        if info is None or not any(
            str(ref).endswith("@" + digest) for ref in info.get("RepoDigests", [])
        ):
            raise TaskEnvironmentError("Task image does not match its declared registry digest")
        return info

    def _ensure_network(self, *, record: dict) -> None:
        name = "ad-task-" + self.key[:20]
        entry = record["resources"].setdefault("network", {"name": name})
        self._save(value=record)
        info = self._inspect(kind="network", name=entry.get("id") or name)
        if info is None:
            if entry.get("id"):
                raise TaskEnvironmentError("LOST: task network cannot be implicitly recreated")
            argv = ["network", "create"]
            for key, value in self.labels.items():
                argv.extend(["--label", key + "=" + value])
            self._docker(argv=[*argv, name], timeout=60, check=True)
        info = self._owned(kind="network", name=entry.get("id") or name, running=False)
        entry["id"] = info["Id"]
        self._save(value=record)

    def _ensure_container(
        self,
        *,
        record: dict,
        identifier: str,
        image: str,
        cwd: str,
        user: str | None,
        resources: dict,
        ptrace: bool,
    ) -> str:
        containers = record["resources"]["containers"]
        name = "ad-task-" + self.key[:16] + "-" + identifier.lower()
        entry = containers.setdefault(identifier, {"name": name, "image": image})
        self._save(value=record)
        info = self._inspect(kind="container", name=entry.get("id") or name)
        expected = self._image(image=image)
        entry["expected_image_id"] = expected["Id"]
        if info is None:
            if entry.get("id"):
                raise TaskEnvironmentError("LOST: task container cannot be implicitly recreated")
            argv = [
                "run",
                "-d",
                "--init",
                "--name",
                name,
                "--network",
                record["resources"]["network"]["id"],
                "--network-alias",
                identifier,
                "--workdir",
                cwd,
                "--entrypoint",
                "/bin/sh",
                "--shm-size",
                "256m",
            ]
            for key, value in self.labels.items():
                argv.extend(["--label", key + "=" + value])
            if user:
                argv.extend(["--user", user])
            if identifier == "task":
                for key, value in self.environment["variables"].items():
                    argv.extend(["--env", key + "=" + value])
            if resources.get("cpus"):
                argv.extend(["--cpus", str(resources["cpus"])])
            if resources.get("memory_mb"):
                argv.extend(["--memory", str(resources["memory_mb"]) + "m"])
            if ptrace:
                argv.extend(["--cap-add", "SYS_PTRACE", "--security-opt", "seccomp=unconfined"])
            for mount in self.harness_mounts if identifier == "task" else []:
                argv.extend(
                    [
                        "--mount",
                        f"type=bind,source={mount['source']},target={mount['target']},readonly",
                    ]
                )
            keeper = (
                "exec sleep infinity" if identifier == "task" else "while :; do sleep 3600; done"
            )
            self._docker(argv=[*argv, image, "-c", keeper], timeout=120, check=True)
            entry["expected_image_id"] = expected["Id"]
        info = self._owned(kind="container", name=entry.get("id") or name, running=True)
        if entry.get("expected_image_id") and info["Image"] != entry["expected_image_id"]:
            raise TaskEnvironmentError("Task container image differs from its declared material")
        entry["id"] = info["Id"]
        entry["image_id"] = info["Image"]
        self._save(value=record)
        if "keepers" not in entry:
            if identifier != "task":
                entry["keepers"] = []
                self._save(value=record)
                return entry["id"]
            probe = self._exec_in(
                container=entry["id"],
                argv=[self.harness_python, "-c", _PROCESS_STATE, json.dumps({"action": "keepers"})],
                cwd="/",
                user="root",
                environment={},
                timeout=30,
            )
            entry["keepers"] = json.loads(probe.stdout)
            self._save(value=record)
        return entry["id"]

    def _stage_inputs(self, *, record: dict) -> None:
        from auto_designer.experiment.task_environments.materials import materialize_input

        state = record.setdefault("inputs", {})
        for item in self.environment["inputs"]:
            identifier = item["id"]
            if state.get(identifier) == "complete":
                continue
            if state.get(identifier) == "started":
                raise TaskEnvironmentError("Interrupted input staging requires a fresh attempt")
            placement = item.get("placement", "task")
            container = record["resources"]["containers"][placement]["id"]
            state[identifier] = "started"
            self._save(value=record)
            with tempfile.TemporaryDirectory(prefix="input-", dir=self.private_root) as temporary:
                directory = Path(temporary)
                materialize_input(material=item["material"], destination=directory)
                target = item["target"]
                parent = (
                    str(PurePosixPath(target).parent)
                    if item["material"]["format"] == "file"
                    else target
                )
                self._exec_in(
                    container=container,
                    argv=["mkdir", "-p", parent],
                    cwd="/",
                    user="root",
                    environment={},
                    timeout=30,
                )
                source = (
                    str(directory / "input")
                    if item["material"]["format"] == "file"
                    else str(directory) + "/."
                )
                self._docker(argv=["cp", source, container + ":" + target], timeout=300, check=True)
            state[identifier] = "complete"
            self._save(value=record)

    def _hook(
        self, *, container: str, command: dict, cwd: str, user: str | None, environment: dict
    ) -> None:
        self._exec_in(
            container=container,
            argv=command["argv"],
            cwd=command.get("cwd", cwd),
            user=user,
            environment=environment,
            timeout=command["timeout_seconds"],
        )

    def _readiness(
        self, *, container: str, command: dict, cwd: str, user: str | None, environment: dict
    ) -> None:
        deadline = time.monotonic() + command["timeout_seconds"]
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TaskEnvironmentError("Task readiness deadline expired")
            self._owned(kind="container", name=container, running=True)
            try:
                self._hook(
                    container=container,
                    command={**command, "timeout_seconds": remaining},
                    cwd=cwd,
                    user=user,
                    environment=environment,
                )
                return
            except TaskEnvironmentError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(min(0.5, max(0, deadline - time.monotonic())))

    def _once(
        self,
        *,
        record: dict,
        key: str,
        container: str,
        command: dict | None,
        cwd: str,
        user: str | None,
        environment: dict,
    ) -> None:
        stages = record.setdefault("stages", {})
        if command is None or stages.get(key) == "complete":
            return
        if stages.get(key) == "started":
            raise TaskEnvironmentError(
                "Interrupted side-effecting environment hook requires recovery"
            )
        stages[key] = "started"
        self._save(value=record)
        self._hook(
            container=container, command=command, cwd=cwd, user=user, environment=environment
        )
        stages[key] = "complete"
        self._save(value=record)

    def _services(self) -> list[dict]:
        remaining = {row["id"]: row for row in self.environment["services"]}
        result = []
        while remaining:
            ready = [
                row
                for row in remaining.values()
                if all(ref not in remaining for ref in row["depends_on"])
            ]
            if not ready:
                raise TaskEnvironmentError("Service dependency cycle")
            for row in ready:
                result.append(row)
                del remaining[row["id"]]
        return result

    def open(self) -> ContainerTaskRuntime:
        if self._reconcile_only:
            raise TaskEnvironmentError("Reconciliation cannot provision or restart an Actor")
        with self._lock():
            record = self._record()
            if not record:
                record = {
                    "version": 1,
                    "identity": self.identity,
                    "key": self.key,
                    "phase": "creating",
                    "environment": self.environment,
                    "harness_python": self.harness_python,
                    "harness_mounts": self.harness_mounts,
                    "expected_git_revision": self.expected_git_revision,
                    "created_at": utc_now(),
                    "resources": {"containers": {}},
                    "services": {},
                }
                self._save(value=record)
            if record["phase"] in {"closed", "stopped", "failed"}:
                raise TaskEnvironmentError("A completed or failed task attempt cannot be restarted")
            try:
                self._ensure_network(record=record)
                task = self._ensure_container(
                    record=record,
                    identifier="task",
                    image=self.environment["image"],
                    cwd=self.environment["workdir"],
                    user=self.environment.get("user"),
                    resources=self.environment["resources"],
                    ptrace="ptrace" in self.environment["capabilities"],
                )
                if record["phase"] in {"ready", "quiesced", "frozen"}:
                    for name, entry in record["resources"]["containers"].items():
                        self._owned(
                            kind="container",
                            name=entry["id"],
                            running=record["phase"] != "frozen" or name == "task",
                        )
                    return ContainerTaskRuntime(manager=self, record=record)
                for row in self._services():
                    if row["placement"] == "companion":
                        self._ensure_container(
                            record=record,
                            identifier=row["id"],
                            image=row["image"],
                            cwd=row.get("cwd", "/"),
                            user=row.get("user"),
                            resources=row["resources"],
                            ptrace=False,
                        )
                self._stage_inputs(record=record)
                self._once(
                    record=record,
                    key="initialize",
                    container=task,
                    command=self.environment.get("initialize"),
                    cwd=self.environment["workdir"],
                    user="root",
                    environment=self.environment["variables"],
                )
                self._exec_in(
                    container=task,
                    argv=["mkdir", "-p", "/opt/auto-designer/harness"],
                    cwd="/",
                    user="root",
                    environment={},
                    timeout=30,
                )
                self._exec_in(
                    container=task,
                    argv=["chmod", "0777", "/opt/auto-designer", "/opt/auto-designer/harness"],
                    cwd="/",
                    user="root",
                    environment={},
                    timeout=30,
                )
                self._exec_in(
                    container=task,
                    argv=[
                        self.harness_python,
                        "-c",
                        "from nexau import Agent,AgentConfig;import sys;print(sys.version)",
                    ],
                    cwd="/",
                    user=self.environment.get("user"),
                    environment={},
                    timeout=60,
                )
                for row in self._services():
                    placement = "task" if row["placement"] == "task" else row["id"]
                    container = record["resources"]["containers"][placement]["id"]
                    service = record["services"].setdefault(
                        row["id"], {"container": placement, "phase": "starting"}
                    )
                    values = {
                        **(self.environment["variables"] if placement == "task" else {}),
                        **row["environment"],
                    }
                    if row["mode"] == "oneshot":
                        self._once(
                            record=record,
                            key="oneshot-" + row["id"],
                            container=container,
                            command={
                                "argv": row["argv"],
                                "timeout_seconds": row["timeout_seconds"],
                            },
                            cwd=row.get(
                                "cwd", self.environment["workdir"] if placement == "task" else "/"
                            ),
                            user=row.get("user"),
                            environment=values,
                        )
                        service["phase"] = "complete"
                        self._save(value=record)
                        continue
                    if "process" not in service:
                        if service.get("launch_intent") == "started":
                            raise TaskEnvironmentError(
                                "Interrupted service start cannot launch another process"
                            )
                        logs = "/tmp/auto-designer-services/" + self.key + "/" + row["id"]
                        payload = {
                            "argv": row["argv"],
                            "cwd": row.get(
                                "cwd", self.environment["workdir"] if placement == "task" else "/"
                            ),
                            "environment": values,
                            "logs": logs,
                        }
                        service["launch_intent"] = "started"
                        self._save(value=record)
                        native = placement != "task"
                        value = self._exec_in(
                            container=container,
                            argv=(
                                [
                                    "/bin/sh",
                                    "-c",
                                    _START_NATIVE_SERVICE,
                                    "service",
                                    logs,
                                    *row["argv"],
                                ]
                                if native
                                else [
                                    self.harness_python,
                                    "-c",
                                    _START_SERVICE,
                                    json.dumps(payload),
                                ]
                            ),
                            cwd=payload["cwd"] if native else "/",
                            user=row.get("user"),
                            environment=values if native else {},
                            timeout=30,
                        )
                        service["process"] = json.loads(value.stdout)
                        service["launch_intent"] = "complete"
                        service["logs"] = logs
                        self._save(value=record)
                    self._readiness(
                        container=container,
                        command=row["readiness"],
                        cwd=row.get(
                            "cwd", self.environment["workdir"] if placement == "task" else "/"
                        ),
                        user=row.get("user"),
                        environment=values,
                    )
                    service["phase"] = "ready"
                    self._save(value=record)
                if self.expected_git_revision is not None:
                    actual = self._exec_in(
                        container=task,
                        argv=["git", "rev-parse", "--verify", "HEAD^{commit}"],
                        cwd=self.environment["workdir"],
                        user=self.environment.get("user"),
                        environment={},
                        timeout=30,
                    ).stdout.strip()
                    if actual != self.expected_git_revision:
                        raise TaskEnvironmentError(
                            "Prepared Git HEAD differs from the frozen source"
                        )
                self._readiness(
                    container=task,
                    command=self.environment["readiness"],
                    cwd=self.environment["workdir"],
                    user=self.environment.get("user"),
                    environment=self.environment["variables"],
                )
                record["phase"] = "ready"
                record["ready_at"] = utc_now()
                self._save(value=record)
                return ContainerTaskRuntime(manager=self, record=record)
            except BaseException as error:
                record["phase"] = "failed"
                record["failure"] = {"type": type(error).__name__, "at": utc_now()}
                self._save(value=record)
                raise

    def quiesce(self) -> None:
        with self._lock():
            record = self._record()
            if record["phase"] in {"quiesced", "frozen"}:
                return
            if record["phase"] != "ready":
                raise TaskEnvironmentError("Task Actor cannot be frozen from its current phase")
            for name, entry in record["resources"]["containers"].items():
                if name != "task":
                    # Companions contain no Actor. Keep the whole workload alive for finalization.
                    continue
                protected = list(entry["keepers"])
                protected.extend(
                    row["process"]
                    for row in record["services"].values()
                    if row["container"] == name and "process" in row
                )
                ports = [
                    port
                    for row in self.environment["services"]
                    if name == "task" and row["placement"] == "task"
                    for port in row.get("handoff_ports", [])
                ]
                stopped = self._exec_in(
                    container=entry["id"],
                    argv=[
                        self.harness_python,
                        "-c",
                        _QUIESCE,
                        json.dumps({"protected": protected, "handoff_ports": ports}),
                    ],
                    cwd="/",
                    user="root",
                    environment={},
                    timeout=15,
                )
                record["resources"]["containers"][name]["actor_freeze"] = json.loads(stopped.stdout)
            record["phase"] = "quiesced"
            record["quiesced_at"] = utc_now()
            self._save(value=record)

    def finalize(self) -> None:
        with self._lock():
            record = self._record()
            if record["phase"] == "frozen":
                return
            if record["phase"] != "quiesced":
                raise TaskEnvironmentError(
                    "Services cannot be finalized before the Actor is quiescent"
                )
            try:
                for row in reversed(self._services()):
                    if row["mode"] == "oneshot":
                        continue
                    placement = "task" if row["placement"] == "task" else row["id"]
                    container = record["resources"]["containers"][placement]["id"]
                    self._once(
                        record=record,
                        key="finalize-service-" + row["id"],
                        container=container,
                        command=row.get("finalize"),
                        cwd=row.get(
                            "cwd", self.environment["workdir"] if placement == "task" else "/"
                        ),
                        user=row.get("user"),
                        environment=row["environment"],
                    )
                task = record["resources"]["containers"]["task"]["id"]
                self._once(
                    record=record,
                    key="finalize-task",
                    container=task,
                    command=self.environment.get("finalize"),
                    cwd=self.environment["workdir"],
                    user="root",
                    environment=self.environment["variables"],
                )
                for name, entry in record["resources"]["containers"].items():
                    if name != "task":
                        self._owned(kind="container", name=entry["id"], running=True)
                        self._docker(
                            argv=["stop", "--time", "2", entry["id"]], timeout=20, check=True
                        )
                        continue
                    self._exec_in(
                        container=entry["id"],
                        argv=[
                            self.harness_python,
                            "-c",
                            _QUIESCE,
                            json.dumps({"protected": entry["keepers"]}),
                        ],
                        cwd="/",
                        user="root",
                        environment={},
                        timeout=15,
                    )
                record["phase"] = "frozen"
                record["frozen_at"] = utc_now()
                for service in record["services"].values():
                    if service["phase"] == "ready":
                        service["phase"] = "finalized"
                self._save(value=record)
            except BaseException as error:
                record["finalization_error"] = {"type": type(error).__name__, "at": utc_now()}
                self._save(value=record)
                raise

    def _read_file(self, *, container: str, root: str, path: str, max_bytes: int) -> bytes:
        if type(max_bytes) is not int or max_bytes <= 0:
            raise ValueError("Artifact export requires a positive byte limit")
        task_id = self._record()["resources"]["containers"]["task"]["id"]
        if container != task_id:
            return self._read_native_file(
                container=container, path=str(PurePosixPath(root) / path), max_bytes=max_bytes
            )
        self._owned(kind="container", name=container, running=True)
        script = (
            "import os,stat,sys\nfrom pathlib import PurePosixPath\n"
            + inspect.getsource(read_bounded_file)
            + "\ntry:\n sys.stdout.buffer.write(read_bounded_file(sys.argv[1],sys.argv[2],int(sys.argv[3])))\nexcept Exception as exc:\n print(type(exc).__name__,file=sys.stderr);sys.exit(1)\n"
        )
        result = subprocess.run(
            [
                "docker",
                "exec",
                "--user",
                "root",
                container,
                self.harness_python,
                "-c",
                script,
                root,
                path,
                str(max_bytes),
            ],
            capture_output=True,
            timeout=30,
        )
        if result.returncode:
            reason = result.stderr.decode(errors="replace").strip()
            if reason == "FileNotFoundError":
                raise FileNotFoundError(path)
            if reason == "OverflowError":
                raise OverflowError("Artifact exceeds declared byte limit")
            if reason == "ValueError":
                raise ValueError("Artifact must be a real regular file")
            raise TaskEnvironmentError("Artifact read failed: " + reason[:200])
        if len(result.stdout) > max_bytes:
            raise OverflowError("Artifact exceeds declared byte limit")
        return result.stdout

    def _copy_header(self, *, container: str, path: str) -> tarfile.TarInfo:
        """Read a single stat header without consuming a directory's recursive archive."""
        with subprocess.Popen(
            ["docker", "cp", container + ":" + path, "-"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        ) as process:
            data = bytearray()
            cursor = 0
            deadline = time.monotonic() + 15
            try:
                with selectors.DefaultSelector() as selector:
                    selector.register(process.stdout, selectors.EVENT_READ)
                    while True:
                        while len(data) < cursor + 512:
                            remaining = deadline - time.monotonic()
                            if remaining <= 0 or not selector.select(remaining):
                                raise TimeoutError("Native companion archive stat deadline")
                            block = os.read(process.stdout.fileno(), 4096)
                            if not block:
                                raise FileNotFoundError(path)
                            data.extend(block)
                            if len(data) > 65536:
                                raise TaskEnvironmentError(
                                    "Native companion archive header too large"
                                )
                        member = tarfile.TarInfo.frombuf(
                            bytes(data[cursor : cursor + 512]), "utf-8", "surrogateescape"
                        )
                        if member.type not in {
                            tarfile.XHDTYPE,
                            tarfile.XGLTYPE,
                            tarfile.GNUTYPE_LONGNAME,
                            tarfile.GNUTYPE_LONGLINK,
                        }:
                            return member
                        cursor += 512 + ((member.size + 511) // 512) * 512
                        if cursor > 65024:
                            raise TaskEnvironmentError("Native companion archive header too large")
            finally:
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=5)

    def _read_native_file(self, *, container: str, path: str, max_bytes: int) -> bytes:
        from auto_designer.observations.publication import bounded_command

        info = self._owned(kind="container", name=container, running=False)
        if info["State"]["Running"]:
            raise TaskEnvironmentError("Native companion writers are not frozen")
        target = PurePosixPath(path)
        if not target.is_absolute() or ".." in target.parts:
            raise ValueError("Invalid native companion output path")
        for parent in reversed(target.parents):
            if str(parent) == "/":
                continue
            if not self._copy_header(container=container, path=str(parent)).isdir():
                raise ValueError("Native companion output parent is not a real directory")
        member = self._copy_header(container=container, path=path)
        if not member.isreg():
            raise ValueError("Native companion output is not a regular file")
        if member.size > max_bytes:
            raise OverflowError("Artifact exceeds declared byte limit")
        raw = bounded_command(
            ["docker", "cp", container + ":" + path, "-"], timeout=30, limit=max_bytes + 65536
        )
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as archive:
            members = archive.getmembers()
            if len(members) != 1 or not members[0].isreg():
                raise ValueError("Native companion output is not a regular file")
            if members[0].size > max_bytes:
                raise OverflowError("Artifact exceeds declared byte limit")
            body = archive.extractfile(members[0]).read(max_bytes + 1)
        if len(body) > max_bytes:
            raise OverflowError("Artifact exceeds declared byte limit")
        return body

    def export_service_file(self, *, handle: str, max_bytes: int) -> bytes:
        with self._lock():
            record = self._record()
            if record["phase"] != "frozen":
                raise TaskEnvironmentError("Service outputs are not frozen")
            for row in self.environment["services"]:
                for output in row["exports"]:
                    if output["handle"] == handle:
                        if output["visibility"] != "task":
                            raise PermissionError(
                                "Management output cannot enter a public task artifact"
                            )
                        placement = "task" if row["placement"] == "task" else row["id"]
                        container = record["resources"]["containers"][placement]["id"]
                        return self._read_file(
                            container=container,
                            root="/",
                            path=output["path"].lstrip("/"),
                            max_bytes=max_bytes,
                        )
            raise KeyError("Unknown owned service output handle")

    def service_export_provenance(self, *, handle: str) -> dict:
        """Attest an owned public output without exposing management measurements."""
        with self._lock():
            record = self._record()
            if record["phase"] != "frozen":
                raise TaskEnvironmentError("Service outputs are not frozen")
            for row in self.environment["services"]:
                for output in row["exports"]:
                    if output["handle"] != handle:
                        continue
                    if output["visibility"] != "task":
                        raise PermissionError("Management output has no public provenance")
                    placement = "task" if row["placement"] == "task" else row["id"]
                    container = record["resources"]["containers"][placement]["id"]
                    self._owned(kind="container", name=container, running=placement == "task")
                    return {
                        "environment_key": self.key,
                        "recipe_hash": self.identity["recipe_hash"],
                        "identity": dict(self.identity),
                        "service": row["id"],
                        "service_id": container,
                        "owner_session_id": self.identity["session_id"],
                        "handle": handle,
                        "placement": row["placement"],
                        "visibility": "task",
                        "sealed_at": record["frozen_at"],
                        "controller_owned": True,
                        "isolated": row["placement"] == "companion",
                        "agent_stopped": bool(record.get("quiesced_at")),
                    }
            raise KeyError("Unknown owned service output handle")

    def capture_management(self) -> None:
        with self._lock():
            record = self._record()
            if record["phase"] != "frozen":
                raise TaskEnvironmentError("Management outputs are not frozen")
            receipts = record.setdefault("management_outputs", {})
            for row in self.environment["services"]:
                placement = "task" if row["placement"] == "task" else row["id"]
                container = record["resources"]["containers"][placement]["id"]
                paths = [
                    (output["handle"], output["path"], PRIVATE_LIMIT, True)
                    for output in row["exports"]
                    if output["visibility"] == "management"
                ]
                log_root = record["services"][row["id"]].get("logs")
                if log_root:
                    paths.extend(
                        [
                            (row["id"] + ".stdout", log_root + "/stdout.log", 1024 * 1024, False),
                            (row["id"] + ".stderr", log_root + "/stderr.log", 1024 * 1024, False),
                        ]
                    )
                for handle, path, limit, required in paths:
                    if receipts.get(handle, {}).get("status") == "collected":
                        continue
                    try:
                        body = self._read_file(
                            container=container, root="/", path=path.lstrip("/"), max_bytes=limit
                        )
                        destination = self.private_root / (handle + ".data")
                        if destination.exists():
                            if destination.is_symlink() or destination.read_bytes() != body:
                                raise TaskEnvironmentError(
                                    "Previously captured management output differs"
                                )
                        else:
                            descriptor = os.open(
                                destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600
                            )
                            with os.fdopen(descriptor, "wb") as stream:
                                stream.write(body)
                        receipts[handle] = {
                            "status": "collected",
                            "path": str(destination),
                            "bytes": len(body),
                            "sha256": hashlib.sha256(body).hexdigest(),
                            "visibility": "management",
                            "required": required,
                        }
                    except Exception as error:
                        receipts[handle] = {
                            "status": "unavailable",
                            "reason": type(error).__name__,
                            "visibility": "management",
                            "required": required,
                        }
                    self._save(value=record)
            if any(
                value.get("required") and value["status"] != "collected"
                for value in receipts.values()
            ):
                raise TaskEnvironmentError("Required management outputs were not captured")

    def close(self, *, retain: bool) -> None:
        with self._lock():
            record = self._record()
            if record["phase"] == "closed":
                return
            for entry in reversed(list(record["resources"]["containers"].values())):
                info = self._inspect(kind="container", name=entry.get("id") or entry["name"])
                if info is None:
                    continue
                self._owned(kind="container", name=info["Id"], running=False)
                if retain:
                    if info.get("State", {}).get("Running"):
                        self._docker(
                            argv=["stop", "--time", "2", info["Id"]], timeout=20, check=True
                        )
                else:
                    self._docker(argv=["rm", "-f", info["Id"]], timeout=30, check=True)
            network = record["resources"].get("network")
            if (
                not retain
                and network
                and self._inspect(kind="network", name=network.get("id") or network["name"])
            ):
                info = self._owned(
                    kind="network", name=network.get("id") or network["name"], running=False
                )
                self._docker(argv=["network", "rm", info["Id"]], timeout=30, check=True)
            if record["phase"] != "stopped":
                record["stopped_from_phase"] = record["phase"]
            record["phase"] = "stopped" if retain else "closed"
            record["closed_at"] = utc_now()
            record["retained"] = retain
            self._save(value=record)


class ContainerTaskRuntime(DockerWorkspaceRuntime):
    """Reuse Docker's execution protocol while owning service-specific freeze semantics."""

    def __init__(self, *, manager: DockerTaskEnvironmentManager, record: dict):
        self.manager = manager
        entry = record["resources"]["containers"]["task"]
        super().__init__(
            container_id=entry["id"],
            container_name=entry["name"],
            image=entry["image"],
            image_digest=entry["image_id"],
            cwd=manager.environment["workdir"],
        )
        self.evidence.update(
            {
                "environment_key": manager.key,
                "environment_registry": str(manager.record_path),
                "recipe_hash": manager.identity["recipe_hash"],
                "harness_python": manager.harness_python,
                "patch_capability": manager.environment["patch"],
                "environment_phase": record["phase"],
            }
        )

    def _actor(self) -> None:
        if getattr(self, "_collection_only", False):
            raise TaskEnvironmentError("Collection recovery cannot run an Actor")
        if self.manager._record()["phase"] != "ready":
            raise TaskEnvironmentError("Task Actor is frozen or unavailable")

    def run(self, cmd: str, timeout: float = 10.0) -> dict:
        self._actor()
        return super().run(cmd, timeout)

    def write_text(self, path: str, content: str) -> str:
        self._actor()
        return super().write_text(path, content)

    def popen_argv(self, argv: list[str], *, cwd: str, env: dict[str, str]) -> list[str]:
        self._actor()
        return super().popen_argv(
            argv, cwd=cwd, env={**env, **self.manager.environment["variables"]}
        )

    def stage_directory(self, source: Path, destination: str) -> None:
        self._actor()
        super().stage_directory(source, destination)

    def review_file_listing(self) -> dict:
        if self.manager.environment["patch"] == "not_applicable":
            script = (
                "import json,sys\n"
                + inspect.getsource(list_review_files)
                + "\nprint(json.dumps(list_review_files(root=sys.argv[1],"
                + "max_output=int(sys.argv[2]))))"
            )
            value = self._exec(
                [self.manager.harness_python, "-c", script, self.cwd, str(_MAX_OUTPUT)],
                timeout=10,
            )
            if value.returncode:
                return {"returncode": value.returncode, "stdout": "", "clipped": True}
            return json.loads(value.stdout)
        value = self._exec(
            ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"], timeout=10
        )
        return {"returncode": value.returncode, "stdout": value.stdout[:20000]}

    def freeze_patch_base(self) -> None:
        if self.manager.environment["patch"] == "not_applicable":
            self.evidence["patch_status"] = "not_applicable"
            return
        return super().freeze_patch_base()

    def export_patch(self) -> tuple[str, str]:
        if self.manager.environment["patch"] == "not_applicable":
            self.evidence["patch_status"] = "not_applicable"
            return "", ""
        return super().export_patch()

    def export_file(self, path: str, max_bytes: int) -> bytes:
        self._ensure_live()
        return self.manager._read_file(
            container=self.container_id, root=self.cwd, path=path, max_bytes=max_bytes
        )

    def export_service_file(self, handle: str, max_bytes: int) -> bytes:
        self._ensure_live()
        return self.manager.export_service_file(handle=handle, max_bytes=max_bytes)

    def service_export_provenance(self, handle: str) -> dict:
        self._ensure_live()
        return self.manager.service_export_provenance(handle=handle)

    def collection_binding(self) -> dict:
        """Original resource identity survives controller retries and attempt increments."""
        return {
            "kind": "container",
            "registry_root": str(self.manager.root),
            "environment_key": self.manager.key,
            "identity": dict(self.manager.identity),
            "patch_base_commit": self._patch_base_commit,
            "patch_base_failed": self._patch_base_failed,
        }

    def quiesce(self) -> None:
        self.manager.quiesce()
        self.evidence["environment_phase"] = "quiesced"

    def finalize_task(self) -> None:
        self.manager.finalize()
        self.manager.capture_management()
        self.evidence["environment_phase"] = "frozen"

    def invalidate(self, reason: str) -> None:
        if self._closed:
            return
        self.evidence.update({"invalidated_at": utc_now(), "invalid_reason": reason})
        self.manager.quiesce()

    def close(self) -> None:
        if self._closed:
            return
        state = self.manager._record()
        outputs = state.get("management_outputs", {})
        missing_management = any(
            outputs.get(output["handle"], {}).get("status") != "collected"
            for service in self.manager.environment["services"]
            for output in service["exports"]
            if output["visibility"] == "management"
        )
        retain = (
            state["phase"] != "frozen"
            or missing_management
            or self.evidence.get("collection_pending") is True
            or bool(self.evidence.get("observation", {}).get("retain_source"))
        )
        self.manager.close(retain=retain)
        self.evidence.update(
            {
                "closed_at": utc_now(),
                "retained_for_observations": retain,
                "environment_phase": "stopped" if retain else "closed",
            }
        )
        self._closed = True


def _collection_manager(*, binding: dict, expected_provenance: dict):
    key = binding.get("environment_key", "")
    if not re.fullmatch(r"[a-f0-9]{64}", key):
        raise TaskEnvironmentError("Invalid collection environment key")
    root = Path(binding["registry_root"])
    path = root / (key + ".json")
    if any(item.is_symlink() for item in (path, *path.parents)):
        raise TaskEnvironmentError("Linked collection recovery journal")
    value = json.loads(path.read_text())
    if value.get("key") != key or value.get("identity") != binding.get("identity"):
        raise TaskEnvironmentError("Collection recovery resource identity changed")
    identity = value["identity"]
    for name in ("run_id", "task_id", "task_digest", "session_id", "round_no", "slot"):
        if identity.get(name) != expected_provenance.get(name):
            raise TaskEnvironmentError("Collection recovery logical session differs")
    manager = DockerTaskEnvironmentManager._from_record(value=value, registry_root=root)
    if manager.key != key or not value.get("frozen_at"):
        raise TaskEnvironmentError("Completed Actor awaits explicit finalization repair")
    return manager, value


def resume_collection(*, binding: dict, expected_provenance: dict) -> ContainerTaskRuntime:
    """Adopt already-frozen resources; restart only their inert keeper, never services or Actor."""
    reconciler, record = _collection_manager(
        binding=binding, expected_provenance=expected_provenance
    )
    if record["phase"] not in {"frozen", "stopped"} or (
        record["phase"] == "stopped" and record.get("stopped_from_phase") != "frozen"
    ):
        raise TaskEnvironmentError("Collection recovery requires an already-frozen environment")
    manager = DockerTaskEnvironmentManager(
        environment=record["environment"],
        identity=record["identity"],
        registry_root=reconciler.root,
        harness_python=record["harness_python"],
        harness_mounts=record["harness_mounts"],
        expected_git_revision=record.get("expected_git_revision"),
    )
    with manager._lock():
        for name, entry in record["resources"]["containers"].items():
            info = manager._owned(kind="container", name=entry["id"], running=False)
            if info["Image"] != entry["image_id"]:
                raise TaskEnvironmentError("Frozen collection image changed")
            if name != "task":
                if info["State"]["Running"]:
                    raise TaskEnvironmentError("Frozen native companion restarted unexpectedly")
                continue
            if not info["State"]["Running"]:
                manager._docker(argv=["start", entry["id"]], timeout=30, check=True)
        record["phase"] = "frozen"
        record["collection_recovered_at"] = utc_now()
        manager._save(value=record)
    runtime = ContainerTaskRuntime(manager=manager, record=record)
    base = binding.get("patch_base_commit")
    if base is not None and not re.fullmatch(r"[a-f0-9]{40}|[a-f0-9]{64}", base):
        raise TaskEnvironmentError("Invalid frozen collection Git base")
    runtime._patch_base_commit = base
    runtime._patch_base_failed = binding.get("patch_base_failed", False) is True
    runtime._collection_only = True
    return runtime


def release_collection(*, binding: dict, expected_provenance: dict) -> None:
    """Release retained frozen resources only after their required private bytes were captured."""
    manager, record = _collection_manager(binding=binding, expected_provenance=expected_provenance)
    outputs = record.get("management_outputs", {})
    if any(
        outputs.get(output["handle"], {}).get("status") != "collected"
        for service in manager.environment["services"]
        for output in service["exports"]
        if output["visibility"] == "management"
    ):
        raise TaskEnvironmentError("Cannot release uncaptured management evidence")
    manager.close(retain=False)


def _registered(
    *, registry_root: Path, run_id: str, config_hash: str
) -> list[DockerTaskEnvironmentManager]:
    root = Path(registry_root)
    if not root.exists():
        return []
    if root.is_symlink():
        raise TaskEnvironmentError("Linked task environment registry")
    result = []
    for path in sorted(root.glob("*.json")):
        if not re.fullmatch(r"[a-f0-9]{64}\.json", path.name):
            continue
        if path.is_symlink():
            raise TaskEnvironmentError("Linked task resource journal")
        value = json.loads(path.read_text())
        identity = value.get("identity", {})
        if identity.get("run_id") != run_id or identity.get("config_hash") != config_hash:
            continue
        manager = DockerTaskEnvironmentManager._from_record(value=value, registry_root=root)
        if manager.key + ".json" != path.name:
            raise TaskEnvironmentError("Task resource journal filename differs from identity")
        result.append(manager)
    return result


def inspect_registered(*, registry_root: Path, run_id: str, config_hash: str) -> dict:
    """Return infrastructure facts without private measurement bytes or task environment secrets."""
    attempts = []
    for manager in _registered(registry_root=registry_root, run_id=run_id, config_hash=config_hash):
        with manager._lock():
            record = manager._record()
            containers = []
            for row in record["resources"]["containers"].values():
                info = manager._inspect(kind="container", name=row.get("id") or row["name"])
                if info is not None:
                    manager._owned(kind="container", name=info["Id"], running=False)
                containers.append(
                    {
                        "id": row.get("id"),
                        "exists": info is not None,
                        "running": bool(info and info.get("State", {}).get("Running")),
                        "image_id": row.get("image_id"),
                    }
                )
            attempts.append(
                {
                    "environment_key": manager.key,
                    "identity": manager.identity,
                    "phase": record["phase"],
                    "containers": containers,
                    "services": {
                        identifier: {"phase": value["phase"]}
                        for identifier, value in record["services"].items()
                    },
                }
            )
    return {"version": 1, "attempts": attempts}


def stop_registered(*, registry_root: Path, run_id: str, config_hash: str) -> dict:
    """Stop only journal-owned containers; preserve interrupted attempt data."""
    for manager in _registered(registry_root=registry_root, run_id=run_id, config_hash=config_hash):
        record = manager._record()
        if record["phase"] != "closed":
            manager.close(retain=True)
    return inspect_registered(registry_root=registry_root, run_id=run_id, config_hash=config_hash)


def destroy_registered(*, registry_root: Path, run_id: str, config_hash: str) -> dict:
    """Remove only resources whose current provider labels prove this run owns them."""
    for manager in _registered(registry_root=registry_root, run_id=run_id, config_hash=config_hash):
        manager.close(retain=False)
    return inspect_registered(registry_root=registry_root, run_id=run_id, config_hash=config_hash)


def probe_docker() -> dict:
    """Observe the actual execution daemon before paid actor sessions begin."""
    result = subprocess.run(
        ["docker", "info", "--format", "{{json .}}"], capture_output=True, text=True, timeout=30
    )
    if result.returncode:
        raise TaskEnvironmentError("Docker daemon is not reachable from the task controller")
    info = json.loads(result.stdout)
    return {
        "server_version": info["ServerVersion"],
        "architecture": info["Architecture"],
        "cpus": info["NCPU"],
        "memory_bytes": info["MemTotal"],
        "cgroup_version": info.get("CgroupVersion"),
        "security_options": info.get("SecurityOptions", []),
    }
