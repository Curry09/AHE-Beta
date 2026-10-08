#!/usr/bin/env python3
"""Run the E2B/Boyue canary using the already-validated N=1 Gitea secret.

The N=1 sandbox contains the VPS Gitea credentials used by its successful
run.  This helper relays them in memory only; it never writes the token to the
repository or to the canary receipt.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from e2b import Sandbox

ROOT = Path(__file__).resolve().parents[2]
SUITE = ROOT / "evaluation" / "harness-suite-20260920"


def read_kv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip().strip("\"'")
    return values


def e2b_key() -> str:
    values = {**read_kv(ROOT / ".e2b"), **read_kv(ROOT.parent / ".e2b")}
    key = values.get("E2B_API_KEY") or values.get("API_KEY") or values.get("API_KET")
    if not key:
        raise RuntimeError("missing E2B API key")
    return key


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-sandbox-id", required=True)
    parser.add_argument("--template-alias", default="hse-runtime-8g-v1")
    parser.add_argument("--template-build-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    source = Sandbox.connect(args.source_sandbox_id, api_key=e2b_key())
    result = source.commands.run(
        "cat /opt/hse-round/backend/deploy/gitea/.env", user="root", timeout=30
    )
    if result.exit_code != 0:
        raise RuntimeError("could not read Gitea credentials from N=1 sandbox")
    gitea: dict[str, str] = {}
    for line in (result.stdout or "").splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            gitea[key.strip()] = value.strip()
    for key in ("GITEA_URL", "OWNER", "TOKEN"):
        if not gitea.get(key):
            raise RuntimeError(f"N=1 sandbox Gitea credential missing: {key}")

    env = {
        **os.environ,
        "ALLOW_INSECURE_GITEA": "1",
        "GITEA_URL": gitea["GITEA_URL"].rstrip("/"),
        "GITEA_USER": gitea["OWNER"],
        "GITEA_TOKEN": gitea["TOKEN"],
    }
    command = [
        sys.executable,
        str(SUITE / "run_e2b_full_loop_canary.py"),
        "--template-alias",
        args.template_alias,
        "--template-build-id",
        args.template_build_id,
        "--output",
        str(args.output),
    ]
    return subprocess.run(command, cwd=ROOT, env=env, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
