"""Run immutable trials, then collect experience without relaunching the actor."""

from dataclasses import replace
from pathlib import Path

from .experience import rate, read, write
from .harbor.executor import HarborExecutor
from .harbor.scheduler import Orchestrator


def add_experience(result, trial, manifest, attempt_root):
    if trial["interaction"] != "simulated_user":
        return result
    source = result.artifacts.get("source_result")
    if not source:
        return result
    agent = Path(source).parent / "agent"
    settings = manifest["metadata"]["evaluation_runtime"]
    try:
        value = rate(agent, settings, attempt_root / "experience")
    except Exception as error:
        value = {"status": "failed", "score": None, "reason": type(error).__name__}
        write(attempt_root / "experience/result.json", value)
    return replace(
        result,
        metrics={**result.metrics, "experience": value},
        artifacts={
            **result.artifacts,
            "experience": str(attempt_root / "experience/result.json"),
        },
    )


class ReviewedExecutor(HarborExecutor):
    def __call__(self, trial, attempt, attempt_root):
        result = super().__call__(trial, attempt, attempt_root)
        return add_experience(result, trial, self.manifest, attempt_root)


def execute(manifest, root, env_file):
    from .credentials import preflight

    preflight(manifest, env_file)
    return Orchestrator(
        manifest,
        root,
        ReviewedExecutor(manifest, root, env_file),
        max_invalid_attempts=1,
    ).run()


def review_saved(manifest, root, env_file):
    from .credentials import values
    from .report import summarize_run
    from .results import TrialResult

    HarborExecutor(manifest, root, env_file)  # Verify the frozen framework identity before review.
    values(manifest["metadata"]["evaluation_runtime"], env_file)
    trials = {t["trial_id"]: t for t in manifest["trials"]}
    state = read(root / "state.json")
    for trial_id, cursor in state.get("trials", {}).items():
        if not cursor.get("result"):
            continue
        p = Path(cursor["result"])
        result = TrialResult.from_dict(read(p))
        updated = add_experience(result, trials[trial_id], manifest, p.parent)
        write(p, updated.to_dict())
    return summarize_run(root)
