#!/usr/bin/env python3
"""Emit auditable resource plans for each scaling point.

No sandbox or model is contacted.  This command only validates that the
formal physical sandbox is provisioned for the developer peak and records the
effective profile expected by each N.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SUITE = ROOT / "evaluation" / "harness-suite-20260920"
CONFIG = ROOT / "examples" / "experiments" / "synthesizer-scaling-e2b.json"
OUT = SUITE / "prepared" / "scaling-e2b-20260922"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", default="all", choices=["all", "4", "8", "16", "32"])
    args = parser.parse_args()
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    e2b = config["e2b"]
    profiles = e2b["resource_profiles"]
    effective = e2b["effective_profile_by_n"]
    values = [1, 4, 8, 16, 32] if args.n == "all" else [int(args.n)]
    outputs = []
    for n in values:
        profile_name = effective[str(n)]
        profile = profiles[profile_name]
        document = {
            "schema_version": "hse-e2b-resource-plan-v1",
            "experiment_id": f"hse-n{n}-e2b-20260922",
            "created_at": datetime.now(UTC).isoformat(),
            "config_sha256": sha256(CONFIG),
            "template_alias": e2b["template_alias"],
            "template_build_id": e2b["template_build_id"],
            "profile": profile_name,
            "resources": profile,
            "phase_policy": "single physical sandbox sized to developer peak",
            "launchable": e2b["template_build_id"] != "pending-e2b-template-build",
        }
        destination = OUT / f"n{n}" / "resource-plan.json"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        outputs.append(str(destination))
    print(
        json.dumps(
            {"plans": outputs, "template_build_id": e2b["template_build_id"]},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
