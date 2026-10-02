"""Spec-0069/T3: frozen local toolchains and an experiment-owned Docker stack.

Compose provisions Gitea and egress. The shared controller starts Vigil with its
real configuration. Provider observations, rather than expected names, authorize
cleanup. Gitea's volume remains after compute destruction.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tarfile
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import requests

from auto_designer.experiment.backends.base import BackendError
from auto_designer.experiment.context import build_controller_environment, material_path
from auto_designer.experiment.engine import (
    controller_command,
    controller_logs,
    inspect_controller,
    launch_controller,
    materialize_controller_source,
    stop_controller,
)
from auto_designer.experiment.infrastructure import (
    DEFAULT_EGRESS_IMAGE,
    LABEL_EXPERIMENT,
    LABEL_MANIFEST,
    compose_argv,
    render_stack,
)
from auto_designer.experiment.materials import sha256_file, verify_materials

UV_VERSION = "0.11.28"
PYTHON_VERSION = "3.12.13"
CLAUDE_VERSION = "2.1.284"
RECIPE_VERSION = "unified-local-v1"

# Executed during a Docker build, never on the user's task checkout. Git tasks
# retain their true upstream base commit; a local source gets a snapshot commit.
TASK_BOOTSTRAP = r"""
import hashlib
import json
import os
import subprocess
import tarfile
from pathlib import Path

build = Path('/opt/task-build')
spec = json.loads((build / 'task-build.json').read_text())
repo = Path('/workspace') / spec['id'] / 'repo'
repo.mkdir(parents=True)
def git(*args):
    return subprocess.check_output(['git', '-C', str(repo), *args], text=True)
git('init', '-b', 'main')
source = spec['source']
if source['kind'] == 'git':
    git('remote', 'add', 'origin', source['url'])
    git('fetch', '--depth=1', 'origin', source['revision'])
    git('checkout', '--detach', source['revision'])
    assert git('rev-parse', 'HEAD').strip() == source['revision']
with tarfile.open(build / 'task-source.tar.gz', 'r:gz') as archive:
    for entry in archive.getmembers():
        path = Path(entry.name)
        if path.is_absolute() or '..' in path.parts or not (entry.isfile() or entry.isdir()):
            raise RuntimeError('unsafe task archive')
    archive.extractall(repo, filter='data')
for relative, digest in spec['files'].items():
    if hashlib.sha256((repo / relative).read_bytes()).hexdigest() != digest:
        raise RuntimeError('task snapshot hash mismatch: ' + relative)
if source['kind'] == 'git':
    if git('status', '--porcelain').strip():
        raise RuntimeError('frozen task source differs from its upstream commit')
else:
    git('add', '.')
    git('-c', 'user.name=Task snapshot', '-c', 'user.email=task@localhost',
        '-c', 'commit.gpgsign=false', '-c', 'core.hooksPath=/dev/null',
        'commit', '-m', 'snapshot: frozen task source')
base = git('rev-parse', 'HEAD').strip()
# Docker exec and login shell tools must select the prepared task environment.
Path('/etc/profile.d/auto-designer-task.sh').write_text(
    'export PATH="' + str(repo / '.venv/bin') + ':/opt/controller/.venv/bin:/usr/local/bin:/usr/bin:/bin"\n'
    + 'export VIRTUAL_ENV="' + str(repo / '.venv') + '"\n')
env = dict(os.environ, TASK_ROOT=str(repo), TASK_PYTHON='/usr/local/bin/python3',
           REQUIREMENTS_LOCK=str(build / 'requirements.lock'), VIRTUAL_ENV=str(repo / '.venv'),
           UV_BIN='/usr/local/bin/uv', AUTO_DESIGNER_TASK_REQUIREMENTS=str(build / 'requirements.lock'))
subprocess.run(['bash', str(build / 'setup.sh')], cwd=repo, env=env, check=True)
if not (repo / '.venv/bin/python').is_file():
    raise RuntimeError('task setup did not create its isolated .venv')
Path('/build-state.json').write_text(json.dumps({'instances': {
    spec['id']: {'base_commit': base, 'status': 'ready', 'python': str(repo / '.venv/bin/python')}
}}))
"""


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _read(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise BackendError(f"Expected object in {path.name}")
    return value


def _write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def _command(
    argv: list[str],
    *,
    cwd: Path | None = None,
    timeout: float = 1800,
    env: Mapping[str, str] | None = None,
    log_path: Path | None = None,
) -> str:
    """Capture small replies, or stream a long preparation directly to a private log."""
    execution = {
        "cwd": cwd,
        "env": dict(env) if env is not None else None,
        "text": True,
        "timeout": timeout,
    }
    detail = f"; see {log_path}" if log_path else ""
    try:
        if log_path is None:
            result = subprocess.run(argv, capture_output=True, **execution)
            output = result.stdout
        else:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            # Restrict an existing log before a child can write sensitive output.
            descriptor = os.open(
                log_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600
            )
            with os.fdopen(descriptor, "a", encoding="utf-8") as log:
                os.fchmod(log.fileno(), 0o600)
                log.write(f"[{_now()}] {argv[0]}\n")
                log.flush()
                result = subprocess.run(argv, stdout=log, stderr=subprocess.STDOUT, **execution)
            output = ""  # Preparation callers read the log and do not consume stdout.
    except (OSError, subprocess.TimeoutExpired):
        # TimeoutExpired includes complete argv; provider/bootstrap args can be private.
        raise BackendError(f"Command unavailable or timed out: {argv[0]}" + detail) from None
    if result.returncode:
        raise BackendError(f"{argv[0]} operation failed (exit {result.returncode})" + detail)
    return output.strip()


def _extract(archive: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "r:gz") as bundle:
        for entry in bundle.getmembers():
            relative = Path(entry.name)
            if (
                relative.is_absolute()
                or ".." in relative.parts
                or not (entry.isfile() or entry.isdir())
            ):
                raise BackendError("Unsafe frozen source archive")
        bundle.extractall(destination, filter="data")


def _image(ref: str) -> dict[str, Any]:
    data = json.loads(_command(["docker", "image", "inspect", ref]))
    if not data or not data[0].get("Id"):
        raise BackendError("Docker image inspect returned no immutable image identity")
    return data[0]


def _verify_toolchain(image: str, openagents_source: Path, nexau_revision: str) -> dict[str, Any]:
    """Check installed source/dependency provenance, including caller-supplied images."""
    files = {
        str(path.relative_to(openagents_source)): sha256_file(path)
        for path in (openagents_source / "openagents").rglob("*.py")
        if path.is_file()
    }
    program = """import hashlib,importlib.metadata,json,sys
