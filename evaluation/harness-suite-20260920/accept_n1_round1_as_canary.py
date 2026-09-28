#!/usr/bin/env python3
"""Record the already completed N=1 Round-1 loop as runtime evidence.

This is not a new run and does not score N=1.  It verifies the persisted N=1
recovery ledger contains a completed user -> triage -> design/development ->
delivery round, then emits a receipt that the N4/N8 launch gate can consume.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--recovery", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    state = json.loads(args.state.read_text(encoding="utf-8"))
    recovery = json.loads(args.recovery.read_text(encoding="utf-8"))
    rounds = recovery.get("rounds") or {}
    round_key = next(
        (key for key in rounds if str(key).replace("_", " ").lower() in {"1", "round 1", "round1"}),
        None,
    )
    if round_key is None:
        round_key = next(
            (key for key in rounds if "round 1" in key.replace("_", " ").lower()), None
        )
    if round_key is None:
        raise SystemExit("N1 recovery ledger has no Round 1")
    record = rounds[round_key]
    stages = record.get("stages") or {}
    required = (
        "round_started",
        "users",
        "triage",
        "designer",
        "divergent",
        "owner",
        "delivery_wait",
        "round_sealed",
    )
    missing = [name for name in required if (stages.get(name) or {}).get("status") != "completed"]
    if missing or record.get("status") != "completed":
        raise SystemExit(
            f"N1 Round 1 is not complete: status={record.get('status')!r}, missing={missing}"
        )

    evidence = {
        "schema_version": "hse-existing-n1-full-loop-evidence-v1",
        "status": "passed",
        "full_loop": True,
        "scoring": False,
        "source": "existing-n1-round-1",
        "source_run_id": state.get("run_id"),
        "source_sandbox_id": state.get("sandbox_id"),
        "task_id": state.get("task_id"),
        "round": 1,
        "observed_stages": list(required),
        "observed_at": datetime.now(UTC).isoformat(),
    }
    canonical = json.dumps(evidence, ensure_ascii=False, sort_keys=True).encode("utf-8")
    evidence["evidence_sha256"] = hashlib.sha256(canonical).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(evidence, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
