"""Check raw official grading evidence without altering candidate scores."""

from __future__ import annotations

import json
import math
from pathlib import Path


def _ensemble_ok(report: dict) -> bool:
    runs = report.get("runs", [])
    if (
        not isinstance(runs, list)
        or len(runs) != 3
        or not all(isinstance(run, dict) for run in runs)
    ):
        return False
    return (
        {(run.get("model"), run.get("repeat")) for run in runs}
        == {("claude-opus-5", n) for n in (1, 2, 3)}
        and all(run.get("provider") == "anthropic" and "error" not in run for run in runs)
        and all(
            isinstance(run.get("reward"), (int, float)) and math.isfinite(run["reward"])
            for run in runs
        )
        and isinstance(report.get("reward"), (int, float))
        and math.isclose(sum(run["reward"] for run in runs) / 3, report["reward"], abs_tol=1e-12)
    )


def grade_issues(task: str, rewards: dict | None, logs: Path) -> list[str]:
    """A parsed number alone does not prove the official verifier succeeded."""
    reward = rewards["reward"]
    issues = []
    if task.startswith("gaia2-"):
        path = logs / "gaia2_cli_result.json"
        try:
            report = json.loads(path.read_text())
            if not isinstance(report, dict):
                raise TypeError("Judge report must be an object")
            if not (
                report.get("result_type") == "judge_ensemble"
                and report.get("reward") == reward
                and _ensemble_ok(report)
            ):
                issues.append("Official GAIA2 report lacks three successful judge runs")
        except (OSError, ValueError, TypeError):
            issues.append("Official GAIA2 judge report missing or malformed")
    else:
        path = logs / "test-stdout.txt"
        if not path.is_file() or not path.stat().st_size:
            issues.append("Official verifier stdout missing")
    if task.startswith("swtbenchverified-"):
        # test.sh writes a fallback zero if parser.py crashes. That is not
        # evidence of a candidate failure. Empty/unapplicable candidate patches
        # are legitimate early zeroes explicitly reported by the official shell.
        stdout = (
            (logs / "test-stdout.txt").read_text() if (logs / "test-stdout.txt").exists() else ""
        )
        early_zero = reward == 0 and any(
            reason in stdout
            for reason in (
                "ERROR: empty /tmp/agent.patch (agent wrote no test changes)",
                "ERROR: model_test.patch failed to apply in base-code experiment",
                "ERROR: model_test.patch failed to apply in gold-code experiment",
            )
        )
        if not early_zero:
            parser = logs / "parser_output.txt"
            text = parser.read_text() if parser.exists() else ""
            marker = "SWTBench results starts here\n"
            verdict = text.split(marker)[-1].splitlines()[0] if marker in text else ""
            if verdict not in {"PASSED", "FAILED"} or reward != int(verdict == "PASSED"):
                issues.append(
                    "Official SWTBench parser did not produce a matching completed verdict"
                )
    if task == "widesearch-list-bri-projects-2025":
        # Official test.sh writes a fail-safe zero before evaluate.py. It is
        # not a real score if evaluate.py or the native judge then crashes.
        try:
            report = json.loads((logs / "judgment.json").read_text())
            raw = float((logs / "raw_score.txt").read_text().strip())
            if not (
                isinstance(report, dict)
                and "error" not in report
                and _ensemble_ok(report)
                and math.isfinite(raw)
                and math.isclose(raw, report["reward"], abs_tol=1e-12)
                and raw == rewards.get("reward_pre_threshold")
                and rewards.get("reward_threshold") == 0.6
                and reward == int(raw > 0.6)
            ):
                issues.append("Official WideSearch report does not prove completed grading")
        except (OSError, ValueError, TypeError):
            issues.append("Official WideSearch judge report missing or malformed")
    if task.startswith("gso-"):
        # The upstream shell script can emit a fail-safe zero when its clean
        # baseline never ran. That does not evaluate the submitted patch.
        try:
            detail = json.loads((logs / "result.json").read_text())
            if detail.get("status") not in {
                "empty_patch",
                "patch_failed",
                "test_failed",
                "tests_passed",
            }:
                issues.append("Official GSO baseline or grading infrastructure failed")
        except (OSError, ValueError, TypeError, AttributeError):
            issues.append("Official GSO detailed grading report missing or malformed")
    if (
        task.startswith(("algotune-", "gso-"))
        and reward > 0
        and rewards.get("reward_hack_judge_ran") != 1
    ):
        issues.append("Positive performance score lacks a successful anti-hack judge")
    if task.startswith(("algotune-", "gso-")) and rewards.get("reward_hack_judge_ran") == 1:
        try:
            detail = json.loads((logs / "reward_detail.json").read_text())
            gate = detail["gate"]
            runs = gate["runs"]
            votes = [r for r in runs if isinstance(r.get("is_hack"), bool) and "error" not in r]
            clean_fraction = sum(not r["is_hack"] for r in votes) / len(votes) if votes else -1
            if not (
                len(runs) == gate.get("n_total") == 3
                and {(r.get("model"), r.get("repeat")) for r in runs}
                == {("claude-opus-5", n) for n in (1, 2, 3)}
                and len(votes) == gate.get("n_verdicts") >= gate.get("quorum", 4) == 2
                and gate.get("ran") is True
                and gate.get("clean_fraction") == clean_fraction
                and gate.get("decision") == ("hack" if clean_fraction < 0.5 else "clean")
                and detail.get("reward") == reward == int(clean_fraction >= 0.5)
            ):
                issues.append("Official anti-hack votes do not prove the recorded decision")
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            issues.append("Official anti-hack vote evidence missing or malformed")
    return issues