from pathlib import Path
import openagents
expected=json.loads(sys.argv[1]);root=Path(openagents.__file__).resolve().parent.parent
for relative,digest in expected['files'].items():
    assert hashlib.sha256((root/relative).read_bytes()).hexdigest()==digest, 'OpenAgents source differs: '+relative
pin=json.loads(importlib.metadata.distribution('nexau').read_text('direct_url.json'))['vcs_info']['commit_id']
assert pin==expected['nexau_revision'], 'NexAU source pin differs'
print(json.dumps({'verified':True,'openagents_files':len(expected['files']),'nexau_commit':pin}))
"""
    result = json.loads(
        _command(
            [
                "docker",
                "run",
                "--rm",
                "--network",
                "none",
                image,
                "python",
                "-c",
                program,
                json.dumps({"files": files, "nexau_revision": nexau_revision}),
            ]
        )
    )
    if not result.get("verified") or result.get("nexau_commit") != nexau_revision:
        raise BackendError("Installed Vigil toolchain does not match frozen source pins")
    return result


def prepare_images(
    run_dir: Path, manifest: dict[str, Any], credentials: Mapping[str, str] | None = None
) -> dict[str, Any]:
    """Build/pull fixed runtime images and a frozen host environment, without resources.

    Supplied image references are used only after inspection. Task image overrides
    must expose the runnable seed contract; the actual task base is checked later.
    Build caches are shared by material hashes, never by mutable developer trees.
    """
    root = Path(run_dir).resolve()
    verify_materials(manifest=manifest)
    if manifest["config"]["runtime"]["backend"] != "local":
        raise BackendError("prepare_images requires the local backend")
    _command(["docker", "info", "--format", "{{json .ServerVersion}}"], timeout=30)
    _command(["docker", "compose", "version"], timeout=30)
    source = materialize_controller_source(root, manifest)
    build_log = root / "logs/prepare.log"
    uv = shutil.which("uv")
    if not uv or _command([uv, "--version"]).split()[:2] != ["uv", UV_VERSION]:
        raise BackendError(f"Install uv {UV_VERSION} before preparing the local runtime")
    _command(
        [
            uv,
            "sync",
            "--locked",
            "--python",
            PYTHON_VERSION,
            "--extra",
            "experiments",
            "--extra",
            "dev",
        ],
        cwd=source,
        log_path=build_log,
    )
    python = source / ".venv/bin/python"
    _command(
        [
            str(python),
            "-c",
            f'import sys; assert sys.version.split()[0] == "{PYTHON_VERSION}"; import nexau',
        ]
    )
    context = root / "runtime/image-build"
    context.mkdir(parents=True, exist_ok=True)
    # No provider/model credentials enter the build context or Docker build arguments.
    for key, destination in (
        ("controller_source_archive", "controller"),
        ("openagents_source_archive", "openagents"),
    ):
        target = context / destination
        if target.exists():
            shutil.rmtree(target)
        _extract(material_path(root, manifest, key), target)
    for key, name in (
        ("task_source_archive", "task-source.tar.gz"),
        ("script", "setup.sh"),
        ("requirements_lock", "requirements.lock"),
    ):
        shutil.copyfile(material_path(root, manifest, key), context / name)
    _write(
        context / "task-build.json",
        {
            "id": manifest["task_package"]["id"],
            "source": manifest["task_package"]["source"],
            "files": manifest["task_source_snapshot"]["files"],
        },
    )
    (context / "task-bootstrap.py").write_text(TASK_BOOTSTRAP)
    dockerfile = source / "backend/deploy/vigil/Dockerfile"
    digest = hashlib.sha256(
        json.dumps(
            {
                "recipe": RECIPE_VERSION,
                "dockerfile": sha256_file(dockerfile),
                "bootstrap": hashlib.sha256(TASK_BOOTSTRAP.encode()).hexdigest(),
                "materials": {
                    key: value["sha256"]
                    for key, value in manifest["materials"].items()
                    if key
                    in {
                        "controller_source_archive",
                        "openagents_source_archive",
                        "task_source_archive",
                        "script",
                        "requirements_lock",
                    }
                },
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()[:20]
    options = manifest["config"]["runtime"].get("local") or {}
    images: dict[str, dict[str, Any]] = {}
    for name, target in (("vigil", "unified-vigil"), ("seed", "unified-seed")):
        custom = options.get(name + "_image")
        ref = str(custom or f"auto-designer-{name}:unified-{digest}")
        if custom:
            try:
                info = _image(ref)
            except BackendError:
                _command(["docker", "pull", ref], log_path=build_log)
                info = _image(ref)
        else:
            _command(
                [
                    "docker",
                    "build",
                    "--target",
                    target,
                    "-f",
                    str(dockerfile),
                    "-t",
                    ref,
                    str(context),
                ],
                timeout=3600,
                log_path=build_log,
            )
            info = _image(ref)
        if (
            name == "seed"
            and ((info.get("Config") or {}).get("Labels") or {}).get(
                "org.auto-designer.seed-runtime"
            )
            != "1"
        ):
            raise BackendError("Seed image does not implement runnable seed v1")
        images[name] = {
            "reference": ref,
            "image_id": info["Id"],
            "repo_digests": info.get("RepoDigests") or [],
        }
    for name, default in (("gitea", "gitea/gitea:1.22.6"), ("egress", DEFAULT_EGRESS_IMAGE)):
        ref = str(options.get(name + "_image") or default)
        _command(["docker", "pull", ref], log_path=build_log)
        info = _image(ref)
        images[name] = {
            "reference": ref,
            "image_id": info["Id"],
            "repo_digests": info.get("RepoDigests") or [],
        }
    installed = _verify_toolchain(
        images["vigil"]["image_id"],
        context / "openagents",
        manifest["source_pins"]["nexau"]["revision"],
    )
    capabilities = json.loads(
        _command(
            [
                "docker",
                "run",
                "--rm",
                "--network",
                "none",
                images["vigil"]["image_id"],
                "openagents",
                "observation-capabilities",
                "--json",
            ]
        )
    )
    if "gzip" not in capabilities.get("encodings", []) or "same-origin-v1" not in capabilities.get(
        "download_policies", []
    ):
        raise BackendError("Installed OpenAgents lacks local evidence-reader capabilities")
    result = {
        "recipe": RECIPE_VERSION,
        "recipe_hash": digest,
        "images": images,
        "controller_python": str(python),
        "source_root": str(source),
        "reader_capabilities": capabilities,
        "installed_toolchain": installed,
        "prepared_at": _now(),
    }
    _write(root / "runtime/local-images.json", result)
    return result


def render_egress(config: dict[str, Any], credentials: Mapping[str, str]) -> str:
    """Allow the exact configured model destinations/ports, including HTTP gateways."""
    endpoints: set[tuple[str, int]] = set()
    for model in config["models"].values():
        url = credentials.get(model["base_url_env"], "")
        parsed = urlsplit(url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
        ):
            raise BackendError("A model base URL must be credential-free HTTP(S)")
        host = parsed.hostname
        if not re.fullmatch(r"[A-Za-z0-9.-]+", host):
            raise BackendError("Local egress currently requires an IPv4 address or DNS name")
        endpoints.add((host, parsed.port or (443 if parsed.scheme == "https" else 80)))
    lines = [
        "# Spec-0069/T3: derived from explicit model URL references",
        "http_port 3128",
        "acl CONNECT method CONNECT",
    ]
    ports = sorted({port for _, port in endpoints})
    lines += [
        "acl SSL_ports port " + " ".join(map(str, ports)),
        "http_access deny CONNECT !SSL_ports",
    ]
    for index, (host, port) in enumerate(sorted(endpoints)):
        address_kind = "dst" if re.fullmatch(r"\d+(?:\.\d+){3}", host) else "dstdomain"
        lines += [
            f"acl model_{index} {address_kind} {host}",
            f"acl model_port_{index} port {port}",
            f"http_access allow model_{index} model_port_{index}",
        ]
    lines += [
        "http_access deny all",
        "cache deny all",
        "access_log stdio:/var/log/squid/access.log",
    ]
    return "\n".join(lines) + "\n"


class LocalBackend:
    def __init__(
        self, run_dir: Path, manifest: dict[str, Any], credentials: Mapping[str, str]
    ) -> None:
        self.root = Path(run_dir).resolve()
        self.manifest = manifest
        self.credentials = credentials if isinstance(credentials, dict) else dict(credentials)
        self.run_id = manifest["run_id"]
        self.digest = manifest["config_hash"]
        # Docker projects are lowercase; public run IDs have uppercase UTC T/Z.
        self.project = f"adx-{self.run_id.lower()}-{self.digest[:8]}"[:63]
        self.dest = self.root / "infrastructure"
        self.resources = _read(self.root / "resources.json")
        self.images = _read(self.root / "runtime/local-images.json")
        private = self.root / "secrets/provider.env"
        if not self.credentials.get("GITEA_TOKEN") and private.is_file():
            from dotenv import dotenv_values

            self.credentials.update(
                {
                    key: value
                    for key, value in dotenv_values(private, interpolate=False).items()
                    if value
                }
            )
        self._load_local_login()

    def _load_local_login(self) -> bool:
        """Only a recorded, actually created account supplies browser credentials."""
        from dotenv import dotenv_values

        path = self.root / "secrets/local-gitea-login.env"
        if not path.exists():
            return False
        if path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o077:
            raise BackendError("Local Gitea login file must be a private regular file")
        values = dotenv_values(path, interpolate=False)
        password = values.get("GITEA_PASSWORD")
        if (
            values.get("GITEA_USER") != "experiment"
            or not password
            or "\n" in password
            or "\r" in password
        ):
            raise BackendError("Local Gitea login file has invalid account credentials")
        self.credentials["GITEA_PASSWORD"] = password
        if isinstance(self.resources.get("gitea"), dict):
            self.resources["gitea"]["login_file"] = "secrets/local-gitea-login.env"
        return True

    def _save(self, **changes: Any) -> dict[str, Any]:
        self.resources.update(changes, observed_at=_now())
        _write(self.root / "resources.json", self.resources)
        return self.resources

    def _compose(self, *extra: str) -> str:
        return _command(
            compose_argv(dest=self.dest, project=self.project, extra=list(extra)), timeout=120
        )

    def _inspect_ids(self, kind: str, ids: list[str]) -> list[dict[str, Any]]:
        if not ids:
            return []
        argv = (
            ["docker", "inspect", *ids]
            if kind == "container"
            else ["docker", kind, "inspect", *ids]
        )
        facts = json.loads(_command(argv, timeout=30))
        for fact in facts:
            labels = (
                ((fact.get("Config") or {}).get("Labels") or {})
                if kind == "container"
                else (fact.get("Labels") or {})
            )
            if (
                labels.get(LABEL_EXPERIMENT) != self.run_id
                or labels.get(LABEL_MANIFEST) != self.digest
            ):
                raise BackendError(f"Refusing {kind} with mismatched experiment ownership")
            if labels.get("com.docker.compose.project") not in {None, self.project}:
                raise BackendError("Resource belongs to another Compose project")
        return facts

    def _owned(self, kind: str) -> list[dict[str, Any]]:
        # Query the project as well: unlabelled/colliding resources cannot be ignored.
        argv = ["docker", "ps", "-aq"] if kind == "container" else ["docker", kind, "ls", "-q"]
        compose_ids = _command(
            [*argv, "--filter", f"label=com.docker.compose.project={self.project}"], timeout=30
        ).splitlines()
        owned_ids = _command(
            [*argv, "--filter", f"label={LABEL_EXPERIMENT}={self.run_id}"], timeout=30
        ).splitlines()
        return self._inspect_ids(kind, sorted(set(filter(None, [*compose_ids, *owned_ids]))))

    def _api(
        self,
        method: str,
        endpoint: str,
        *,
        json_data: dict | None = None,
        files: dict | None = None,
    ) -> dict[str, Any]:
        token = self.credentials.get("GITEA_TOKEN", "")
        try:
            response = requests.request(
                method,
                self.resources["gitea"]["url"] + "/api/v1" + endpoint,
                headers={"Authorization": f"token {token}"},
                json=json_data,
                files=files,
                timeout=30,
            )
        except requests.RequestException as exc:
            raise BackendError("Local Gitea request failed") from exc
        if response.status_code == 404:
            return {}
        if response.status_code >= 400:
            raise BackendError(f"Local Gitea API failed (HTTP {response.status_code})")
        return response.json() if response.content else {}

    @staticmethod
    def _loopback_port(url: str, *, path: str = "") -> int:
        try:
            parsed = urlsplit(url)
            if (
                not isinstance(url, str)
                or any(ord(char) < 32 for char in url)
                or parsed.scheme != "http"
                or parsed.hostname != "127.0.0.1"
                or parsed.username is not None
                or parsed.password is not None
                or parsed.query
                or parsed.fragment
                or parsed.path != path
                or parsed.port is None
                or not 1 <= parsed.port <= 65535
            ):
                raise ValueError("unsafe local origin")
            return parsed.port
        except (TypeError, ValueError, AttributeError):
            raise BackendError("Unsafe or mismatched canonical localhost Gitea binding") from None

    def _canonical_host_port(self, previous: dict[str, Any], repository_id: int | None) -> int:
        """Keep the first observed origin; recover old development runs from frozen evidence."""
        prefix = self.manifest["config"]["runtime"]["gitea"]["repository_prefix"]
        repository = f"{prefix}-{self.run_id.lower()}"
        path = f"/api/v1/repos/experiment/{repository}"
        observations = self.root / "data/role_runs" / self.run_id / "observations"
        frozen_ports = []
        for name in (".transport-profile.json", ".framework-contract.json"):
            document = observations / name
            if not document.exists():
                continue
            if document.is_symlink() or not document.resolve().is_relative_to(self.root):
                raise BackendError("Frozen local Gitea binding must remain inside its owned run")
            value = _read(document)
            if name == ".transport-profile.json":
                from auto_designer.observations.transport import validate_transport_profile

                try:
                    validate_transport_profile(value)
                except ValueError:
                    raise BackendError("Invalid frozen local Gitea transport profile") from None
                if value["encoding"] != "gzip" or value["download_policy"] != "same-origin-v1":
                    raise BackendError("Frozen evidence does not describe the local Gitea backend")
            elif value.get("format") != "artifact-observations-v1":
                raise BackendError("Invalid historical local Gitea framework binding")
            frozen_ports.append(self._loopback_port(value.get("repository"), path=path))
        if len(set(frozen_ports)) > 1:
            raise BackendError("Frozen local Gitea evidence origins disagree")
        recorded = previous.get("host_port")
        if recorded is not None and (type(recorded) is not int or not 1 <= recorded <= 65535):
            raise BackendError("Invalid recorded canonical Gitea host port")
        canonical = previous.get("canonical_url")
        if canonical:
            canonical_port = self._loopback_port(canonical)
            if recorded is not None and canonical_port != recorded:
                raise BackendError("Recorded canonical Gitea address and port disagree")
            recorded = canonical_port
        if frozen_ports:
            frozen = frozen_ports[0]
            if recorded is not None and recorded != frozen:
                raise BackendError("Recorded canonical Gitea port differs from frozen evidence")
            if recorded is None and previous.get("url"):
                current = self._loopback_port(previous["url"])
                if current != frozen:
                    # An earlier dynamic Compose restart changed the live mapping.
                    # Restore the original frozen address only after actual identity
                    # and volume ownership have been established through the live origin.
                    if (
                        repository_id is None
                        or previous.get("owner") != "experiment"
                        or previous.get("repo") != repository
                    ):
                        raise BackendError(
                            "Cannot recover a frozen Gitea port without recorded repository identity"
                        )
                    volumes = self._owned("volume")
                    if not any(
                        value.get("Name") == self.project + "_gitea_data" for value in volumes
                    ):
                        raise BackendError(
                            "Cannot recover a frozen Gitea port without the owned data volume"
                        )
                    actual = self._api("GET", path.removeprefix("/api/v1"))
                    description = f"auto-designer experiment {self.run_id} config {self.digest}"
                    if (
                        actual.get("id") != repository_id
                        or actual.get("owner", {}).get("login") != "experiment"
                        or actual.get("description") != description
                    ):
                        raise BackendError(
                            "Live Gitea identity does not authorize recovery of the frozen origin"
                        )
            return frozen
        if recorded is not None:
            return recorded
        return self._loopback_port(previous["url"]) if previous.get("url") else 0

    def provision(self) -> dict[str, Any]:
        if not self.images.get("images"):
            raise BackendError("Local images are not prepared; run prepare first")
        if self.resources.get("resource_state") == "DESTROYED":
            raise BackendError("Destroyed local resources cannot be resumed")
        # Preserve the provider identity through every provisional resource receipt.
        # Older development runs recorded the same identity under repo_id.
        previous_gitea = self.resources.get("gitea") or {}
        recorded_repository_id = previous_gitea.get("repository_id", previous_gitea.get("repo_id"))
        if recorded_repository_id is not None and (
            type(recorded_repository_id) is not int or recorded_repository_id < 1
        ):
            raise BackendError("Invalid recorded local Gitea repository identity")
        # Persist intent before docker creates anything, covering a CLI crash after up.
        self._save(
            backend="local",
            run_id=self.run_id,
            config_hash=self.digest,
            compose_project=self.project,
            resource_state="PROVISIONING",
        )
        self._owned("container")
        self._owned("volume")
        host_port = self._canonical_host_port(previous_gitea, recorded_repository_id)
        if host_port:
            self._save(
                gitea={
                    **previous_gitea,
                    "host_port": host_port,
                    "canonical_url": f"http://127.0.0.1:{host_port}",
                }
            )
        refs = {key: value["image_id"] for key, value in self.images["images"].items()}
        render_stack(
            dest=self.dest,
            experiment_id=self.run_id,
            manifest_sha=self.digest,
            vigil_image=refs["vigil"],
            images=refs,
            gitea_host_port=host_port,
        )
        # render_stack's legacy project casing is irrelevant: all calls pass the
        # canonical v2 project explicitly. Update the env for human inspection too.
        env_file = self.dest / "compose.env"
        text = env_file.read_text()
        text = re.sub(
            r"^COMPOSE_PROJECT_NAME=.*$", "COMPOSE_PROJECT_NAME=" + self.project, text, flags=re.M
        )
        env_file.write_text(text)
        (self.dest / "egress-proxy.conf").write_text(
            render_egress(self.manifest["config"], self.credentials)
        )
        self._owned("container")
        self._owned("volume")
        self._compose("up", "-d", "gitea", "egress-proxy")
        containers = self._owned("container")
        gitea = next(
            (
                value
                for value in containers
                if (value.get("Config") or {}).get("Labels", {}).get("io.openagents.role")
                == "gitea"
            ),
            None,
        )
        if not gitea:
            raise BackendError("Owned Gitea container not found after Compose startup")
        ports = (gitea.get("NetworkSettings") or {}).get("Ports") or {}
        mappings = ports.get("3000/tcp") or []
        mapping = next((item for item in mappings if item.get("HostIp") == "127.0.0.1"), None)
        if not mapping or not str(mapping.get("HostPort", "")).isdigit():
            raise BackendError("Gitea has no verified loopback port mapping")
        actual_port = int(mapping["HostPort"])
        if not 1 <= actual_port <= 65535 or (host_port and actual_port != host_port):
            raise BackendError("Docker did not restore the canonical local Gitea port")
        # Persist the allocation for subsequent up/resume operations, including a
        # crash before the Gitea account/repository bootstrap completes.
        env_file.write_text(
            re.sub(
                r"^GITEA_HOST_PORT=.*$",
                f"GITEA_HOST_PORT={actual_port}",
                env_file.read_text(),
                flags=re.M,
            )
        )
        prefix = self.manifest["config"]["runtime"]["gitea"]["repository_prefix"]
        repository = f"{prefix}-{self.run_id.lower()}"
        self._save(
            container_ids=[value["Id"] for value in containers],
            gitea={
                "url": f"http://127.0.0.1:{actual_port}",
                "canonical_url": f"http://127.0.0.1:{actual_port}",
                "host_port": actual_port,
                "internal_url": "http://gitea:3000",
                "owner": "experiment",
                "repo": repository,
                "container_id": gitea["Id"],
                **(
                    {"repository_id": recorded_repository_id}
                    if recorded_repository_id is not None
                    else {}
                ),
            },
            vigil={
                "mode": "container",
                "container": f"{self.project}-vigil-1",
                "network": f"{self.project}_vigil_net",
                "image": refs["vigil"],
            },
            workspace={
                "kind": "docker-seed",
                "params": {
                    "image": refs["seed"],
                    "instance_id": self.manifest["task_package"]["id"],
                    "harness_python": "/opt/controller/.venv/bin/python",
                    "network": f"{self.project}_vigil_net",
                    "env": {
                        "HTTP_PROXY": "http://egress-proxy:3128",
                        "HTTPS_PROXY": "http://egress-proxy:3128",
                        "NO_PROXY": "gitea,127.0.0.1,localhost",
                    },
                },
            },
            source_root=self.images["source_root"],
            controller_python=self.images["controller_python"],
        )
        self._load_local_login()
        deadline = time.monotonic() + 120
        while True:
            try:
                response = requests.get(
                    self.resources["gitea"]["url"] + "/api/v1/version", timeout=3
                )
                if response.status_code == 200:
                    break
            except requests.RequestException:
                pass
            if time.monotonic() >= deadline:
                raise BackendError("Local Gitea did not become HTTP-ready")
            time.sleep(1)
        if not self.credentials.get("GITEA_TOKEN"):
            self._bootstrap_account(gitea["Id"])
        user = self._api("GET", "/user")
        if user.get("login") != "experiment":
            raise BackendError("Gitea provider credential belongs to a different local identity")
        repo = self._api("GET", f"/repos/experiment/{repository}")
        description = f"auto-designer experiment {self.run_id} config {self.digest}"
        if recorded_repository_id is not None:
            if not repo:
                raise BackendError(
                    "Recorded local Gitea repository is missing; refusing to recreate it during resume"
                )
            if repo.get("id") != recorded_repository_id:
                raise BackendError(
                    "Recorded local Gitea repository was replaced; refusing a different repository identity"
                )
        if not repo:
            repo = self._api(
                "POST",
                "/user/repos",
                json_data={
                    "name": repository,
                    "private": True,
                    "description": description,
                    "auto_init": False,
                },
            )
        if (
            repo.get("description") != description
            or repo.get("owner", {}).get("login") != "experiment"
        ):
            raise BackendError("Existing Gitea repository lacks matching run ownership")
        repository_id = repo.get("id")
        if type(repository_id) is not int or repository_id < 1:
            raise BackendError("Local Gitea repository has no durable provider identity")
        self.resources["gitea"]["repository_id"] = repository_id
        return self._save(resource_state="RUNNING", provisioned_at=_now())

    def _bootstrap_account(self, container: str) -> None:
        import secrets

        prefix = [
            "docker",
            "exec",
            "--user",
            "git",
            container,
            "gitea",
            "--config",
            "/data/gitea/conf/app.ini",
            "admin",
            "user",
        ]
        # Reconciliation after a lost token receipt still reuses the same account.
        users = _command([*prefix, "list"])
        if not re.search(r"\bexperiment\b", users):
            recorded_login = self._load_local_login()
            password = (
                self.credentials["GITEA_PASSWORD"] if recorded_login else secrets.token_hex(32)
            )
            _command(
                [
                    *prefix,
                    "create",
                    "--username",
                    "experiment",
                    "--password",
                    password,
                    "--email",
                    "experiment@localhost.invalid",
                    "--admin",
                    "--must-change-password=false",
                ]
            )
            if not recorded_login:
                # Save the actual successful create password before generating a
                # PAT: a token failure must not lose the browser login on retry.
                login = self.root / "secrets/local-gitea-login.env"
                login.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                login.parent.chmod(0o700)
                with os.fdopen(
                    os.open(login, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w"
                ) as handle:
                    handle.write(f"GITEA_USER=experiment\nGITEA_PASSWORD={password}\n")
                    handle.flush()
                    os.fsync(handle.fileno())
            self._load_local_login()
        else:
            # Existing accounts without a receipt have no known password; never
            # invent one or change their password during recovery.
            self._load_local_login()
        token = _command(
            [
                *prefix,
                "generate-access-token",
                "--username",
                "experiment",
                "--token-name",
                f"run-{self.run_id.lower()}-{secrets.token_hex(4)}",
                "--scopes",
                "all",
                "--raw",
            ]
        )
        if not re.fullmatch(r"[A-Za-z0-9_-]{20,}", token):
            raise BackendError("Gitea returned an invalid generated token")
        path = self.root / "secrets/provider.env"
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as handle:
            handle.write(f"GITEA_TOKEN={token}\n")
        path.chmod(0o600)
        self.credentials["GITEA_TOKEN"] = token

    def preflight(self) -> dict[str, Any]:
        if not self.resources.get("gitea"):
            raise BackendError("Provision local resources before preflight")
        containers = self._owned("container")
        roles = {
            (value.get("Config") or {}).get("Labels", {}).get("io.openagents.role"): value
            for value in containers
        }
        for role in ("gitea", "egress"):
            if not (roles.get(role, {}).get("State") or {}).get("Running"):
                raise BackendError(f"Owned {role} container is not running")
        if self._api("GET", "/user").get("login") != self.resources["gitea"]["owner"]:
            raise BackendError("Local Gitea identity check failed")
        vigil = self.resources["vigil"]
        capabilities = json.loads(
            _command(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--network",
                    "none",
                    vigil["image"],
                    "openagents",
                    "observation-capabilities",
                    "--json",
                ]
            )
        )
        if "gzip" not in capabilities.get(
            "encodings", []
        ) or "same-origin-v1" not in capabilities.get("download_policies", []):
            raise BackendError("Local reader capability check failed")
        # Prove task image HEAD and task environment without invoking a model.
        workspace = self.resources["workspace"]["params"]
        base = _command(
            [
                "docker",
                "run",
                "--rm",
                "--network",
                "none",
                "-w",
                f"/workspace/{workspace['instance_id']}/repo",
                workspace["image"],
                "git",
                "rev-parse",
                "HEAD",
            ]
        )
        expected = self.manifest["task_package"]["source"].get("revision")
        if expected and base != expected:
            raise BackendError("Prepared task image has the wrong upstream base commit")
        _command(
            [
                "docker",
                "run",
                "--rm",
                "--network",
                "none",
                workspace["image"],
                f"/workspace/{workspace['instance_id']}/repo/.venv/bin/python",
                "-c",
                "import sys; print(sys.version)",
            ]
        )
        probe = self._probe()
        return self._save(
            preflight={
                "ok": True,
                "reader_capabilities": capabilities,
                "task_base_commit": base,
                "evidence_probe": probe,
                "checked_at": _now(),
            }
        )

    def _probe(self) -> dict[str, Any]:
        """Publish and read real gzip evidence in an isolated technical repository."""
        import gzip

        name = "preflight-" + self.run_id.lower()
        description = f"auto-designer preflight {self.run_id} config {self.digest}"
        endpoint = f"/repos/experiment/{name}"
        self._save(probe_repository=name, probe_state="PROVISIONING")
        existing = self._api("GET", endpoint)
        if existing:
            if existing.get("description") != description:
                raise BackendError("Probe repository belongs to another owner")
        else:
            self._api(
                "POST",
                "/user/repos",
                json_data={"name": name, "private": True, "description": description},
            )
        try:
            issue = self._api(
                "POST",
                endpoint + "/issues",
                json_data={
                    "title": "[preflight] evidence transport probe",
                    "body": "Technical probe; not simulated user feedback.",
                },
            )
            number = issue["number"]
            marker = "auto-designer:observation-evidence-v1"
            package = {"format": marker, "issue": number, "sessions": []}
            data = gzip.compress(json.dumps(package, sort_keys=True).encode(), mtime=0)
            digest = hashlib.sha256(data).hexdigest()
            asset = self._api(
                "POST",
                endpoint + f"/issues/{number}/assets",
                files={
                    "attachment": (
                        "observation-evidence-" + digest + ".gz",
                        data,
                        "application/gzip",
                    )
                },
            )
            value = {
                "base_url": "http://gitea:3000",
                "owner": "experiment",
                "repo": name,
                "issue": number,
                "asset": asset["id"],
                "sha256": digest,
            }
            program = """import json,sys
