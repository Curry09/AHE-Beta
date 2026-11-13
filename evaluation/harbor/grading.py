"""Check raw official rewards, then invoke only the selected task-set profile."""

import json
import math
from pathlib import Path

from evaluation.benchmarks import get_profile


def grade_issues(case: dict, rewards: dict | None, logs: Path) -> list[str]:
    if not isinstance(rewards, dict) or "reward" not in rewards:
        return ["Official reward missing"]
    reward = rewards["reward"]
    if (
        isinstance(reward, bool)
        or not isinstance(reward, (int, float))
        or not math.isfinite(reward)
    ):
        return ["Official reward is not a finite number"]
    issues = []
    # A verifier must not turn a lost submission into a valid solver zero.
    # Truly absent outputs remain ordinary failures, with task-log evidence.
    artifact_manifest = logs.parent / "artifacts/manifest.json"
    trial_log = logs.parent / "trial.log"
    if artifact_manifest.exists():
        evidence = trial_log.read_text(errors="replace") if trial_log.exists() else ""
        for entry in json.loads(artifact_manifest.read_text()):
            if entry.get("status") != "failed":
                continue
            missing = "FileNotFoundException: path '" + entry["source"] + "' does not exist"
            e2b_missing = (
                "FileNotFoundException: path not found: lstat "
                + entry["source"]
                + ": no such file or directory"
            )
            if missing not in evidence and e2b_missing not in evidence:
                issues.append("Task artifact collection incomplete: " + entry["source"])
    reward_file = next(
        (p for p in (logs / "reward.json", logs / "reward.txt") if p.is_file()), None
    )
    if reward_file is None:
        issues.append("Official raw reward missing")
    else:
        try:
            raw = (
                json.loads(reward_file.read_text())
                if reward_file.suffix == ".json"
                else float(reward_file.read_text().strip())
            )
            if isinstance(raw, dict):
                raw = raw.get("reward")
            if raw != reward:
                issues.append("Parsed/raw official reward mismatch")
        except (ValueError, TypeError):
            issues.append("Official raw reward cannot be parsed")
    if issues:
        return issues
    profile = get_profile(case["benchmark"])
    if profile:
        issues.extend(profile.grade_issues(case["task_id"], rewards, logs))
    return issues
