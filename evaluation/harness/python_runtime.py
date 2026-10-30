"""Validate the self-contained CPython tree before archiving its prefix."""

import sys
from pathlib import Path


def portable_python_base() -> Path:
    base = Path(sys.base_prefix).resolve()
    if (
        not sys.platform.startswith("linux")
        or sys.version_info[:2] != (3, 12)
        or base in {Path("/"), Path("/usr"), Path("/usr/local")}
        or not all(
            (base / name).is_file() for name in ("BUILD", "bin/python3.12", "lib/python3.12/os.py")
        )
    ):
        raise ValueError(
            "Runtime packaging requires self-contained Linux CPython 3.12; "
            "create the environment with uv-managed Python. "
            "System installation prefixes cannot be archived."
        )
    return base