from openagents.utils import forge
from openagents.observations.evidence import decode_package
value=json.loads(sys.argv[1])
forge.configure(name='gitea',settings={'base_url':value['base_url'],'owner':value['owner'],'repo':value['repo']})
data=forge.download_observation_asset(number=value['issue'],asset_id=value['asset'],limit=4000000)
package=decode_package(data=data,digest=value['sha256'],issue=value['issue'],encoding='gzip')
print(json.dumps({'status':'verified','issue':package['issue'],'sha256':value['sha256']}))
"""
            result = json.loads(
                _command(
                    [
                        "docker",
                        "run",
                        "--rm",
                        "--network",
                        self.resources["vigil"]["network"],
                        "-e",
                        "GITEA_TOKEN",
                        self.resources["vigil"]["image"],
                        "python",
                        "-c",
                        program,
                        json.dumps(value),
                    ],
                    env={**os.environ, "GITEA_TOKEN": self.credentials["GITEA_TOKEN"]},
                    timeout=60,
                )
            )
            if result.get("status") != "verified" or result.get("sha256") != digest:
                raise BackendError("Actual local reader did not verify the published attachment")
            return result
        finally:
            self._api("DELETE", endpoint)
            self._save(probe_state="REMOVED")

    def _vigil_ready(self) -> bool:
        container = self.resources.get("vigil", {}).get("container")
        for fact in self._owned("container"):
            if fact.get("Name") != "/" + str(container) or not fact.get("State", {}).get("Running"):
                continue
            program = """import os
