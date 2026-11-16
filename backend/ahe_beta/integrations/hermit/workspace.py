"""Native AHE workspace operations over the host's run/read/write boundary."""

from __future__ import annotations

import base64
import hashlib
import inspect
import json
import os
import shlex
import subprocess
from pathlib import Path, PurePosixPath

from ahe_beta.user.sim.runtime import (
    InvalidWorkspaceArtifact,
    _capture_patch_base,
    _prediction_patch_argv,
    list_review_files,
    read_bounded_file,
    utc_now,
)


class RemoteWorkspace:
    def __init__(self, workspace, *, cwd, runtime_id, patch, finalize, services, artifact_root):
        if (
            not runtime_id
            or PurePosixPath(runtime_id).name != runtime_id
            or runtime_id in {".", ".."}
        ):
            raise ValueError("invalid runtime identity")
        self.transport = workspace
        self.cwd = cwd
        self.runtime_id = runtime_id
        self.finalize = finalize
        self.services = services
        self.artifact_root = Path(artifact_root)
        self._sealed_at = None
        self.evidence = {
            "kind": "external",
            "runtime_id": runtime_id,
            "cwd": cwd,
            "started_at": utc_now(),
            "patch_capability": patch,
        }
        self._patch_base_commit = None
        self._patch_base_failed = False
        self._closed = False

    def _exec(self, argv):
        if self._closed:
            raise RuntimeError("workspace capability is closed")
        result = self.transport.run(shlex.join(argv), timeout=60, cwd=self.cwd)
        return subprocess.CompletedProcess(argv, result["code"], result["stdout"], result["stderr"])

    def resolve(self, path):
        relative = PurePosixPath(path)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("workspace path must be relative")
        return str(PurePosixPath(self.cwd) / relative)

    def read_text(self, path):
        return self.transport.read(self.resolve(path))

    def write_text(self, path, content):
        target = self.resolve(path)
        self.transport.write(target, content)
        return target

    def run(self, cmd, timeout=10.0):
        if self._closed:
            raise RuntimeError("workspace capability is closed")
        started = utc_now()
        result = self.transport.run(cmd, timeout=timeout, cwd=self.cwd)
        return {
            "ok": True,
            "status": "completed",
            "returncode": result["code"],
            "stdout": result["stdout"][:20000],
            "stderr": result["stderr"][:20000],
            "started_at": started,
            "finished_at": utc_now(),
        }

    def list_files(self, path="."):
        result = self._exec(["ls", "-la", self.resolve(path)])
        if result.returncode:
            raise OSError(result.stderr)
        return result.stdout

    def read_diff(self):
        return self.export_patch()[0]

    def review_file_listing(self):
        script = (
            inspect.getsource(list_review_files)
            + "\nimport json; print(json.dumps(list_review_files(root="
            + repr(self.cwd)
            + ", max_output=20000)))"
        )
        result = self._exec(["python3", "-c", script])
        if result.returncode:
            raise RuntimeError(result.stderr)
        return json.loads(result.stdout)

    def freeze_patch_base(self):
        if self.evidence["patch_capability"] == "git":
            _capture_patch_base(self, self._exec)

    def export_patch(self):
        if self.evidence["patch_capability"] != "git":
            return "", hashlib.sha256(b"").hexdigest()
        if self._patch_base_failed:
            raise RuntimeError("original patch base is unavailable")
        result = self._exec(_prediction_patch_argv(self._patch_base_commit))
        if result.returncode == 128:
            raise InvalidWorkspaceArtifact("Actor no longer supplies a valid Git artifact")
        if result.returncode:
            raise RuntimeError(result.stderr)
        digest = hashlib.sha256(result.stdout.encode()).hexdigest()
        self.evidence.update(diff_sha256=digest, diff_bytes=len(result.stdout.encode()))
        return result.stdout, digest

    def export_file(self, path, max_bytes):
        # Send the controller's bounded reader; never execute a task-supplied exporter.
        script = (
            "import os,stat,base64\nfrom pathlib import PurePosixPath\n"
            + inspect.getsource(read_bounded_file)
            + "\ntry:\n print(base64.b64encode(read_bounded_file("
            + repr(self.cwd)
            + ","
            + repr(path)
            + ","
            + str(max_bytes)
            + ")).decode())\n"
            + "except Exception as e:\n print(type(e).__name__); raise SystemExit(1)\n"
        )
        result = self._exec(["python3", "-c", script])
        if result.returncode:
            errors = {
                "FileNotFoundError": FileNotFoundError,
                "OverflowError": OverflowError,
                "ValueError": ValueError,
            }
            raise errors.get(result.stdout.strip(), RuntimeError)(path)
        return base64.b64decode(result.stdout.strip(), validate=True)

    def quiesce(self):
        self.transport.quiesce()
        self.evidence["quiesced_at"] = utc_now()

    def _service_output(self, handle):
        if self._sealed_at is None:
            raise RuntimeError("service outputs have not been finalized")
        for service in self.services:
            for output in service.get("exports", []):
                if output["handle"] == handle:
                    if output["visibility"] != "task":
                        raise PermissionError("management output is not a public task artifact")
                    return service, output
        raise KeyError(handle)

    def export_service_file(self, handle, max_bytes):
        service, output = self._service_output(handle)
        return self.transport.service_read(
            output["path"],
            max_bytes=max_bytes,
            service=None if service["placement"] == "task" else service["id"],
        )

    def service_export_provenance(self, handle):
        service, _ = self._service_output(handle)
        return {
            "owner_session_id": self.runtime_id,
            "service": service["id"],
            "service_id": self.transport.service_identity(service["id"]),
            "handle": handle,
            "placement": service["placement"],
            "visibility": "task",
            "sealed_at": self._sealed_at,
            "controller_owned": True,
            "isolated": service["placement"] == "companion",
            "agent_stopped": True,
            "provider": "harbor-compose",
        }

    def finalize_task(self):
        # Reverse recipe order keeps dependencies alive while their consumers finalize.
        for service in reversed(self.services):
            finalizer = service.get("finalize")
            if finalizer:
                result = self.transport.service_run(
                    shlex.join(finalizer["argv"]),
                    service=None if service["placement"] == "task" else service["id"],
                    timeout=finalizer["timeout_seconds"],
                    cwd=finalizer.get("cwd", service.get("cwd", self.cwd)),
                )
                if result["code"]:
                    raise RuntimeError("service finalization failed: " + service["id"])
        if self.finalize:
            result = self.transport.run(
                shlex.join(self.finalize["argv"]),
                timeout=self.finalize["timeout_seconds"],
                cwd=self.finalize.get("cwd", self.cwd),
            )
            if result["code"]:
                raise RuntimeError("task finalization failed: " + result["stderr"])

        self._sealed_at = utc_now()
        self._capture_management()

    def _capture_management(self):
        # These files stay on the host, outside the Actor and terminal-review snapshot.
        outputs = [
            (service, output)
            for service in self.services
            for output in service.get("exports", [])
            if output.get("visibility", "management") == "management"
        ]
        if not outputs:
            return
        root = self.artifact_root / "management" / self.runtime_id
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        receipts = {}
        for service, output in outputs:
            handle = output["handle"]
            try:
                if PurePosixPath(handle).name != handle or handle in {".", ".."}:
                    raise ValueError("invalid service output handle")
                body = self.transport.service_read(
                    output["path"],
                    max_bytes=64 * 1024 * 1024,
                    service=None if service["placement"] == "task" else service["id"],
                )
                destination = root / (handle + ".data")
                if destination.exists():
                    if destination.is_symlink() or destination.read_bytes() != body:
                        raise RuntimeError("previously collected service output differs")
                else:
                    fd = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                    with os.fdopen(fd, "wb") as stream:
                        stream.write(body)
                receipts[handle] = {
                    "status": "collected",
                    "path": destination.name,
                    "bytes": len(body),
                    "sha256": hashlib.sha256(body).hexdigest(),
                    "service": service["id"],
                    "visibility": "management",
                    "sealed_at": self._sealed_at,
                }
            except Exception as exc:
                receipts[handle] = {"status": "unavailable", "reason": type(exc).__name__}
        (root / "receipts.json").write_text(json.dumps(receipts, indent=2) + "\n")
        if any(value["status"] != "collected" for value in receipts.values()):
            raise RuntimeError("required management outputs were not captured")

    def invalidate(self, reason):
        self.evidence["invalid_reason"] = reason
        self.transport.quiesce()
        self.close()

    def close(self):
        self._closed = True
        self.evidence["closed_at"] = utc_now()
        self.transport.close()
