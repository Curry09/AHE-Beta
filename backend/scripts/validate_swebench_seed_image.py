#!/usr/bin/env python3
"""Extract and validate every prepared workspace in a SWE-bench seed image."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from auto_designer.models import WorkspaceSpec  # noqa: E402
from auto_designer.user.sim.seed_source import provision  # noqa: E402

IMPORT_NAMES = {
    "astropy/astropy": "astropy",
    "django/django": "django",
    "matplotlib/matplotlib": "matplotlib",
    "mwaskom/seaborn": "seaborn",
    "psf/requests": "requests",
    "pylint-dev/pylint": "pylint",
    "pydata/xarray": "xarray",
    "pytest-dev/pytest": "pytest",
    "scikit-learn/scikit-learn": "sklearn",
    "sphinx-doc/sphinx": "sphinx",
    "sympy/sympy": "sympy",
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", required=True)
    parser.add_argument("--state", type=Path, required=True)
    args = parser.parse_args()

    instances = json.loads(args.state.read_text(encoding="utf-8"))["instances"]
    failures: list[str] = []
    for index, (instance_id, meta) in enumerate(instances.items(), 1):
        repo_name = str(meta["repo"])
        import_name = IMPORT_NAMES[repo_name]
        try:
            with tempfile.TemporaryDirectory(prefix="seed_image_check_") as tmp:
                repo = Path(
                    provision(
                        WorkspaceSpec(
                            kind="docker-seed",
                            params={"image": args.image, "instance_id": instance_id},
                        ),
                        dest_root=tmp,
                    )
                )
                head = subprocess.run(
                    ["git", "rev-parse", "HEAD"],
                    cwd=repo,
                    check=True,
                    capture_output=True,
                    text=True,
                ).stdout.strip()
                if head != meta["base_commit"]:
                    raise RuntimeError(f"HEAD={head}, expected={meta['base_commit']}")
                code = (
                    "import importlib, pathlib, sys; "
                    f"m=importlib.import_module({import_name!r}); "
                    "p=pathlib.Path(m.__file__).resolve(); root=pathlib.Path.cwd().resolve(); "
                    "assert p.is_relative_to(root), (p, root); "
                    "print(sys.version.split()[0], p)"
                )
                imported = subprocess.run(
                    [str(repo / ".venv/bin/python"), "-W", "ignore", "-c", code],
                    cwd=repo,
                    check=True,
                    capture_output=True,
                    text=True,
                ).stdout.strip()
                print(f"[{index:02}/{len(instances)}] PASS {instance_id}: {imported}")
        except Exception as exc:  # noqa: BLE001 - validate all entries before failing
            failures.append(instance_id)
            print(f"[{index:02}/{len(instances)}] FAIL {instance_id}: {exc}", file=sys.stderr)
    print(f"summary: passed={len(instances) - len(failures)} failed={len(failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
