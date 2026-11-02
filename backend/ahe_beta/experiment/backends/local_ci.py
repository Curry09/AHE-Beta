"""Spec-0077/T2: private registration and real PR readiness for an owned runner.

The backend supplies Docker and forge operations; this module never imports the
backend or controller context. Runner credentials stay in its private volume.
"""

from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import time
from datetime import UTC, datetime
from typing import Any

from ahe_beta.experiment.backends.base import BackendError

DEFAULT_RUNNER_IMAGE = "gitea/act_runner:0.2.11"
DEFAULT_DAEMON_IMAGE = "docker:27.5.1-dind"
DEFAULT_JOB_IMAGE = (
    "catthehacker/ubuntu@sha256:05207c9c141931a00844d6349c5aace750b26d1339212087fcfd90f8efde5c71"
)
EXPERIMENT_LABEL = "io.openagents.experiment_id"
MANIFEST_LABEL = "io.openagents.manifest_sha"
ROLE_LABEL = "io.openagents.role"
JOB_ROLE = "ci-job"
READINESS_TIMEOUT = 600

PROBE_WORKFLOW = """name: ci-readiness
on:
  push:
    branches: [main]
  pull_request:
jobs:
  smoke:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: python3 -m py_compile probe.py
"""


def enabled(manifest: dict[str, Any]) -> bool:
    return manifest["config"]["runtime"].get("local", {}).get("ci_enabled") is True


def compose_service() -> str:
    """Rendered only for opt-in runs; no secret environment substitutions."""
    return """
  ci-daemon:
    image: ${CI_DAEMON_IMAGE}
    restart: unless-stopped
    privileged: true
    command: [--tls=false]
    environment:
      DOCKER_TLS_CERTDIR: ""
    labels:
      io.openagents.experiment_id: "${EXPERIMENT_ID}"
      io.openagents.manifest_sha: "${MANIFEST_SHA}"
      io.openagents.role: ci-daemon
    volumes:
      - ci_docker_data:/var/lib/docker
    networks:
      - ci

  act-runner:
    image: ${RUNNER_IMAGE}
    restart: unless-stopped
    working_dir: /data
    entrypoint: [act_runner]
    command: [daemon, --config, /runner-config.yaml]
    environment:
      DOCKER_HOST: tcp://ci-daemon:2375
    labels:
      io.openagents.experiment_id: "${EXPERIMENT_ID}"
      io.openagents.manifest_sha: "${MANIFEST_SHA}"
      io.openagents.role: ci-runner
    volumes:
      - runner_data:/data
      - ./runner-config.yaml:/runner-config.yaml:ro
    networks:
      - ci

"""


def write_config(backend: Any) -> None:
    labels = {
        EXPERIMENT_LABEL: backend.run_id,
        MANIFEST_LABEL: backend.digest,
        ROLE_LABEL: JOB_ROLE,
    }
    data = {
        "log": {"level": "warn"},
        "runner": {
            "file": ".runner",
            "capacity": 1,
            "timeout": "20m",
            "shutdown_timeout": "10s",
            "labels": ["ubuntu-latest:docker://" + backend.images["images"]["ci_job"]["image_id"]],
        },
        "cache": {"enabled": False},
        "container": {
            # Host refers to the private daemon's network namespace, not the
            # user's Docker host. Global act names/toolcache stay inside it.
            "network": "host",
            "options": " ".join("--label " + key + "=" + value for key, value in labels.items()),
            "privileged": False,
            "valid_volumes": [],
            "docker_host": "-",
            "force_pull": False,
        },
    }
    (backend.dest / "runner-config.yaml").write_text(json.dumps(data, indent=2) + "\n")


