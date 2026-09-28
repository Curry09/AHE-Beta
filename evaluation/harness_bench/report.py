"""Aggregate only sealed results with explicit denominators."""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from .outcomes import OutcomeKind, TrialResult
from .schema import PlanError


def summarize(results: Iterable[TrialResult]) -> dict[str, Any]:
    rows = list(results)
    valid = [item for item in rows if item.valid_trial]
    counts = {kind.value: 0 for kind in OutcomeKind}
    for item in rows:
        counts[item.outcome.value] += 1
    costs: dict[str, float] = defaultdict(float)
    for item in rows:
        for role, amount in item.costs.items():
            costs[role] += float(amount)
    denominator = len(valid)
    return {
        "attempts": len(rows),
        "valid_trials": denominator,
        "invalid_attempts": len(rows) - denominator,
        "passed": sum(item.passed for item in valid),
        "task_pass_rate": (
            sum(item.passed for item in valid) / denominator if denominator else None
        ),
        "terminal_reply_rate": (
            sum(item.terminal_reply for item in valid) / denominator if denominator else None
        ),
        "normal_reply_rate": (
            sum(item.normal_reply for item in valid) / denominator if denominator else None
        ),
        "grader_reach_rate": (
            sum(item.grader_reached for item in valid) / denominator if denominator else None
        ),
        "outcomes": counts,
        "costs": dict(sorted(costs.items())),
    }


def summarize_run(run_root: str | Path) -> dict[str, Any]:
    root = Path(run_root)
    result_paths = sorted(root.glob("trials/*/attempt-*/result.json"))
    results = [
        TrialResult.from_dict(json.loads(path.read_text(encoding="utf-8"))) for path in result_paths
    ]
    summary = summarize(results)
    manifest_path = root / "manifest.json"
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        trials = {str(item["trial_id"]): item for item in manifest.get("trials", [])}
        for field, output_name in (
            ("benchmark", "by_benchmark"),
            ("interaction", "by_interaction"),
            ("harness", "by_harness"),
        ):
            grouped: dict[str, list[TrialResult]] = defaultdict(list)
            for result in results:
                trial = trials.get(result.trial_id)
                if trial is not None:
                    grouped[str(trial[field])].append(result)
            summary[output_name] = {key: summarize(group) for key, group in sorted(grouped.items())}
    (root / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return summary


def compare(left: Mapping[str, Any], right: Mapping[str, Any]) -> dict[str, Any]:
    comparable = left.get("valid_trials") == right.get("valid_trials")
    left_rate = left.get("task_pass_rate")
    right_rate = right.get("task_pass_rate")
    return {
        "comparable_denominator": comparable,
        "left": dict(left),
        "right": dict(right),
        "pass_rate_delta": (
            float(right_rate) - float(left_rate)
            if left_rate is not None and right_rate is not None
            else None
        ),
    }


def comparison_signature(manifest: Mapping[str, Any]) -> dict[str, Any]:
    """Return variables that must match for a Harness A/B comparison.

    Harness identity is intentionally excluded: it is the treatment variable.
    Run ids, timestamps, and manifest digests are execution identity rather than
    experimental inputs.
    """
    trial_pairs = sorted(
        (
            str(item.get("benchmark")),
            str(item.get("task_id")),
            str(item.get("interaction")),
            str(item.get("policy")),
            item.get("seed"),
            int(item.get("repetition", 0)),
        )
        for item in manifest.get("trials", [])
    )
    return {
        "schema_version": manifest.get("schema_version"),
        "suite": manifest.get("suite"),
        "framework_commit": manifest.get("framework_commit"),
        "cases": manifest.get("cases"),
        "harness_model": manifest.get("harness_model"),
        "interactions": manifest.get("interactions"),
        "provider": manifest.get("provider"),
        "measurement": manifest.get("measurement"),
        "fallback_agent_timeout_seconds": manifest.get("fallback_agent_timeout_seconds"),
        "resolved_cases": manifest.get("resolved_cases"),
        "image_digests": manifest.get("image_digests"),
        "trial_pairs": trial_pairs,
    }


def compare_runs(left_root: str | Path, right_root: str | Path) -> dict[str, Any]:
    left_root = Path(left_root)
    right_root = Path(right_root)
    left_manifest = json.loads((left_root / "manifest.json").read_text(encoding="utf-8"))
    right_manifest = json.loads((right_root / "manifest.json").read_text(encoding="utf-8"))
    if comparison_signature(left_manifest) != comparison_signature(right_manifest):
        raise PlanError(
            "runs are not a paired Harness comparison: task, interaction, model, "
            "budget, resource, framework, or schedule variables differ"
        )
    left = json.loads((left_root / "summary.json").read_text(encoding="utf-8"))
    right = json.loads((right_root / "summary.json").read_text(encoding="utf-8"))
    return compare(left, right)
