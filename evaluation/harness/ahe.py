"""Install pinned AHE sources and an independently verified native NexAU runtime."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

ARTIFACT = Path(__file__).with_name("ahe_artifact")
WHEEL = "nexau-0.4.1-py3-none-any.whl"


def provenance():
    return json.loads((ARTIFACT / "provenance.json").read_text())


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_source(source: Path):
    pin = provenance()
    expected = dict(pin["upstream_files"])
    expected["LICENSE"] = pin["license_sha256"]
    expected["provenance.json"] = sha256(ARTIFACT / "provenance.json")
    expected["entry.py"] = sha256(Path(__file__).with_name("ahe_entry.py"))
    actual = set()
    for path in source.rglob("*"):
        relative = path.relative_to(source)
        if any(part in {".git", "__pycache__", ".pytest_cache"} for part in relative.parts):
            continue
        if path.is_symlink():
            raise ValueError("AHE frozen source contains a symbolic link: " + str(relative))
        if path.is_file():
            actual.add(relative.as_posix())
    if actual != set(expected):
        raise ValueError("AHE frozen source file inventory changed")
    for relative, digest in expected.items():
        if sha256(source / relative) != digest:
            raise ValueError("AHE frozen source changed: " + relative)
    return pin


def materialize(destination: Path):
    destination.mkdir(parents=True, exist_ok=False)
    shutil.copytree(ARTIFACT, destination, dirs_exist_ok=True)
    shutil.copyfile(Path(__file__).with_name("ahe_entry.py"), destination / "entry.py")
    verify_source(destination)
    return destination


def verify_native_wheel(path: Path):
    """Verify package bytes independently of wheel timestamps and build metadata."""
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError("Duplicate files in AHE runtime wheel")
        if any(
            not name.startswith(("nexau/", "nexau-0.4.1.dist-info/")) or ".." in Path(name).parts
            for name in names
        ):
            raise ValueError("Unexpected files in AHE runtime wheel")
        files = {
            name: hashlib.sha256(archive.read(name)).hexdigest()
            for name in sorted(names)
            if name.startswith("nexau/") and not name.endswith("/")
        }
        license_file = "nexau-0.4.1.dist-info/licenses/LICENSE"
        if (
            license_file not in names
            or hashlib.sha256(archive.read(license_file)).hexdigest()
            != provenance()["nexau_license_sha256"]
        ):
            raise ValueError("AHE runtime SDK license is missing or changed")
    digest = hashlib.sha256(
        json.dumps(files, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    if digest != provenance()["nexau_package_sha256"]:
        raise ValueError("AHE requires the unmodified pinned NexAU package")


def runtime_directory():
    package = ARTIFACT.parent.parent
    runtime = package / "_runtime"
    return runtime if runtime.is_dir() else package.parent / "runtime"


def prepare_runtime(destination: Path, wheel: Path | None = None):
    """Build or import the fixed native SDK without changing the controller SDK."""
    if destination.exists():
        raise ValueError("AHE runtime output must not exist")
    lock = runtime_directory() / "runtime.lock"
    pin = provenance()
    if sha256(lock) != pin["runtime_lock_sha256"]:
        raise ValueError("AHE runtime dependency lock changed")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".ahe-runtime-", dir=destination.parent) as temp:
        staging = Path(temp)
        if wheel is None:
            checkout = staging / "sdk"
            subprocess.run(["git", "init", "--quiet", str(checkout)], check=True)
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(checkout),
                    "fetch",
                    "--depth=1",
                    pin["nexau_repository"],
                    pin["nexau_revision"],
                ],
                check=True,
            )
            subprocess.run(
                ["git", "-C", str(checkout), "checkout", "--quiet", "--detach", "FETCH_HEAD"],
                check=True,
            )
            subprocess.run(
                [
                    "uv",
                    "build",
                    "--wheel",
                    "--no-build-logs",
                    "--out-dir",
                    str(staging / "built"),
                    str(checkout),
                ],
                check=True,
            )
            wheel = staging / "built" / WHEEL
        verify_native_wheel(wheel)
        kit = staging / "kit"
        kit.mkdir()
        shutil.copyfile(wheel, kit / WHEEL)
        shutil.copyfile(lock, kit / "runtime.lock")
        hashes = {name: sha256(kit / name) for name in [WHEEL, "runtime.lock"]}
        (kit / "manifest.json").write_text(json.dumps(hashes, indent=2) + "\n")
        kit.rename(destination)
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, required=True)
    inputs = parser.add_mutually_exclusive_group()
    inputs.add_argument("--build-runtime", action="store_true")
    inputs.add_argument("--runtime-wheel", type=Path)
    parser.add_argument("--runtime-output", type=Path)
    args = parser.parse_args()
    if args.destination.exists():
        parser.error("AHE source destination must not exist")
    if args.build_runtime or args.runtime_wheel is not None:
        output = args.runtime_output or runtime_directory() / "ahe"
        prepare_runtime(output.resolve(), args.runtime_wheel)
    print(materialize(args.destination).resolve())


if __name__ == "__main__":
    main()