def _private_command(argv: list[str], *, input_text: str | None) -> str:
    """Never interpolate captured private output into an exception or a log."""
    try:
        result = subprocess.run(argv, input=input_text, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:
        raise BackendError("Private CI registration operation failed") from exc
    if result.returncode:
        raise BackendError("Private CI registration operation failed")
    return result.stdout


def _compose_argv(backend: Any, *extra: str) -> list[str]:
    from ahe_beta.experiment.infrastructure import compose_argv

    return compose_argv(dest=backend.dest, project=backend.project, extra=list(extra))


def _registration(backend: Any, *, container_id: str | None) -> dict[str, Any] | None:
    # A shell prints no data for the unregistered case. Successful output is
    # intentionally private: the registration JSON also contains a bearer token.
    argv = (
        ["docker", "exec", container_id, "cat", "/data/.runner"]
        if container_id
        else _compose_argv(
            backend,
            "run",
            "--rm",
            "--no-deps",
            "-T",
            "--entrypoint",
            "/bin/sh",
            "act-runner",
            "-c",
            "if test -f /data/.runner; then cat /data/.runner; fi",
        )
    )
    raw = _private_command(argv, input_text=None)
    if not raw.strip():
        return None
    try:
        value = json.loads(raw)
    except ValueError as exc:
        raise BackendError("Invalid private runner registration") from exc
    expected_labels = ["ubuntu-latest:docker://" + backend.images["images"]["ci_job"]["image_id"]]
    if (
        type(value.get("id")) is not int
        or value["id"] < 1
        or value.get("name") != backend.project + "-ci"
        or str(value.get("address", "")).rstrip("/") != "http://gitea:3000"
        or value.get("labels") != expected_labels
    ):
        raise BackendError("Private runner registration identity or labels changed")
    previous = (backend.resources.get("ci") or {}).get("runner") or {}
    if previous.get("id") is not None and previous["id"] != value["id"]:
        raise BackendError("Registered CI runner identity changed")
    return {"id": value["id"], "name": value["name"]}


def _daemon(backend: Any) -> dict[str, Any]:
    """Every nested Docker operation first verifies the outer owned daemon."""
    ci = backend.resources.get("ci") or {}
    recorded = ci.get("daemon") or {}
    daemon = next(
        (
            item
            for item in backend._owned("container")
            if item.get("Id") == recorded.get("container_id")
        ),
        None,
    )
    if not daemon or not daemon.get("State", {}).get("Running"):
        raise BackendError("Owned private CI Docker daemon is not running")
    labels = daemon.get("Config", {}).get("Labels", {})
    mounts = daemon.get("Mounts", [])
    if (
        daemon.get("Image") != recorded.get("image_id")
        or labels.get(EXPERIMENT_LABEL) != backend.run_id
        or labels.get(MANIFEST_LABEL) != backend.digest
        or labels.get(ROLE_LABEL) != "ci-daemon"
        or recorded.get("network") != backend.project + "_ci"
        or recorded["network"] not in daemon.get("NetworkSettings", {}).get("Networks", {})
        or not any(
            mount.get("Name") == backend.project + "_ci_docker_data"
            and mount.get("Destination") == "/var/lib/docker"
            for mount in mounts
        )
    ):
        raise BackendError("Private CI Docker daemon identity changed")
    return daemon


def _docker(backend: Any, *args: str) -> str:
    daemon = _daemon(backend)
    return backend._ci_command(["docker", "exec", daemon["Id"], "docker", *args])


def _load_job_image(backend: Any) -> None:
    """Stream the frozen host image into its private daemon without buffering it."""
    image_id = backend.resources["ci"]["job_image_id"]
    daemon = _daemon(backend)
    present = _docker(backend, "image", "ls", "--no-trunc", "-q").splitlines()
    if image_id not in present:
        producer = subprocess.Popen(
            ["docker", "image", "save", image_id], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
        )
        try:
            result = subprocess.run(
                ["docker", "exec", "-i", daemon["Id"], "docker", "image", "load"],
                stdin=producer.stdout,
                capture_output=True,
                timeout=180,
            )
            producer.stdout.close()
            if result.returncode or producer.wait(timeout=30):
                raise BackendError(
                    "Frozen CI job image could not be loaded into its private daemon"
                )
        except (OSError, subprocess.SubprocessError) as exc:
            raise BackendError("Frozen CI job image import failed") from exc
        finally:
            if producer.poll() is None:
                producer.kill()
                producer.wait()
    facts = json.loads(_docker(backend, "image", "inspect", image_id))
    if len(facts) != 1 or facts[0].get("Id") != image_id:
        raise BackendError("Private CI daemon job image differs from the prepared image")


def _provision_daemon(backend: Any) -> None:
    ci = dict(backend.resources["ci"])
    image_id = backend.images["images"]["ci_daemon"]["image_id"]
    old = ci.get("daemon") or {}
    if old.get("image_id") and old["image_id"] != image_id:
        raise BackendError("Private CI daemon image changed during recovery")
    backend._compose("up", "-d", "ci-daemon")
    actual = next(
        (
            item
            for item in backend._owned("container")
            if item.get("Config", {}).get("Labels", {}).get(ROLE_LABEL) == "ci-daemon"
        ),
        None,
    )
    if not actual:
        raise BackendError("Owned private CI daemon was not created")
    if old.get("container_id") and old["container_id"] != actual["Id"]:
        raise BackendError("Original private CI daemon container was replaced")
    ci.update(
        daemon={
            "container_id": actual["Id"],
            "image_id": image_id,
            "network": backend.project + "_ci",
            "storage_volume": backend.project + "_ci_docker_data",
        },
        topology="private-docker-daemon-v1",
        job_network="host",
    )
    backend._save(ci=ci)
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        try:
            info = json.loads(_docker(backend, "info", "--format", "{{json .ServerVersion}}"))
            if isinstance(info, str) and info:
                break
        except (BackendError, ValueError):
            pass
        time.sleep(1)
    else:
        raise BackendError("Private CI Docker daemon did not become ready within 90 seconds")
    _load_job_image(backend)


def provision(backend: Any) -> dict[str, Any]:
    previous = backend.resources.get("ci") or {}
    if previous and (
        previous.get("run_id") != backend.run_id or previous.get("config_hash") != backend.digest
    ):
        raise BackendError("CI receipt belongs to a different experiment")
    images = backend.images.get("images", {})
    if any(not images.get(key, {}).get("image_id") for key in ("runner", "ci_job", "ci_daemon")):
        raise BackendError("CI images were not frozen during preparation")
    for key in ("runner", "ci_job", "ci_daemon"):
        fact = json.loads(
            backend._ci_command(["docker", "image", "inspect", images[key]["image_id"]])
        )
        if len(fact) != 1 or fact[0].get("Id") != images[key]["image_id"]:
            raise BackendError("Prepared CI image is missing or changed")
    ci = {
        **previous,
        "enabled": True,
        "state": "REGISTERING",
        "run_id": backend.run_id,
        "config_hash": backend.digest,
        "network": backend.project + "_ci",
        "job_image_id": images["ci_job"]["image_id"],
    }
    if previous.get("job_image_id") and previous["job_image_id"] != ci["job_image_id"]:
        raise BackendError("CI job image changed during recovery")
    previous_runner = previous.get("runner") or {}
    if (
        previous_runner.get("image_id")
        and previous_runner["image_id"] != images["runner"]["image_id"]
    ):
        raise BackendError("CI runner image changed during recovery")
    backend._save(ci=ci)
    write_config(backend)
    _provision_daemon(backend)
    ci = dict(backend.resources["ci"])
    registration = _registration(backend, container_id=None)
    if registration is None:
        if previous_runner.get("id"):
            raise BackendError("Original private runner registration is missing")
        gitea_id = backend.resources["gitea"]["container_id"]
        token = _private_command(
            [
                "docker",
                "exec",
                "--user",
                "git",
                gitea_id,
                "gitea",
                "--config",
                "/data/gitea/conf/app.ini",
                "actions",
                "generate-runner-token",
            ],
            input_text=None,
        ).strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]+", token):
            raise BackendError("Gitea did not generate a valid private runner token")
        script = (
            "IFS= read -r registration_token; "
            "act_runner register --no-interactive --config /runner-config.yaml "
            '--instance http://gitea:3000 --name "$1" --labels "$2" '
            '--token "$registration_token" >/dev/null 2>&1'
        )
        _private_command(
            _compose_argv(
                backend,
                "run",
                "--rm",
                "--no-deps",
                "-T",
                "--entrypoint",
                "/bin/sh",
                "act-runner",
                "-c",
                script,
                "register",
                backend.project + "-ci",
                "ubuntu-latest:docker://" + ci["job_image_id"],
            ),
            input_text=token + "\n",
        )
        registration = _registration(backend, container_id=None)
        if registration is None:
            raise BackendError("CI runner registration did not persist")
    backend._compose("up", "-d", "act-runner")
    containers = backend._owned("container")
    runner = next(
        (
            item
            for item in containers
            if item.get("Config", {}).get("Labels", {}).get(ROLE_LABEL) == "ci-runner"
        ),
        None,
    )
    if not runner or not runner.get("State", {}).get("Running"):
        raise BackendError("Owned CI runner did not start")
    if previous_runner.get("container_id") and previous_runner["container_id"] != runner["Id"]:
        raise BackendError("Original CI runner container was replaced")
    if runner.get("Image") != images["runner"]["image_id"] or ci["network"] not in runner.get(
        "NetworkSettings", {}
    ).get("Networks", {}):
        raise BackendError("CI runner image or network changed")
    ci.update(
        state="REGISTERED",
        runner={
            **registration,
            "container_id": runner["Id"],
            "image_id": images["runner"]["image_id"],
        },
    )
    return backend._save(ci=ci)


