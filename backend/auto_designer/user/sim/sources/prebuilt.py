"""Prebuilt SeedSource: copy a prepared workspace and relocate its venv.

The source is intended for SWE-bench seed caches.  A prepared repository may
contain an editable virtualenv whose text metadata records its original
absolute path.  After copying, those references are rewritten to the fresh
per-session destination so imports remain isolated.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from auto_designer.models import WorkspaceSpec
from auto_designer.user.sim.seed_source import register

_TEXT_SUFFIXES = {".pth", ".egg-link", ".py", ".json"}


@register("prebuilt")
class PrebuiltSource:
    kind = "prebuilt"

    def provision(self, spec: WorkspaceSpec, dest_root: str | None = None) -> str:
        source_raw = spec.params.get("source")
        if not source_raw:
            raise ValueError("prebuilt 源需要非空 params.source")
        source = Path(str(source_raw)).resolve()
        if not source.is_dir():
            raise FileNotFoundError(f"prebuilt workspace 不存在：{source}")

        base = Path(dest_root) if dest_root else Path(tempfile.mkdtemp(prefix="sim_ws_prebuilt_"))
        dest = base / "repo"
        shutil.copytree(
            source,
            dest,
            symlinks=True,
            ignore=shutil.ignore_patterns(".venv.stale-*"),
        )
        _relocate_venv(dest=dest, old_root=source)
        return str(dest.resolve())


def _relocate_venv(*, dest: Path, old_root: Path) -> None:
    venv = dest / ".venv"
    if not venv.is_dir():
        return
    old = str(old_root).encode()
    new = str(dest.resolve()).encode()
    candidates: list[Path] = [venv / "pyvenv.cfg"]
    bin_dir = venv / "bin"
    if bin_dir.is_dir():
        candidates.extend(path for path in bin_dir.iterdir() if path.is_file() and not path.is_symlink())
    lib_dir = venv / "lib"
    if lib_dir.is_dir():
        candidates.extend(
            path
            for path in lib_dir.rglob("*")
            if path.is_file()
            and (path.suffix in _TEXT_SUFFIXES or path.name == "direct_url.json")
        )

    for path in candidates:
        try:
            data = path.read_bytes()
        except OSError:
            continue
        if old in data:
            path.write_bytes(data.replace(old, new))
