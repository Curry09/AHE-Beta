"""Initialize a fresh task workspace from a verified original Git bundle."""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import subprocess
from pathlib import Path


def git(*args: str, cwd: Path | None = None) -> str:
    environment = dict(
        os.environ,
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL="/dev/null",
        GIT_TERMINAL_PROMPT="0",
        GIT_NO_LAZY_FETCH="1",
    )
    result = subprocess.run(
        ["git", "-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false", *args],
        cwd=cwd,
        env=environment,
        capture_output=True,
        text=True,
        check=True,
        timeout=120,
    )
    return result.stdout.strip()


def file_hash(path: Path) -> bytes:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.digest()


def overlay(*, source: Path, destination: Path) -> None:
    """Add original ignored input files; refuse conflicting tracked source bytes."""
    if not source.is_dir() or source.is_symlink():
        raise ValueError("Overlay must be a verified, unlinked input directory")
    for path in sorted(source.rglob("*")):
        relative = path.relative_to(source)
        if ".git" in relative.parts or path.is_symlink():
            raise ValueError("An input overlay cannot replace Git metadata or introduce links")
        target = destination / relative
        if target.is_symlink() or any(
            parent.is_symlink() for parent in target.parents if parent != destination.parent
        ):
            raise ValueError("An input overlay cannot overwrite a linked source path")
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        if not path.is_file():
            raise ValueError("Unsupported input file")
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if not target.is_file():
                raise ValueError("Input shape differs from the original source tree")
            if file_hash(path) != file_hash(target):
                raise ValueError(f"Input overlay differs from the original source: {relative}")
        else:
            shutil.copy2(path, target)


def initialize(
    *,
    bundle: Path,
    revision: str,
    workspace: Path,
    overlays: list[Path],
    shallow_roots: list[str] | None = None,
    bundle_ref: str = "HEAD",
    in_place: bool = False,
) -> None:
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("An exact original Git revision is required")
    if bundle.is_symlink() or not bundle.is_file():
        raise ValueError("The verified original Git bundle is missing")
    if not workspace.is_absolute() or workspace == Path("/") or workspace.is_symlink():
        raise ValueError("A fresh absolute task workspace is required")
    roots = shallow_roots or []
    if any(not re.fullmatch(r"[0-9a-f]{40}", root) for root in roots):
        raise ValueError("Shallow boundaries must be actual original Git commit IDs")
    if len(set(roots)) != len(roots) or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9/._-]*", bundle_ref
    ):
        raise ValueError("Invalid original bundle reference or duplicate shallow boundary")
    if not in_place and workspace.exists() and any(workspace.iterdir()):
        raise ValueError("Initialization requires an empty task workspace")
    if roots or in_place:
        git("init", str(workspace))
        if roots:
            (workspace / ".git/shallow").write_text("\n".join(roots) + "\n")
        git("fetch", "--no-tags", str(bundle), bundle_ref, cwd=workspace)
        if git("rev-parse", "FETCH_HEAD", cwd=workspace) != revision:
            raise ValueError("The original bundle reference differs from its declared revision")
        if in_place:
            git("reset", "--mixed", revision, cwd=workspace)
            git("diff", "--exit-code", revision, cwd=workspace)
        else:
            git("checkout", "--detach", revision, cwd=workspace)
    else:
        git("clone", "--no-checkout", "--no-hardlinks", str(bundle), str(workspace))
        git("checkout", "--detach", revision, cwd=workspace)
    if git("rev-parse", "HEAD", cwd=workspace) != revision:
        raise ValueError("The original Git baseline was not restored")
    for source in overlays:
        overlay(source=source, destination=workspace)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--overlay", type=Path, action="append", default=[])
    parser.add_argument("--shallow-root", action="append", default=[])
    parser.add_argument("--bundle-ref", default="HEAD")
    parser.add_argument("--in-place", action="store_true")
    parser.add_argument("--venv", action="store_true")
    parser.add_argument("--editable", action="store_true")
    parser.add_argument("--python", default="python3")
    args = parser.parse_args()
    initialize(
        bundle=args.bundle,
        revision=args.revision,
        workspace=args.workspace,
        overlays=args.overlay,
        shallow_roots=args.shallow_root,
        bundle_ref=args.bundle_ref,
        in_place=args.in_place,
    )
    if args.venv:
        subprocess.run(
            [args.python, "-m", "venv", "--system-site-packages", str(args.workspace / ".venv")],
            check=True,
            timeout=60,
        )
    if args.editable:
        subprocess.run(
            [args.python, "-m", "pip", "install", "--no-deps", "--no-build-isolation", "-e", "."],
            cwd=args.workspace,
            check=True,
            timeout=120,
        )


if __name__ == "__main__":
    main()