def _wait_status(
    backend: Any, prefix: str, sha: str, expected: str, deadline: float
) -> dict[str, Any]:
    if not re.fullmatch(r"[a-f0-9]{40}", sha):
        raise BackendError("CI probe did not produce an immutable head SHA")
    while time.monotonic() < deadline:
        status = backend._api("GET", prefix + "/commits/" + sha + "/status")
        rows = status.get("statuses") or []
        state = str(status.get("state", "")).lower()
        if rows and state == expected:
            return {
                "head_sha": sha,
                "status_count": len(rows),
                "state": state,
                "checked_at": datetime.now(UTC).isoformat(),
                "statuses": [
                    {
                        key: row[key]
                        for key in ("context", "status", "target_url", "created_at")
                        if key in row
                    }
                    for row in rows
                    if isinstance(row, dict)
                ],
            }
        if rows and state in {"failure", "error"} and expected == "success":
            raise BackendError("Real CI readiness smoke failed; inspect retained CI diagnostics")
        jobs(backend)
        time.sleep(2)
    raise BackendError("Real CI readiness timed out without the expected current-head status")


def _reader_environment(backend: Any) -> str:
    """Docker env files use literal values, unlike shell-quoted dotenv receipts."""
    token = backend.credentials.get("GITEA_TOKEN")
    if not isinstance(token, str) or not token or any(char in token for char in "\r\n\x00"):
        raise BackendError("CI reader requires a valid private Gitea token")
    directory = backend.root / "secrets"
    if directory.is_symlink():
        raise BackendError("CI reader secrets directory must not be a symbolic link")
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    directory.chmod(0o700)
    path = directory / "ci-reader.env"
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            os.fchmod(handle.fileno(), 0o600)
            handle.write("GITEA_TOKEN=" + token + "\n")
    except OSError as exc:
        raise BackendError("CI reader private environment could not be written") from exc
    return str(path)


