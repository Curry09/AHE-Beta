"""Keep untracked Harness bookkeeping out of task-owned Git collection hooks."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def reserve_bookkeeping(workdir: Path) -> dict:
    workdir = workdir.resolve()
    command = ["git", "-c", "safe.directory=*", "-C", str(workdir)]
    try:
        root = subprocess.run(
            [*command, "rev-parse", "--show-toplevel"], capture_output=True, text=True
        )
    except FileNotFoundError:
        return {"excluded": [], "reason": "git_unavailable"}
    if root.returncode:
        return {"excluded": [], "reason": "not_git_workspace"}
    tracked = subprocess.run(
        [*command, "ls-files", "-z", "--", ".harness"], capture_output=True, check=True
    )
    if tracked.stdout:
        # A task-owned tracked path is never hidden or removed from a patch.
        return {"excluded": [], "reason": "task_tracks_bookkeeping_path"}
    relative = workdir.relative_to(Path(root.stdout.strip()).resolve())
    prefix = "" if relative == Path(".") else relative.as_posix() + "/"
    for character in ("\\", "[", "*", "?"):
        prefix = prefix.replace(character, "\\" + character)
    pattern = "/" + prefix + ".harness/"
    git_path = subprocess.run(
        [*command, "rev-parse", "--git-path", "info/exclude"],
        capture_output=True,
        text=True,
        check=True,
    )
    exclude = Path(git_path.stdout.strip())
    if not exclude.is_absolute():
        exclude = workdir / exclude
    contents = exclude.read_text() if exclude.exists() else ""
    if pattern not in contents.splitlines():
        exclude.parent.mkdir(parents=True, exist_ok=True)
        with exclude.open("a") as stream:
            if contents and not contents.endswith("\n"):
                stream.write("\n")
            stream.write("# Frozen Harness runtime bookkeeping\n" + pattern + "\n")
    return {"excluded": [pattern], "reason": "untracked_runtime_bookkeeping"}


if __name__ == "__main__":
    receipt = reserve_bookkeeping(Path(sys.argv[1]))
    Path(sys.argv[2]).write_text(json.dumps(receipt) + "\n")
