"""Freeze a Git Harness and build a reproducible independent Python runtime kit."""

from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
import subprocess
import tarfile
import tempfile
import zipfile
from importlib.metadata import distribution, distributions
from pathlib import Path

from .python_runtime import portable_python_base


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare_materials(harness_dir: Path, output: Path) -> dict:
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise ValueError("Material output must not exist; existing kits are immutable")
    with tempfile.TemporaryDirectory(prefix=".materials-", dir=output.parent) as temporary:
        staging = Path(temporary)
        descriptor = build_materials(harness_dir.resolve(), staging)
        staging.rename(output)
    return descriptor


def build_materials(harness_dir: Path, output: Path) -> dict:
    base = portable_python_base()

    def git(*args):
        return subprocess.check_output(["git", "-C", str(harness_dir), *args]).decode().strip()

    revision = git("rev-parse", "HEAD")
    prefix = git("rev-parse", "--show-prefix").rstrip("/")
    tree = f"HEAD:{prefix}" if prefix else "HEAD"
    repository = git("rev-parse", "--show-toplevel")
    archive = output / "harness.tar.gz"
    with archive.open("wb") as out:
        subprocess.run(
            ["git", "-C", repository, "archive", "--format=tar.gz", tree], stdout=out, check=True
        )
    with tarfile.open(archive) as pack:
        if "entry.py" not in pack.getnames():
            raise ValueError("Frozen Git tree must contain entry.py at archive root")
    # Repack the pinned controller-installed NexAU distribution as a portable
    # wheel. Preserve its metadata/license; regenerate only installation RECORD.
    installed = distribution("nexau")
    if installed.version != "0.4.1":
        raise ValueError("Runtime kit currently requires NexAU 0.4.1")
    wheel = output / "nexau-0.4.1-py3-none-any.whl"
    records = []
    with zipfile.ZipFile(wheel, "w", zipfile.ZIP_DEFLATED) as pack:
        for item in installed.files or []:
            relative = str(item)
            if (
                "__pycache__" in relative
                or relative.endswith(("/RECORD", "/INSTALLER", "/direct_url.json"))
                or ".." in item.parts
            ):
                continue
            path = Path(installed.locate_file(item))
            if not path.is_file():
                continue
            data = path.read_bytes()
            pack.writestr(relative, data)
            digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).decode().rstrip("=")
            records.append([relative, "sha256=" + digest, str(len(data))])
        record = "nexau-0.4.1.dist-info/RECORD"
        records.append([record, "", ""])
        text = io.StringIO()
        csv.writer(text).writerows(records)
        pack.writestr(record, text.getvalue())
    python = output / "python312.tar.gz"
    with tarfile.open(python, "w:gz") as pack:
        pack.add(
            base,
            arcname="python312",
            filter=lambda item: None if "__pycache__" in Path(item.name).parts else item,
        )
    requirements = output / "runtime.in"
    requirements.write_text(f"{wheel}\nag-ui-protocol==0.1.22\nsqlalchemy[asyncio]\n")
    # Resolve against the controller's locked versions, rather than whichever
    # transitive releases happen to be newest when the kit is prepared.
    constraints = output / "runtime.constraints"
    constraints.write_text(
        "\n".join(
            sorted(
                f"{item.metadata['Name']}=={item.version}"
                for item in distributions()
                if item.metadata.get("Name")
            )
        )
        + "\n"
    )
    lock = output / "runtime.lock"
    subprocess.run(
        [
            "uv",
            "pip",
            "compile",
            "--python",
            "3.12",
            "--constraint",
            str(constraints),
            "--no-header",
            "--no-annotate",
            str(requirements),
            "-o",
            str(lock),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
    )
    # Fail locally before publishing a kit that cannot even import its runtime.
    with tempfile.TemporaryDirectory(prefix="harness-runtime-check-") as temporary:
        checked_runtime = Path(temporary) / "venv"
        subprocess.run(
            ["uv", "venv", "--python", str(base / "bin/python3.12"), str(checked_runtime)],
            check=True,
            stdout=subprocess.DEVNULL,
        )
        interpreter = checked_runtime / "bin/python"
        subprocess.run(
            ["uv", "pip", "install", "--python", str(interpreter), "--no-deps", "-r", str(lock)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        subprocess.run(
            [
                str(interpreter),
                "-I",
                "-c",
                "from nexau import Agent, AgentConfig; from ag_ui.core import BaseEvent",
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
    lock.write_text(
        lock.read_text()
        .replace(wheel.as_uri(), "/opt/frozen-harness/materials/" + wheel.name)
        .replace(str(wheel), "/opt/frozen-harness/materials/" + wheel.name)
    )
    requirements.unlink()
    constraints.unlink()
    descriptor = {
        "archive": archive.name,
        "sha256": sha256(archive),
        "revision": revision,
        "runtime": {
            "runtime_wheel": wheel.name,
            "runtime_sha256": sha256(wheel),
            "runtime_lock": lock.name,
            "runtime_lock_sha256": sha256(lock),
            "python_archive": python.name,
            "python_sha256": sha256(python),
        },
    }
    (output / "materials.json").write_text(json.dumps(descriptor, indent=2) + "\n")
    return descriptor