def _reader_status(
    backend: Any, repo: str, pull: int, evidence: dict[str, Any], *, deadline: float
) -> dict[str, Any]:
    """Ask the frozen OpenAgents consumer how it classifies this actual PR head."""
    program = """import json,sys
from openagents.utils import forge
from openagents.recipes.vigil import _ci_state
value=json.loads(sys.argv[1])
forge.configure(name='gitea',settings={'base_url':'http://gitea:3000','owner':value['owner'],'repo':value['repo']})
snapshot=forge.check_snapshot(pr_number=value['pull'])
head=forge.pr_snapshot(pr_number=value['pull']).head_sha
print(json.dumps({'head_sha':head,'state':snapshot.state,'status_count':snapshot.count,'ci_state':_ci_state(snapshot=snapshot)}))
"""
    argv = [
        "docker",
        "run",
        "--rm",
        "--network",
        backend.project + "_ci",
        "--env-file",
        _reader_environment(backend),
        "--label",
        EXPERIMENT_LABEL + "=" + backend.run_id,
        "--label",
        MANIFEST_LABEL + "=" + backend.digest,
        "--label",
        "io.ahe-beta.run_id=" + backend.run_id,
        backend.images["images"]["vigil"]["image_id"],
        "python",
        "-c",
        program,
        json.dumps({"owner": backend.resources["gitea"]["owner"], "repo": repo, "pull": pull}),
    ]
    expected = "pass" if evidence["state"] == "success" else "fail"
    while time.monotonic() < deadline:
        raw = json.loads(backend._ci_command(argv))
        result = {key: raw.get(key) for key in ("head_sha", "state", "status_count", "ci_state")}
        ci = dict(backend.resources.get("ci") or {})
        ci["reader_observation"] = {
            **result,
            "expected_head_sha": evidence["head_sha"],
            "expected_state": evidence["state"],
            "checked_at": datetime.now(UTC).isoformat(),
        }
        backend._save(ci=ci)
        if result["head_sha"] != evidence["head_sha"]:
            raise BackendError(
                "Frozen OpenAgents reader did not confirm the actual PR CI status: head changed"
            )
        count = result["status_count"]
        if type(count) is not int or count < 0:
            raise BackendError("Frozen OpenAgents reader returned an invalid status count")
        if count > 0 and result["state"] == expected and result["ci_state"] == evidence["state"]:
            return result
        if count == 0 or result["ci_state"] in {"pending", "none"}:
            time.sleep(min(2, max(0, deadline - time.monotonic())))
            continue
        raise BackendError(
            "Frozen OpenAgents reader did not confirm the actual PR CI status: terminal classification disagrees"
        )
    raise BackendError(
        "Frozen OpenAgents reader did not confirm the actual PR CI status before the readiness deadline"
    )


