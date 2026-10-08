#!/usr/bin/env python3
"""Build the pinned E2B template used by the formal scaling runs.

This is intentionally an explicit operator action.  Resource values are part
of the template build, not merely launcher metadata; a sandbox created from
the old ``base`` template cannot be upgraded in place.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


def _credentials() -> str:
    for path in (Path(".e2b"), Path("../.e2b")):
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            key, sep, value = line.partition("=")
            if sep and key.strip() in {"E2B_API_KEY", "API_KEY", "API_KET"} and value.strip():
                return value.strip().strip("\"'")
    return os.environ.get("E2B_API_KEY", "")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--alias", default="hse-runtime-8g-v1")
    parser.add_argument("--cpu-count", type=int, default=4)
    parser.add_argument("--memory-mb", type=int, default=8192)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.cpu_count < 1 or args.memory_mb < 512 or args.memory_mb % 2:
        raise SystemExit("cpu-count must be positive; memory-mb must be an even value >= 512")
    plan = {
        "alias": args.alias,
        "cpu_count": args.cpu_count,
        "memory_mb": args.memory_mb,
        "storage_mb": 10240,
        "base_template": "base",
    }
    if args.dry_run:
        print(json.dumps({**plan, "credentials_loaded": False}, indent=2))
        return 0
    key = _credentials()
    if not key:
        raise SystemExit("missing E2B_API_KEY in environment or .e2b")
    from e2b import Template

    template = Template().from_template("base")
    build = Template.build(
        template,
        alias=args.alias,
        cpu_count=args.cpu_count,
        memory_mb=args.memory_mb,
        api_key=key,
    )
    print(json.dumps({**plan, "build": str(build)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
