#!/usr/bin/env python3
"""Relocate prepared virtualenv metadata after seed workspaces enter the image."""

from __future__ import annotations

import json
from pathlib import Path

TEXT_SUFFIXES = {".pth", ".egg-link", ".py", ".json"}


def main() -> None:
    state = json.loads(Path("/build-state.json").read_text(encoding="utf-8"))
    for instance_id, meta in (state.get("instances") or {}).items():
        repo = Path("/workspace") / instance_id / "repo"
        venv = repo / ".venv"
        if not venv.is_dir():
            continue
        old = str(meta.get("source_path") or "").encode()
        new = str(repo).encode()
        candidates = [venv / "pyvenv.cfg"]
        bin_dir = venv / "bin"
        if bin_dir.is_dir():
            candidates.extend(
                path for path in bin_dir.iterdir() if path.is_file() and not path.is_symlink()
            )
            for link in bin_dir.glob("python3.*"):
                if not link.is_symlink():
                    continue
                system_python = Path("/usr/bin") / link.name
                if system_python.exists():
                    link.unlink()
                    link.symlink_to(system_python)
        lib_dir = venv / "lib"
        if lib_dir.is_dir():
            candidates.extend(
                path
                for path in lib_dir.rglob("*")
                if path.is_file()
                and not path.is_symlink()
                and (path.suffix in TEXT_SUFFIXES or path.name == "direct_url.json")
            )
        if not old:
            continue
        for path in candidates:
            try:
                data = path.read_bytes()
            except OSError:
                continue
            if old in data:
                path.write_bytes(data.replace(old, new))


if __name__ == "__main__":
    main()