def readiness(backend: Any, *, timeout: float = READINESS_TIMEOUT) -> dict[str, Any]:
    """Real main, red PR, and repaired PR head checks within one bounded deadline."""
    ci = dict(backend.resources["ci"])
    ci["state"] = "CHECKING"
    backend._save(ci=ci)
    deadline = time.monotonic() + min(timeout, READINESS_TIMEOUT)
    owner = backend.resources["gitea"]["owner"]
    name = backend.project + "-ci-probe"
    prefix = "/repos/" + owner + "/" + name
    description = "ahe-beta CI probe " + backend.run_id + " " + backend.digest
    try:
        repo = backend._api("GET", prefix)
        if repo:
            if (
                repo.get("description") != description
                or repo.get("owner", {}).get("login") != owner
            ):
                raise BackendError("CI probe repository is not owned by this run")
            recorded = ci.get("probe", {}).get("repository_id")
            if recorded is not None and repo.get("id") != recorded:
                raise BackendError("Recorded CI probe repository identity changed")
            backend._api("DELETE", prefix)
        repo = backend._api(
            "POST",
            "/user/repos",
            json_data={
                "name": name,
                "private": True,
                "auto_init": True,
                "default_branch": "main",
                "description": description,
            },
        )
        ci["probe"] = {"repo": name, "repository_id": repo["id"], "state": "CREATED"}
        backend._save(ci=ci)

        def put(path: str, content: str, branch: str, *, update: bool = False) -> dict:
            data = {
                "content": base64.b64encode(content.encode()).decode(),
                "branch": branch,
                "message": "CI readiness technical probe",
            }
            if update:
                data["sha"] = backend._api("GET", prefix + "/contents/" + path + "?ref=" + branch)[
                    "sha"
                ]
            return backend._api(
                "PUT" if update else "POST", prefix + "/contents/" + path, json_data=data
            )

        put("probe.py", "print('ci readiness')\n", "main")
        main = put(".gitea/workflows/probe.yml", PROBE_WORKFLOW, "main")
        main_evidence = _wait_status(backend, prefix, main["commit"]["sha"], "success", deadline)
        ci = dict(backend.resources["ci"])
        ci["readiness"] = {"main": main_evidence}
        backend._save(ci=ci)
        backend._api(
            "POST",
            prefix + "/branches",
            json_data={"new_branch_name": "readiness", "old_ref_name": "main"},
        )
        put("probe.py", "this is deliberately invalid Python !!!\n", "readiness", update=True)
        pull = backend._api(
            "POST",
            prefix + "/pulls",
            json_data={
                "title": "CI readiness red/green probe",
                "head": "readiness",
                "base": "main",
            },
        )
        pull_path = prefix + "/pulls/" + str(pull["number"])
        red = _wait_status(backend, prefix, pull["head"]["sha"], "failure", deadline)
        red["reader"] = _reader_status(backend, name, pull["number"], red, deadline=deadline)
        ci = dict(backend.resources["ci"])
        ci["readiness"]["failed_pr"] = red
        backend._save(ci=ci)
        put("probe.py", "print('ci repaired readiness')\n", "readiness", update=True)
        # Re-read forge head; never treat an old green commit as a new PR's proof.
        pull = backend._api("GET", pull_path)
        green = _wait_status(backend, prefix, pull["head"]["sha"], "success", deadline)
        green["reader"] = _reader_status(backend, name, pull["number"], green, deadline=deadline)
        current = backend._api("GET", pull_path)
        if current["head"]["sha"] != green["head_sha"]:
            raise BackendError("CI probe head changed while checking readiness")
        ci = dict(backend.resources["ci"])
        ci.update(
            state="READY",
            readiness={
                **green,
                "main": main_evidence,
                "failed_pr": red,
                "pull_number": pull["number"],
            },
        )
        backend._api("DELETE", prefix)
        ci["probe"]["state"] = "REMOVED"
        return backend._save(ci=ci)
    except Exception:
        ci = dict(backend.resources["ci"])
        ci["state"] = "FAILED"
        backend._save(ci=ci)
        raise


