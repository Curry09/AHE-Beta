"""Spec-0082/T1: demand reads a commit snapshot rather than a moving checkout."""

from __future__ import annotations

import io
import subprocess
import tarfile
import tempfile
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path


class HarnessSource:
    """One lazily exported, read-only source view shared by a feedback phase."""

    def __init__(self, repo: str | Path, sha: str) -> None:
        self.repo = Path(repo)
        self.sha = sha
        self._temporary: tempfile.TemporaryDirectory | None = None
        self._lock = threading.Lock()

    def snapshot(self) -> Path:
        with self._lock:
            if self._temporary is None:
                resolved = subprocess.check_output(
                    [
                        "git",
                        "-C",
                        str(self.repo),
                        "rev-parse",
                        "--verify",
                        f"{self.sha}^{{commit}}",
                    ],
                    text=True,
                ).strip()
                if resolved != self.sha:
                    raise ValueError("Feedback source must use the frozen full commit SHA")
                archive = subprocess.check_output(
                    ["git", "-C", str(self.repo), "archive", "--format=tar", self.sha]
                )
                temporary = tempfile.TemporaryDirectory(prefix="harness-source-")
                try:
                    with tarfile.open(fileobj=io.BytesIO(archive)) as stream:
                        stream.extractall(temporary.name, filter="data")
                    # Source roles have only read tools; modes also prevent accidental writes.
                    for path in Path(temporary.name).rglob("*"):
                        if not path.is_symlink():
                            path.chmod(0o555 if path.is_dir() else 0o444)
                    self._temporary = temporary
                except BaseException:
                    temporary.cleanup()
                    raise
            return Path(self._temporary.name)

    def close(self) -> None:
        if self._temporary is not None:
            # TemporaryDirectory restores owner permissions when removing its contents.
            self._temporary.cleanup()


_SOURCE: ContextVar[HarnessSource | None] = ContextVar("feedback_harness_source", default=None)


def current_harness_source() -> HarnessSource | None:
    return _SOURCE.get()


@contextmanager
def bind_harness_source(repo: str | Path | None, sha: str) -> Iterator[None]:
    """Keep fake/injected roles lazy; a real agent must successfully export the SHA."""
    if repo is None:
        yield
        return
    source = HarnessSource(repo, sha)
    token = _SOURCE.set(source)
    try:
        yield
    finally:
        _SOURCE.reset(token)
        source.close()