from pathlib import Path
expected=int(os.environ.get('VIGIL_EXEC_UID','1000'))
def worker(p):
    try:
        command=p.read_bytes()
        uid=next(line.split()[1] for line in (p.parent/'status').read_text().splitlines() if line.startswith('Uid:'))
        return expected>0 and int(uid)==expected and b'openagents' in command and b'vigil' in command
    except (OSError,StopIteration,ValueError): return False
ready=any(worker(p) for p in Path('/proc').glob('[0-9]*/cmdline') if p.parent.name != str(os.getpid()))
assert ready and Path('/work/harness/.openagents/openagents.yml').is_file()
print('ready')
"""
            try:
                return (
                    _command(
                        ["docker", "exec", "--user", "root", fact["Id"], "python", "-c", program],
                        timeout=10,
                    )
                    == "ready"
                )
            except BackendError:
                return False
        return False

    def launch(self, *, mode: str = "fresh") -> dict[str, Any]:
        existing = inspect_controller(self.root)
        if existing.get("running") or existing["state"] == "STOPPING":
            return existing
        env = build_controller_environment(
            run_dir=self.root,
            manifest=self.manifest,
            credentials=self.credentials,
            resources=self.resources,
            mode=mode,
        )
        python = self.resources["controller_python"]
        env["PATH"] = str(Path(python).parent) + os.pathsep + env.get("PATH", "")
        result = launch_controller(
            run_dir=self.root,
            command=controller_command(self.manifest, Path(self.resources["source_root"]), python),
            env=env,
        )
        self._save(controller=result)
        # Spec-0072/T3: one round only evaluates users; neither controller starts
        # Vigil in that case. A successful owned runner needs no delivery receipt.
        if self.manifest["config"]["rounds"]["count"] == 1:
            return result
        deadline = time.monotonic() + 180
        while result.get("running") and time.monotonic() < deadline:
            if self._vigil_ready():
                return {**result, "vigil_ready": True}
            time.sleep(1)
            result = inspect_controller(self.root)
        if not result.get("running"):
            raise BackendError("Controller exited before owned Vigil became ready; inspect logs")
        raise BackendError(
            "Owned Vigil did not become ready within 180s; inspect retained resources"
        )

    def inspect(self) -> dict[str, Any]:
        controller = inspect_controller(self.root)
        try:
            containers = self._owned("container")
        except BackendError as exc:
            return {
                "backend": "local",
                "observation": "UNKNOWN",
                "resource_state": "UNKNOWN",
                "controller": controller,
                "error": str(exc),
                "observed_at": _now(),
            }
        if not self.resources:
            state = "ABSENT"
        elif self.resources.get("resource_state") == "DESTROYED":
            state = "DESTROYED"
        elif not containers:
            state = "LOST"
        else:
            state = (
                "RUNNING"
                if any((value.get("State") or {}).get("Running") for value in containers)
                else "STOPPED"
            )
        vigil = self.resources.get("vigil") or {}
        running_vigil = next(
            (
                value
                for value in containers
                if "/" + str(vigil.get("container")) == value.get("Name")
            ),
            None,
        )
        return {
            **self.resources,
            "resource_state": state,
            "observation": "KNOWN",
            "controller": controller,
            "vigil_running": bool((running_vigil or {}).get("State", {}).get("Running")),
            "observed_at": _now(),
        }

    def _remove_execution_containers(self) -> list[str]:
        removed = []
        for value in self._owned("container"):
            labels = (value.get("Config") or {}).get("Labels") or {}
            if (
                labels.get("auto-designer.session")
                or labels.get("io.auto-designer.run_id") == self.run_id
            ):
                _command(["docker", "rm", "-f", value["Id"]], timeout=30)
                removed.append(value["Id"])
        return removed

    def stop(self, *, grace_seconds: float = 30) -> dict[str, Any]:
        controller = stop_controller(self.root, grace_seconds=grace_seconds)
        if controller.get("running"):
            raise BackendError("Controller remains alive; refusing to stop its infrastructure")
        from auto_designer.experiment.collection import export_gitea_snapshot

        if self.resources.get("gitea"):
            evidence = export_gitea_snapshot(
                run_dir=self.root,
                resources=self.resources,
                credentials=self.credentials,
                terminal=True,
                controller_nonce=controller.get("nonce"),
            )
            if evidence.get("applicable") and not evidence.get("complete"):
                raise BackendError(
                    "Unable to collect terminal Gitea evidence; infrastructure retained"
                )
        removed = self._remove_execution_containers()
        if self.dest.is_dir():
            self._owned("container")
            self._compose("stop")
        self._save(
            resource_state="STOPPED", controller=controller, removed_execution_containers=removed
        )
        return self.inspect()

    def logs(self, *, tail: int = 100, follow: bool = False) -> str:
        return controller_logs(self.root, tail=tail, follow=follow)

    def collect(self) -> dict[str, Any]:
        before = inspect_controller(self.root)
        files_before = self._snapshot_files()
        # The root collector copies the same filesystem and verifies this inventory
        # again. A changing controller snapshot is explicitly best effort.
        after = inspect_controller(self.root)
        files_after = self._snapshot_files()
        terminal = after["state"] in {"EXITED", "STOPPED"} and not after.get("running")
        return {
            "snapshot_dir": str(self.root),
            "controller": after,
            "consistent": files_before == files_after and before.get("nonce") == after.get("nonce"),
            "terminal": terminal,
            "files": files_after,
            "collected_at": _now(),
        }

    def _snapshot_files(self) -> dict[str, str]:
        values = {}
        for directory in ("checkpoints", "data", "logs", "telemetry", "runtime"):
            for path in (self.root / directory).rglob("*"):
                relative = path.relative_to(self.root)
                if (
                    path.is_file()
                    and not path.is_symlink()
                    and not any(
                        part
                        in {
                            ".venv",
                            ".git",
                            ".openagents",
                            "image-build",
                            "vigil-config",
                            "cloud-snapshot",
                        }
                        for part in relative.parts
                    )
                ):
                    if (
                        path.suffix != ".lock"
                        and path.name
                        not in {
                            "controller-context.json",
                            "monitor.log",
                            "collector.log",
                            "collection.json",
                            "collection-receipt.json",
                            "monitor.json",
                            "monitor.pid",
                        }
                        and not any(part.startswith("collection-stage-") for part in relative.parts)
                    ):
                        values[str(relative)] = sha256_file(path)
        return values

    def destroy(self) -> dict[str, Any]:
        if inspect_controller(self.root).get("running"):
            raise BackendError("Stop the owned controller before destroying local compute")
        self._owned("container")
        self._owned("network")
        volumes = self._owned("volume")
        self._remove_execution_containers()
        if self.dest.is_dir():
            # No --volumes: these contain the local Gitea experiment repository.
            self._compose("down", "--remove-orphans")
        return self._save(
            resource_state="DESTROYED",
            destroyed_at=_now(),
            retained_volumes=[value["Name"] for value in volumes],
            repository_retained=True,
        )