def jobs(backend: Any) -> list[dict[str, Any]]:
    """Inspect jobs inside the verified private daemon, never the host namespace."""
    ids = _docker(backend, "ps", "--no-trunc", "-aq").splitlines()
    selected = []
    for identifier in ids:
        try:
            facts = json.loads(_docker(backend, "inspect", identifier))
        except BackendError:
            # act_runner automatically removes completed jobs. Only a fresh,
            # successful daemon observation authorizes skipping a vanished ID.
            if identifier not in _docker(backend, "ps", "--no-trunc", "-aq").splitlines():
                continue
            raise
        if not isinstance(facts, list) or len(facts) != 1 or facts[0].get("Id") != identifier:
            raise BackendError("Private CI job inspection returned an invalid identity")
        selected.append(facts[0])
    for item in selected:
        labels = item.get("Config", {}).get("Labels", {})
        if (
            labels.get(EXPERIMENT_LABEL) != backend.run_id
            or labels.get(MANIFEST_LABEL) != backend.digest
            or labels.get(ROLE_LABEL) != JOB_ROLE
            or item.get("HostConfig", {}).get("NetworkMode") != "host"
        ):
            raise BackendError("Private CI job ownership or network changed")
    ci = dict(backend.resources["ci"])
    ci.update(job_container_ids=[item["Id"] for item in selected])
    backend._save(ci=ci)
    return selected


