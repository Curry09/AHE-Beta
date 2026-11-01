"""Spec-0081/T5: freeze only verified original inputs into a reproducible Git child."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import tempfile
from pathlib import Path, PurePosixPath

# Match the production prediction index exactly. Existing Git ignore rules still apply.
PREDICTION_PATHS = [
    ".",
    ":(glob,exclude)**/.venv/**",
    ":(glob,exclude)**/__pycache__/**",
    ":(glob,exclude)**/*.py[cod]",
]
IDENTITY = {
    "GIT_AUTHOR_NAME": "Auto Designer Materials",
    "GIT_AUTHOR_EMAIL": "materials@auto-designer.invalid",
    "GIT_COMMITTER_NAME": "Auto Designer Materials",
    "GIT_COMMITTER_EMAIL": "materials@auto-designer.invalid",
    "GIT_AUTHOR_DATE": "2026-11-01T00:00:00+00:00",
    "GIT_COMMITTER_DATE": "2026-11-01T00:00:00+00:00",
}
MESSAGE = "Freeze verified original inputs before Actor execution\n"
SHA = re.compile(r"[0-9a-f]{40}")


def git(
    workspace: Path,
    *arguments: str,
    index: Path | None = None,
    message: str | None = None,
    binary: bool = False,
) -> str | bytes:
    environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    environment.update(
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL="/dev/null",
        GIT_TERMINAL_PROMPT="0",
        GIT_NO_LAZY_FETCH="1",
        **IDENTITY,
    )
    if index is not None:
        environment["GIT_INDEX_FILE"] = str(index)
    filters = subprocess.run(
        [
            "git",
            "config",
            "--local",
            "--null",
            "--name-only",
            "--get-regexp",
            r"^filter\..*\.(clean|smudge|process|required)$",
        ],
        cwd=workspace,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if filters.returncode not in {0, 1}:
        raise ValueError("Cannot verify original Git filter settings")
    filter_options = []
    for key in filters.stdout.split("\0"):
        if key:
            filter_options.extend(["-c", key + ("=false" if key.endswith(".required") else "=")])
    result = subprocess.run(
        [
            "git",
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "core.fsmonitor=false",
            "-c",
            "core.autocrlf=false",
            "-c",
            "core.fileMode=true",
            "-c",
            "core.attributesFile=/dev/null",
            "-c",
            "commit.gpgsign=false",
            "-c",
            "i18n.commitEncoding=UTF-8",
            *filter_options,
            *arguments,
        ],
        cwd=workspace,
        env=environment,
        input=message,
        capture_output=True,
        text=not binary,
        check=True,
        timeout=180,
    )
    return result.stdout if binary else result.stdout.rstrip("\n")


def file_state(path: Path) -> dict:
    info = path.lstat()
    value = {"mode": stat.S_IMODE(info.st_mode)}
    if stat.S_ISLNK(info.st_mode):
        target = os.readlink(path)
        value.update(
            type="symlink", target=target, sha256=hashlib.sha256(os.fsencode(target)).hexdigest()
        )
    elif stat.S_ISREG(info.st_mode):
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
        value.update(type="file", bytes=info.st_size, sha256=digest.hexdigest())
    elif stat.S_ISDIR(info.st_mode):
        value["type"] = "directory"
    else:
        raise ValueError(f"Unsupported original workspace file: {path}")
    return value


def inventory(workspace: Path) -> dict:
    result = {".": file_state(workspace)}
    for directory, directories, filenames in os.walk(workspace, followlinks=False):
        directories[:] = sorted(name for name in directories if name != ".git")
        for name in sorted([*directories, *filenames]):
            if name == ".git":
                continue
            path = Path(directory) / name
            result[path.relative_to(workspace).as_posix()] = file_state(path)
    return result


def inventory_hash(value: dict) -> str:
    data = json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode()
    return hashlib.sha256(data).hexdigest()


def validate_allowed(workspace: Path, allowed: dict) -> None:
    if not isinstance(allowed, dict) or not allowed:
        raise ValueError("An explicit nonempty original-input whitelist is required")
    for relative, expected in allowed.items():
        if not isinstance(relative, str):
            raise ValueError("An original input path must be a string")
        path = PurePosixPath(relative)
        if (
            not isinstance(relative, str)
            or relative != path.as_posix()
            or path.is_absolute()
            or any(part in {".", "..", ".git"} for part in path.parts)
            or "\0" in relative
            or not isinstance(expected, dict)
            or set(expected) != {"sha256", "bytes", "mode", "git_mode"}
            or not re.fullmatch(r"[0-9a-f]{64}", expected.get("sha256", ""))
            or expected.get("git_mode") not in {"100644", "100755"}
            or type(expected.get("bytes")) is not int
            or expected["bytes"] < 0
            or type(expected.get("mode")) is not int
            or not 0 <= expected["mode"] <= 0o7777
        ):
            raise ValueError("The original-input whitelist contains an invalid declaration")
        candidate = workspace / relative
        if any(parent.is_symlink() for parent in candidate.parents if parent != workspace.parent):
            raise ValueError("A whitelisted original input cannot traverse a symlink")
        actual = file_state(candidate)
        wanted = {"type": "file", **{key: expected[key] for key in ("sha256", "bytes", "mode")}}
        if actual != wanted:
            raise ValueError(f"Original input content, type, or mode differs: {relative}")
        mode = "100755" if actual["mode"] & 0o111 else "100644"
        if mode != expected["git_mode"]:
            raise ValueError(f"Original input Git mode differs: {relative}")


def prediction_index(workspace: Path, base: str, index: Path) -> list[str]:
    git(workspace, "read-tree", base, index=index)
    git(workspace, "add", "-A", "--", *PREDICTION_PATHS, index=index)
    names = git(
        workspace, "diff", "--cached", "--name-only", "-z", "--no-renames", base, "--", index=index
    )
    return [name for name in names.split("\0") if name]


def verify(*, workspace: Path, parent: str, allowed: dict, expected: str) -> dict:
    if not SHA.fullmatch(parent) or not SHA.fullmatch(expected):
        raise ValueError("Exact original parent and prepared commit IDs are required")
    if git(workspace, "rev-parse", "HEAD") != expected:
        raise ValueError("Prepared Git HEAD differs from its fixed declaration")
    if git(workspace, "rev-parse", "HEAD^") != parent:
        raise ValueError("Prepared Git HEAD does not directly extend the declared original parent")
    validate_allowed(workspace, allowed)
    with tempfile.TemporaryDirectory(prefix="initial-git-verify-") as temporary:
        changed = prediction_index(workspace, expected, Path(temporary) / "index")
    if changed:
        raise ValueError("Prepared initial workspace has undeclared changes: " + repr(changed))
    return {
        "parent": parent,
        "prepared": expected,
        "tree": git(workspace, "rev-parse", "HEAD^{tree}"),
        "initial_prediction": "empty",
    }


def freeze(*, workspace: Path, parent: str, allowed: dict, expected: str | None) -> dict:
    if not workspace.is_absolute() or workspace.is_symlink() or not SHA.fullmatch(parent):
        raise ValueError("An absolute original workspace and exact parent are required")
    if expected is not None and not SHA.fullmatch(expected):
        raise ValueError("The production initializer requires a fixed prepared commit ID")
    if git(workspace, "rev-parse", "HEAD") != parent:
        raise ValueError("Original initialization did not establish the declared parent")
    validate_allowed(workspace, allowed)
    before = inventory(workspace)
    with tempfile.TemporaryDirectory(prefix="initial-git-index-") as temporary:
        index = Path(temporary) / "index"
        changed = prediction_index(workspace, parent, index)
        if set(changed) != set(allowed):
            raise ValueError(
                "Initial changes differ from the exact original-input whitelist: " + repr(changed)
            )
        statuses = git(
            workspace,
            "diff",
            "--cached",
            "--name-status",
            "-z",
            "--no-renames",
            parent,
            "--",
            index=index,
        ).split("\0")
        if statuses[-1] == "":
            statuses.pop()
        if len(statuses) != len(allowed) * 2 or any(status != "A" for status in statuses[::2]):
            raise ValueError("Normalization may only add the declared original untracked inputs")
        for relative in allowed:
            stage = git(workspace, "ls-files", "--stage", "--", relative, index=index)
            if stage.split(" ", 1)[0] != allowed[relative]["git_mode"]:
                raise ValueError("Staged original input mode differs: " + relative)
            blob = git(workspace, "show", ":" + relative, index=index, binary=True)
            if hashlib.sha256(blob).hexdigest() != allowed[relative]["sha256"]:
                raise ValueError("Staged original input bytes differ: " + relative)
        tree = git(workspace, "write-tree", index=index)
        prepared = git(workspace, "commit-tree", tree, "-p", parent, message=MESSAGE)
        if expected is not None and prepared != expected:
            raise ValueError("Prepared commit is not reproducible under its fixed declaration")
        git(workspace, "update-ref", "--no-deref", "HEAD", prepared, parent)
        git(workspace, "read-tree", prepared)
    after = inventory(workspace)
    if before != after:
        raise ValueError("Normalizing the Git baseline changed original workspace bytes/type/mode")
    receipt = {
        **verify(workspace=workspace, parent=parent, allowed=allowed, expected=prepared),
        "kind": "publication-prepared child over verified original task inputs",
        "original_files": allowed,
        "workspace_inventory": before,
        "before_inventory_sha256": inventory_hash(before),
        "after_inventory_sha256": inventory_hash(after),
        "workspace_content_type_and_mode_unchanged": True,
        "identity": IDENTITY,
        "message": MESSAGE,
        "prediction_pathspec": PREDICTION_PATHS,
    }
    git_directory = Path(git(workspace, "rev-parse", "--git-dir"))
    if not git_directory.is_absolute():
        git_directory = workspace / git_directory
    if not git_directory.resolve().is_relative_to(workspace.resolve()):
        raise ValueError("Task Git provenance must remain inside its own workspace")
    (git_directory / "auto-designer-initial-inputs.json").write_text(
        json.dumps(receipt, indent=2) + "\n"
    )
    return receipt


def command(value: str) -> list[str]:
    argv = json.loads(value)
    if (
        not isinstance(argv, list)
        or not argv
        or any(not isinstance(arg, str) or "\0" in arg for arg in argv)
    ):
        raise ValueError("Initialization and readiness require explicit argv lists")
    return argv


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--parent", required=True)
    parser.add_argument("--allow-json", required=True)
    parser.add_argument("--expected-prepared")
    parser.add_argument("--initialize-argv-json")
    parser.add_argument("--readiness-argv-json")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument(
        "--compute",
        action="store_true",
        help="Maintainer-only technical precomputation; never used by published task initialization",
    )
    modes.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    allowed = json.loads(args.allow_json)
    if not args.compute and not args.expected_prepared:
        parser.error("Production initialization/readiness requires --expected-prepared")
    if args.verify_only:
        receipt = verify(
            workspace=args.workspace,
            parent=args.parent,
            allowed=allowed,
            expected=args.expected_prepared,
        )
    else:
        if not args.initialize_argv_json or not args.readiness_argv_json:
            parser.error(
                "Original initialization and readiness argv are required before normalization"
            )
        for value in (args.initialize_argv_json, args.readiness_argv_json):
            subprocess.run(command(value), cwd=args.workspace, check=True, timeout=240)
        receipt = freeze(
            workspace=args.workspace,
            parent=args.parent,
            allowed=allowed,
            expected=args.expected_prepared,
        )
    print(
        json.dumps(
            {key: receipt[key] for key in ("parent", "prepared", "tree", "initial_prediction")}
        )
    )


if __name__ == "__main__":
    main()
