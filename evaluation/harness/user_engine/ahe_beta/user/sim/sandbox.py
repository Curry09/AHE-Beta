"""Minimal execution sandbox for inner-layer user agent (spec-0008/T2).

Provides restricted shell execution and path resolution within a working directory as cwd
(from 0008/T1 materialize, or default to a newly created empty tempdir). All paths are
resolved relative to cwd; escaping the subtree is forbidden.

Not a security sandbox: only minimal isolation (cwd confinement + timeout), no defense
against malicious code (no Docker/seccomp). The threat model is "user running assistant-proposed
code on their own machine," different from production sandboxes; strong isolation left for later.
"""

from __future__ import annotations

from ahe_beta.user.sim.runtime import Workspace, as_runtime, make_empty_runtime

# run_shell output truncation limit (characters), prevent a single run from producing massive output that floods the prompt.
_MAX_OUTPUT = 20_000


class Sandbox:
    """One working directory + restricted execution. workspace defaults to creating an empty tempdir and deletes it on cleanup."""

    def __init__(self, workspace: Workspace | None = None) -> None:
        self._runtime = make_empty_runtime() if workspace is None else as_runtime(workspace)
        self._owns_tmp = workspace is None
        self.cwd = self._runtime.cwd

    def resolve(self, path: str) -> str:
        """Resolve relative path to absolute path within cwd subtree; reject escapes (.. / absolute paths)."""
        return self._runtime.resolve(path)

    def read_text(self, path: str) -> str:
        return self._runtime.read_text(path)

    def write_text(self, path: str, content: str) -> str:
        return self._runtime.write_text(path, content)

    def list_files(self, path: str = ".") -> list[str]:
        return self._runtime.list_files(path)

    def read_diff(self) -> str:
        return self._runtime.read_diff()

    def _env(self) -> dict[str, str] | None:
        """Return the private tool execution environment.

        Keep consistent with the default harness shell environment: share only cwd, do not
        automatically activate `.venv` under the workspace. If the harness created or used
        a particular virtual environment, it should be reflected via explicit commands (e.g.
        `.venv/bin/python -m pytest ...`); user private tools use the same commands to reproduce.
        """
        return None

    def run(self, cmd: str, timeout: float = 10.0) -> dict:
        """Run a shell command under cwd. Return {ok, stdout, stderr, returncode}; ok=False on timeout.

        Command inherits host environment and only switches cwd; does not implicitly select/activate
        workspace `.venv`.
        """
        return self._runtime.run(cmd, timeout=timeout)

    def cleanup(self) -> None:
        """Only clean up self-created tempdir; leave externally passed workspace untouched (managed by caller/0008-T1)."""
        if self._owns_tmp:
            self._runtime.close()