def inspect(backend: Any, containers: list[dict]) -> dict[str, Any]:
    """Observe original runner and private daemon identities before trusting READY."""
    ci = dict(backend.resources.get("ci") or {})
    recorded = ci.get("runner") or {}
    runner = next((item for item in containers if item["Id"] == recorded.get("container_id")), None)
    ci["runner_running"] = bool((runner or {}).get("State", {}).get("Running"))
    daemon = next(
        (item for item in containers if item.get("Id") == ci.get("daemon", {}).get("container_id")),
        None,
    )
    ci["daemon_running"] = bool((daemon or {}).get("State", {}).get("Running"))
    if not ci["runner_running"] or not ci["daemon_running"]:
        if ci.get("state") == "READY":
            ci["state"] = "UNAVAILABLE"
        return ci
    _daemon(backend)
    if (
        runner.get("Image") != recorded.get("image_id")
        or ci.get("network") not in runner.get("NetworkSettings", {}).get("Networks", {})
        or runner.get("Config", {}).get("Labels", {}).get(ROLE_LABEL) != "ci-runner"
    ):
        raise BackendError("Recorded CI runner container identity changed")
    registration = _registration(backend, container_id=runner["Id"])
    if not registration or registration["id"] != recorded.get("id"):
        raise BackendError("Recorded CI runner private identity changed")
    return ci


def stop(backend: Any) -> dict[str, Any]:
    """Stop scheduling and clear jobs/caches exclusively inside this run's daemon."""
    backend._compose("stop", "-t", "15", "act-runner")
    recorded = backend.resources.get("ci", {}).get("daemon") or {}
    actual = next(
        (
            item
            for item in backend._owned("container")
            if item.get("Id") == recorded.get("container_id")
        ),
        None,
    )
    removed_volumes = []
    if actual and actual.get("State", {}).get("Running"):
        for item in jobs(backend):
            try:
                _docker(backend, "rm", "-f", "-v", item["Id"])
            except BackendError:
                if item["Id"] in _docker(backend, "ps", "--no-trunc", "-aq").splitlines():
                    raise
        if _docker(backend, "ps", "--no-trunc", "-aq").strip():
            raise BackendError("Private CI jobs remained after stopping; resources retained")
        # act-toolcache and workspace names are unlabelled in act_runner 0.2.11.
        # Their namespace belongs entirely to the verified per-run daemon.
        for volume in _docker(backend, "volume", "ls", "-q").splitlines():
            if _docker(backend, "ps", "-aq", "--filter", "volume=" + volume).strip():
                raise BackendError("Private CI volume remains in use")
            try:
                _docker(backend, "volume", "rm", volume)
            except BackendError:
                if volume in _docker(backend, "volume", "ls", "-q").splitlines():
                    raise
            removed_volumes.append(volume)
    ci = dict(backend.resources["ci"])
    ci.update(
        state="STOPPED",
        job_container_ids=[],
        removed_job_volumes=removed_volumes,
        retained_job_volumes=[],
        retained_runner_volume=backend.project + "_runner_data",
    )
    return backend._save(ci=ci)


def destroy_storage(backend: Any) -> None:
    """Remove only labelled private Docker storage after its daemon is removed."""
    volume_name = backend.project + "_ci_docker_data"
    for fact in backend._owned("volume"):
        if fact.get("Name") != volume_name:
            continue
        labels = fact.get("Labels") or {}
        if (
            labels.get(EXPERIMENT_LABEL) != backend.run_id
            or labels.get(MANIFEST_LABEL) != backend.digest
        ):
            raise BackendError("Private CI Docker storage ownership changed")
        consumers = backend._ci_command(
            ["docker", "ps", "-aq", "--filter", "volume=" + volume_name]
        )
        if consumers.strip():
            raise BackendError("Private CI Docker storage is still in use")
        backend._ci_command(["docker", "volume", "rm", volume_name])
    ci = dict(backend.resources["ci"])
    ci.update(state="DESTROYED", private_docker_storage_destroyed=True)
    backend._save(ci=ci)
